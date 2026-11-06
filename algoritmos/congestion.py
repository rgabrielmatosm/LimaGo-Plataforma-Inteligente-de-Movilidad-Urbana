"""Reto B — Pesos dinámicos por hora punta (congestión **simulada**).

No hay datos de tráfico en tiempo real: se modela un perfil horario sintético
y documentado. Lo importante es que el cambio afecta a los **pesos del grafo**
(segundos por tramo) y, por tanto, a las rutas y ETA que calcula Dijkstra/A*.

tiempo(u→v, h) = longitud / velocidad_libre(tipo) × factor(tipo, h)

factor(tipo, h) = 1 + intensidad(tipo) × [ G(h; 8.0, 1.0) + 0.9·G(h; 18.5, 1.2) + 0.25·G(h; 13.0, 1.5) ]

donde G(h; μ, σ) = exp(−(h−μ)² / (2σ²)). Las vías principales se congestionan
más que las residenciales, por eso a las 8:00 puede convenir otra ruta.
"""
from __future__ import annotations

import math
from functools import lru_cache

from algoritmos.grafo import Adyacencia, DatosArista, GrafoVial

VELOCIDAD_LIBRE_KMH = {
    "motorway": 60.0,
    "trunk": 50.0,
    "primary": 45.0,
    "secondary": 40.0,
    "tertiary": 32.0,
    "residential": 25.0,
    "living_street": 15.0,
    "service": 15.0,
    "unclassified": 25.0,
}
INTENSIDAD = {
    "motorway": 2.2,
    "trunk": 2.2,
    "primary": 2.0,
    "secondary": 1.6,
    "tertiary": 1.1,
    "residential": 0.45,
    "living_street": 0.2,
    "service": 0.2,
    "unclassified": 0.5,
}


def _clase(tipo_via: str) -> str:
    base = tipo_via.replace("_link", "")
    return base if base in VELOCIDAD_LIBRE_KMH else "unclassified"


def _gauss(h: float, media: float, sigma: float) -> float:
    return math.exp(-((h - media) ** 2) / (2 * sigma**2))


def factor_congestion(tipo_via: str, hora: float) -> float:
    """Multiplicador (≥ 1) del tiempo de viaje para un tipo de vía y una hora (0–24)."""
    if not 0 <= hora <= 24:
        raise ValueError("La hora debe estar entre 0 y 24")
    perfil = _gauss(hora, 8.0, 1.0) + 0.9 * _gauss(hora, 18.5, 1.2) + 0.25 * _gauss(hora, 13.0, 1.5)
    return 1.0 + INTENSIDAD[_clase(tipo_via)] * perfil


def velocidad_libre_ms(tipo_via: str) -> float:
    return VELOCIDAD_LIBRE_KMH[_clase(tipo_via)] / 3.6


def velocidad_maxima_ms() -> float:
    """Velocidad máxima de flujo libre: hace admisible la heurística de A* en segundos."""
    return max(VELOCIDAD_LIBRE_KMH.values()) / 3.6


def tiempo_arista(datos: DatosArista, hora: float) -> float:
    return datos.longitud / velocidad_libre_ms(datos.tipo_via) * factor_congestion(datos.tipo_via, hora)


class PesosDinamicos:
    """Genera (y memoriza por cuarto de hora) las adyacencias ponderadas en segundos."""

    def __init__(self, grafo: GrafoVial) -> None:
        self.grafo = grafo
        self._cache: dict[float, tuple[Adyacencia, Adyacencia]] = {}

    @staticmethod
    def redondear_hora(hora: float) -> float:
        return round((hora % 24) * 4) / 4

    def adyacencias(self, hora: float) -> tuple[Adyacencia, Adyacencia]:
        """Devuelve ``(adyacencia, inversa)`` con pesos en segundos para la hora dada."""
        clave = self.redondear_hora(hora)
        if clave not in self._cache:
            directa: Adyacencia = {n: [] for n in self.grafo.nodos}
            inversa: Adyacencia = {n: [] for n in self.grafo.nodos}
            for (u, v), datos in self.grafo.aristas.items():
                t = tiempo_arista(datos, clave)
                directa[u].append((v, t))
                inversa[v].append((u, t))
            self._cache[clave] = (directa, inversa)
        return self._cache[clave]


@lru_cache(maxsize=None)
def describir_hora(hora: float) -> str:
    h = int(hora) % 24
    m = int(round((hora - int(hora)) * 60)) % 60
    return f"{h:02d}:{m:02d}"
