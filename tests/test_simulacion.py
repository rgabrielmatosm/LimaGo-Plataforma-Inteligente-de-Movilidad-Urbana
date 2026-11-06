"""Pruebas de la simulación por turnos (RF-06) y de la red real (RF-01, RF-09)."""
import json
import random

import networkx as nx
import pytest

from algoritmos.dijkstra import dijkstra
from simulacion.modelos import EstadoConductor
from simulacion.turnos import Simulador
from tests.conftest import nodo_malla


def test_simulacion_mantiene_quadtree_consistente(malla, ajustes_prueba):
    simulador = Simulador(malla, ajustes_prueba.con(num_conductores=12, tasa_solicitudes_por_turno=0.5))
    posiciones_previas = {c.id: c.nodo for c in simulador.despachador.conductores.values()}
    for _ in range(60):
        simulador.avanzar_turno()
        simulador.despachador.verificar_consistencia()
        for conductor in simulador.despachador.conductores.values():
            previo = posiciones_previas[conductor.id]
            if previo != conductor.nodo:
                # nunca hay saltos imposibles: existe un camino dirigido del nodo previo al actual
                assert conductor.nodo in dijkstra(malla.adyacencia, previo).distancias
            posiciones_previas[conductor.id] = conductor.nodo
    assert simulador.turno == 60


def test_ciclo_de_vida_de_un_viaje(malla, ajustes_prueba):
    simulador = Simulador(malla, ajustes_prueba.con(num_conductores=5, proporcion_ocupados=0.0))
    lat, lon = malla.coordenadas(nodo_malla(5, 5))
    destino = malla.coordenadas(nodo_malla(0, 5))
    pasajero = simulador.despachador.crear_pasajero(1, lat, lon, destino=destino)
    resultado = simulador.solicitar_viaje(pasajero, solicitud_id=77)
    conductor = simulador.despachador.conductores[resultado.seleccionado.conductor_id]
    assert conductor.estado is EstadoConductor.EN_CAMINO and conductor.solicitud_id == 77
    tipos = []
    for _ in range(200):
        tipos += [e.tipo for e in simulador.avanzar_turno() if e.solicitud_id == 77]
        if "viaje_finalizado" in tipos:
            break
    assert tipos == ["recogida", "viaje_finalizado"]
    assert conductor.esta_disponible and conductor.nodo == nodo_malla(0, 5)
    assert simulador.despachador.quadtree.esta_disponible(conductor.id)


def test_pausa_reinicio_y_reproducibilidad(malla, ajustes_prueba):
    ajustes = ajustes_prueba.con(num_conductores=10, tasa_solicitudes_por_turno=0.7)
    a, b = Simulador(malla, ajustes), Simulador(malla, ajustes)
    for _ in range(25):
        a.avanzar_turno()
        b.avanzar_turno()
    assert a.instantanea() == b.instantanea()
    a.pausar()
    assert a.en_pausa
    a.reanudar()
    a.reiniciar()
    assert a.turno == 0
    assert [c.nodo for c in a.despachador.conductores.values()] == \
           [c.nodo for c in Simulador(malla, ajustes).despachador.conductores.values()]
    assert a.proxima_solicitud_id >= b.proxima_solicitud_id  # los ids de solicitud no se reutilizan
    a.reiniciar(num_conductores=4, semilla=99)
    assert len(a.despachador.conductores) == 4 and a.semilla == 99


def test_instantanea_restaura_exactamente(malla, ajustes_prueba):
    ajustes = ajustes_prueba.con(num_conductores=10, tasa_solicitudes_por_turno=0.8)
    original = Simulador(malla, ajustes)
    for _ in range(15):
        original.avanzar_turno()
    copia = Simulador.desde_instantanea(malla, ajustes, json.loads(json.dumps(original.instantanea())))
    for _ in range(20):
        original.avanzar_turno()
        copia.avanzar_turno()
    assert original.instantanea() == copia.instantanea()


# ------------------------------------------------------------- red real


def test_red_real_cargada_y_dirigida(grafo_real, grafo_real_nx):
    assert grafo_real.num_nodos == len(grafo_real_nx) > 500
    assert sum(d.sentido_unico for d in grafo_real.aristas.values()) > 0
    assert len(grafo_real.componente_principal()) == len(max(nx.strongly_connected_components(grafo_real_nx), key=len))


def test_dijkstra_igual_a_networkx_en_miraflores(grafo_real, grafo_real_nx):
    r = random.Random(2024)
    nodos = sorted(grafo_real.nodos)
    for _ in range(10):
        origen, destino = r.choice(nodos), r.choice(nodos)
        propio = dijkstra(grafo_real.adyacencia, origen).distancias
        try:
            esperado = nx.shortest_path_length(grafo_real_nx, origen, destino, weight="length")
        except nx.NetworkXNoPath:
            assert destino not in propio
            continue
        assert propio[destino] == pytest.approx(esperado, abs=1e-6)


def test_simulacion_real_300_conductores(grafo_real, ajustes_prueba):
    simulador = Simulador(grafo_real, ajustes_prueba.con(num_conductores=300, k_candidatos=5,
                                                         tasa_solicitudes_por_turno=2.0, segundos_por_turno=30))
    for _ in range(40):
        simulador.avanzar_turno()
    simulador.despachador.verificar_consistencia()
    conteo = simulador.despachador.conteo_estados()
    assert sum(conteo.values()) == 300 and conteo["disponible"] < 300


def test_mapa_folium_con_todos_los_elementos(malla, ajustes_prueba, tmp_path):
    from visualizacion.mapa_folium import generar_mapa_asignacion

    simulador = Simulador(malla, ajustes_prueba.con(num_conductores=12, proporcion_ocupados=0.3))
    lat, lon = malla.coordenadas(nodo_malla(3, 3))
    resultado = simulador.solicitar_viaje(simulador.despachador.crear_pasajero(1, lat, lon, "Plaza"), 1)
    ruta = generar_mapa_asignacion(simulador.despachador, resultado, tmp_path / "mapa.html", "Prueba")
    html = ruta.read_text(encoding="utf-8")
    assert "Pasajero" in html and "Ruta asignada" in html and "Seleccionado" in html
    assert html.count("Candidato LG-") == len(resultado.candidatos) - 1  # el seleccionado lleva su propio marcador
    assert "Ocupado (en viaje)" in html and "Disponible" in html
