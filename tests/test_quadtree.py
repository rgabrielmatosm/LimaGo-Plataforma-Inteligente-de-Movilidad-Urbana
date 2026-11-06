"""Pruebas del Quadtree propio (RF-03) y de la búsqueda k-NN (RF-04)."""
import random

import pytest

from estructuras.busqueda_lineal import buscar_k_cercanos_lineal
from estructuras.geografia import Rectangulo, haversine_metros
from estructuras.quadtree import Quadtree

LIMITES = Rectangulo(-77.06, -12.14, -77.01, -12.10)


def poblar(q: Quadtree, n: int, semilla: int = 1, prop_disponibles: float = 0.7) -> dict:
    r = random.Random(semilla)
    puntos = {}
    for i in range(n):
        lat, lon = r.uniform(-12.14, -12.10), r.uniform(-77.06, -77.01)
        disponible = r.random() < prop_disponibles
        q.insertar(i, lat, lon, disponible)
        puntos[i] = (lat, lon, disponible)
    return puntos


def como_lista(puntos: dict):
    return [(i, la, lo, d) for i, (la, lo, d) in puntos.items()]


def test_quadtree_vacio():
    q = Quadtree(LIMITES)
    assert q.esta_vacio() and len(q) == 0
    assert q.buscar_rectangulo(LIMITES) == []
    assert q.buscar_k_cercanos(-12.12, -77.03, 5) == []
    assert q.vecino_mas_cercano(-12.12, -77.03) is None
    assert q.eliminar(123) is False
    q.verificar_consistencia()


def test_insercion_y_subdivision():
    q = Quadtree(LIMITES, capacidad=4)
    poblar(q, 200)
    assert len(q) == 200
    assert not q.raiz.es_hoja()
    assert q.raiz.total == 200
    q.verificar_consistencia()


def test_insercion_duplicada_y_fuera_de_limites():
    q = Quadtree(LIMITES)
    q.insertar(1, -12.12, -77.03)
    with pytest.raises(ValueError):
        q.insertar(1, -12.11, -77.02)
    with pytest.raises(ValueError):
        q.insertar(2, -12.50, -77.03)


def test_conductores_en_el_mismo_punto_no_subdividen_infinitamente():
    q = Quadtree(LIMITES, capacidad=2, profundidad_maxima=10)
    for i in range(500):
        q.insertar(i, -12.12, -77.03)
    q.verificar_consistencia()
    assert q.profundidad() == 0  # cubeta de puntos coincidentes: la raíz no se divide
    assert len(q.buscar_k_cercanos(-12.12, -77.03, 10)) == 10
    q.insertar(1000, -12.1201, -77.0301)  # un punto distinto sí provoca la división
    q.verificar_consistencia()
    assert 0 < q.profundidad() <= 10


def test_puntos_casi_coincidentes_respetan_profundidad_maxima():
    q = Quadtree(LIMITES, capacidad=1, profundidad_maxima=6)
    for i in range(50):
        q.insertar(i, -12.12 + i * 1e-12, -77.03)
    assert q.profundidad() <= 6
    q.verificar_consistencia()


def test_conductores_en_los_bordes():
    q = Quadtree(LIMITES, capacidad=1)
    esquinas = [(LIMITES.lat_min, LIMITES.lon_min), (LIMITES.lat_max, LIMITES.lon_max),
                (LIMITES.lat_min, LIMITES.lon_max), (LIMITES.lat_max, LIMITES.lon_min),
                (LIMITES.lat_centro, LIMITES.lon_centro), (LIMITES.lat_centro, LIMITES.lon_min)]
    for i, (lat, lon) in enumerate(esquinas):
        q.insertar(i, lat, lon)
    q.verificar_consistencia()
    assert sorted(q.buscar_rectangulo(LIMITES)) == list(range(len(esquinas)))
    centro = Rectangulo(LIMITES.lon_centro, LIMITES.lat_centro, LIMITES.lon_centro, LIMITES.lat_centro)
    assert q.buscar_rectangulo(centro) == [4]


def test_eliminacion_y_fusion():
    q = Quadtree(LIMITES, capacidad=4)
    puntos = poblar(q, 100)
    for i in range(0, 100, 2):
        assert q.eliminar(i)
        del puntos[i]
    assert q.eliminar(0) is False
    q.verificar_consistencia()
    for i in list(puntos):
        q.eliminar(i)
    assert q.esta_vacio() and q.raiz.es_hoja()  # todo se fusionó de nuevo en la raíz


def test_busqueda_rectangular_igual_a_filtrado_lineal():
    q = Quadtree(LIMITES, capacidad=6)
    puntos = poblar(q, 1000, semilla=3)
    r = Rectangulo(-77.045, -12.13, -77.025, -12.115)
    esperado = sorted(i for i, (la, lo, _) in puntos.items() if r.contiene(la, lo))
    assert sorted(q.buscar_rectangulo(r)) == esperado
    esperado_disp = sorted(i for i, (la, lo, d) in puntos.items() if d and r.contiene(la, lo))
    assert sorted(q.buscar_rectangulo(r, solo_disponibles=True)) == esperado_disp


def test_actualizacion_repetida_de_posiciones():
    q = Quadtree(LIMITES, capacidad=3)
    puntos = poblar(q, 300, semilla=5)
    r = random.Random(9)
    for _ in range(3000):
        i = r.randrange(300)
        lat, lon = r.uniform(-12.14, -12.10), r.uniform(-77.06, -77.01)
        q.actualizar_posicion(i, lat, lon)
        puntos[i] = (lat, lon, puntos[i][2])
    q.verificar_consistencia()
    for i, (lat, lon, _) in puntos.items():
        assert q.obtener_posicion(i) == (lat, lon)
    with pytest.raises(KeyError):
        q.actualizar_posicion(10_000, -12.12, -77.03)


def test_k_cercanos_exactos_frente_a_busqueda_lineal():
    q = Quadtree(LIMITES, capacidad=8)
    puntos = poblar(q, 3000, semilla=11)
    r = random.Random(4)
    for _ in range(300):
        lat, lon = r.uniform(-12.15, -12.09), r.uniform(-77.07, -77.00)  # incluye consultas fuera del área
        k = r.randint(1, 12)
        assert q.buscar_k_cercanos(lat, lon, k) == buscar_k_cercanos_lineal(como_lista(puntos), lat, lon, k)


def test_k_cercanos_poda_el_espacio():
    q = Quadtree(LIMITES, capacidad=8)
    poblar(q, 30000, semilla=2, prop_disponibles=1.0)
    q.buscar_k_cercanos(-12.12, -77.03, 5)
    assert q.ultima_busqueda.distancias_calculadas < 500  # muy lejos de las 30 000 de la búsqueda lineal


def test_conductores_no_disponibles_se_excluyen():
    q = Quadtree(LIMITES)
    q.insertar(1, -12.1200, -77.0300, disponible=False)  # el más cercano, pero ocupado
    q.insertar(2, -12.1210, -77.0300, disponible=True)
    q.insertar(3, -12.1300, -77.0300, disponible=True)
    assert [i for _, i in q.buscar_k_cercanos(-12.12, -77.03, 1)] == [2]
    q.cambiar_disponibilidad(2, False)
    assert [i for _, i in q.buscar_k_cercanos(-12.12, -77.03, 5)] == [3]
    q.cambiar_disponibilidad(3, False)
    assert q.buscar_k_cercanos(-12.12, -77.03, 5) == []  # sin conductores disponibles
    assert len(q.buscar_k_cercanos(-12.12, -77.03, 5, solo_disponibles=False)) == 3
    q.verificar_consistencia()


def test_k_mayor_que_disponibles_y_empates():
    q = Quadtree(LIMITES)
    for i in (5, 3, 9):
        q.insertar(i, -12.12, -77.03)  # tres conductores coincidentes → empate exacto
    resultado = q.buscar_k_cercanos(-12.121, -77.03, 10)
    assert [i for _, i in resultado] == [3, 5, 9]  # desempate determinista por id
    assert q.buscar_k_cercanos(-12.121, -77.03, 0) == []


def test_haversine_valores_conocidos():
    assert haversine_metros(-12.12, -77.03, -12.12, -77.03) == 0.0
    # 1 grado de latitud ≈ 111.2 km con R = 6 371 009 m
    assert haversine_metros(0, 0, 1, 0) == pytest.approx(111_195.08, rel=1e-6)
    # Lima → Cusco ≈ 573 km (valor de referencia de calculadoras de círculo máximo)
    assert haversine_metros(-12.0464, -77.0428, -13.5320, -71.9675) == pytest.approx(573_000, rel=0.01)
    # simetría
    assert haversine_metros(-12.1, -77.0, -12.2, -77.1) == pytest.approx(haversine_metros(-12.2, -77.1, -12.1, -77.0))


def test_cota_inferior_de_rectangulo_es_valida():
    r = random.Random(0)
    rect = Rectangulo(-77.04, -12.13, -77.02, -12.11)
    for _ in range(2000):
        lat, lon = r.uniform(-12.2, -12.05), r.uniform(-77.1, -76.95)
        cota = rect.distancia_minima_metros(lat, lon)
        # muestreo denso del rectángulo: ninguna distancia real puede ser menor que la cota
        minimo = min(haversine_metros(lat, lon, rect.lat_min + (rect.lat_max - rect.lat_min) * a / 20,
                                      rect.lon_min + (rect.lon_max - rect.lon_min) * b / 20)
                     for a in range(21) for b in range(21))
        assert cota <= minimo + 1e-6
