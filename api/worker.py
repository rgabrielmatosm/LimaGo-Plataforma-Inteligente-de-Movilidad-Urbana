"""Worker de simulación: único dueño de la flota (ver ``api/persistencia.py``).

Bucle:
1. Atiende los comandos pendientes en orden (solicitudes, pausa, reinicio, ...).
2. Si no está en pausa y pasó ``intervalo_real_turno_s``, ejecuta un turno.
3. Publica la instantánea versionada y registra un latido (health check).

    python -m api.worker
"""
from __future__ import annotations

import logging
import signal
import threading
import time

from api.persistencia import BaseDatos
from config.ajustes import Ajustes, cargar_ajustes
from datos.red_vial import cargar_red_vial
from simulacion.despachador import ResultadoAsignacion
from simulacion.errores import ErrorLimaGo
from simulacion.modelos import EstadoConductor
from simulacion.turnos import Evento, Simulador

registro = logging.getLogger("limago.worker")
ESTADOS_SOLICITUD = {"asignado": "asignada", "sin_conductores": "sin_conductores", "sin_ruta": "sin_ruta"}


class Trabajador:
    def __init__(self, ajustes: Ajustes, base_datos: BaseDatos, grafo=None) -> None:
        self.ajustes = ajustes
        self.bd = base_datos
        self.grafo = grafo if grafo is not None else cargar_red_vial(ajustes)
        self.nodos_validos = self.grafo.componente_principal()
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
            except ErrorLimaGo as error:
                self.bd.cerrar_comando(comando["id"], "error", None, error.codigo, str(error))
            except Exception as error:  # noqa: BLE001 - un comando malo no detiene el worker
                registro.exception("Error al ejecutar el comando %s", comando["id"])
                self.bd.cerrar_comando(comando["id"], "error", None, "error_interno", str(error))
        if pendientes:
            self.publicar()
        return len(pendientes)

    def ejecutar(self, tipo: str, carga: dict) -> dict:
        sim = self.simulador
        if tipo == "solicitar_viaje":
            return self._solicitar_viaje(carga)
        if tipo == "cancelar_viaje":
            return self._cancelar_viaje(int(carga["solicitud_id"]))
        if tipo == "asignar_lote":
            return self._asignar_lote(carga)
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
        fila = dict(
            id=solicitud_id, canal=canal, estado=ESTADOS_SOLICITUD[resultado.estado],
            origen_texto=origen_texto, origen_lat=p.lat, origen_lon=p.lon,
            destino_texto=destino_texto, destino_lat=p.destino_lat, destino_lon=p.destino_lon,
            conductor_id=sel.conductor_id if sel else None, eta_s=sel.eta_s if sel else None,
            distancia_calles_m=sel.distancia_calles_m if sel else None,
            distancia_recta_m=sel.distancia_recta_m if sel else None,
            candidatos=[c.a_diccionario() for c in resultado.candidatos],
            ruta_recogida=[list(punto) for punto in resultado.ruta_coordenadas],
            mensaje=resultado.mensaje, turno_solicitud=self.simulador.turno,
        )
        self.bd.insertar_solicitud(**fila)
        return {"solicitud_id": solicitud_id, "estado": fila["estado"], "mensaje": fila["mensaje"],
                "conductor_id": fila["conductor_id"], "eta_s": fila["eta_s"]}

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
            self.bd.insertar_solicitud(id=solicitud_id, canal="app", estado="rechazada",
                                       origen_texto=origen.get("direccion", ""), origen_lat=origen.get("lat"),
                                       origen_lon=origen.get("lon"), mensaje=str(error),
                                       turno_solicitud=sim.turno)
            raise
        resultado = sim.solicitar_viaje(pasajero, solicitud_id, k=carga.get("k"))
        return self._registrar_resultado(solicitud_id, "app", resultado, origen.get("direccion", ""),
                                         destino.get("direccion", "") if destino else "")

    def _cancelar_viaje(self, solicitud_id: int) -> dict:
        despachador = self.simulador.despachador
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
            self._registrar_resultado(sid, "app", resultado, resultado.pasajero.direccion, "")
        return {"solicitudes": ids, "estrategia": estrategia, "espera_total_s": plan["espera_total_s"],
                "espera_total_alternativa_s": comparacion["espera_total_s"], "asignaciones": plan["asignaciones"]}

    # --------------------------------------------------------------- turnos
    def _turno(self) -> list[Evento]:
        sim = self.simulador
        eventos = sim.avanzar_turno()
        for evento in eventos:
            if evento.solicitud_id is None:
                continue
            if evento.tipo == "recogida":
                conductor = sim.despachador.conductores[evento.conductor_id]
                ruta = self.grafo.geometria_ruta([conductor.nodo] + conductor.ruta)
                self.bd.actualizar_solicitud(evento.solicitud_id, estado="en_viaje", turno_recogida=sim.turno,
                                             ruta_viaje=[list(p) for p in ruta])
            elif evento.tipo == "viaje_finalizado":
                self.bd.actualizar_solicitud(evento.solicitud_id, estado="completada", turno_fin=sim.turno,
                                             mensaje="Viaje completado")
            elif evento.tipo == "solicitud_simulada":
                datos = evento.datos
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

    def publicar(self) -> None:
        self.bd.guardar_instantanea(self.simulador.instantanea())
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


def principal() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ajustes = cargar_ajustes()
    trabajador = Trabajador(ajustes, BaseDatos(ajustes.url_base_datos))
    signal.signal(signal.SIGTERM, lambda *_: trabajador.detener())
    signal.signal(signal.SIGINT, lambda *_: trabajador.detener())
    trabajador.ejecutar_bucle()


if __name__ == "__main__":
    principal()
