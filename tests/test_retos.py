"""Pruebas de los retos opcionales B (congestión), C (varios pasajeros) y D (H3), y de RF-08."""
import random

import pytest

from algoritmos.asignacion_multiple import algoritmo_hungaro, asignacion_codiciosa, costo_total, fuerza_bruta
from algoritmos.congestion import PesosDinamicos, factor_congestion, velocidad_maxima_ms
from algoritmos.a_estrella import a_estrella, heuristica_haversine
from algoritmos.dijkstra import ruta_mas_corta
from estructuras.busqueda_lineal import buscar_k_cercanos_lineal
from simulacion.despachador import Despachador
from simulacion.errores import CoordenadasInvalidas, DireccionAmbigua, DireccionNoEncontrada, FueraDeCobertura
from simulacion.flota import generar_flota
from simulacion.geocodificacion import Geocodificador, interpretar_coordenadas
from tests.conftest import nodo_malla


# ------------------------------------------------------------ Reto B
def test_congestion_hora_punta_cambia_pesos_y_eta(malla, ajustes_prueba):
    assert factor_congestion("primary", 8.0) > factor_congestion("primary", 15.0) > 1.0
    assert factor_congestion("primary", 8.0) - 1 > factor_congestion("residential", 8.0) - 1
    pesos = PesosDinamicos(malla)
    ady_8, _ = pesos.adyacencias(8.0)
    ady_15, _ = pesos.adyacencias(15.0)
    o, d = nodo_malla(0, 0), nodo_malla(5, 5)
    t8, ruta8, _ = ruta_mas_corta(ady_8, o, d)
    t15, ruta15, _ = ruta_mas_corta(ady_15, o, d)
    assert t8 > t15
    # el despachador usa esos pesos: la misma solicitud tiene ETA mayor a las 8:00
    flota = generar_flota(malla, 6, semilla=1, proporcion_ocupados=0)
    etas = {}
    for hora in (8.0, 15.0):
        desp = Despachador(malla, [c for c in generar_flota(malla, 6, semilla=1, proporcion_ocupados=0)],
                           ajustes_prueba.con(congestion_activa=True))
        desp.hora_actual = hora
        lat, lon = malla.coordenadas(nodo_malla(3, 3))
        etas[hora] = desp.solicitar_viaje(desp.crear_pasajero(1, lat, lon)).seleccionado.eta_s
    assert etas[8.0] > etas[15.0]
    assert flota  # misma flota en ambos escenarios


def test_a_estrella_admisible_con_pesos_en_tiempo(malla):
    pesos = PesosDinamicos(malla)
    ady, _ = pesos.adyacencias(8.0)
    o, d = nodo_malla(0, 0), nodo_malla(5, 4)
    coste_d, _, _ = ruta_mas_corta(ady, o, d)
    coste_a, _, _ = a_estrella(ady, o, d, heuristica_haversine(malla.nodos, d, velocidad_maxima_ms()))
    assert coste_a == pytest.approx(coste_d)


# ------------------------------------------------------------ Reto C
def test_hungaro_optimo_frente_a_fuerza_bruta_y_codicioso():
    r = random.Random(8)
    mejoras = 0
    for _ in range(60):
        n, m = r.randint(1, 5), r.randint(5, 7)
        costo = [[r.uniform(30, 600) for _ in range(m)] for _ in range(n)]
        asignacion = algoritmo_hungaro(costo)
        assert len(set(asignacion)) == n  # un conductor por pasajero
        assert costo_total(costo, asignacion) == pytest.approx(fuerza_bruta(costo))
        codicioso = costo_total(costo, asignacion_codiciosa(costo))
        assert costo_total(costo, asignacion) <= codicioso + 1e-9
        mejoras += costo_total(costo, asignacion) < codicioso - 1e-9
    assert mejoras > 0


def test_ejemplo_donde_codicioso_falla():
    # P1 llega primero y toma a C1 (10); P2 queda con C2 (100): total 110.
    # Óptimo: P1←C2 (20), P2←C1 (15): total 35.
    costo = [[10, 20], [15, 100]]
    assert costo_total(costo, asignacion_codiciosa(costo)) == 110
    assert costo_total(costo, algoritmo_hungaro(costo)) == 35


def test_asignacion_multiple_en_despachador(malla, ajustes_prueba):
    flota = generar_flota(malla, 8, semilla=5, proporcion_ocupados=0)
    desp = Despachador(malla, flota, ajustes_prueba)
    puntos = [nodo_malla(0, 0), nodo_malla(0, 1), nodo_malla(5, 5), nodo_malla(2, 3)]
    pasajeros = [desp.crear_pasajero(i, *malla.coordenadas(n)) for i, n in enumerate(puntos)]
    optimo = desp.asignar_varios(pasajeros, estrategia="optima")
    codicioso = desp.asignar_varios(pasajeros, estrategia="codiciosa")
    elegidos = [a["conductor_id"] for a in optimo["asignaciones"]]
    assert None not in elegidos and len(set(elegidos)) == len(pasajeros)
    assert optimo["espera_total_s"] <= codicioso["espera_total_s"] + 1e-9
    desp.confirmar_asignaciones(pasajeros, optimo, solicitud_ids=[10, 11, 12, 13])
    desp.verificar_consistencia()
    assert sum(not c.esta_disponible for c in desp.conductores.values()) == 4


# ------------------------------------------------------------ Reto D
def test_indice_h3_experimental_igual_a_lineal():
    from experimental.indice_h3 import IndiceH3

    r = random.Random(13)
    indice, puntos = IndiceH3(resolucion=9), []
    for i in range(2000):
        lat, lon, disp = r.uniform(-12.14, -12.10), r.uniform(-77.06, -77.01), r.random() < 0.8
        indice.insertar(i, lat, lon, disp)
        puntos.append((i, lat, lon, disp))
    for _ in range(200):
        lat, lon = r.uniform(-12.14, -12.10), r.uniform(-77.06, -77.01)
        assert indice.buscar_k_cercanos(lat, lon, 5) == buscar_k_cercanos_lineal(puntos, lat, lon, 5)
    indice.actualizar_posicion(0, -12.12, -77.03)
    assert indice.eliminar(0) and not indice.eliminar(0)


def test_solucion_principal_sin_librerias_prohibidas():
    """Análisis del código (AST): ni imports prohibidos ni llamadas a rutas/índices ya hechos."""
    import ast
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    modulos_prohibidos = {"h3", "rtree", "scipy", "sklearn", "experimental"}
    llamadas_prohibidas = {"nearest_nodes", "shortest_path", "shortest_path_length", "single_source_dijkstra",
                           "single_source_dijkstra_path_length", "dijkstra_path", "astar_path", "KDTree",
                           "cKDTree", "STRtree", "BallTree"}
    for carpeta in ("estructuras", "algoritmos", "simulacion", "api", "datos", "visualizacion"):
        for archivo in (raiz / carpeta).glob("*.py"):
            arbol = ast.parse(archivo.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    assert not {a.name.split(".")[0] for a in nodo.names} & modulos_prohibidos, archivo
                elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                    assert nodo.module.split(".")[0] not in modulos_prohibidos, archivo
                    assert not {a.name for a in nodo.names} & llamadas_prohibidas, archivo
                elif isinstance(nodo, ast.Attribute):
                    assert nodo.attr not in llamadas_prohibidas, f"{nodo.attr} en {archivo}"


# ------------------------------------------------------------ RF-08
def falso_nominatim(respuestas):
    def cliente(ruta, parametros):
        return respuestas.get(parametros.get("q"), [])
    return cliente


def test_ingreso_por_coordenadas_y_validacion(malla, ajustes_prueba):
    assert interpretar_coordenadas("-12.1211, -77.0297") == (-12.1211, -77.0297)
    assert interpretar_coordenadas("(-12,1211; -77,0297)") == (-12.1211, -77.0297)
    assert interpretar_coordenadas("Av. Larco 345") is None
    with pytest.raises(CoordenadasInvalidas):
        interpretar_coordenadas("-120.5, -77.0")
    geo = Geocodificador(ajustes_prueba, malla.limites(), cliente_http=falso_nominatim({}), usar_cache=False)
    lat, lon = malla.coordenadas(nodo_malla(1, 1))
    assert geo.resolver(f"{lat}, {lon}").lat == lat
    with pytest.raises(FueraDeCobertura):
        geo.resolver("-12.0464, -77.0428")


def test_direccion_encontrada_ambigua_y_no_encontrada(malla, ajustes_prueba):
    a = malla.coordenadas(nodo_malla(0, 0))
    b = malla.coordenadas(nodo_malla(5, 5))
    respuestas = {
        "Parque Central, Lima": [{"display_name": "Parque Central, Miraflores", "lat": a[0], "lon": a[1], "importance": 0.5}],
        "Calle Bolognesi, Lima": [
            {"display_name": "Calle Bolognesi, Barrio A", "lat": a[0], "lon": a[1], "importance": 0.4},
            {"display_name": "Calle Bolognesi, Barrio B", "lat": b[0], "lon": b[1], "importance": 0.3},
        ],
        "Lugar Lejano, Lima": [{"display_name": "Callao", "lat": -12.05, "lon": -77.13, "importance": 0.9}],
    }
    geo = Geocodificador(ajustes_prueba, malla.limites(), cliente_http=falso_nominatim(respuestas), usar_cache=False)
    assert geo.resolver("Parque Central").direccion == "Parque Central, Miraflores"
    with pytest.raises(DireccionAmbigua) as error:
        geo.resolver("Calle Bolognesi")
    assert len(error.value.opciones) == 2
    with pytest.raises(DireccionNoEncontrada):
        geo.resolver("Lugar Lejano")  # existe, pero fuera de la cobertura
    with pytest.raises(DireccionNoEncontrada):
        geo.resolver("ab")
