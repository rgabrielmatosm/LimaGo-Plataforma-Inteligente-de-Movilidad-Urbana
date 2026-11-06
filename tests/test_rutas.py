"""Pruebas de Dijkstra (RF-05) y A* (Reto A)."""
import math
import random

import networkx as nx
import pytest

from algoritmos.a_estrella import a_estrella, heuristica_haversine
from algoritmos.dijkstra import (dijkstra, distancias_hacia_destino, eta_segundos, reconstruir_ruta,
                                 reconstruir_ruta_hacia, ruta_mas_corta)
from tests.conftest import nodo_malla


def a_networkx(grafo):
    g = nx.DiGraph()
    for (u, v), datos in grafo.aristas.items():
        g.add_edge(u, v, length=datos.longitud)
    g.add_nodes_from(grafo.nodos)
    return g


def test_dijkstra_grafo_pequeno_conocido():
    ady = {"A": [("B", 4), ("C", 1)], "C": [("B", 2), ("D", 7)], "B": [("D", 1)], "D": []}
    resultado = dijkstra(ady, "A")
    assert resultado.distancias == {"A": 0, "C": 1, "B": 3, "D": 4}
    assert reconstruir_ruta(resultado.predecesores, "A", "D") == ["A", "C", "B", "D"]


def test_dijkstra_igual_a_networkx_en_malla(malla):
    referencia = a_networkx(malla)
    for origen in [nodo_malla(0, 0), nodo_malla(3, 4), nodo_malla(5, 5)]:
        propio = dijkstra(malla.adyacencia, origen).distancias
        esperado = nx.single_source_dijkstra_path_length(referencia, origen, weight="length")
        assert set(propio) == set(esperado)
        for nodo, valor in esperado.items():
            assert propio[nodo] == pytest.approx(valor, abs=1e-6)


def test_reconstruccion_de_ruta_valida(malla):
    distancia, ruta, _ = ruta_mas_corta(malla.adyacencia, nodo_malla(0, 0), nodo_malla(4, 5))
    assert ruta[0] == nodo_malla(0, 0) and ruta[-1] == nodo_malla(4, 5)
    for a, b in zip(ruta, ruta[1:]):
        assert (a, b) in malla.aristas  # cada paso es una calle real en el sentido correcto
    assert malla.longitud_ruta(ruta) == pytest.approx(distancia)


def test_calle_de_sentido_unico_se_respeta(malla):
    este = ruta_mas_corta(malla.adyacencia, nodo_malla(2, 0), nodo_malla(2, 3))
    oeste = ruta_mas_corta(malla.adyacencia, nodo_malla(2, 3), nodo_malla(2, 0))
    assert este[1] == [nodo_malla(2, c) for c in range(4)]   # a favor: recta por la fila 2
    assert oeste[0] > este[0]                                  # en contra: debe rodear
    pasos_prohibidos = {(nodo_malla(2, c + 1), nodo_malla(2, c)) for c in range(5)}
    assert not pasos_prohibidos & set(zip(oeste[1], oeste[1][1:]))


def test_destino_inaccesible(malla):
    distancia, ruta, _ = ruta_mas_corta(malla.adyacencia, 999, nodo_malla(0, 0))
    assert math.isinf(distancia) and ruta is None
    with pytest.raises(KeyError):
        ruta_mas_corta(malla.adyacencia, 12345, nodo_malla(0, 0))


def test_dijkstra_inverso_equivale_a_varias_ejecuciones(malla):
    destino = nodo_malla(2, 5)
    origenes = [nodo_malla(0, 0), nodo_malla(5, 0), nodo_malla(2, 4), 999]
    inverso = distancias_hacia_destino(malla.inversa, destino, origenes)
    for origen in origenes:
        directo, ruta, _ = ruta_mas_corta(malla.adyacencia, origen, destino)
        if math.isinf(directo):
            assert origen not in inverso.asentados
            continue
        assert inverso.distancias[origen] == pytest.approx(directo)
        ruta_inv = reconstruir_ruta_hacia(inverso.predecesores, origen, destino)
        assert malla.longitud_ruta(ruta_inv) == pytest.approx(directo)


def test_eta_con_velocidad_configurable():
    assert eta_segundos(1000, 36) == pytest.approx(100)
    assert eta_segundos(1000, 18) == pytest.approx(200)
    assert math.isinf(eta_segundos(math.inf, 30))
    with pytest.raises(ValueError):
        eta_segundos(100, 0)


def test_a_estrella_igual_coste_y_menos_nodos(malla):
    r = random.Random(3)
    nodos = [n for n in malla.nodos if n != 999]
    total_a, total_d = 0, 0
    for _ in range(30):
        o, d = r.choice(nodos), r.choice(nodos)
        coste_d, _, explorados_d = ruta_mas_corta(malla.adyacencia, o, d)
        coste_a, ruta_a, explorados_a = a_estrella(malla.adyacencia, o, d, heuristica_haversine(malla.nodos, d))
        assert coste_a == pytest.approx(coste_d, abs=1e-6)
        total_a += explorados_a
        total_d += explorados_d
    assert total_a <= total_d


def test_dijkstra_rechaza_pesos_negativos():
    with pytest.raises(ValueError):
        dijkstra({1: [(2, -1.0)], 2: []}, 1)
