"""Worker de simulación: único dueño de la flota (ver ``api/persistencia.py``).

Bucle:
1. Atiende los comandos pendientes en orden (solicitudes, pausa, reinicio, ...).
2. Si no está en pausa y pasó ``intervalo_real_turno_s``, ejecuta un turno.
3. Publica la instantánea versionada y registra un latido (health check).

    python -m api.worker
"""
from __future__ import annotations

import logging
import os
import random
import signal
import threading
import time
import uuid

from api import metricas
from api.persistencia import BaseDatos, ahora
from estructuras.geografia import haversine_metros
from config.ajustes import Ajustes, cargar_ajustes
from datos.red_vial import cargar_red_vial
from simulacion.despachador import ResultadoAsignacion
from simulacion.errores import ErrorLimaGo
from simulacion.aceptacion import resumen_oferta
from simulacion.modelos import EstadoConductor, Pasajero
from simulacion.reloj import nivel_trafico
from simulacion.tarifas import calcular_tarifa, estimar_viaje, parametros_tarifa
from simulacion.ubicacion import Distritos
from simulacion.turnos import Evento, Simulador

registro = logging.getLogger("limago.worker")
ESTADOS_SOLICITUD = {"asignado": "asignada", "sin_conductores": "sin_conductores", "sin_ruta": "sin_ruta",
                     "buscando": "buscando"}
VIGENCIA_COTIZACION_S = 300


class Trabajador:
    def __init__(self, ajustes: Ajustes, base_datos: BaseDatos, grafo=None) -> None:
        self.ajustes = ajustes
        self.bd = base_datos
        self.grafo = grafo if grafo is not None else cargar_red_vial(ajustes)
        self.nodos_validos = self.grafo.componente_principal()
        self.distritos = Distritos(ajustes.ruta_distritos)
        self.simulador: Simulador | None = None
        self._detener = threading.Event()
        self._ultimo_turno = 0.0
        self._ultimo_latido = 0.0

    # ------------------------------------------------------------- arranque
    def iniciar(self) -> None:
        self.bd.crear_tablas()
        estado = self.bd.leer_estado()
        if estado is not None:
            try:
                self.simulador = Simulador.desde_instantanea(self.grafo, self.ajustes, estado["instantanea"],
                                                             self.nodos_validos)
                registro.info("Simulación restaurada en el turno %s", self.simulador.turno)
            except (KeyError, ValueError) as error:  # instantánea de otra red o versión
                registro.warning("No se pudo restaurar la instantánea (%s); se inicia de cero", error)
                self.simulador = None
        if self.simulador is None:
            self.simulador = Simulador(self.grafo, self.ajustes, None, self.nodos_validos)
            self._interrumpir_activas("La simulación se reinició")
        self.simulador.proxima_solicitud_id = max(self.simulador.proxima_solicitud_id, self.bd.max_id_solicitud() + 1)
        self.publicar()

    def _interrumpir_activas(self, motivo: str) -> None:
        for fila in self.bd.solicitudes_activas():
            self.bd.actualizar_solicitud(fila["id"], estado="interrumpida", mensaje=motivo)

    # ------------------------------------------------------------- comandos
    def procesar_comandos(self) -> int:
        pendientes = self.bd.comandos_pendientes()
        for comando in pendientes:
            try:
                resultado = self.ejecutar(comando["tipo"], comando["carga"] or {})
                self.bd.cerrar_comando(comando["id"], "hecho", resultado)
                metricas.COMANDOS.labels(comando["tipo"], "hecho").inc()
            except (ErrorLimaGo, ValueError) as error:
                codigo = getattr(error, "codigo", "datos_invalidos")
                self.bd.cerrar_comando(comando["id"], "error", None, codigo, str(error))
                metricas.COMANDOS.labels(comando["tipo"], "error").inc()
            except Exception as error:  # noqa: BLE001 - un comando malo no detiene el worker
                registro.exception("Error al ejecutar el comando %s", comando["id"])
                self.bd.cerrar_comando(comando["id"], "error", None, "error_interno", str(error))
                metricas.COMANDOS.labels(comando["tipo"], "error_interno").inc()
        if pendientes:
            self.publicar()
        return len(pendientes)

    def ejecutar(self, tipo: str, carga: dict) -> dict:
        sim = self.simulador
        if tipo == "solicitar_viaje":
            return self._solicitar_viaje(carga)
        if tipo == "cancelar_viaje":
            return self._cancelar_viaje(int(carga["solicitud_id"]))
        if tipo == "cotizar":
            return self._cotizar(carga)
        if tipo == "alerta":
            return self._alerta(int(carga["solicitud_id"]))
        if tipo == "atender_alerta":
            return self._atender_alerta(int(carga["alerta_id"]), carga.get("nota", ""))
        if tipo == "asignar_lote":
            return self._asignar_lote(carga)
        if tipo == "lote_aleatorio":
            return self._lote_aleatorio(int(carga.get("cantidad", 5)), carga.get("estrategia", "optima"))
        if tipo == "configurar":
            configuracion = sim.configurar(carga.get("congestion_activa"), carga.get("hora"),
                                           carga.get("tasa_solicitudes_por_turno"), carga.get("k_candidatos"),
                                           carga.get("reloj_lima"))
            return {"turno": sim.turno, "en_pausa": sim.en_pausa, "semilla": sim.semilla,
                    "hora_simulada": sim.hora_simulada, "configuracion": configuracion}
        if tipo == "pausar":
            sim.pausar()
        elif tipo == "reanudar":
            sim.reanudar()
        elif tipo == "avanzar":
            for _ in range(max(1, min(int(carga.get("turnos", 1)), 500))):
                self._turno()
        elif tipo == "reiniciar":
            sim.reiniciar(carga.get("semilla"), carga.get("num_conductores"))
            sim.proxima_solicitud_id = max(sim.proxima_solicitud_id, self.bd.max_id_solicitud() + 1)
            self._interrumpir_activas("El escenario se reinició")
        else:
            raise ValueError(f"Comando desconocido: {tipo}")
        return {"turno": sim.turno, "en_pausa": sim.en_pausa, "semilla": sim.semilla}

    def _registrar_resultado(self, solicitud_id: int, canal: str, resultado: ResultadoAsignacion,
                             origen_texto: str, destino_texto: str) -> dict:
        p = resultado.pasajero
        sel = resultado.seleccionado
        metricas.registrar_asignacion(canal, resultado)
        viaje = {}
        if sel is not None and p.destino_lat is not None:
            despachador = self.simulador.despachador
            estimacion = estimar_viaje(self.grafo, despachador.ubicador, (p.lat, p.lon), (p.destino_lat, p.destino_lon),
                                       despachador.velocidad_kmh,
                                       despachador.hora_actual if despachador.pesos_dinamicos else None,
                                       despachador.pesos_dinamicos)
            viaje = {"distancia_viaje_m": estimacion.distancia_m, "duracion_viaje_s": estimacion.duracion_s,
                     "tarifa_estimada": estimacion.tarifa["estimada"]}
        fila = dict(
            id=solicitud_id, canal=canal, estado=ESTADOS_SOLICITUD[resultado.estado],
            origen_texto=origen_texto, origen_lat=p.lat, origen_lon=p.lon,
            destino_texto=destino_texto, destino_lat=p.destino_lat, destino_lon=p.destino_lon,
            conductor_id=sel.conductor_id if sel else None, eta_s=sel.eta_s if sel else None,
            distancia_calles_m=sel.distancia_calles_m if sel else None,
            distancia_recta_m=sel.distancia_recta_m if sel else None,
            candidatos=[c.a_diccionario() for c in resultado.candidatos],
            ruta_recogida=[list(punto) for punto in resultado.ruta_coordenadas],
            mensaje=resultado.mensaje, turno_solicitud=self.simulador.turno, **viaje,
        )
        self.bd.insertar_solicitud(**fila)
        return {"solicitud_id": solicitud_id, "estado": fila["estado"], "mensaje": fila["mensaje"],
                "conductor_id": fila["conductor_id"], "eta_s": fila["eta_s"],
                "tarifa_estimada": fila.get("tarifa_estimada")}

    def _solicitar_viaje(self, carga: dict) -> dict:
        sim = self.simulador
        origen = carga["origen"]
        destino = carga.get("destino")
        solicitud_id = sim.nuevo_id_solicitud()
        try:
            pasajero = sim.despachador.crear_pasajero(
                solicitud_id, float(origen["lat"]), float(origen["lon"]), origen.get("direccion", ""),
                (float(destino["lat"]), float(destino["lon"])) if destino else None,
                destino.get("direccion", "") if destino else "")
        except ErrorLimaGo as error:
            metricas.ASIGNACIONES.labels("app", "rechazada").inc()
            self.bd.insertar_solicitud(id=solicitud_id, canal="app", estado="rechazada",
                                       origen_texto=origen.get("direccion", ""), origen_lat=origen.get("lat"),
                                       origen_lon=origen.get("lon"), mensaje=str(error),
                                       turno_solicitud=sim.turno)
            raise
        cotizacion = carga.get("cotizacion")
        if self.simulador.ajustes.motor_aceptacion:
            return self._solicitar_con_aceptacion(solicitud_id, pasajero, origen, destino, cotizacion)
        resultado = sim.solicitar_viaje(pasajero, solicitud_id, k=carga.get("k"))
        respuesta = self._registrar_resultado(solicitud_id, "app", resultado, origen.get("direccion", ""),
                                              destino.get("direccion", "") if destino else "")
        if cotizacion:  # la tarifa se fija con la cotización confirmada
            self.bd.actualizar_solicitud(solicitud_id, tarifa_estimada=cotizacion["tarifa"]["total"],
                                         tarifa_desglose=cotizacion["tarifa"], cotizacion_id=cotizacion["id"])
        return respuesta

    def _distrito(self, lat, lon) -> str | None:
        return self.distritos.distrito_de(lat, lon) if lat is not None and len(self.distritos) else None

    def _solicitar_con_aceptacion(self, solicitud_id: int, pasajero: Pasajero, origen: dict, destino: dict | None,
                                  cotizacion: dict | None) -> dict:
        """V3: se registra la solicitud como «buscando» y se envía la primera oferta (ver simulacion/aceptacion.py)."""
        sim = self.simulador
        oferta = sim.solicitar_con_aceptacion(pasajero, solicitud_id)
        tarifa = cotizacion["tarifa"] if cotizacion else None
        fila = dict(id=solicitud_id, canal="app", origen_texto=origen.get("direccion", ""), origen_lat=pasajero.lat,
                    origen_lon=pasajero.lon, destino_texto=destino.get("direccion", "") if destino else "",
                    destino_lat=pasajero.destino_lat, destino_lon=pasajero.destino_lon, turno_solicitud=sim.turno,
                    distrito_origen=self._distrito(pasajero.lat, pasajero.lon),
                    distrito_destino=self._distrito(pasajero.destino_lat, pasajero.destino_lon),
                    tarifa_estimada=tarifa["total"] if tarifa else None, tarifa_desglose=tarifa,
                    cotizacion_id=cotizacion["id"] if cotizacion else None,
                    distancia_viaje_m=cotizacion["distancia_m"] if cotizacion else None,
                    duracion_viaje_s=cotizacion["duracion_s"] if cotizacion else None)
        if oferta is None:
            metricas.ASIGNACIONES.labels("app", "sin_conductores").inc()
            self.bd.insertar_solicitud(estado="sin_conductores", mensaje="No hay conductores disponibles cerca", **fila)
            return {"solicitud_id": solicitud_id, "estado": "sin_conductores"}
        metricas.OFERTAS.labels("enviada").inc()
        academico = oferta.academico
        self.bd.insertar_solicitud(estado="buscando", mensaje="Buscando conductor",
                                   candidatos=[{k: v for k, v in c.items() if k != "ruta"} for c in oferta.candidatos],
                                   conductor_academico_id=academico["conductor_id"],
                                   eta_academico_s=academico["eta_s"], **fila)
        return {"solicitud_id": solicitud_id, "estado": "buscando", "candidatos": len(oferta.candidatos)}

    def _cotizar(self, carga: dict) -> dict:
        """V3: ruta, duración con el tráfico de la hora actual, recogida estimada y tarifa (se guarda 5 min)."""
        sim = self.simulador
        despachador = sim.despachador
        o, d = carga["origen"], carga["destino"]
        nodo_o, _ = despachador.ubicar_en_red(float(o["lat"]), float(o["lon"]))
        despachador.ubicar_en_red(float(d["lat"]), float(d["lon"]))
        parametros = parametros_tarifa(sim.ajustes)
        hora = despachador.hora_actual
        estimacion = estimar_viaje(self.grafo, despachador.ubicador, (o["lat"], o["lon"]), (d["lat"], d["lon"]),
                                   despachador.velocidad_kmh, hora if despachador.pesos_dinamicos else None,
                                   despachador.pesos_dinamicos, 0.0, parametros)
        pasajero = Pasajero(0, float(o["lat"]), float(o["lon"]), nodo=nodo_o)
        with despachador._candado:  # solo lectura: no reserva conductores
            candidatos = despachador.buscar_candidatos(pasajero)
            despachador.calcular_eta(pasajero, candidatos)
        mejor = despachador.elegir_mejor(candidatos)
        recogida_m = mejor.distancia_calles_m if mejor else 0.0
        tarifa = calcular_tarifa(estimacion.distancia_m, estimacion.duracion_s, recogida_m, parametros)
        datos = {
            "id": uuid.uuid4().hex,
            "origen": {**o, "distrito": self._distrito(o["lat"], o["lon"])},
            "destino": {**d, "distrito": self._distrito(d["lat"], d["lon"])},
            "distancia_m": estimacion.distancia_m, "duracion_s": estimacion.duracion_s,
            "ruta": [list(p) for p in self.grafo.geometria_ruta(estimacion.ruta)],
            "recogida": {"conductores_cerca": sum(c.alcanzable for c in candidatos),
                         "eta_s": mejor.eta_s if mejor else None, "distancia_m": recogida_m},
            "tarifa": tarifa,
            "trafico": {"hora": hora, "nivel": nivel_trafico(hora) if despachador.pesos_dinamicos else "sin_ajuste",
                        "modelo": "simulado_por_horario" if despachador.pesos_dinamicos else "velocidad_promedio",
                        "reloj": sim.ajustes.reloj},
            "vigencia_s": VIGENCIA_COTIZACION_S,
        }
        self.bd.guardar_cotizacion(datos["id"], datos)
        return datos

    def _cancelar_viaje(self, solicitud_id: int) -> dict:
        despachador = self.simulador.despachador
        if self.simulador.motor.cancelar(solicitud_id):  # aún se buscaba conductor
            self.bd.actualizar_solicitud(solicitud_id, estado="cancelada", mensaje="Cancelada por el pasajero",
                                         turno_fin=self.simulador.turno)
            return {"solicitud_id": solicitud_id, "estado": "cancelada"}
        for conductor in despachador.conductores.values():
            if conductor.solicitud_id == solicitud_id:
                if conductor.estado is EstadoConductor.EN_VIAJE:
                    raise ErrorLimaGo("El viaje ya está en curso y no puede cancelarse")
                despachador.liberar_conductor(conductor.id)
                break
        self.bd.actualizar_solicitud(solicitud_id, estado="cancelada", mensaje="Cancelada por el pasajero",
                                     turno_fin=self.simulador.turno)
        return {"solicitud_id": solicitud_id, "estado": "cancelada"}

    def _asignar_lote(self, carga: dict) -> dict:
        """Reto C: varios pasajeros a la vez minimizando la espera total."""
        sim = self.simulador
        estrategia = carga.get("estrategia", "optima")
        pasajeros, ids = [], []
        for punto in carga["pasajeros"]:
            sid = sim.nuevo_id_solicitud()
            pasajeros.append(sim.despachador.crear_pasajero(sid, float(punto["lat"]), float(punto["lon"]),
                                                            punto.get("direccion", "")))
            ids.append(sid)
        plan = sim.despachador.asignar_varios(pasajeros, estrategia=estrategia)
        comparacion = sim.despachador.asignar_varios(
            pasajeros, estrategia="codiciosa" if estrategia == "optima" else "optima")
        resultados = sim.despachador.confirmar_asignaciones(pasajeros, plan, ids)
        for sid, resultado in zip(ids, resultados):
            self._registrar_resultado(sid, carga.get("canal", "operaciones"), resultado, resultado.pasajero.direccion, "")
        return {"solicitudes": ids, "estrategia": estrategia, "espera_total_s": plan["espera_total_s"],
                "espera_total_alternativa_s": comparacion["espera_total_s"], "asignaciones": plan["asignaciones"]}

    def _lote_aleatorio(self, cantidad: int, estrategia: str) -> dict:
        """Genera ``cantidad`` pasajeros simultáneos alrededor de un punto (p. ej. la salida de un evento).

        Usa un generador propio sembrado con (semilla, turno, cantidad) para no alterar la
        secuencia aleatoria de la simulación y para que el lote sea reproducible.
        """
        if not 2 <= cantidad <= 30:
            raise ValueError("El lote debe tener entre 2 y 30 pasajeros")
        if estrategia not in {"optima", "codiciosa"}:
            raise ValueError("Estrategia desconocida")
        sim = self.simulador
        generador = random.Random(f"{sim.semilla}-{sim.turno}-{cantidad}")
        nodos = sorted(self.nodos_validos)
        centro = generador.choice(nodos)
        clat, clon = self.grafo.coordenadas(centro)
        cercanos = [n for n in nodos if haversine_metros(clat, clon, *self.grafo.coordenadas(n)) <= 600]
        elegidos = generador.sample(cercanos, min(cantidad, len(cercanos)))
        puntos = [{"lat": self.grafo.coordenadas(n)[0], "lon": self.grafo.coordenadas(n)[1],
                   "direccion": f"Pasajero {i + 1} del lote"} for i, n in enumerate(elegidos)]
        resultado = self._asignar_lote({"pasajeros": puntos, "estrategia": estrategia})
        resultado["centro"] = [clat, clon]
        return resultado

    # ------------------------------------------------------------- alertas
    def _alerta(self, solicitud_id: int) -> dict:
        """Alerta de seguridad **de demostración**: se registra y se asigna la unidad simulada más cercana."""
        solicitud = self.bd.obtener_solicitud(solicitud_id)
        if solicitud is None or solicitud["estado"] not in ("asignada", "esperando_recogida", "en_viaje"):
            raise ErrorLimaGo("La alerta solo está disponible durante un viaje activo")
        existente = self.bd.alerta_abierta(solicitud_id)
        if existente:
            return {**_serializable(existente), "duplicada": True}
        conductor = self.simulador.despachador.conductores.get(solicitud["conductor_id"])
        if solicitud["estado"] == "en_viaje" and conductor is not None:
            lat, lon, _ = (self.grafo.punto_en_tramo(conductor.nodo, conductor.ruta[0], conductor.avance_m)
                           if conductor.ruta else (conductor.lat, conductor.lon, 0))
        else:
            lat, lon = solicitud["origen_lat"], solicitud["origen_lon"]
        alerta_id = self.bd.crear_alerta(solicitud_id=solicitud_id, lat=lat, lon=lon, estado_viaje=solicitud["estado"],
                                         conductor_id=solicitud["conductor_id"])
        asignada = self.simulador.apoyo.asignar_mas_cercana(lat, lon, alerta_id)
        if asignada:
            unidad, distancia = asignada
            self.bd.actualizar_alerta(alerta_id, unidad=unidad.codigo, distancia_unidad_m=distancia)
        metricas.ALERTAS.labels("abierta").inc()
        return {**_serializable(self.bd.alerta(alerta_id)), "duplicada": False}

    def _atender_alerta(self, alerta_id: int, nota: str) -> dict:
        alerta = self.bd.atender_alerta(alerta_id, nota)
        if alerta is None:
            raise ErrorLimaGo("No existe esa alerta")
        self.simulador.apoyo.liberar(alerta_id)
        metricas.ALERTAS.labels("atendida").inc()
        return _serializable(alerta)

    # --------------------------------------------------------------- turnos
    def _turno(self) -> list[Evento]:
        sim = self.simulador
        inicio = time.perf_counter()
        eventos = sim.avanzar_turno()
        metricas.DURACION_TURNO.observe(time.perf_counter() - inicio)
        metricas.TURNOS.inc()
        for evento in eventos:
            if evento.solicitud_id is None:
                continue
            if evento.tipo == "recogida":
                conductor = sim.despachador.conductores[evento.conductor_id]
                ruta = self.grafo.geometria_ruta([conductor.nodo] + conductor.ruta)
                self.bd.actualizar_solicitud(evento.solicitud_id, estado="en_viaje", turno_recogida=sim.turno,
                                             ruta_viaje=[list(p) for p in ruta], recogida_en=ahora(),
                                             distancia_viaje_m=self.grafo.longitud_ruta([conductor.nodo] + conductor.ruta))
            elif evento.tipo == "viaje_finalizado":
                self.bd.actualizar_solicitud(evento.solicitud_id, estado="completada", turno_fin=sim.turno,
                                             mensaje="Viaje completado", finalizada_en=ahora())
                metricas.VIAJES_COMPLETADOS.inc()
            elif evento.tipo == "llegada_recogida":
                self.bd.actualizar_solicitud(evento.solicitud_id, estado="esperando_recogida",
                                             mensaje="El conductor llegó al punto de recojo")
            elif evento.tipo == "oferta_aceptada":
                self._oferta_aceptada(evento)
            elif evento.tipo in ("oferta_rechaza", "oferta_vencida"):
                metricas.OFERTAS.labels(evento.tipo.removeprefix("oferta_")).inc()
            elif evento.tipo == "sin_aceptacion":
                oferta = evento.datos["oferta"]
                metricas.OFERTAS.labels("sin_aceptacion").inc()
                self.bd.actualizar_solicitud(evento.solicitud_id, estado="sin_aceptacion", intentos=oferta["intentos"],
                                             mensaje="Ningún conductor cercano aceptó el viaje", turno_fin=sim.turno)
            elif evento.tipo == "solicitud_simulada":
                datos = evento.datos
                metricas.ASIGNACIONES.labels("simulacion", datos["estado"]).inc()
                if datos["eta_s"] is not None:
                    metricas.ETA_ASIGNACION.labels("simulacion").observe(datos["eta_s"])
                self.bd.insertar_solicitud(
                    id=evento.solicitud_id, canal="simulacion",
                    estado=ESTADOS_SOLICITUD.get(datos["estado"], "sin_conductores"),
                    origen_texto="Demanda simulada", origen_lat=datos["origen"][0], origen_lon=datos["origen"][1],
                    destino_lat=datos["destino"][0], destino_lon=datos["destino"][1],
                    conductor_id=evento.conductor_id, eta_s=datos["eta_s"],
                    distancia_calles_m=datos["distancia_calles_m"], mensaje="Demanda simulada",
                    turno_solicitud=sim.turno)
        self._ultimo_turno = time.monotonic()
        return eventos

    def _oferta_aceptada(self, evento) -> None:
        oferta = evento.datos["oferta"]
        elegido = oferta["candidatos"][oferta["indice"]]
        resumen = resumen_oferta(oferta)
        metricas.OFERTAS.labels("aceptada").inc()
        metricas.ETA_ASIGNACION.labels("aceptada").observe(resumen["eta_operativo_s"])
        metricas.ACEPTACION_COINCIDE.labels("si" if resumen["coincide"] else "no").inc()
        self.bd.actualizar_solicitud(
            evento.solicitud_id, estado="asignada", conductor_id=elegido["conductor_id"],
            eta_s=elegido["eta_confirmado_s"], distancia_calles_m=elegido["distancia_confirmada_m"],
            distancia_recta_m=elegido["distancia_recta_m"], intentos=oferta["intentos"],
            ruta_recogida=[list(p) for p in self.grafo.geometria_ruta(elegido["ruta"])],
            mensaje=f"Conductor LG-{elegido['conductor_id']:05d} aceptó el viaje", asignada_en=ahora())

    def publicar(self) -> None:
        self.bd.guardar_instantanea(self.simulador.instantanea())
        metricas.actualizar_estado_simulacion(self.simulador)
        self._ultimo_latido = time.monotonic()

    def paso(self) -> None:
        """Una iteración del bucle (útil en pruebas)."""
        cambios = self.procesar_comandos()
        if not self.simulador.en_pausa and time.monotonic() - self._ultimo_turno >= self.ajustes.intervalo_real_turno_s:
            self._turno()
            self.publicar()
        elif not cambios and time.monotonic() - self._ultimo_latido >= 2.0:
            self.bd.latido()
            self._ultimo_latido = time.monotonic()

    def ejecutar_bucle(self, espera_s: float = 0.1) -> None:
        self.iniciar()
        registro.info("Worker listo: %s", self.grafo.resumen())
        while not self._detener.is_set():
            self.paso()
            self._detener.wait(espera_s)

    def detener(self) -> None:
        self._detener.set()


def _serializable(fila: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in fila.items()}


def principal() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ajustes = cargar_ajustes()
    puerto = int(os.getenv("LIMAGO_PUERTO_METRICAS_WORKER", "9100"))
    if puerto > 0:
        from prometheus_client import start_http_server

        start_http_server(puerto, registry=metricas.REGISTRO_WORKER)
        registro.info("Métricas del worker en :%s/metrics", puerto)
    trabajador = Trabajador(ajustes, BaseDatos(ajustes.url_base_datos))
    signal.signal(signal.SIGTERM, lambda *_: trabajador.detener())
    signal.signal(signal.SIGINT, lambda *_: trabajador.detener())
    trabajador.ejecutar_bucle()


if __name__ == "__main__":
    principal()
