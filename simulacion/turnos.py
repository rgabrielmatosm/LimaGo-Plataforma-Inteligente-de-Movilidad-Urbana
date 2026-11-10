"""RF-06 — Simulación por turnos.

En cada turno (``segundos_por_turno`` de tiempo simulado):

1. El reloj simulado avanza.
2. Cada conductor (en orden de id, para que sea determinista) recorre su
   presupuesto de distancia **solo por aristas existentes** del grafo dirigido:
   * disponible → deambula por calles vecinas (paseo aleatorio con semilla);
   * en camino  → sigue la ruta asignada hasta el pasajero; al llegar pasa a "en viaje";
   * en viaje   → sigue la ruta al destino; al llegar queda disponible.
   Tras moverse se actualiza el Quadtree mediante ``Despachador.mover_conductor``.
3. Con cierta probabilidad aparece una solicitud simulada que se asigna con el
   mismo Despachador (demanda de fondo para que los estados cambien).

Las posiciones siempre son intersecciones; el avance parcial sobre un tramo se
acumula en ``avance_m``. Así no hay saltos imposibles ni posiciones fuera de la red.

V3 (solo si el escenario lo activa; Miraflores académico no cambia):

* **Motor de aceptación** (``simulacion/aceptacion.py``): las solicitudes se
  ofrecen a los candidatos por orden de ETA y cada turno se resuelven las respuestas.
* **Espera en el punto de recojo** (``turnos_espera_recogida``) y estado ``finalizado``.
* **Desconexiones/reconexiones** reproducibles de conductores disponibles.
* **Reloj de Lima**: la hora del tráfico simulado es la hora local real.
* **Movimiento por tiempo**: con congestión activa cada tramo se recorre con el
  tiempo de su peso horario, coherente con el ETA calculado.
* **Destinos cercanos** para la demanda simulada y **tope de rutas por turno**,
  para que la simulación sobre toda Lima siga siendo fluida.
* **Unidades de apoyo simuladas** para la alerta de seguridad de demostración.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from algoritmos.congestion import tiempo_arista
from algoritmos.dijkstra import dijkstra, reconstruir_ruta
from config.ajustes import Ajustes
from estructuras.geografia import Rectangulo
from simulacion.aceptacion import MotorAceptacion, asignar_politicas
from simulacion.alertas import UnidadesApoyo
from simulacion.despachador import Despachador, ResultadoAsignacion
from simulacion.flota import generar_flota
from simulacion.modelos import Conductor, EstadoConductor, Pasajero
from simulacion.reloj import hora_lima

MAX_RUTAS_POR_TURNO_LIMA = 60


@dataclass
class Evento:
    tipo: str
    turno: int
    conductor_id: int | None = None
    solicitud_id: int | None = None
    datos: dict = field(default_factory=dict)

    def a_diccionario(self) -> dict:
        return {"tipo": self.tipo, "turno": self.turno, "conductor_id": self.conductor_id,
                "solicitud_id": self.solicitud_id, "datos": self.datos}


class Simulador:
    def __init__(self, grafo, ajustes: Ajustes, conductores: list[Conductor] | None = None,
                 nodos_validos: set[int] | None = None) -> None:
        self.grafo = grafo
        self.ajustes = ajustes
        self.nodos_validos = nodos_validos if nodos_validos is not None else grafo.componente_principal()
        self._nodos_ordenados = sorted(self.nodos_validos)
        self.semilla = ajustes.semilla
        self.generador = random.Random(ajustes.semilla)
        self.turno = 0
        self.en_pausa = False
        self.proxima_solicitud_id = 1
        self.ultimos_eventos: list[Evento] = []
        nueva = conductores is None
        flota = conductores if conductores is not None else generar_flota(
            grafo, ajustes.num_conductores, ajustes.semilla, ajustes.proporcion_ocupados, self.nodos_validos)
        if nueva and ajustes.motor_aceptacion:
            asignar_politicas(flota, ajustes.semilla, ajustes.distribucion_politicas)
        self.despachador = Despachador(grafo, flota, ajustes, self.nodos_validos)
        if nueva and ajustes.radio_destino_simulado_m:
            self._destinos_iniciales_cercanos(flota)
        self.motor = MotorAceptacion(self.despachador, ajustes.semilla, ajustes.plazo_oferta_turnos,
                                     ajustes.probabilidad_aceptacion)
        self.apoyo = UnidadesApoyo(grafo, self.nodos_validos, ajustes.unidades_apoyo, ajustes.semilla)
        self.rutas_pendientes = 0  # conductores en viaje que esperan cálculo de ruta (tope por turno)
        if ajustes.reloj == "lima":
            self.despachador.hora_actual = hora_lima()

    def _destinos_iniciales_cercanos(self, flota: list[Conductor]) -> None:
        """En Lima, los conductores que empiezan en viaje van a un destino cercano (generador propio)."""
        generador = random.Random(f"destinos-{self.ajustes.semilla}")
        for conductor in flota:
            if conductor.estado is EstadoConductor.EN_VIAJE:
                conductor.destino_nodo = self._nodo_cercano(conductor.lat, conductor.lon, generador)

    def _nodo_cercano(self, lat: float, lon: float, generador: random.Random) -> int:
        """Intersección al azar a menos de ``radio_destino_simulado_m`` (búsqueda rectangular del Quadtree)."""
        caja = Rectangulo.alrededor(lat, lon, self.ajustes.radio_destino_simulado_m)
        indice = self.despachador.indice_intersecciones
        recortada = Rectangulo(max(caja.lon_min, indice.limites.lon_min), max(caja.lat_min, indice.limites.lat_min),
                               min(caja.lon_max, indice.limites.lon_max), min(caja.lat_max, indice.limites.lat_max))
        cercanos = sorted(indice.buscar_rectangulo(recortada))
        return generador.choice(cercanos) if cercanos else generador.choice(self._nodos_ordenados)

    # ---------------------------------------------------------------- tiempo
    @property
    def hora_simulada(self) -> float:
        return self.despachador.hora_actual

    def _velocidad_ms(self) -> float:
        return self.ajustes.velocidad_promedio_kmh / 3.6

    # ------------------------------------------------------------ control
    def pausar(self) -> None:
        self.en_pausa = True

    def reanudar(self) -> None:
        self.en_pausa = False

    def reiniciar(self, semilla: int | None = None, num_conductores: int | None = None) -> None:
        """Vuelve al turno 0 con la flota que genera la semilla (escenario reproducible)."""
        cambios = {}
        if semilla is not None:
            cambios["semilla"] = int(semilla)
        if num_conductores is not None:
            cambios["num_conductores"] = int(num_conductores)
        self.ajustes = self.ajustes.con(**cambios) if cambios else self.ajustes
        proximo_id = self.proxima_solicitud_id
        self.__init__(self.grafo, self.ajustes, None, self.nodos_validos)
        self.proxima_solicitud_id = proximo_id  # los ids de solicitudes nunca se repiten

    def configurar(self, congestion_activa: bool | None = None, hora: float | None = None,
                   tasa_solicitudes_por_turno: float | None = None, k_candidatos: int | None = None,
                   reloj_lima: bool | None = None) -> dict:
        """Cambia el escenario sin reiniciar la flota (centro de operaciones)."""
        cambios = {}
        if tasa_solicitudes_por_turno is not None:
            if not 0 <= tasa_solicitudes_por_turno <= 50:
                raise ValueError("La demanda debe estar entre 0 y 50 solicitudes por turno")
            cambios["tasa_solicitudes_por_turno"] = float(tasa_solicitudes_por_turno)
        if k_candidatos is not None:
            if not 1 <= k_candidatos <= 50:
                raise ValueError("k debe estar entre 1 y 50")
            cambios["k_candidatos"] = int(k_candidatos)
        if congestion_activa is not None:
            cambios["congestion_activa"] = bool(congestion_activa)
        self.ajustes = self.ajustes.con(**cambios) if cambios else self.ajustes
        self.despachador.ajustes = self.ajustes
        if hora is not None and self.ajustes.reloj == "lima":
            self.ajustes = self.ajustes.con(reloj="simulado")  # el operador fijó una hora: el reloj deja de seguir a Lima
            self.despachador.ajustes = self.ajustes
        if reloj_lima and hora is None:
            self.ajustes = self.ajustes.con(reloj="lima")  # vuelve a seguir la hora local de Lima
            self.despachador.ajustes = self.ajustes
            hora = hora_lima()
        self.despachador.configurar_congestion(self.ajustes.congestion_activa, hora)
        return self.configuracion()

    def configuracion(self) -> dict:
        return {
            "congestion_activa": self.ajustes.congestion_activa,
            "tasa_solicitudes_por_turno": self.ajustes.tasa_solicitudes_por_turno,
            "k_candidatos": self.ajustes.k_candidatos,
            "velocidad_promedio_kmh": self.ajustes.velocidad_promedio_kmh,
            "segundos_por_turno": self.ajustes.segundos_por_turno,
            "reloj": self.ajustes.reloj,
            "motor_aceptacion": self.ajustes.motor_aceptacion,
            "escenario": self.ajustes.escenario,
        }

    def nuevo_id_solicitud(self) -> int:
        identificador = self.proxima_solicitud_id
        self.proxima_solicitud_id += 1
        return identificador

    # ------------------------------------------------------------ solicitudes
    def solicitar_viaje(self, pasajero: Pasajero, solicitud_id: int | None = None, k: int | None = None) -> ResultadoAsignacion:
        if solicitud_id is None:
            solicitud_id = self.nuevo_id_solicitud()
        return self.despachador.solicitar_viaje(pasajero, k=k, solicitud_id=solicitud_id)

    def solicitar_con_aceptacion(self, pasajero: Pasajero, solicitud_id: int, k: int | None = None):
        """V3: inicia la búsqueda con ofertas (capa comercial). ``None`` si no hay candidatos alcanzables."""
        return self.motor.iniciar(pasajero, solicitud_id, self.turno, k)

    def _solicitudes_automaticas(self) -> list[tuple[int, ResultadoAsignacion]]:
        """Demanda de fondo: ``tasa`` solicitudes por turno en promedio (parte entera + Bernoulli)."""
        tasa = max(0.0, self.ajustes.tasa_solicitudes_por_turno)
        cantidad = int(tasa) + (1 if self.generador.random() < tasa - int(tasa) else 0)
        resultados = []
        for _ in range(cantidad):
            origen = self.generador.choice(self._nodos_ordenados)
            if self.ajustes.radio_destino_simulado_m:
                destino = self._nodo_cercano(*self.grafo.coordenadas(origen), self.generador)
            else:
                destino = self.generador.choice(self._nodos_ordenados)
            lat, lon = self.grafo.coordenadas(origen)
            dlat, dlon = self.grafo.coordenadas(destino)
            solicitud_id = self.nuevo_id_solicitud()
            pasajero = Pasajero(id=solicitud_id, lat=lat, lon=lon, nodo=origen, distancia_a_red_m=0.0,
                                destino_lat=dlat, destino_lon=dlon, destino_nodo=destino,
                                direccion="Solicitud simulada")
            if self.ajustes.motor_aceptacion:
                oferta = self.motor.iniciar(pasajero, solicitud_id, self.turno)
                resultados.append((solicitud_id, oferta if oferta is not None else
                                   ResultadoAsignacion("sin_conductores", "Sin candidatos", pasajero)))
            else:
                resultados.append((solicitud_id, self.despachador.solicitar_viaje(pasajero, solicitud_id=solicitud_id)))
        return resultados

    # -------------------------------------------------------------- rutas
    def _ruta(self, origen: int, destino: int) -> list[int]:
        """Ruta por calles (Dijkstra propio) sin el nodo de origen."""
        if origen == destino:
            return []
        resultado = dijkstra(self.grafo.adyacencia, origen, objetivos=[destino])
        ruta = reconstruir_ruta(resultado.predecesores, origen, destino)
        return ruta[1:] if ruta else []

    def _siguiente_paseo(self, conductor: Conductor) -> list[int]:
        vecinos = [v for v, _ in self.grafo.adyacencia[conductor.nodo] if v in self.nodos_validos]
        if not vecinos:
            return []
        return [self.generador.choice(sorted(vecinos))]

    # -------------------------------------------------------------- turno
    def avanzar_turno(self) -> list[Evento]:
        """Ejecuta un turno completo y devuelve los eventos ocurridos."""
        self.turno += 1
        if self.ajustes.reloj == "lima":
            self.despachador.hora_actual = hora_lima()
        else:
            self.despachador.hora_actual = (self.despachador.hora_actual + self.ajustes.segundos_por_turno / 3600) % 24
        eventos: list[Evento] = []
        presupuesto = self._velocidad_ms() * self.ajustes.segundos_por_turno
        tope = MAX_RUTAS_POR_TURNO_LIMA if self.ajustes.radio_destino_simulado_m else None
        rutas_calculadas = 0
        self.rutas_pendientes = 0
        if self.ajustes.probabilidad_desconexion or self.ajustes.probabilidad_reconexion:
            self._conexiones(eventos)
        for conductor_id in sorted(self.despachador.conductores):
            conductor = self.despachador.conductores[conductor_id]
            if conductor.estado in (EstadoConductor.DESCONECTADO, EstadoConductor.OFERTA_PENDIENTE):
                continue  # no se mueven: fuera de servicio o decidiendo una oferta
            if conductor.estado is EstadoConductor.ESPERANDO_RECOGIDA:
                self._esperar_recogida(conductor, eventos)
                continue
            if conductor.estado is EstadoConductor.EN_VIAJE and not conductor.ruta and conductor.destino_nodo is not None \
                    and conductor.nodo != conductor.destino_nodo:
                if tope is not None and rutas_calculadas >= tope:
                    self.rutas_pendientes += 1
                    continue
                conductor.ruta = self._ruta(conductor.nodo, conductor.destino_nodo)
                rutas_calculadas += 1
            if conductor.esta_disponible and not conductor.ruta:
                conductor.ruta = self._siguiente_paseo(conductor)
            if self.despachador.pesos_dinamicos is not None:
                self._mover_por_tiempo(conductor, self.ajustes.segundos_por_turno, eventos)
            else:
                self._mover(conductor, presupuesto, eventos)
        for evento in self.motor.procesar_turno(self.turno):
            eventos.append(Evento(evento["tipo"], self.turno, evento.get("conductor_id"), evento["solicitud_id"],
                                  {k: v for k, v in evento.items() if k not in ("tipo", "conductor_id", "solicitud_id")}))
        for solicitud_id, asignacion in self._solicitudes_automaticas():
            if not isinstance(asignacion, ResultadoAsignacion):  # oferta enviada (motor de aceptación)
                eventos.append(Evento("solicitud_simulada", self.turno, None, solicitud_id, {
                    "estado": "buscando", "eta_s": None, "distancia_calles_m": None,
                    "origen": [asignacion.pasajero["lat"], asignacion.pasajero["lon"]],
                    "destino": [asignacion.pasajero["destino_lat"], asignacion.pasajero["destino_lon"]]}))
                continue
            seleccionado = asignacion.seleccionado
            p = asignacion.pasajero
            eventos.append(Evento("solicitud_simulada", self.turno, seleccionado.conductor_id if seleccionado else None,
                                  solicitud_id, {"estado": asignacion.estado,
                                                 "eta_s": seleccionado.eta_s if seleccionado else None,
                                                 "distancia_calles_m": seleccionado.distancia_calles_m if seleccionado else None,
                                                 "origen": [p.lat, p.lon], "destino": [p.destino_lat, p.destino_lon]}))
        self.ultimos_eventos = eventos
        return eventos

    def _mover(self, conductor: Conductor, presupuesto_m: float, eventos: list[Evento]) -> None:
        conductor.avance_m += presupuesto_m
        nodo_final = conductor.nodo
        while conductor.ruta:
            siguiente = conductor.ruta[0]
            longitud = self.grafo.longitud_arista(nodo_final, siguiente)  # KeyError si fuera un salto imposible
            if conductor.avance_m < longitud:
                break
            conductor.avance_m -= longitud
            conductor.distancia_recorrida_m += longitud
            nodo_final = conductor.ruta.pop(0)
        if nodo_final != conductor.nodo:
            self.despachador.mover_conductor(conductor.id, nodo_final)
        if conductor.ruta:
            return
        conductor.avance_m = 0.0 if not conductor.esta_disponible else min(conductor.avance_m, presupuesto_m)
        if conductor.estado is EstadoConductor.EN_CAMINO:
            if self.ajustes.turnos_espera_recogida > 0:
                self.despachador.cambiar_estado(conductor.id, EstadoConductor.ESPERANDO_RECOGIDA)
                conductor.espera_restante = self.ajustes.turnos_espera_recogida
                eventos.append(Evento("llegada_recogida", self.turno, conductor.id, conductor.solicitud_id))
                return
            self._iniciar_viaje(conductor, eventos)
        elif conductor.estado is EstadoConductor.EN_VIAJE and (
                conductor.destino_nodo is None or conductor.nodo == conductor.destino_nodo):
            solicitud = conductor.solicitud_id
            self.despachador.liberar_conductor(conductor.id)
            eventos.append(Evento("viaje_finalizado", self.turno, conductor.id, solicitud))

    def _iniciar_viaje(self, conductor: Conductor, eventos: list[Evento]) -> None:
        destino = conductor.destino_nodo
        if destino is None:
            if self.ajustes.radio_destino_simulado_m:
                destino = self._nodo_cercano(conductor.lat, conductor.lon, self.generador)
            else:
                destino = self.generador.choice(self._nodos_ordenados)
            conductor.destino_nodo = destino
        self.despachador.cambiar_estado(conductor.id, EstadoConductor.EN_VIAJE)
        conductor.ruta = self._ruta(conductor.nodo, destino)
        conductor.avance_m = 0.0
        eventos.append(Evento("recogida", self.turno, conductor.id, conductor.solicitud_id))

    def _esperar_recogida(self, conductor: Conductor, eventos: list[Evento]) -> None:
        conductor.espera_restante -= 1
        if conductor.espera_restante <= 0:
            self._iniciar_viaje(conductor, eventos)

    def _conexiones(self, eventos: list[Evento]) -> None:
        """Desconexión/reconexión reproducible (solo conductores sin viaje)."""
        for conductor_id in sorted(self.despachador.conductores):
            conductor = self.despachador.conductores[conductor_id]
            if conductor.estado is EstadoConductor.DISPONIBLE and self.generador.random() < self.ajustes.probabilidad_desconexion:
                conductor.ruta, conductor.avance_m = [], 0.0
                self.despachador.cambiar_estado(conductor_id, EstadoConductor.DESCONECTADO)
                eventos.append(Evento("desconexion", self.turno, conductor_id))
            elif conductor.estado is EstadoConductor.DESCONECTADO and self.generador.random() < self.ajustes.probabilidad_reconexion:
                self.despachador.cambiar_estado(conductor_id, EstadoConductor.DISPONIBLE)
                eventos.append(Evento("reconexion", self.turno, conductor_id))

    def _mover_por_tiempo(self, conductor: Conductor, segundos: float, eventos: list[Evento]) -> None:
        """Avance con congestión: cada tramo consume el tiempo de su peso horario (coherente con el ETA)."""
        hora = self.despachador.pesos_dinamicos.redondear_hora(self.despachador.hora_actual)
        restante = segundos
        nodo_final = conductor.nodo
        while conductor.ruta and restante > 0:
            siguiente = conductor.ruta[0]
            datos = self.grafo.aristas[(nodo_final, siguiente)]  # KeyError si fuera un salto imposible
            velocidad = datos.longitud / max(tiempo_arista(datos, hora), 1e-9)  # m/s en este tramo y hora
            falta = datos.longitud - conductor.avance_m
            if velocidad * restante < falta:
                conductor.avance_m += velocidad * restante
                restante = 0
                break
            restante -= falta / velocidad
            conductor.distancia_recorrida_m += datos.longitud
            conductor.avance_m = 0.0
            nodo_final = conductor.ruta.pop(0)
        if nodo_final != conductor.nodo:
            self.despachador.mover_conductor(conductor.id, nodo_final)
        if conductor.ruta:
            return
        conductor.avance_m = 0.0
        if conductor.estado is EstadoConductor.EN_CAMINO:
            if self.ajustes.turnos_espera_recogida > 0:
                self.despachador.cambiar_estado(conductor.id, EstadoConductor.ESPERANDO_RECOGIDA)
                conductor.espera_restante = self.ajustes.turnos_espera_recogida
                eventos.append(Evento("llegada_recogida", self.turno, conductor.id, conductor.solicitud_id))
            else:
                self._iniciar_viaje(conductor, eventos)
        elif conductor.estado is EstadoConductor.EN_VIAJE and (
                conductor.destino_nodo is None or conductor.nodo == conductor.destino_nodo):
            solicitud = conductor.solicitud_id
            self.despachador.liberar_conductor(conductor.id)
            eventos.append(Evento("viaje_finalizado", self.turno, conductor.id, solicitud))

    # ---------------------------------------------------------- persistencia
    def instantanea(self) -> dict:
        """Estado completo y serializable (se guarda en la base de datos)."""
        return {
            "turno": self.turno,
            "en_pausa": self.en_pausa,
            "semilla": self.semilla,
            "hora_simulada": self.hora_simulada,
            "proxima_solicitud_id": self.proxima_solicitud_id,
            "estado_generador": _serializar_generador(self.generador),
            "num_conductores": len(self.despachador.conductores),
            "configuracion": self.configuracion(),
            "ofertas": self.motor.a_diccionario(),
            "unidades_apoyo": self.apoyo.a_diccionario(),
            "rutas_pendientes": self.rutas_pendientes,
            "conteo": self.despachador.conteo_estados(),
            "conductores": [c.a_diccionario() for c in sorted(self.despachador.conductores.values(), key=lambda c: c.id)],
        }

    @classmethod
    def desde_instantanea(cls, grafo, ajustes: Ajustes, datos: dict, nodos_validos: set[int] | None = None) -> "Simulador":
        conductores = [Conductor.desde_diccionario(d) for d in datos["conductores"]]
        configuracion = datos.get("configuracion") or {}  # ausente en instantáneas de la V1
        cambios = {k: configuracion[k] for k in ("congestion_activa", "tasa_solicitudes_por_turno", "k_candidatos",
                                                 "reloj") if k in configuracion}
        simulador = cls(grafo, ajustes.con(semilla=datos["semilla"], **cambios), conductores, nodos_validos)
        simulador.turno = datos["turno"]
        simulador.en_pausa = datos["en_pausa"]
        simulador.despachador.hora_actual = datos["hora_simulada"]
        simulador.proxima_solicitud_id = datos["proxima_solicitud_id"]
        simulador.generador.setstate(_deserializar_generador(datos["estado_generador"]))
        simulador.motor.restaurar(datos.get("ofertas", []))
        if datos.get("unidades_apoyo") is not None:
            simulador.apoyo = UnidadesApoyo(grafo, simulador.nodos_validos, 0, simulador.semilla,
                                            UnidadesApoyo.desde_diccionario(datos["unidades_apoyo"]))
        return simulador


def _serializar_generador(generador: random.Random) -> list:
    version, estado, gauss = generador.getstate()
    return [version, list(estado), gauss]


def _deserializar_generador(datos: list) -> tuple:
    return (datos[0], tuple(datos[1]), datos[2])
