"""Fixtures compartidas: grafos sintéticos pequeños y, si existe, la red real."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from algoritmos.grafo import GrafoVial  # noqa: E402
from config.ajustes import Ajustes  # noqa: E402
from estructuras.geografia import haversine_metros  # noqa: E402

LAT0, LON0, PASO = -12.1250, -77.0350, 0.001  # ~111 m entre intersecciones


def nodo_malla(fila: int, columna: int) -> int:
    return fila * 10 + columna


def construir_malla(n: int = 6, calle_unica_fila: int | None = 2) -> GrafoVial:
    """Malla n×n de calles de doble sentido; la fila ``calle_unica_fila`` es de sentido único (oeste→este).

    Se agrega además un nodo ``999`` "trampa": se puede entrar desde (0,0) pero no salir.
    """
    grafo = GrafoVial()
    for f in range(n):
        for c in range(n):
            grafo.agregar_nodo(nodo_malla(f, c), LAT0 + f * PASO, LON0 + c * PASO)

    def unir(a: int, b: int, doble: bool = True) -> None:
        la, loa = grafo.coordenadas(a)
        lb, lob = grafo.coordenadas(b)
        d = haversine_metros(la, loa, lb, lob)
        grafo.agregar_arista(a, b, d, tipo_via="residential", sentido_unico=not doble)
        if doble:
            grafo.agregar_arista(b, a, d, tipo_via="residential")

    for f in range(n):
        for c in range(n):
            if c + 1 < n:
                unir(nodo_malla(f, c), nodo_malla(f, c + 1), doble=(f != calle_unica_fila))
            if f + 1 < n:
                unir(nodo_malla(f, c), nodo_malla(f + 1, c))
    grafo.agregar_nodo(999, LAT0 - PASO, LON0 - PASO)
    la, loa = grafo.coordenadas(0)
    grafo.agregar_arista(0, 999, haversine_metros(la, loa, LAT0 - PASO, LON0 - PASO), tipo_via="service", sentido_unico=True)
    return grafo


@pytest.fixture
def malla() -> GrafoVial:
    return construir_malla()


@pytest.fixture
def ajustes_prueba(tmp_path) -> Ajustes:
    return Ajustes().con(
        num_conductores=20,
        semilla=7,
        k_candidatos=3,
        velocidad_promedio_kmh=36.0,  # 10 m/s: ETA fácil de verificar
        segundos_por_turno=10.0,
        tasa_solicitudes_por_turno=0.0,
        distancia_maxima_conexion_m=250.0,
        ruta_cache_geocodificacion=tmp_path / "cache.json",
        url_base_datos=f"sqlite:///{tmp_path / 'prueba.db'}",
    )


@pytest.fixture(scope="session")
def grafo_real_nx():
    ruta = RAIZ / "datos" / "miraflores.graphml"
    if not ruta.exists():
        pytest.skip("La red real de Miraflores aún no se ha descargado (python -m datos.red_vial)")
    import osmnx as ox

    return ox.load_graphml(ruta)


@pytest.fixture(scope="session")
def grafo_real(grafo_real_nx) -> GrafoVial:
    return GrafoVial.desde_networkx(grafo_real_nx)
