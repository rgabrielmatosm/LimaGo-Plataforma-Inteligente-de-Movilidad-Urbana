"""Pruebas de flota (RF-02), Despachador (RF-04/05) y ubicación del pasajero (RF-08)."""
import threading

import pytest

from estructuras.geografia import haversine_metros
from simulacion.despachador import Despachador
from simulacion.errores import CoordenadasInvalidas, FueraDeCobertura, SinConexionVial
from simulacion.flota import generar_flota
from simulacion.modelos import Conductor, EstadoConductor
from tests.conftest import LAT0, LON0, PASO, nodo_malla


def conductor_en(grafo, cid, nodo, estado=EstadoConductor.DISPONIBLE):
    lat, lon = grafo.coordenadas(nodo)
    return Conductor(id=cid, nodo=nodo, lat=lat, lon=lon, estado=estado)


def test_flota_reproducible_y_sobre_intersecciones(malla):
    a = generar_flota(malla, 50, semilla=123, proporcion_ocupados=0.3)
    b = generar_flota(malla, 50, semilla=123, proporcion_ocupados=0.3)
    c = generar_flota(malla, 50, semilla=124, proporcion_ocupados=0.3)
    firma = lambda flota: [(x.id, x.nodo, x.estado, x.destino_nodo) for x in flota]  # noqa: E731
    assert firma(a) == firma(b)
    assert firma(a) != firma(c)
    principal = malla.componente_principal()
    assert 999 not in principal  # el nodo trampa no es válido para ubicar conductores
    for conductor in a:
        assert conductor.nodo in principal
        assert (conductor.lat, conductor.lon) == malla.coordenadas(conductor.nodo)
    assert len({x.id for x in a}) == 50
    assert generar_flota(malla, 0, 1) == []


def test_seleccion_por_menor_eta_no_por_linea_recta(malla, ajustes_prueba):
    # Pasajero en (2,1). El conductor A está en (2,2): a 1 cuadra en línea recta, pero la fila 2
    # es de sentido único hacia el este y debe rodear (3 cuadras). B está en (4,1): el doble de
    # lejos en línea recta, pero llega directo (2 cuadras).
    pasajero_nodo = nodo_malla(2, 1)
    a = conductor_en(malla, 1, nodo_malla(2, 2))
    b = conductor_en(malla, 2, nodo_malla(4, 1))
    despachador = Despachador(malla, [a, b], ajustes_prueba)
    lat, lon = malla.coordenadas(pasajero_nodo)
    pasajero = despachador.crear_pasajero(1, lat, lon)
    resultado = despachador.solicitar_viaje(pasajero, k=2)
    por_id = {c.conductor_id: c for c in resultado.candidatos}
    assert por_id[1].distancia_recta_m < por_id[2].distancia_recta_m
    assert resultado.seleccionado.conductor_id == 2
    assert por_id[2].eta_s < por_id[1].eta_s
    assert por_id[1].eta_s > por_id[1].distancia_recta_m / 10  # tuvo que rodear
    assert resultado.seleccionado.eta_s == pytest.approx(resultado.seleccionado.distancia_calles_m / 10)
    assert resultado.ruta_coordenadas[-1] == (lat, lon)


def test_estado_actualizado_y_sin_asignacion_duplicada(malla, ajustes_prueba):
    flota = [conductor_en(malla, 1, nodo_malla(0, 0)), conductor_en(malla, 2, nodo_malla(5, 5))]
    despachador = Despachador(malla, flota, ajustes_prueba)
    lat, lon = malla.coordenadas(nodo_malla(0, 1))
    r1 = despachador.solicitar_viaje(despachador.crear_pasajero(1, lat, lon), solicitud_id=1)
    r2 = despachador.solicitar_viaje(despachador.crear_pasajero(2, lat, lon), solicitud_id=2)
    r3 = despachador.solicitar_viaje(despachador.crear_pasajero(3, lat, lon), solicitud_id=3)
    assert r1.seleccionado.conductor_id == 1 and r2.seleccionado.conductor_id == 2
    assert r3.estado == "sin_conductores"  # búsqueda sin conductores disponibles
    assert despachador.conductores[1].estado is EstadoConductor.EN_CAMINO
    assert not despachador.quadtree.esta_disponible(1)
    despachador.verificar_consistencia()


def test_solicitudes_concurrentes_no_comparten_conductor(malla, ajustes_prueba):
    flota = generar_flota(malla, 15, semilla=3, proporcion_ocupados=0.0)
    despachador = Despachador(malla, flota, ajustes_prueba)
    lat, lon = malla.coordenadas(nodo_malla(3, 3))
    resultados = []

    def pedir(i):
        resultados.append(despachador.solicitar_viaje(despachador.crear_pasajero(i, lat, lon), solicitud_id=i))

    hilos = [threading.Thread(target=pedir, args=(i,)) for i in range(25)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    asignados = [r.seleccionado.conductor_id for r in resultados if r.exito]
    assert len(asignados) == 15 and len(set(asignados)) == 15
    assert sum(r.estado == "sin_conductores" for r in resultados) == 10
    despachador.verificar_consistencia()


def test_conductor_que_no_puede_llegar(malla, ajustes_prueba):
    atrapado = conductor_en(malla, 1, 999)  # desde el nodo trampa no se puede salir
    despachador = Despachador(malla, [atrapado], ajustes_prueba, nodos_validos=set(malla.nodos))
    lat, lon = malla.coordenadas(nodo_malla(3, 3))
    resultado = despachador.solicitar_viaje(despachador.crear_pasajero(1, lat, lon))
    assert resultado.estado == "sin_ruta"
    assert despachador.conductores[1].esta_disponible  # no se ocupa a nadie si no hay ruta


def test_pasajero_sin_conexion_vial(malla, ajustes_prueba):
    despachador = Despachador(malla, [], ajustes_prueba.con(distancia_maxima_conexion_m=30))
    # centro de una manzana: ~78 m de cualquier intersección
    with pytest.raises(SinConexionVial):
        despachador.crear_pasajero(1, LAT0 + 2.5 * PASO, LON0 + 2.5 * PASO)


def test_validacion_de_coordenadas(malla, ajustes_prueba):
    despachador = Despachador(malla, [], ajustes_prueba)
    with pytest.raises(CoordenadasInvalidas):
        despachador.crear_pasajero(1, 95.0, -77.03)
    with pytest.raises(CoordenadasInvalidas):
        despachador.crear_pasajero(1, float("nan"), -77.03)
    with pytest.raises(FueraDeCobertura):
        despachador.crear_pasajero(1, -12.0464, -77.0428)  # centro de Lima, fuera de la malla
    pasajero = despachador.crear_pasajero(1, LAT0 + 0.0001, LON0 + 0.0001)
    assert pasajero.nodo == nodo_malla(0, 0)
    assert pasajero.distancia_a_red_m == pytest.approx(haversine_metros(LAT0 + 0.0001, LON0 + 0.0001, LAT0, LON0))


def test_ubicacion_usa_quadtree_de_intersecciones(malla, ajustes_prueba):
    despachador = Despachador(malla, [], ajustes_prueba)
    for nodo in malla.componente_principal():
        lat, lon = malla.coordenadas(nodo)
        assert despachador.ubicar_en_red(lat + 1e-5, lon - 1e-5)[0] == nodo
