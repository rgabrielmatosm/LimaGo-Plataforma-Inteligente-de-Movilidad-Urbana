"""Reto D — Índice experimental basado en celdas hexagonales H3 (Uber).

**Aislado de la solución principal**: ningún módulo de ``simulacion/``,
``estructuras/``, ``algoritmos/`` o ``api/`` importa este archivo. La guía
prohíbe ``h3`` en la solución; aquí se usa solo para el reto comparativo.

Búsqueda k-NN con anillos:

1. Se ubica la celda del pasajero y se recorren anillos ``grid_ring(c, r)`` con
   r = 0, 1, 2, ... acumulando candidatos y calculando Haversine.
2. En una malla hexagonal regular de arista ``e``, los centros de las celdas
   del anillo r distan al menos ``1.5·r·e`` del centro de origen; restando el
   radio de la celda de origen y el de la celda destino (``e`` cada uno), todo
   punto del anillo r (y de los siguientes) está a más de ``(1.5·r − 2)·e``.
   Se aplica un factor 0.6 por la deformación de las celdas H3. Cuando esa
   cota supera la k-ésima mejor distancia se detiene la búsqueda.

Limitación documentada: H3 no es un árbol jerárquico exacto (los hijos no
cubren exactamente al padre) y las celdas se deforman lejos del centro de la
proyección icosaédrica; por eso la cota es conservadora y se valida contra la
búsqueda lineal en las pruebas.
"""
from __future__ import annotations

import heapq

import h3

from estructuras.geografia import haversine_metros


class IndiceH3:
    def __init__(self, resolucion: int = 9) -> None:
        self.resolucion = resolucion
        self.celdas: dict[str, dict[int, tuple[float, float, bool]]] = {}
        self.ubicacion: dict[int, str] = {}
        # Longitud media de arista de la resolución (m). El apotema de un hexágono
        # regular es arista·√3/2; dos centros vecinos distan ≈ arista·√3.
        self.arista_m = h3.average_hexagon_edge_length(resolucion, unit="m")
        self.distancias_calculadas = 0

    def __len__(self) -> int:
        return len(self.ubicacion)

    def insertar(self, identificador: int, lat: float, lon: float, disponible: bool = True) -> None:
        if identificador in self.ubicacion:
            raise ValueError("Identificador duplicado")
        celda = h3.latlng_to_cell(lat, lon, self.resolucion)
        self.celdas.setdefault(celda, {})[identificador] = (lat, lon, disponible)
        self.ubicacion[identificador] = celda

    def eliminar(self, identificador: int) -> bool:
        celda = self.ubicacion.pop(identificador, None)
        if celda is None:
            return False
        del self.celdas[celda][identificador]
        if not self.celdas[celda]:
            del self.celdas[celda]
        return True

    def actualizar_posicion(self, identificador: int, lat: float, lon: float) -> None:
        _, _, disponible = self.celdas[self.ubicacion[identificador]][identificador]
        self.eliminar(identificador)
        self.insertar(identificador, lat, lon, disponible)

    def buscar_k_cercanos(self, lat: float, lon: float, k: int, solo_disponibles: bool = True,
                          anillo_maximo: int = 200) -> list[tuple[float, int]]:
        self.distancias_calculadas = 0
        if k <= 0 or not self.ubicacion:
            return []
        origen = h3.latlng_to_cell(lat, lon, self.resolucion)
        mejores: list[tuple[float, int]] = []
        arista = self.arista_m * 0.6  # factor conservador por la deformación de H3
        for r in range(anillo_maximo + 1):
            if len(mejores) == k and (1.5 * r - 2) * arista > -mejores[0][0]:
                break
            celdas = [origen] if r == 0 else h3.grid_ring(origen, r)
            for celda in celdas:
                for identificador, (plat, plon, disponible) in self.celdas.get(celda, {}).items():
                    if solo_disponibles and not disponible:
                        continue
                    distancia = haversine_metros(lat, lon, plat, plon)
                    self.distancias_calculadas += 1
                    clave = (-distancia, -identificador)
                    if len(mejores) < k:
                        heapq.heappush(mejores, clave)
                    elif clave > mejores[0]:
                        heapq.heapreplace(mejores, clave)
        return sorted((-d, -i) for d, i in mejores)
