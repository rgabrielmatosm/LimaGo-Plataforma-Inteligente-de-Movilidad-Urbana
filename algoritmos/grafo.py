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

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from estructuras.geografia import Rectangulo

Adyacencia = dict[int, list[tuple[int, float]]]


@dataclass(slots=True)
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

    # ------------------------------------------------------ formato compacto
    def guardar_compacto(self, ruta: Path) -> None:
        """Guarda el grafo en un ``.npz`` comprimido (arreglos numpy).

        Para Lima Metropolitana el GraphML ocupa cientos de MB y tarda en
        cargarse; este formato guarda exactamente la misma información que usa
        ``GrafoVial`` (nodos, aristas dirigidas, longitudes, tipo de vía, nombre,
        sentido único y geometría) y se carga en pocos segundos.
        """
        import numpy as np

        ids = list(self.nodos)
        indice = {n: i for i, n in enumerate(ids)}
        tipos = sorted({d.tipo_via for d in self.aristas.values()})
        nombres = sorted({d.nombre for d in self.aristas.values() if d.nombre})
        id_tipo = {t: i for i, t in enumerate(tipos)}
        id_nombre = {n: i for i, n in enumerate(nombres)}
        u, v, longitud, tipo, nombre, unico, desplazamientos, lat_geom, lon_geom = ([] for _ in range(9))
        desplazamientos.append(0)
        for (a, b), d in self.aristas.items():
            u.append(indice[a])
            v.append(indice[b])
            longitud.append(d.longitud)
            tipo.append(id_tipo[d.tipo_via])
            nombre.append(id_nombre.get(d.nombre, -1))
            unico.append(d.sentido_unico)
            for la, lo in d.geometria:
                lat_geom.append(la)
                lon_geom.append(lo)
            desplazamientos.append(len(lat_geom))
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            ruta,
            nodo_id=np.array(ids, dtype=np.int64),
            nodo_lat=np.array([self.nodos[n][0] for n in ids], dtype=np.float64),
            nodo_lon=np.array([self.nodos[n][1] for n in ids], dtype=np.float64),
            u=np.array(u, dtype=np.int32), v=np.array(v, dtype=np.int32),
            longitud=np.array(longitud, dtype=np.float64),
            tipo=np.array(tipo, dtype=np.int16), nombre=np.array(nombre, dtype=np.int32),
            sentido_unico=np.array(unico, dtype=np.bool_),
            geom_desplazamiento=np.array(desplazamientos, dtype=np.int64),
            geom_lat=np.array(lat_geom, dtype=np.float64), geom_lon=np.array(lon_geom, dtype=np.float64),
            catalogos=np.array([json.dumps({"tipos": tipos, "nombres": nombres}, ensure_ascii=False)]),
        )

    @classmethod
    def cargar_compacto(cls, ruta: Path) -> "GrafoVial":
        import numpy as np

        datos = np.load(Path(ruta), allow_pickle=False)
        catalogos = json.loads(str(datos["catalogos"][0]))
        tipos, nombres = catalogos["tipos"], catalogos["nombres"]
        ids = datos["nodo_id"].tolist()
        lats, lons = datos["nodo_lat"].tolist(), datos["nodo_lon"].tolist()
        grafo = cls()
        grafo.nodos = {n: (la, lo) for n, la, lo in zip(ids, lats, lons)}
        grafo.adyacencia = {n: [] for n in ids}
        grafo.inversa = {n: [] for n in ids}
        desp = datos["geom_desplazamiento"].tolist()
        glat, glon = datos["geom_lat"].tolist(), datos["geom_lon"].tolist()
        for i, (a, b, largo, t, nom, unico) in enumerate(zip(
                datos["u"].tolist(), datos["v"].tolist(), datos["longitud"].tolist(), datos["tipo"].tolist(),
                datos["nombre"].tolist(), datos["sentido_unico"].tolist())):
            na, nb = ids[a], ids[b]
            geometria = list(zip(glat[desp[i]:desp[i + 1]], glon[desp[i]:desp[i + 1]]))
            grafo.aristas[(na, nb)] = DatosArista(largo, tipos[t], nombres[nom] if nom >= 0 else "", bool(unico), geometria)
            grafo.adyacencia[na].append((nb, largo))
            grafo.inversa[nb].append((na, largo))
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

    def punto_en_tramo(self, u: int, v: int, metros: float) -> tuple[float, float, float]:
        """Posición (lat, lon) y rumbo (grados, 0 = norte) a ``metros`` del inicio del tramo u→v.

        Recorre la geometría real del tramo; el avance se escala porque la longitud
        OSM y la suma de segmentos pueden diferir en centímetros.
        """
        from estructuras.geografia import haversine_metros, rumbo_grados

        datos = self.aristas[(u, v)]
        puntos = datos.geometria if len(datos.geometria) >= 2 else [self.nodos[u], self.nodos[v]]
        tramos = [haversine_metros(*a, *b) for a, b in zip(puntos, puntos[1:])]
        total = sum(tramos) or 1.0
        objetivo = max(0.0, min(1.0, metros / max(datos.longitud, 1e-9))) * total
        for (a, b), largo in zip(zip(puntos, puntos[1:]), tramos):
            if objetivo <= largo or largo == tramos[-1]:
                f = 0.0 if largo == 0 else min(1.0, objetivo / largo)
                return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, rumbo_grados(*a, *b)
            objetivo -= largo
        return (*puntos[-1], rumbo_grados(*puntos[-2], *puntos[-1]))

    def geometria_desde(self, nodo: int, ruta: list[int], avance_m: float) -> list[tuple[float, float]]:
        """Polilínea de la ruta restante empezando en la posición exacta (nodo + avance sobre el siguiente tramo)."""
        if not ruta:
            return [self.nodos[nodo]]
        lat, lon, _ = self.punto_en_tramo(nodo, ruta[0], avance_m)
        completa = self.geometria_ruta([nodo] + list(ruta))
        primer_tramo = self.aristas[(nodo, ruta[0])].geometria or [self.nodos[nodo], self.nodos[ruta[0]]]
        # descarta los vértices del primer tramo ya recorridos
        from estructuras.geografia import haversine_metros

        recorridos = 0
        acumulado = 0.0
        for a, b in zip(primer_tramo, primer_tramo[1:]):
            acumulado += haversine_metros(*a, *b)
            if acumulado <= avance_m:
                recorridos += 1
        return [(lat, lon)] + completa[1 + recorridos:]

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
