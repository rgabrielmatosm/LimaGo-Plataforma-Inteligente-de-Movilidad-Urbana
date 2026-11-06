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
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from algoritmos.dijkstra import dijkstra, reconstruir_ruta
from config.ajustes import Ajustes
from simulacion.despachador import Despachador, ResultadoAsignacion
from simulacion.flota import generar_flota
from simulacion.modelos import Conductor, EstadoConductor, Pasajero


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
        flota = conductores if conductores is not None else generar_flota(
            grafo, ajustes.num_conductores, ajustes.semilla, ajustes.proporcion_ocupados, self.nodos_validos)
        self.despachador = Despachador(grafo, flota, ajustes, self.nodos_validos)

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

    def nuevo_id_solicitud(self) -> int:
        identificador = self.proxima_solicitud_id
        self.proxima_solicitud_id += 1
        return identificador

    # ------------------------------------------------------------ solicitudes
    def solicitar_viaje(self, pasajero: Pasajero, solicitud_id: int | None = None, k: int | None = None) -> ResultadoAsignacion:
        if solicitud_id is None:
            solicitud_id = self.nuevo_id_solicitud()
        return self.despachador.solicitar_viaje(pasajero, k=k, solicitud_id=solicitud_id)

    def _solicitudes_automaticas(self) -> list[tuple[int, ResultadoAsignacion]]:
        """Demanda de fondo: ``tasa`` solicitudes por turno en promedio (parte entera + Bernoulli)."""
        tasa = max(0.0, self.ajustes.tasa_solicitudes_por_turno)
        cantidad = int(tasa) + (1 if self.generador.random() < tasa - int(tasa) else 0)
        resultados = []
        for _ in range(cantidad):
            origen = self.generador.choice(self._nodos_ordenados)
            destino = self.generador.choice(self._nodos_ordenados)
            lat, lon = self.grafo.coordenadas(origen)
            dlat, dlon = self.grafo.coordenadas(destino)
            solicitud_id = self.nuevo_id_solicitud()
            pasajero = Pasajero(id=solicitud_id, lat=lat, lon=lon, nodo=origen, distancia_a_red_m=0.0,
                                destino_lat=dlat, destino_lon=dlon, destino_nodo=destino,
                                direccion="Solicitud simulada")
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
        self.despachador.hora_actual = (self.despachador.hora_actual + self.ajustes.segundos_por_turno / 3600) % 24
        eventos: list[Evento] = []
        presupuesto = self._velocidad_ms() * self.ajustes.segundos_por_turno
        for conductor_id in sorted(self.despachador.conductores):
            conductor = self.despachador.conductores[conductor_id]
            if conductor.estado is EstadoConductor.EN_VIAJE and not conductor.ruta and conductor.destino_nodo is not None \
                    and conductor.nodo != conductor.destino_nodo:
                conductor.ruta = self._ruta(conductor.nodo, conductor.destino_nodo)
            if conductor.esta_disponible and not conductor.ruta:
                conductor.ruta = self._siguiente_paseo(conductor)
            self._mover(conductor, presupuesto, eventos)
        for solicitud_id, asignacion in self._solicitudes_automaticas():
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
            destino = conductor.destino_nodo
            if destino is None:
                destino = self.generador.choice(self._nodos_ordenados)
                conductor.destino_nodo = destino
            self.despachador.cambiar_estado(conductor.id, EstadoConductor.EN_VIAJE)
            conductor.ruta = self._ruta(conductor.nodo, destino)
            eventos.append(Evento("recogida", self.turno, conductor.id, conductor.solicitud_id))
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
            "conteo": self.despachador.conteo_estados(),
            "conductores": [c.a_diccionario() for c in sorted(self.despachador.conductores.values(), key=lambda c: c.id)],
        }

    @classmethod
    def desde_instantanea(cls, grafo, ajustes: Ajustes, datos: dict, nodos_validos: set[int] | None = None) -> "Simulador":
        conductores = [Conductor.desde_diccionario(d) for d in datos["conductores"]]
        simulador = cls(grafo, ajustes.con(semilla=datos["semilla"]), conductores, nodos_validos)
        simulador.turno = datos["turno"]
        simulador.en_pausa = datos["en_pausa"]
        simulador.despachador.hora_actual = datos["hora_simulada"]
        simulador.proxima_solicitud_id = datos["proxima_solicitud_id"]
        simulador.generador.setstate(_deserializar_generador(datos["estado_generador"]))
        return simulador


def _serializar_generador(generador: random.Random) -> list:
    version, estado, gauss = generador.getstate()
    return [version, list(estado), gauss]


def _deserializar_generador(datos: list) -> tuple:
    return (datos[0], tuple(datos[1]), datos[2])
