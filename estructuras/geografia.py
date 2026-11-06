"""Utilidades geográficas propias: Haversine y rectángulos lat/lon.

Convención: las coordenadas se expresan en grados decimales (latitud, longitud).
Dentro del Quadtree se usa ``x = longitud`` e ``y = latitud``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Radio medio terrestre usado también por osmnx para calcular ``length``.
# Usar el mismo radio garantiza que la heurística de A* sea admisible.
RADIO_TIERRA_M = 6_371_009.0


def haversine_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia de círculo máximo entre dos puntos, en metros.

    a = sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)
    d = 2R · asin(√a)
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    a = min(1.0, max(0.0, a))  # protege contra errores de redondeo
    return 2.0 * RADIO_TIERRA_M * math.asin(math.sqrt(a))


def validar_coordenadas(lat: float, lon: float) -> None:
    """Lanza ``ValueError`` si las coordenadas no son válidas en la Tierra."""
    if lat is None or lon is None:
        raise ValueError("Las coordenadas no pueden estar vacías")
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError) as error:
        raise ValueError("Las coordenadas deben ser numéricas") from error
    if math.isnan(lat) or math.isnan(lon) or math.isinf(lat) or math.isinf(lon):
        raise ValueError("Las coordenadas deben ser números finitos")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"Latitud fuera de rango [-90, 90]: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"Longitud fuera de rango [-180, 180]: {lon}")


@dataclass(frozen=True)
class Rectangulo:
    """Rectángulo alineado a los ejes en grados: [lon_min, lon_max] × [lat_min, lat_max]."""

    lon_min: float
    lat_min: float
    lon_max: float
    lat_max: float

    def __post_init__(self) -> None:
        if self.lon_min > self.lon_max or self.lat_min > self.lat_max:
            raise ValueError("Rectángulo inválido: mínimo mayor que máximo")

    @property
    def lon_centro(self) -> float:
        return (self.lon_min + self.lon_max) / 2.0

    @property
    def lat_centro(self) -> float:
        return (self.lat_min + self.lat_max) / 2.0

    def contiene(self, lat: float, lon: float) -> bool:
        """Intervalo cerrado: los puntos en el borde pertenecen al rectángulo."""
        return self.lon_min <= lon <= self.lon_max and self.lat_min <= lat <= self.lat_max

    def intersecta(self, otro: "Rectangulo") -> bool:
        return not (
            otro.lon_min > self.lon_max
            or otro.lon_max < self.lon_min
            or otro.lat_min > self.lat_max
            or otro.lat_max < self.lat_min
        )

    def contiene_rectangulo(self, otro: "Rectangulo") -> bool:
        return (
            self.lon_min <= otro.lon_min
            and otro.lon_max <= self.lon_max
            and self.lat_min <= otro.lat_min
            and otro.lat_max <= self.lat_max
        )

    def distancia_minima_metros(self, lat: float, lon: float) -> float:
        """Cota inferior **garantizada** de la distancia Haversine a cualquier punto del rectángulo.

        Se usa para podar ramas del Quadtree sin perder exactitud:

        * Si la latitud del punto está fuera de [lat_min, lat_max], cualquier
          camino sobre la esfera debe recorrer al menos ``R·|Δφ|`` (la distancia
          por un meridiano es la mínima para cambiar de latitud).
        * Si la longitud está fuera de [lon_min, lon_max], la distancia al
          meridiano más cercano completo es ``R·asin(cos φ · sin Δλ)``
          (triángulo esférico rectángulo); al segmento de meridiano no puede ser menor.

        La cota es el máximo de ambas; vale 0 si el punto está dentro.
        """
        if self.contiene(lat, lon):
            return 0.0
        cota_lat = 0.0
        if lat < self.lat_min:
            cota_lat = RADIO_TIERRA_M * math.radians(self.lat_min - lat)
        elif lat > self.lat_max:
            cota_lat = RADIO_TIERRA_M * math.radians(lat - self.lat_max)
        cota_lon = 0.0
        delta_lon = 0.0
        if lon < self.lon_min:
            delta_lon = self.lon_min - lon
        elif lon > self.lon_max:
            delta_lon = lon - self.lon_max
        if delta_lon > 0.0:
            delta = math.radians(min(delta_lon, 90.0))
            valor = abs(math.cos(math.radians(lat)) * math.sin(delta))
            cota_lon = RADIO_TIERRA_M * math.asin(min(1.0, valor))
        return max(cota_lat, cota_lon)

    def subdividir(self) -> tuple["Rectangulo", "Rectangulo", "Rectangulo", "Rectangulo"]:
        """Devuelve los cuadrantes en orden: noroeste, noreste, suroeste, sureste."""
        lon_c, lat_c = self.lon_centro, self.lat_centro
        return (
            Rectangulo(self.lon_min, lat_c, lon_c, self.lat_max),
            Rectangulo(lon_c, lat_c, self.lon_max, self.lat_max),
            Rectangulo(self.lon_min, self.lat_min, lon_c, lat_c),
            Rectangulo(lon_c, self.lat_min, self.lon_max, lat_c),
        )

    @classmethod
    def alrededor(cls, lat: float, lon: float, radio_m: float) -> "Rectangulo":
        """Rectángulo que contiene el círculo de ``radio_m`` metros alrededor del punto."""
        delta_lat = math.degrees(radio_m / RADIO_TIERRA_M)
        cos_lat = max(1e-9, math.cos(math.radians(lat)))
        delta_lon = math.degrees(radio_m / (RADIO_TIERRA_M * cos_lat))
        return cls(lon - delta_lon, lat - delta_lat, lon + delta_lon, lat + delta_lat)

    @classmethod
    def desde_puntos(cls, puntos, margen_grados: float = 1e-4) -> "Rectangulo":
        """Rectángulo mínimo (con margen) que contiene los puntos ``(lat, lon)``."""
        puntos = list(puntos)
        if not puntos:
            raise ValueError("Se necesita al menos un punto")
        lats = [p[0] for p in puntos]
        lons = [p[1] for p in puntos]
        return cls(
            min(lons) - margen_grados,
            min(lats) - margen_grados,
            max(lons) + margen_grados,
            max(lats) + margen_grados,
        )
