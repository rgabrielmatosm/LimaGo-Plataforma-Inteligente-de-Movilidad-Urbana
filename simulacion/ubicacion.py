"""Ubicación de puntos sobre la red vial (RF-08) con un Quadtree propio de intersecciones.

Se separó del Despachador para reutilizarla en el backend (validar cobertura y
estimar tarifas) sin que el backend tenga una copia de la flota. No se usa
``osmnx.nearest_nodes`` porque depende de un índice espacial ya hecho.

V3: la cobertura se valida con el **polígono real** del área (algoritmo propio
de cruce de rayos, :class:`estructuras.geografia.PoligonoCobertura`), no con un
rectángulo, y después con la distancia a la vía más cercana: así no se afirma
cobertura en zonas sin datos viales utilizables.
"""
from __future__ import annotations

import json
from pathlib import Path

from algoritmos.grafo import GrafoVial
from estructuras.geografia import PoligonoCobertura, Rectangulo, validar_coordenadas
from estructuras.quadtree import Quadtree
from simulacion.errores import CoordenadasInvalidas, FueraDeCobertura, SinConexionVial


def cargar_poligono(ruta: Path | None) -> PoligonoCobertura | None:
    if ruta is None or not Path(ruta).exists():
        return None
    return PoligonoCobertura.desde_geojson(json.loads(Path(ruta).read_text(encoding="utf-8")))


class UbicadorRed:
    def __init__(self, grafo: GrafoVial, distancia_maxima_m: float, nodos_validos: set[int] | None = None,
                 poligono: PoligonoCobertura | None = None, nombre_cobertura: str = "Miraflores") -> None:
        self.grafo = grafo
        self.distancia_maxima_m = distancia_maxima_m
        self.nodos_validos = nodos_validos if nodos_validos is not None else grafo.componente_principal()
        self.limites: Rectangulo = grafo.limites()
        self.poligono = poligono
        self.nombre_cobertura = nombre_cobertura
        self.indice = Quadtree(self.limites, capacidad=16, profundidad_maxima=22)
        for nodo in sorted(self.nodos_validos):
            lat, lon = grafo.coordenadas(nodo)
            self.indice.insertar(nodo, lat, lon, True)

    def en_cobertura(self, lat: float, lon: float) -> bool:
        if not self.limites.contiene(lat, lon):
            return False
        return self.poligono.contiene(lat, lon) if self.poligono is not None else True

    def ubicar(self, lat: float, lon: float) -> tuple[int, float]:
        """Intersección conectada más cercana y su distancia en metros.

        Lanza :class:`CoordenadasInvalidas`, :class:`FueraDeCobertura` o
        :class:`SinConexionVial` con mensajes aptos para el usuario.
        """
        try:
            validar_coordenadas(lat, lon)
        except ValueError as error:
            raise CoordenadasInvalidas(str(error)) from error
        if not self.en_cobertura(lat, lon):
            raise FueraDeCobertura(f"La ubicación está fuera de la zona de cobertura de {self.nombre_cobertura}")
        mas_cercano = self.indice.vecino_mas_cercano(lat, lon)
        if mas_cercano is None:
            raise SinConexionVial("No hay calles disponibles en la red")
        distancia, nodo = mas_cercano
        if distancia > self.distancia_maxima_m:
            raise SinConexionVial(
                f"La ubicación está a {distancia:.0f} m de la calle más cercana; elige un punto junto a una vía"
            )
        return nodo, distancia


class Distritos:
    """Nombre del distrito de un punto (límites OSM admin_level 8), con el mismo algoritmo de cruce de rayos."""

    def __init__(self, ruta: Path | None) -> None:
        self.zonas: list[tuple[str, PoligonoCobertura]] = []
        if ruta is not None and Path(ruta).exists():
            datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
            for f in datos["features"]:
                self.zonas.append((f["properties"]["nombre"], PoligonoCobertura.desde_geojson(f)))

    def __len__(self) -> int:
        return len(self.zonas)

    def nombres(self) -> list[str]:
        return [n for n, _ in self.zonas]

    def distrito_de(self, lat: float, lon: float) -> str | None:
        for nombre, poligono in self.zonas:
            if poligono.contiene(lat, lon):
                return nombre
        return None
