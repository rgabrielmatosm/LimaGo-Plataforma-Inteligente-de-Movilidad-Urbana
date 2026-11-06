"""RF-02 — Generación reproducible de la flota simulada."""
from __future__ import annotations

import random

from algoritmos.grafo import GrafoVial
from simulacion.modelos import Conductor, EstadoConductor


def generar_flota(
    grafo: GrafoVial,
    cantidad: int = 300,
    semilla: int = 42,
    proporcion_ocupados: float = 0.2,
    nodos_validos: set[int] | None = None,
) -> list[Conductor]:
    """Crea ``cantidad`` conductores sobre intersecciones elegidas al azar.

    * La misma semilla produce exactamente la misma flota (posiciones, estados y destinos).
    * ``nodos_validos`` (por defecto, la mayor componente fuertemente conexa)
      evita ubicar conductores en tramos desde los que no se puede salir.
    * Varios conductores pueden compartir intersección (caso real y caso límite
      del Quadtree).
    * Los conductores ocupados inician "en viaje" con un destino aleatorio.
    """
    if cantidad < 0:
        raise ValueError("La cantidad de conductores no puede ser negativa")
    if not 0.0 <= proporcion_ocupados <= 1.0:
        raise ValueError("La proporción de ocupados debe estar entre 0 y 1")
    generador = random.Random(semilla)
    candidatos = sorted(nodos_validos if nodos_validos is not None else grafo.componente_principal())
    if not candidatos:
        raise ValueError("No hay intersecciones válidas para ubicar conductores")
    flota: list[Conductor] = []
    for identificador in range(1, cantidad + 1):
        nodo = generador.choice(candidatos)
        lat, lon = grafo.coordenadas(nodo)
        conductor = Conductor(id=identificador, nodo=nodo, lat=lat, lon=lon)
        if generador.random() < proporcion_ocupados:
            conductor.estado = EstadoConductor.EN_VIAJE
            conductor.destino_nodo = generador.choice(candidatos)
        flota.append(conductor)
    return flota
