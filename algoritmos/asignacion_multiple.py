"""Reto C — Asignación simultánea de varios pasajeros.

Problema: dada una matriz ``costo[p][c]`` (ETA del conductor c hasta el
pasajero p), elegir a lo sumo un conductor por pasajero y un pasajero por
conductor minimizando la **suma** de esperas. Es el problema de asignación
lineal; se resuelve de forma exacta con el **algoritmo húngaro** (versión con
potenciales de Kuhn–Munkres / Jonker–Volgenant simplificada), O(n²·m) para
n pasajeros y m ≥ n conductores.

Se compara con la estrategia **codiciosa individual**: atender a los pasajeros
en orden de llegada y dar a cada uno el mejor conductor que quede libre.
"""
from __future__ import annotations

import math

COSTO_INALCANZABLE = 1e12


def algoritmo_hungaro(costo: list[list[float]]) -> list[int]:
    """Devuelve ``asignacion[fila] = columna`` minimizando la suma de costos.

    Requiere ``filas <= columnas``. Los valores infinitos se reemplazan por un
    costo muy alto para que el algoritmo los evite siempre que sea posible.
    """
    n = len(costo)
    if n == 0:
        return []
    m = len(costo[0])
    if any(len(fila) != m for fila in costo):
        raise ValueError("La matriz de costos debe ser rectangular")
    if n > m:
        raise ValueError("Debe haber al menos tantas columnas (conductores) como filas (pasajeros)")
    a = [[0.0] * (m + 1)] + [
        [0.0] + [COSTO_INALCANZABLE if math.isinf(x) else float(x) for x in fila] for fila in costo
    ]
    u = [0.0] * (n + 1)          # potenciales de filas
    v = [0.0] * (m + 1)          # potenciales de columnas
    p = [0] * (m + 1)            # p[j] = fila asignada a la columna j (0 = ninguna)
    camino = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minimo = [math.inf] * (m + 1)
        usado = [False] * (m + 1)
        while True:
            usado[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            for j in range(1, m + 1):
                if usado[j]:
                    continue
                actual = a[i0][j] - u[i0] - v[j]
                if actual < minimo[j]:
                    minimo[j] = actual
                    camino[j] = j0
                if minimo[j] < delta:
                    delta = minimo[j]
                    j1 = j
            for j in range(m + 1):
                if usado[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimo[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:  # invierte el camino aumentante
            j1 = camino[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    asignacion = [-1] * n
    for j in range(1, m + 1):
        if p[j] != 0:
            asignacion[p[j] - 1] = j - 1
    return asignacion


def asignacion_codiciosa(costo: list[list[float]]) -> list[int]:
    """Cada pasajero, en orden, toma el conductor libre de menor costo (-1 si no queda ninguno)."""
    tomadas: set[int] = set()
    resultado: list[int] = []
    for fila in costo:
        mejor, mejor_costo = -1, math.inf
        for j, valor in enumerate(fila):
            if j not in tomadas and valor < mejor_costo:
                mejor, mejor_costo = j, valor
        if mejor >= 0:
            tomadas.add(mejor)
        resultado.append(mejor)
    return resultado


def costo_total(costo: list[list[float]], asignacion: list[int]) -> float:
    return sum(costo[i][j] for i, j in enumerate(asignacion) if j >= 0)


def fuerza_bruta(costo: list[list[float]]) -> float:
    """Óptimo por enumeración (solo para validar en pruebas con matrices pequeñas)."""
    from itertools import permutations

    n, m = len(costo), len(costo[0]) if costo else 0
    if n == 0:
        return 0.0
    return min(sum(costo[i][perm[i]] for i in range(n)) for perm in permutations(range(m), n))
