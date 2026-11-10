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


# ------------------------------------------------- API + worker (integración)
TOKEN = "token-de-prueba"


def crear_entorno_api(malla, ajustes):
    """API real con un worker en un hilo, SQLite temporal y geocodificador falso (sin red). Generador."""
    import threading
    import time

    from fastapi.testclient import TestClient

    from api import main as api_main
    from api.persistencia import BaseDatos
    from api.worker import Trabajador
    from simulacion.geocodificacion import Geocodificador

    respuestas = {"Plaza Central, Lima": [{"display_name": "Plaza Central, Miraflores", "lat": LAT0 + 3 * PASO,
                                           "lon": LON0 + 3 * PASO, "importance": 0.5}]}
    geo = Geocodificador(ajustes, malla.limites(), cliente_http=lambda r, p: respuestas.get(p.get("q"), []),
                         usar_cache=False)
    trabajador = Trabajador(ajustes, BaseDatos(ajustes.url_base_datos), malla)
    trabajador.iniciar()
    trabajador.simulador.pausar()  # turnos controlados por la prueba
    trabajador.publicar()

    def bucle():
        while not trabajador._detener.is_set():
            trabajador.paso()
            time.sleep(0.02)

    hilo = threading.Thread(target=bucle, daemon=True)
    hilo.start()
    api_main.configurar(ajustes, malla, geo)
    with TestClient(api_main.app) as cliente:
        cliente.headers.update({"Authorization": f"Bearer {TOKEN}"})  # operador autenticado
        yield cliente, trabajador
    trabajador.detener()
    hilo.join(timeout=5)


def ajustes_api(ajustes_prueba, **extra):
    return ajustes_prueba.con(num_conductores=10, proporcion_ocupados=0.0, intervalo_real_turno_s=0.05,
                              distancia_maxima_conexion_m=60, token_operaciones=TOKEN, **extra)


@pytest.fixture
def entorno_api(malla, ajustes_prueba):
    yield from crear_entorno_api(malla, ajustes_api(ajustes_prueba))
