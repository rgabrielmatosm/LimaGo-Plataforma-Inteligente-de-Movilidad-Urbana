"""RF-03 / RF-04 — Quadtree propio de puntos (región) con búsqueda k-NN exacta.

Diseño
------
* Cada :class:`NodoQuadtree` cubre un :class:`Rectangulo` (x = longitud, y = latitud).
  Un nodo es **hoja** (guarda una lista de entradas) o **interno** (tiene
  exactamente cuatro hijos: NO, NE, SO, SE).
* Cada nodo mantiene dos contadores de su subárbol: ``total`` y ``disponibles``.
  Permiten podar ramas sin conductores disponibles y decidir fusiones.
* Política anti-subdivisión infinita:
    1. una hoja se divide solo si supera ``capacidad`` **y** su profundidad es
       menor que ``profundidad_maxima``;
    2. si todos los puntos de la hoja tienen exactamente las mismas
       coordenadas, no se divide (dividir nunca los separaría): la hoja actúa
       como *cubeta* y crece más allá de la capacidad.
* Bordes: los rectángulos son cerrados, pero cada punto se envía a un único
  hijo con la regla determinista ``lon >= centro → este`` y
  ``lat >= centro → norte``. Así ningún punto se duplica ni se pierde.
* Un diccionario ``id → entrada`` permite eliminar y actualizar en
  O(profundidad) sin recorrer el árbol completo.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Iterator

from estructuras.geografia import Rectangulo, haversine_metros

NOROESTE, NORESTE, SUROESTE, SURESTE = 0, 1, 2, 3


class EntradaQuadtree:
    """Punto almacenado: identificador del conductor, posición y disponibilidad."""

    __slots__ = ("id", "lat", "lon", "disponible")

    def __init__(self, identificador: int, lat: float, lon: float, disponible: bool) -> None:
        self.id = identificador
        self.lat = lat
        self.lon = lon
        self.disponible = disponible

    def __repr__(self) -> str:  # pragma: no cover - depuración
        estado = "D" if self.disponible else "O"
        return f"Entrada({self.id}, {self.lat:.6f}, {self.lon:.6f}, {estado})"


class NodoQuadtree:
    """Nodo del Quadtree. Hoja si ``hijos is None``."""

    __slots__ = ("limites", "profundidad", "puntos", "hijos", "total", "disponibles")

    def __init__(self, limites: Rectangulo, profundidad: int = 0) -> None:
        self.limites = limites
        self.profundidad = profundidad
        self.puntos: list[EntradaQuadtree] | None = []
        self.hijos: list[NodoQuadtree] | None = None
        self.total = 0
        self.disponibles = 0

    def es_hoja(self) -> bool:
        return self.hijos is None

    def indice_hijo(self, lat: float, lon: float) -> int:
        """Cuadrante que corresponde al punto (regla determinista en bordes)."""
        este = lon >= self.limites.lon_centro
        norte = lat >= self.limites.lat_centro
        if norte:
            return NORESTE if este else NOROESTE
        return SURESTE if este else SUROESTE

    def puntos_coincidentes(self) -> bool:
        """``True`` si todos los puntos de la hoja tienen las mismas coordenadas."""
        if not self.puntos:
            return True
        primero = self.puntos[0]
        return all(p.lat == primero.lat and p.lon == primero.lon for p in self.puntos)

    def __repr__(self) -> str:  # pragma: no cover - depuración
        tipo = "hoja" if self.es_hoja() else "interno"
        return f"NodoQuadtree({tipo}, prof={self.profundidad}, total={self.total})"


@dataclass
class EstadisticasBusqueda:
    """Métricas de la última búsqueda (para explicar la poda en la sustentación)."""

    nodos_visitados: int = 0
    distancias_calculadas: int = 0
    nodos_podados: int = 0
    extra: dict = field(default_factory=dict)


class Quadtree:
    """Índice espacial propio de conductores."""

    def __init__(self, limites: Rectangulo, capacidad: int = 8, profundidad_maxima: int = 18) -> None:
        if capacidad < 1:
            raise ValueError("La capacidad debe ser al menos 1")
        if profundidad_maxima < 0:
            raise ValueError("La profundidad máxima no puede ser negativa")
        self.limites = limites
        self.capacidad = capacidad
        self.profundidad_maxima = profundidad_maxima
        self.raiz = NodoQuadtree(limites, 0)
        self._entradas: dict[int, EntradaQuadtree] = {}
        self.ultima_busqueda = EstadisticasBusqueda()

    # ------------------------------------------------------------------ util
    def __len__(self) -> int:
        return len(self._entradas)

    def __contains__(self, identificador: int) -> bool:
        return identificador in self._entradas

    def esta_vacio(self) -> bool:
        return not self._entradas

    def obtener_posicion(self, identificador: int) -> tuple[float, float]:
        entrada = self._entradas[identificador]
        return entrada.lat, entrada.lon

    def esta_disponible(self, identificador: int) -> bool:
        return self._entradas[identificador].disponible

    def _camino_hasta_hoja(self, lat: float, lon: float) -> list[NodoQuadtree]:
        camino = [self.raiz]
        nodo = self.raiz
        while nodo.hijos is not None:
            nodo = nodo.hijos[nodo.indice_hijo(lat, lon)]
            camino.append(nodo)
        return camino

    # -------------------------------------------------------------- insertar
    def insertar(self, identificador: int, lat: float, lon: float, disponible: bool = True) -> None:
        """Inserta un conductor. O(profundidad) amortizado.

        Lanza ``ValueError`` si el identificador ya existe o el punto está fuera
        de los límites del árbol.
        """
        if identificador in self._entradas:
            raise ValueError(f"El conductor {identificador} ya está en el Quadtree")
        if not self.limites.contiene(lat, lon):
            raise ValueError(f"Punto fuera de los límites del Quadtree: ({lat}, {lon})")
        entrada = EntradaQuadtree(identificador, lat, lon, disponible)
        self._entradas[identificador] = entrada
        nodo = self.raiz
        while True:
            nodo.total += 1
            if disponible:
                nodo.disponibles += 1
            if nodo.hijos is None:
                nodo.puntos.append(entrada)
                self._dividir_si_corresponde(nodo)
                return
            nodo = nodo.hijos[nodo.indice_hijo(lat, lon)]

    def _dividir_si_corresponde(self, hoja: NodoQuadtree) -> None:
        pendientes = [hoja]
        while pendientes:
            nodo = pendientes.pop()
            if (
                len(nodo.puntos) <= self.capacidad
                or nodo.profundidad >= self.profundidad_maxima
                or nodo.puntos_coincidentes()
            ):
                continue
            nodo.hijos = [NodoQuadtree(r, nodo.profundidad + 1) for r in nodo.limites.subdividir()]
            for entrada in nodo.puntos:
                hijo = nodo.hijos[nodo.indice_hijo(entrada.lat, entrada.lon)]
                hijo.puntos.append(entrada)
                hijo.total += 1
                if entrada.disponible:
                    hijo.disponibles += 1
            nodo.puntos = None
            pendientes.extend(h for h in nodo.hijos if len(h.puntos) > self.capacidad)

    # -------------------------------------------------------------- eliminar
    def eliminar(self, identificador: int) -> bool:
        """Elimina un conductor. Devuelve ``False`` si no existía. O(profundidad).

        Después de eliminar, los nodos internos cuyo subárbol queda con
        ``total <= capacidad`` se fusionan en una hoja para mantener el árbol
        compacto.
        """
        entrada = self._entradas.pop(identificador, None)
        if entrada is None:
            return False
        camino = self._camino_hasta_hoja(entrada.lat, entrada.lon)
        hoja = camino[-1]
        for indice, punto in enumerate(hoja.puntos):
            if punto is entrada:
                hoja.puntos.pop(indice)
                break
        else:  # pragma: no cover - indicaría corrupción del árbol
            raise RuntimeError("Inconsistencia: la entrada no está en su hoja")
        for nodo in camino:
            nodo.total -= 1
            if entrada.disponible:
                nodo.disponibles -= 1
        for nodo in reversed(camino[:-1]):
            if nodo.total <= self.capacidad:
                self._fusionar(nodo)
        return True

    @staticmethod
    def _fusionar(nodo: NodoQuadtree) -> None:
        puntos: list[EntradaQuadtree] = []
        pila = [nodo]
        while pila:
            actual = pila.pop()
            if actual.hijos is None:
                puntos.extend(actual.puntos)
            else:
                pila.extend(actual.hijos)
        nodo.hijos = None
        nodo.puntos = puntos

    # ------------------------------------------------------------ actualizar
    def actualizar_posicion(self, identificador: int, lat: float, lon: float) -> None:
        """Mueve un conductor. Si sigue en la misma hoja solo cambia sus coordenadas;
        si cambia de hoja se elimina y se reinserta. O(profundidad)."""
        entrada = self._entradas.get(identificador)
        if entrada is None:
            raise KeyError(f"El conductor {identificador} no está en el Quadtree")
        if not self.limites.contiene(lat, lon):
            raise ValueError(f"Punto fuera de los límites del Quadtree: ({lat}, {lon})")
        if entrada.lat == lat and entrada.lon == lon:
            return
        hoja = self._camino_hasta_hoja(entrada.lat, entrada.lon)[-1]
        if hoja.limites.contiene(lat, lon) and hoja is self._camino_hasta_hoja(lat, lon)[-1]:
            entrada.lat, entrada.lon = lat, lon
            self._dividir_si_corresponde(hoja)  # una cubeta coincidente puede separarse
            return
        disponible = entrada.disponible
        self.eliminar(identificador)
        self.insertar(identificador, lat, lon, disponible)

    def cambiar_disponibilidad(self, identificador: int, disponible: bool) -> None:
        """Marca un conductor como disponible u ocupado actualizando los contadores. O(profundidad)."""
        entrada = self._entradas.get(identificador)
        if entrada is None:
            raise KeyError(f"El conductor {identificador} no está en el Quadtree")
        if entrada.disponible == disponible:
            return
        delta = 1 if disponible else -1
        for nodo in self._camino_hasta_hoja(entrada.lat, entrada.lon):
            nodo.disponibles += delta
        entrada.disponible = disponible

    # ----------------------------------------------------- búsqueda rectángulo
    def buscar_rectangulo(self, rectangulo: Rectangulo, solo_disponibles: bool = False) -> list[int]:
        """Identificadores dentro del rectángulo (bordes incluidos). O(log n + m) típico."""
        resultado: list[int] = []
        pila = [self.raiz]
        while pila:
            nodo = pila.pop()
            if nodo.total == 0 or (solo_disponibles and nodo.disponibles == 0):
                continue
            if not nodo.limites.intersecta(rectangulo):
                continue
            if nodo.hijos is None:
                for p in nodo.puntos:
                    if (not solo_disponibles or p.disponible) and rectangulo.contiene(p.lat, p.lon):
                        resultado.append(p.id)
            else:
                pila.extend(nodo.hijos)
        return resultado

    # ------------------------------------------------------- k más cercanos
    def buscar_k_cercanos(
        self, lat: float, lon: float, k: int, solo_disponibles: bool = True
    ) -> list[tuple[float, int]]:
        """Los ``k`` conductores más cercanos en línea recta (Haversine), exactos.

        Búsqueda *best-first*:

        * ``frontera`` es un min-heap de nodos ordenados por la cota inferior de
          distancia de su rectángulo (``Rectangulo.distancia_minima_metros``).
        * ``mejores`` es un max-heap de tamaño ``k`` (se guardan valores
          negados) con los candidatos encontrados.
        * Cuando la menor cota de la frontera supera la peor distancia de
          ``mejores`` ningún nodo pendiente puede mejorar el resultado y la
          búsqueda termina: esa es la poda espacial.

        Devuelve una lista ``[(distancia_m, id), ...]`` ordenada de menor a mayor
        (empates por id). Si hay menos de ``k`` conductores elegibles se
        devuelven todos los que haya.
        """
        estadisticas = EstadisticasBusqueda()
        self.ultima_busqueda = estadisticas
        if k <= 0:
            return []
        contador = 0
        frontera: list[tuple[float, int, NodoQuadtree]] = [(0.0, contador, self.raiz)]
        mejores: list[tuple[float, int]] = []  # (-distancia, -id)
        while frontera:
            cota, _, nodo = heapq.heappop(frontera)
            if len(mejores) == k and cota > -mejores[0][0]:
                estadisticas.nodos_podados += len(frontera) + 1
                break
            estadisticas.nodos_visitados += 1
            if nodo.hijos is None:
                for p in nodo.puntos:
                    if solo_disponibles and not p.disponible:
                        continue
                    distancia = haversine_metros(lat, lon, p.lat, p.lon)
                    estadisticas.distancias_calculadas += 1
                    clave = (-distancia, -p.id)
                    if len(mejores) < k:
                        heapq.heappush(mejores, clave)
                    elif clave > mejores[0]:  # (dist, id) menor que el peor actual
                        heapq.heapreplace(mejores, clave)
                continue
            for hijo in nodo.hijos:
                cantidad = hijo.disponibles if solo_disponibles else hijo.total
                if cantidad == 0:
                    estadisticas.nodos_podados += 1
                    continue
                cota_hijo = hijo.limites.distancia_minima_metros(lat, lon)
                if len(mejores) == k and cota_hijo > -mejores[0][0]:
                    estadisticas.nodos_podados += 1
                    continue
                contador += 1
                heapq.heappush(frontera, (cota_hijo, contador, hijo))
        return sorted((-d, -i) for d, i in mejores)

    def vecino_mas_cercano(self, lat: float, lon: float) -> tuple[float, int] | None:
        resultado = self.buscar_k_cercanos(lat, lon, 1, solo_disponibles=False)
        return resultado[0] if resultado else None

    # ----------------------------------------------------- diagnóstico
    def iterar_nodos(self) -> Iterator[NodoQuadtree]:
        pila = [self.raiz]
        while pila:
            nodo = pila.pop()
            yield nodo
            if nodo.hijos is not None:
                pila.extend(nodo.hijos)

    def profundidad(self) -> int:
        return max(n.profundidad for n in self.iterar_nodos())

    def contar_nodos(self) -> int:
        return sum(1 for _ in self.iterar_nodos())

    def verificar_consistencia(self) -> None:
        """Comprueba invariantes; lanza ``AssertionError`` si alguno falla."""
        vistos: set[int] = set()
        for nodo in self.iterar_nodos():
            if nodo.hijos is None:
                assert nodo.total == len(nodo.puntos), "total de hoja incorrecto"
                assert nodo.disponibles == sum(p.disponible for p in nodo.puntos)
                for p in nodo.puntos:
                    assert nodo.limites.contiene(p.lat, p.lon), "punto fuera de su hoja"
                    assert p.id not in vistos, "punto duplicado"
                    assert self._entradas.get(p.id) is p, "diccionario desincronizado"
                    assert self._camino_hasta_hoja(p.lat, p.lon)[-1] is nodo, "hoja incorrecta"
                    vistos.add(p.id)
            else:
                assert nodo.puntos is None and len(nodo.hijos) == 4
                assert nodo.total == sum(h.total for h in nodo.hijos)
                assert nodo.disponibles == sum(h.disponibles for h in nodo.hijos)
        assert vistos == set(self._entradas), "hay entradas perdidas"
