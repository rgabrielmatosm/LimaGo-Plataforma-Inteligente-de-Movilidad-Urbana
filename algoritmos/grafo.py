"""Grafo vial dirigido propio (listas de adyacencia).

Se construye una sola vez a partir del ``MultiDiGraph`` de osmnx. Desde ese
momento todos los algoritmos de la solución (Dijkstra, A*, componentes) operan
sobre esta estructura, sin llamar a funciones de rutas de networkx/osmnx.

* ``adyacencia[u]``  → lista de ``(v, metros)`` para aristas u→v (sentido de circulación).
* ``inversa[v]``     → lista de ``(u, metros)`` para las mismas aristas invertidas.
* Si hay aristas paralelas u→v se conserva la más corta (es la única que
  puede formar parte de un camino mínimo).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from estructuras.geografia import Rectangulo

Adyacencia = dict[int, list[tuple[int, float]]]


@dataclass
class DatosArista:
    longitud: float
    tipo_via: str = "unclassified"
    nombre: str = ""
    sentido_unico: bool = False
    geometria: list[tuple[float, float]] = field(default_factory=list)  # (lat, lon)


class GrafoVial:
    def __init__(self) -> None:
        self.nodos: dict[int, tuple[float, float]] = {}
        self.adyacencia: Adyacencia = {}
        self.inversa: Adyacencia = {}
        self.aristas: dict[tuple[int, int], DatosArista] = {}

    # ------------------------------------------------------------ construcción
    def agregar_nodo(self, nodo: int, lat: float, lon: float) -> None:
        self.nodos[nodo] = (float(lat), float(lon))
        self.adyacencia.setdefault(nodo, [])
        self.inversa.setdefault(nodo, [])

    def agregar_arista(self, u: int, v: int, longitud: float, **datos) -> None:
        """Agrega la arista dirigida u→v (o la reemplaza si la nueva es más corta)."""
        if u not in self.nodos or v not in self.nodos:
            raise KeyError("Ambos extremos deben existir antes de agregar la arista")
        if longitud < 0:
            raise ValueError("Las longitudes deben ser no negativas")
        existente = self.aristas.get((u, v))
        if existente is not None and existente.longitud <= longitud:
            return
        self.aristas[(u, v)] = DatosArista(longitud=float(longitud), **datos)
        self.adyacencia[u] = [(x, w) for x, w in self.adyacencia[u] if x != v] + [(v, float(longitud))]
        self.inversa[v] = [(x, w) for x, w in self.inversa[v] if x != u] + [(u, float(longitud))]

    @classmethod
    def desde_networkx(cls, grafo_nx) -> "GrafoVial":
        """Convierte el grafo de osmnx (solo lectura de nodos y atributos)."""
        grafo = cls()
        for nodo, datos in grafo_nx.nodes(data=True):
            grafo.agregar_nodo(int(nodo), float(datos["y"]), float(datos["x"]))
        for u, v, datos in grafo_nx.edges(data=True):
            tipo = datos.get("highway", "unclassified")
            if isinstance(tipo, (list, tuple)):
                tipo = tipo[0]
            nombre = datos.get("name", "")
            if isinstance(nombre, (list, tuple)):
                nombre = " / ".join(map(str, nombre))
            geometria: list[tuple[float, float]] = []
            geom = datos.get("geometry")
            if geom is not None and hasattr(geom, "coords"):
                geometria = [(float(y), float(x)) for x, y in geom.coords]
            sentido = datos.get("oneway", False)
            if isinstance(sentido, str):
                sentido = sentido.lower() in {"true", "yes", "1"}
            grafo.agregar_arista(
                int(u),
                int(v),
                float(datos["length"]),
                tipo_via=str(tipo),
                nombre=str(nombre) if nombre else "",
                sentido_unico=bool(sentido),
                geometria=geometria,
            )
        return grafo

    # --------------------------------------------------------------- consultas
    @property
    def num_nodos(self) -> int:
        return len(self.nodos)

    @property
    def num_aristas(self) -> int:
        return len(self.aristas)

    def coordenadas(self, nodo: int) -> tuple[float, float]:
        return self.nodos[nodo]

    def longitud_arista(self, u: int, v: int) -> float:
        return self.aristas[(u, v)].longitud

    def limites(self, margen_grados: float = 5e-4) -> Rectangulo:
        return Rectangulo.desde_puntos(self.nodos.values(), margen_grados)

    def longitud_ruta(self, ruta: list[int]) -> float:
        return sum(self.longitud_arista(a, b) for a, b in zip(ruta, ruta[1:]))

    def geometria_ruta(self, ruta: Iterable[int]) -> list[tuple[float, float]]:
        """Polilínea (lat, lon) siguiendo la forma real de cada calle de la ruta."""
        ruta = list(ruta)
        if not ruta:
            return []
        puntos = [self.nodos[ruta[0]]]
        for a, b in zip(ruta, ruta[1:]):
            datos = self.aristas[(a, b)]
            if len(datos.geometria) >= 2:
                puntos.extend(datos.geometria[1:])
            else:
                puntos.append(self.nodos[b])
        return puntos

    def adyacencia_ponderada(self, peso: Callable[[int, int, DatosArista], float]) -> Adyacencia:
        """Lista de adyacencia con un peso distinto a la longitud (Reto B)."""
        resultado: Adyacencia = {n: [] for n in self.nodos}
        for (u, v), datos in self.aristas.items():
            resultado[u].append((v, peso(u, v, datos)))
        return resultado

    def componentes_fuertemente_conexas(self) -> list[set[int]]:
        """Algoritmo de Kosaraju iterativo, O(V + E)."""
        visitados: set[int] = set()
        orden: list[int] = []
        for inicio in self.nodos:
            if inicio in visitados:
                continue
            visitados.add(inicio)
            pila = [(inicio, iter(self.adyacencia[inicio]))]
            while pila:
                nodo, vecinos = pila[-1]
                avanzo = False
                for v, _ in vecinos:
                    if v not in visitados:
                        visitados.add(v)
                        pila.append((v, iter(self.adyacencia[v])))
                        avanzo = True
                        break
                if not avanzo:
                    orden.append(nodo)
                    pila.pop()
        asignado: set[int] = set()
        componentes: list[set[int]] = []
        for raiz in reversed(orden):
            if raiz in asignado:
                continue
            componente = {raiz}
            asignado.add(raiz)
            pila = [raiz]
            while pila:
                nodo = pila.pop()
                for u, _ in self.inversa[nodo]:
                    if u not in asignado:
                        asignado.add(u)
                        componente.add(u)
                        pila.append(u)
            componentes.append(componente)
        return componentes

    def componente_principal(self) -> set[int]:
        """Mayor componente fuertemente conexa: desde cualquiera de sus nodos se
        puede llegar a cualquier otro respetando los sentidos de circulación."""
        return max(self.componentes_fuertemente_conexas(), key=len)

    def resumen(self) -> str:
        unicos = sum(1 for d in self.aristas.values() if d.sentido_unico)
        total_km = sum(d.longitud for d in self.aristas.values()) / 1000
        return (
            f"Red vial: {self.num_nodos} intersecciones, {self.num_aristas} tramos dirigidos "
            f"({unicos} de sentido único), {total_km:.1f} km de tramos"
        )
