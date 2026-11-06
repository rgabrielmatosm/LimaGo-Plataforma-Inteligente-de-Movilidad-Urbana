"""RF-05 — Dijkstra propio con ``heapq`` (cola de prioridad con borrado perezoso).

Complejidad: O((V + E) log V). Cada arista se relaja una vez y cada inserción
en el heap cuesta O(log V); las entradas obsoletas se descartan al extraerlas.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping

INFINITO = math.inf


@dataclass
class ResultadoDijkstra:
    distancias: dict[int, float]
    predecesores: dict[int, int | None]
    nodos_explorados: int = 0
    asentados: set[int] = field(default_factory=set)

    def distancia(self, nodo: int) -> float:
        return self.distancias.get(nodo, INFINITO)


def dijkstra(
    adyacencia: Mapping[int, list[tuple[int, float]]],
    origen: int,
    objetivos: Iterable[int] | None = None,
) -> ResultadoDijkstra:
    """Caminos mínimos desde ``origen``.

    Si se indican ``objetivos`` la búsqueda se detiene en cuanto todos ellos han
    sido asentados (su distancia ya es definitiva), lo que evita explorar todo el
    grafo cuando solo interesan unos pocos nodos.
    """
    if origen not in adyacencia:
        raise KeyError(f"El nodo de origen {origen} no existe en el grafo")
    pendientes = set(objetivos) if objetivos is not None else None
    distancias: dict[int, float] = {origen: 0.0}
    predecesores: dict[int, int | None] = {origen: None}
    asentados: set[int] = set()
    heap: list[tuple[float, int]] = [(0.0, origen)]
    while heap:
        distancia_u, u = heapq.heappop(heap)
        if u in asentados:
            continue  # entrada obsoleta (borrado perezoso)
        asentados.add(u)
        if pendientes is not None:
            pendientes.discard(u)
            if not pendientes:
                break
        for v, peso in adyacencia.get(u, ()):
            if peso < 0:
                raise ValueError("Dijkstra no admite pesos negativos")
            nueva = distancia_u + peso
            if nueva < distancias.get(v, INFINITO):
                distancias[v] = nueva
                predecesores[v] = u
                heapq.heappush(heap, (nueva, v))
    return ResultadoDijkstra(distancias, predecesores, len(asentados), asentados)


def reconstruir_ruta(predecesores: Mapping[int, int | None], origen: int, destino: int) -> list[int] | None:
    """Ruta origen→destino siguiendo predecesores hacia atrás. ``None`` si no hay camino."""
    if destino not in predecesores:
        return None
    ruta = [destino]
    actual = destino
    while actual != origen:
        actual = predecesores[actual]
        if actual is None:
            return None
        ruta.append(actual)
    ruta.reverse()
    return ruta


def ruta_mas_corta(
    adyacencia: Mapping[int, list[tuple[int, float]]], origen: int, destino: int
) -> tuple[float, list[int] | None, int]:
    """Distancia, ruta y nodos explorados entre dos nodos (parada temprana en el destino)."""
    if destino not in adyacencia:
        raise KeyError(f"El nodo de destino {destino} no existe en el grafo")
    resultado = dijkstra(adyacencia, origen, objetivos=[destino])
    if destino not in resultado.asentados:
        return INFINITO, None, resultado.nodos_explorados
    return resultado.distancias[destino], reconstruir_ruta(resultado.predecesores, origen, destino), resultado.nodos_explorados


def distancias_hacia_destino(
    inversa: Mapping[int, list[tuple[int, float]]], destino: int, origenes: Iterable[int]
) -> ResultadoDijkstra:
    """Distancias por calles desde varios orígenes hacia **un** destino.

    Se ejecuta Dijkstra una sola vez sobre el grafo **invertido** partiendo del
    destino (el pasajero). La distancia en el grafo invertido de destino→x es la
    distancia en el grafo real de x→destino, por lo que se respetan los sentidos
    de circulación. Es equivalente a k ejecuciones independientes, pero cuesta
    una sola.
    """
    return dijkstra(inversa, destino, objetivos=origenes)


def reconstruir_ruta_hacia(predecesores_inversos: Mapping[int, int | None], origen: int, destino: int) -> list[int] | None:
    """Ruta real origen→destino a partir del árbol de un Dijkstra sobre el grafo invertido.

    En ese árbol ``predecesores_inversos[x]`` es el siguiente nodo de x en el
    sentido real de circulación hacia el destino.
    """
    if origen not in predecesores_inversos:
        return None
    ruta = [origen]
    actual = origen
    while actual != destino:
        actual = predecesores_inversos[actual]
        if actual is None:
            return None
        ruta.append(actual)
    return ruta


def eta_segundos(distancia_m: float, velocidad_kmh: float) -> float:
    """Convierte metros a segundos con una velocidad promedio en km/h."""
    if velocidad_kmh <= 0:
        raise ValueError("La velocidad promedio debe ser positiva")
    if math.isinf(distancia_m):
        return INFINITO
    return distancia_m / (velocidad_kmh / 3.6)
