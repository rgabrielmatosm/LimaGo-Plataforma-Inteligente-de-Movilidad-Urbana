"""V3 — Unidades de apoyo **simuladas** para la alerta de seguridad de demostración.

No hay conexión con Policía Nacional, SAMU, serenazgo ni ningún servicio real:
las unidades son puntos simulados sobre intersecciones de la red. Cuando un
pasajero activa una alerta, se elige la unidad disponible más cercana con el
**mismo Quadtree propio** (k = 1) y se registra la distancia en línea recta.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from algoritmos.grafo import GrafoVial
from estructuras.quadtree import Quadtree


@dataclass
class UnidadApoyo:
    id: int
    nodo: int
    lat: float
    lon: float
    estado: str = "disponible"          # disponible | asignada
    alerta_id: int | None = None

    @property
    def codigo(self) -> str:
        return f"AP-{self.id:03d}"

    def a_diccionario(self) -> dict:
        return asdict(self) | {"codigo": self.codigo}


class UnidadesApoyo:
    def __init__(self, grafo: GrafoVial, nodos_validos, cantidad: int, semilla: int,
                 unidades: list[UnidadApoyo] | None = None) -> None:
        self.grafo = grafo
        if unidades is None:
            generador = random.Random(f"apoyo-{semilla}")  # no altera el generador de la simulación
            nodos = sorted(nodos_validos)
            unidades = []
            for i in range(1, cantidad + 1):
                nodo = generador.choice(nodos)
                lat, lon = grafo.coordenadas(nodo)
                unidades.append(UnidadApoyo(i, nodo, lat, lon))
        self.unidades = {u.id: u for u in unidades}
        self.indice = Quadtree(grafo.limites(), capacidad=8, profundidad_maxima=18)
        for u in unidades:
            self.indice.insertar(u.id, u.lat, u.lon, u.estado == "disponible")

    def __len__(self) -> int:
        return len(self.unidades)

    def asignar_mas_cercana(self, lat: float, lon: float, alerta_id: int) -> tuple[UnidadApoyo, float] | None:
        resultado = self.indice.buscar_k_cercanos(lat, lon, 1, solo_disponibles=True)
        if not resultado:
            return None
        distancia, uid = resultado[0]
        unidad = self.unidades[uid]
        unidad.estado, unidad.alerta_id = "asignada", alerta_id
        self.indice.cambiar_disponibilidad(uid, False)
        return unidad, distancia

    def liberar(self, alerta_id: int) -> None:
        for unidad in self.unidades.values():
            if unidad.alerta_id == alerta_id:
                unidad.estado, unidad.alerta_id = "disponible", None
                self.indice.cambiar_disponibilidad(unidad.id, True)

    def a_diccionario(self) -> list[dict]:
        return [u.a_diccionario() for u in self.unidades.values()]

    @staticmethod
    def desde_diccionario(datos: list[dict]) -> list[UnidadApoyo]:
        return [UnidadApoyo(**{k: v for k, v in d.items() if k != "codigo"}) for d in datos]
