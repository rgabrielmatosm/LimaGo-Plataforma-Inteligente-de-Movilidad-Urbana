"""Entidades del dominio: ``Conductor`` y ``Pasajero``."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EstadoConductor(str, Enum):
    """Estados explícitos del conductor (V3). «Ocupado» agrupa a todos menos disponible y desconectado."""

    DESCONECTADO = "desconectado"            # fuera de servicio: sigue en la flota y en el Quadtree
    DISPONIBLE = "disponible"
    OFERTA_PENDIENTE = "oferta_pendiente"    # recibió una oferta y aún no responde (reservado)
    ACEPTADO = "aceptado"                    # aceptó; pasa a «en camino» al calcular su ruta
    EN_CAMINO = "en_camino"                  # va a recoger al pasajero
    ESPERANDO_RECOGIDA = "esperando_recogida"  # llegó al punto de recojo
    EN_VIAJE = "en_viaje"                    # lleva al pasajero a su destino
    FINALIZADO = "finalizado"                # terminó el viaje; vuelve a estar disponible

    @property
    def ocupado(self) -> bool:
        return self not in (EstadoConductor.DISPONIBLE, EstadoConductor.DESCONECTADO)


E = EstadoConductor
#: Transiciones válidas. Cualquier otra se rechaza (evita estados contradictorios).
TRANSICIONES: dict[EstadoConductor, frozenset[EstadoConductor]] = {
    E.DESCONECTADO: frozenset({E.DISPONIBLE}),
    E.DISPONIBLE: frozenset({E.DESCONECTADO, E.OFERTA_PENDIENTE, E.EN_CAMINO}),  # EN_CAMINO: asignación académica directa
    E.OFERTA_PENDIENTE: frozenset({E.ACEPTADO, E.DISPONIBLE}),                 # DISPONIBLE: rechazo o expiración
    E.ACEPTADO: frozenset({E.EN_CAMINO, E.DISPONIBLE}),
    E.EN_CAMINO: frozenset({E.ESPERANDO_RECOGIDA, E.EN_VIAJE, E.DISPONIBLE}),   # DISPONIBLE: cancelación
    E.ESPERANDO_RECOGIDA: frozenset({E.EN_VIAJE, E.DISPONIBLE}),
    E.EN_VIAJE: frozenset({E.FINALIZADO, E.DISPONIBLE}),
    E.FINALIZADO: frozenset({E.DISPONIBLE}),
}


class TransicionInvalida(ValueError):
    pass


def validar_transicion(actual: EstadoConductor, nuevo: EstadoConductor) -> None:
    if actual is not nuevo and nuevo not in TRANSICIONES[actual]:
        raise TransicionInvalida(f"Transición no permitida: {actual.value} → {nuevo.value}")


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
    politica: str = "automatica"                       # V3: respuesta a ofertas (ver simulacion/aceptacion.py)
    espera_restante: int = 0                           # V3: turnos de espera en el punto de recojo

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
            "politica": self.politica,
            "espera_restante": self.espera_restante,
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
            politica=datos.get("politica", "automatica"),
            espera_restante=int(datos.get("espera_restante", 0)),
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
