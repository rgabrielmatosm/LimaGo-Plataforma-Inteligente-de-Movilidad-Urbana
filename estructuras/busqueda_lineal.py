"""Búsqueda lineal de referencia (RF-04 / RF-09).

**No** se usa en la asignación: sirve únicamente para validar que el Quadtree
devuelve exactamente los mismos k candidatos y como línea base del benchmark.
Recorre los n conductores, calcula Haversine para cada uno y mantiene un
max-heap de tamaño k → O(n log k).
"""
from __future__ import annotations

import heapq
from typing import Iterable

from estructuras.geografia import haversine_metros


def buscar_k_cercanos_lineal(
    puntos: Iterable[tuple[int, float, float, bool]],
    lat: float,
    lon: float,
    k: int,
    solo_disponibles: bool = True,
) -> list[tuple[float, int]]:
    """``puntos`` es un iterable de ``(id, lat, lon, disponible)``.

    Devuelve ``[(distancia_m, id), ...]`` ordenado (empates por id), igual que
    :meth:`estructuras.quadtree.Quadtree.buscar_k_cercanos`.
    """
    if k <= 0:
        return []
    mejores: list[tuple[float, int]] = []
    for identificador, plat, plon, disponible in puntos:
        if solo_disponibles and not disponible:
            continue
        clave = (-haversine_metros(lat, lon, plat, plon), -identificador)
        if len(mejores) < k:
            heapq.heappush(mejores, clave)
        elif clave > mejores[0]:
            heapq.heapreplace(mejores, clave)
    return sorted((-d, -i) for d, i in mejores)
