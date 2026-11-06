"""Reto A — A* propio.

f(n) = g(n) + h(n). Con pesos en metros, h(n) = Haversine(n, destino):

* **Admisible**: osmnx calcula ``length`` como suma de distancias de círculo
  máximo con el mismo radio terrestre (6 371 009 m), y ningún camino sobre la
  esfera es más corto que el arco de círculo máximo, así que h(n) ≤ coste real.
* **Consistente**: por la desigualdad triangular en la esfera,
  h(u) ≤ w(u, v) + h(v).

Con pesos en segundos (Reto B) se usa h(n) = Haversine / velocidad máxima de
flujo libre, que sigue siendo admisible porque la congestión solo aumenta los
tiempos.

Para tolerar diferencias de redondeo en las longitudes se permite reabrir un
nodo si se encuentra un g menor (A* con reapertura); con una heurística
consistente esto nunca ocurre y el algoritmo coincide con la versión clásica.
"""
from __future__ import annotations

import heapq
import math
from typing import Callable, Mapping

from estructuras.geografia import haversine_metros


def a_estrella(
    adyacencia: Mapping[int, list[tuple[int, float]]],
    origen: int,
    destino: int,
    heuristica: Callable[[int], float],
) -> tuple[float, list[int] | None, int]:
    """Devuelve ``(coste, ruta, nodos_explorados)``; ``(inf, None, n)`` si no hay camino."""
    if origen not in adyacencia or destino not in adyacencia:
        raise KeyError("Origen o destino inexistente")
    g: dict[int, float] = {origen: 0.0}
    predecesores: dict[int, int | None] = {origen: None}
    heap: list[tuple[float, float, int]] = [(heuristica(origen), 0.0, origen)]
    expandidos: set[int] = set()
    while heap:
        _, g_u, u = heapq.heappop(heap)
        if g_u > g.get(u, math.inf):
            continue  # entrada obsoleta
        expandidos.add(u)
        if u == destino:
            ruta = [destino]
            while ruta[-1] != origen:
                ruta.append(predecesores[ruta[-1]])
            ruta.reverse()
            return g_u, ruta, len(expandidos)
        for v, peso in adyacencia.get(u, ()):
            nuevo = g_u + peso
            if nuevo < g.get(v, math.inf):
                g[v] = nuevo
                predecesores[v] = u
                heapq.heappush(heap, (nuevo + heuristica(v), nuevo, v))
    return math.inf, None, len(expandidos)


def heuristica_haversine(nodos: Mapping[int, tuple[float, float]], destino: int, divisor: float = 1.0):
    """h(n) = Haversine(n, destino) / divisor (divisor = velocidad en m/s para pesos en tiempo)."""
    lat_d, lon_d = nodos[destino]

    def h(nodo: int) -> float:
        lat, lon = nodos[nodo]
        return haversine_metros(lat, lon, lat_d, lon_d) / divisor

    return h
