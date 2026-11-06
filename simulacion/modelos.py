"""Entidades del dominio: ``Conductor`` y ``Pasajero``."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EstadoConductor(str, Enum):
    DISPONIBLE = "disponible"
    EN_CAMINO = "en_camino"   # ocupado: va a recoger al pasajero
    EN_VIAJE = "en_viaje"     # ocupado: lleva al pasajero a su destino

    @property
    def ocupado(self) -> bool:
        return self is not EstadoConductor.DISPONIBLE


@dataclass
class Conductor:
    """Conductor de la flota simulada, siempre ubicado en una intersección."""

    id: int
    nodo: int
    lat: float
    lon: float
    estado: EstadoConductor = EstadoConductor.DISPONIBLE
    ruta: list[int] = field(default_factory=list)      # nodos pendientes por recorrer
    solicitud_id: int | None = None
    destino_nodo: int | None = None
    distancia_recorrida_m: float = 0.0
    avance_m: float = 0.0                              # metros acumulados hacia el siguiente nodo

    @property
    def esta_disponible(self) -> bool:
        return self.estado is EstadoConductor.DISPONIBLE

    @property
    def codigo(self) -> str:
        return f"LG-{self.id:05d}"

    def a_diccionario(self) -> dict:
        return {
            "id": self.id,
            "codigo": self.codigo,
            "nodo": self.nodo,
            "lat": self.lat,
            "lon": self.lon,
            "estado": self.estado.value,
            "solicitud_id": self.solicitud_id,
            "destino_nodo": self.destino_nodo,
            "ruta": list(self.ruta),
            "distancia_recorrida_m": self.distancia_recorrida_m,
            "avance_m": self.avance_m,
        }

    @classmethod
    def desde_diccionario(cls, datos: dict) -> "Conductor":
        return cls(
            id=int(datos["id"]),
            nodo=int(datos["nodo"]),
            lat=float(datos["lat"]),
            lon=float(datos["lon"]),
            estado=EstadoConductor(datos["estado"]),
            ruta=[int(n) for n in datos.get("ruta", [])],
            solicitud_id=datos.get("solicitud_id"),
            destino_nodo=datos.get("destino_nodo"),
            distancia_recorrida_m=float(datos.get("distancia_recorrida_m", 0.0)),
            avance_m=float(datos.get("avance_m", 0.0)),
        )


@dataclass
class Pasajero:
    """Pasajero que solicita un viaje. ``nodo`` es la intersección más cercana."""

    id: int
    lat: float
    lon: float
    nodo: int | None = None
    distancia_a_red_m: float | None = None
    direccion: str = ""
    destino_lat: float | None = None
    destino_lon: float | None = None
    destino_nodo: int | None = None
    destino_direccion: str = ""
