"""Pruebas de la V3: estados del conductor, motor de aceptación, tarifas con recogida, tráfico automático,
alertas simuladas, cotización/confirmación, cobertura metropolitana y coherencia de la animación."""
import json
import math
import random
import threading
import time
from pathlib import Path

import pytest

from estructuras.busqueda_lineal import buscar_k_cercanos_lineal
from estructuras.geografia import PoligonoCobertura, haversine_metros
from simulacion.aceptacion import MotorAceptacion, asignar_politicas, resumen_oferta
from simulacion.despachador import Despachador
from simulacion.flota import generar_flota
from simulacion.modelos import Conductor, EstadoConductor, TransicionInvalida
from simulacion.reloj import hora_lima, nivel_trafico
from simulacion.tarifas import calcular_tarifa
from simulacion.turnos import Simulador
from tests.conftest import nodo_malla

RAIZ = Path(__file__).resolve().parent.parent
LIMA = RAIZ / "datos" / "lima"


def conductor_en(grafo, cid, nodo, politica="automatica"):
    lat, lon = grafo.coordenadas(nodo)
    return Conductor(id=cid, nodo=nodo, lat=lat, lon=lon, politica=politica)


def ajustes_v3(ajustes_prueba, **extra):
    return ajustes_prueba.con(motor_aceptacion=True, turnos_espera_recogida=1, plazo_oferta_turnos=2,
                              unidades_apoyo=3, **extra)


# --------------------------------------------------------------- estados
def test_transiciones_validas_e_invalidas(malla, ajustes_prueba):
    d = Despachador(malla, [conductor_en(malla, 1, nodo_malla(0, 0))], ajustes_prueba)
    with pytest.raises(TransicionInvalida):
        d.cambiar_estado(1, EstadoConductor.EN_VIAJE)  # disponible → en viaje: no permitido
    d.cambiar_estado(1, EstadoConductor.DESCONECTADO)
    assert len(d.quadtree) == 1 and not d.quadtree.esta_disponible(1)  # sigue en el Quadtree, oculto de la búsqueda
    with pytest.raises(TransicionInvalida):
        d.cambiar_estado(1, EstadoConductor.OFERTA_PENDIENTE)  # desconectado no recibe ofertas
    d.cambiar_estado(1, EstadoConductor.DISPONIBLE)
    d.verificar_consistencia()


def test_conductor_desconectado_no_es_candidato(malla, ajustes_prueba):
    flota = [conductor_en(malla, 1, nodo_malla(2, 2)), conductor_en(malla, 2, nodo_malla(5, 5))]
    d = Despachador(malla, flota, ajustes_prueba)
    d.cambiar_estado(1, EstadoConductor.DESCONECTADO)
    pasajero = d.crear_pasajero(1, *malla.coordenadas(nodo_malla(2, 3)))
    assert [c.conductor_id for c in d.buscar_candidatos(pasajero, 5)] == [2]


# ------------------------------------------------------ motor de aceptación
def _motor(malla, ajustes_prueba, flota, plazo=2):
    d = Despachador(malla, flota, ajustes_prueba)
    return d, MotorAceptacion(d, semilla=7, plazo_turnos=plazo)


def test_aceptacion_automatica_y_comparacion_academica(malla, ajustes_prueba):
    flota = [conductor_en(malla, 1, nodo_malla(0, 0)), conductor_en(malla, 2, nodo_malla(5, 5))]
    d, motor = _motor(malla, ajustes_prueba, flota)
    pasajero = d.crear_pasajero(10, *malla.coordenadas(nodo_malla(0, 1)))
    oferta = motor.iniciar(pasajero, 10, turno=0)
    assert oferta.conductor_id == 1 and d.conductores[1].estado is EstadoConductor.OFERTA_PENDIENTE
    assert not d.quadtree.esta_disponible(1)  # reservado: nadie más lo recibe
    eventos = motor.procesar_turno(1)
    assert [e["tipo"] for e in eventos] == ["oferta_aceptada"]
    assert d.conductores[1].estado is EstadoConductor.EN_CAMINO and d.conductores[1].solicitud_id == 10
    assert resumen_oferta(eventos[0]["oferta"])["coincide"] is True
    d.verificar_consistencia()


def test_rechazo_pasa_al_siguiente_candidato(malla, ajustes_prueba):
    flota = [conductor_en(malla, 1, nodo_malla(0, 0), "rechazo"), conductor_en(malla, 2, nodo_malla(1, 1))]
    d, motor = _motor(malla, ajustes_prueba, flota)
    pasajero = d.crear_pasajero(11, *malla.coordenadas(nodo_malla(0, 1)))
    motor.iniciar(pasajero, 11, turno=0)
    eventos = motor.procesar_turno(1)
    assert [e["tipo"] for e in eventos] == ["oferta_rechaza"]
    assert d.conductores[1].esta_disponible and d.conductores[2].estado is EstadoConductor.OFERTA_PENDIENTE
    eventos = motor.procesar_turno(2)
    assert eventos[0]["tipo"] == "oferta_aceptada" and eventos[0]["conductor_id"] == 2
    resumen = resumen_oferta(eventos[0]["oferta"])
    assert resumen["coincide"] is False and resumen["intentos"] == 2 and resumen["diferencia_eta_s"] >= 0


def test_oferta_vence_si_no_hay_respuesta(malla, ajustes_prueba):
    flota = [conductor_en(malla, 1, nodo_malla(0, 0), "sin_respuesta")]
    d, motor = _motor(malla, ajustes_prueba, flota, plazo=3)
    motor.iniciar(d.crear_pasajero(12, *malla.coordenadas(nodo_malla(0, 1))), 12, turno=0)
    assert motor.procesar_turno(1) == [] and motor.procesar_turno(2) == []
    eventos = motor.procesar_turno(3)
    assert [e["tipo"] for e in eventos] == ["oferta_vencida", "sin_aceptacion"]
    assert d.conductores[1].esta_disponible and 12 not in motor.ofertas


def test_decisiones_reproducibles_e_independientes_del_orden(malla, ajustes_prueba):
    flota = generar_flota(malla, 30, semilla=3, proporcion_ocupados=0)
    asignar_politicas(flota, 3, ajustes_prueba.distribucion_politicas)
    otra = generar_flota(malla, 30, semilla=3, proporcion_ocupados=0)
    asignar_politicas(otra, 3, ajustes_prueba.distribucion_politicas)
    assert [c.politica for c in flota] == [c.politica for c in otra]
    assert [(c.nodo, c.estado) for c in flota] == [(c.nodo, c.estado) for c in generar_flota(malla, 30, 3, 0)]  # flota académica intacta
    motor = MotorAceptacion(Despachador(malla, flota, ajustes_prueba), semilla=5)
    decisiones = [motor.decidir(c, 99) for c in flota]
    assert decisiones == [motor.decidir(c, 99) for c in reversed(flota)][::-1]


def test_sin_doble_asignacion_con_ofertas_concurrentes(malla, ajustes_prueba):
    flota = [conductor_en(malla, i, nodo_malla(i % 6, i // 6)) for i in range(1, 7)]
    d, motor = _motor(malla, ajustes_prueba, flota)
    lat, lon = malla.coordenadas(nodo_malla(3, 3))
    ofertas = []

    def pedir(i):
        ofertas.append(motor.iniciar(d.crear_pasajero(i, lat, lon), 100 + i, turno=0))

    hilos = [threading.Thread(target=pedir, args=(i,)) for i in range(12)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    reservados = [o.conductor_id for o in ofertas if o is not None and o.conductor_id is not None]
    assert len(reservados) == len(set(reservados)) == 6  # 6 conductores, cada uno a lo sumo en una oferta
    motor.procesar_turno(1)
    asignados = [c.solicitud_id for c in d.conductores.values() if c.solicitud_id]
    assert len(asignados) == len(set(asignados)) == 6
    d.verificar_consistencia()


def test_funcion_academica_sigue_asignando_menor_eta(malla, ajustes_prueba):
    """La capa comercial no cambia el algoritmo académico: el primer candidato del motor es el que elige solicitar_viaje."""
    flota = generar_flota(malla, 15, semilla=4, proporcion_ocupados=0)
    d1 = Despachador(malla, [Conductor(**vars(c)) for c in flota], ajustes_prueba)
    d2, motor = _motor(malla, ajustes_prueba, [Conductor(**vars(c)) for c in flota])
    lat, lon = malla.coordenadas(nodo_malla(2, 1))
    academico = d1.solicitar_viaje(d1.crear_pasajero(1, lat, lon)).seleccionado
    oferta = motor.iniciar(d2.crear_pasajero(1, lat, lon), 1, turno=0)
    assert oferta.academico["conductor_id"] == academico.conductor_id
    assert oferta.academico["eta_s"] == pytest.approx(academico.eta_s)


# ------------------------------------------------------- simulación V3
def test_simulacion_v3_ciclo_completo_y_recuperacion(malla, ajustes_prueba):
    ajustes = ajustes_v3(ajustes_prueba, num_conductores=12, proporcion_ocupados=0.2, tasa_solicitudes_por_turno=0.8,
                         probabilidad_desconexion=0.05, probabilidad_reconexion=0.3)
    sim = Simulador(malla, ajustes)
    tipos = set()
    for _ in range(40):
        tipos |= {e.tipo for e in sim.avanzar_turno()}
        sim.despachador.verificar_consistencia()
    assert {"oferta_aceptada", "llegada_recogida", "recogida", "viaje_finalizado"} <= tipos
    copia = Simulador.desde_instantanea(malla, ajustes, json.loads(json.dumps(sim.instantanea())))
    for _ in range(25):
        sim.avanzar_turno()
        copia.avanzar_turno()
    assert sim.instantanea() == copia.instantanea()  # ofertas, esperas y unidades se restauran exactamente


def test_simulacion_pausada_no_avanza_ofertas(entorno_api_v3, malla):
    cliente, trabajador = entorno_api_v3
    cliente.post("/api/operaciones/pausar")
    lat, lon = malla.coordenadas(nodo_malla(3, 3))
    viaje = cliente.post("/api/viajes", json={"origen": {"lat": lat, "lon": lon}}).json()
    assert viaje["estado"] == "buscando"
    turno = trabajador.simulador.turno
    time.sleep(0.4)
    assert cliente.get(f"/api/viajes/{viaje['id']}").json()["estado"] == "buscando"
    assert trabajador.simulador.turno == turno
    assert cliente.get(f"/api/viajes/{viaje['id']}").json()["simulacion"]["en_pausa"] is True


# -------------------------------------------------------------- tarifas
def test_tarifa_componentes_unidades_y_tope_de_recogida():
    t = calcular_tarifa(8000, 1200, 1000)
    d = t["desglose"]
    assert d["recogida"] == 0  # primeros 1,5 km de recogida sin costo
    assert t["total"] == pytest.approx(round(d["base"] + d["recorrido"] + d["tiempo"] + d["recogida"], 1), abs=0.11)
    assert t["unidades"]["moneda"].startswith("S/")
    assert calcular_tarifa(8000, 1200, 50_000)["desglose"]["recogida"] == 4.00  # tope
    assert calcular_tarifa(8000, 1200, 3500)["desglose"]["recogida"] == pytest.approx(0.6 * 2.0)


def test_congestion_no_se_cuenta_dos_veces():
    punta, tarde = calcular_tarifa(5000, 900), calcular_tarifa(5000, 600)
    assert punta["desglose"]["recorrido"] == tarde["desglose"]["recorrido"]  # la distancia no cambia con el tráfico
    assert punta["desglose"]["tiempo"] > tarde["desglose"]["tiempo"]


def test_trafico_automatico_con_hora_de_lima(malla, ajustes_prueba):
    sim = Simulador(malla, ajustes_prueba.con(reloj="lima", congestion_activa=True))
    assert abs(sim.hora_simulada - hora_lima()) < 0.05
    sim.avanzar_turno()
    assert abs(sim.hora_simulada - hora_lima()) < 0.05
    assert nivel_trafico(8.0) == "alto" and nivel_trafico(3.0) == "fluido"


# ---------------------------------------------- API: cotizar, confirmar, alerta
@pytest.fixture
def entorno_api_v3(malla, ajustes_prueba):
    from tests.conftest import ajustes_api, crear_entorno_api

    yield from crear_entorno_api(malla, ajustes_api(ajustes_prueba, motor_aceptacion=True, turnos_espera_recogida=1,
                                                    plazo_oferta_turnos=2, unidades_apoyo=3))


def _esperar(cliente, trabajador, viaje_id, estados, turnos=60):
    for _ in range(turnos):
        estado = cliente.get(f"/api/viajes/{viaje_id}").json()
        if estado["estado"] in estados:
            return estado
        trabajador.ejecutar("avanzar", {"turnos": 1})
        trabajador.publicar()
    return cliente.get(f"/api/viajes/{viaje_id}").json()


def test_cotizar_confirmar_alerta(entorno_api_v3, malla):
    cliente, trabajador = entorno_api_v3
    o, d = malla.coordenadas(nodo_malla(0, 0)), malla.coordenadas(nodo_malla(5, 5))
    cot = cliente.post("/api/viajes/cotizar", json={"origen": {"lat": o[0], "lon": o[1]},
                                                    "destino": {"lat": d[0], "lon": d[1]}})
    assert cot.status_code == 200, cot.text
    cot = cot.json()
    assert cot["tarifa"]["total"] >= 6 and cot["distancia_m"] > 0 and len(cot["ruta"]) > 2
    assert cot["recogida"]["conductores_cerca"] >= 1
    viaje = cliente.post("/api/viajes", json={"cotizacion_id": cot["id"]})
    assert viaje.status_code == 201, viaje.text
    viaje = viaje.json()
    assert viaje["estado"] == "buscando" and viaje["tarifa_estimada"] == cot["tarifa"]["total"]
    assert cliente.post("/api/viajes", json={"cotizacion_id": cot["id"]}).status_code == 409  # no se confirma dos veces
    assigned = _esperar(cliente, trabajador, viaje["id"], {"asignada", "esperando_recogida", "en_viaje"})
    assert assigned["conductor"] is not None and assigned["ruta_restante"]
    assert assigned["conductor_academico_id"] is not None
    # la posición publicada está sobre la ruta restante (la animación del navegador parte de ahí)
    assert assigned["ruta_restante"][0] == pytest.approx([assigned["conductor"]["lat"], assigned["conductor"]["lon"]])
    alerta = cliente.post(f"/api/viajes/{viaje['id']}/alerta")
    assert alerta.status_code == 201, alerta.text
    alerta = alerta.json()
    assert alerta["duplicada"] is False and alerta["unidad"].startswith("AP-")
    assert cliente.post(f"/api/viajes/{viaje['id']}/alerta").json()["duplicada"] is True
    lista = cliente.get("/api/operaciones/alertas").json()
    assert lista["alertas"][0]["id"] == alerta["id"]
    assert sum(u["estado"] == "asignada" for u in lista["unidades"]) == 1
    atendida = cliente.post(f"/api/operaciones/alertas/{alerta['id']}/atender", json={"nota": "prueba"}).json()
    assert atendida["estado"] == "atendida"
    final = _esperar(cliente, trabajador, viaje["id"], {"completada"}, turnos=120)
    assert final["estado"] == "completada"
    assert cliente.get("/api/operaciones/resumen").json()["aceptacion"]["aceptadas"] >= 1


def test_alerta_rechazada_sin_viaje_activo_y_cancelacion_en_busqueda(entorno_api_v3, malla):
    cliente, trabajador = entorno_api_v3
    cliente.post("/api/operaciones/pausar")
    lat, lon = malla.coordenadas(nodo_malla(4, 4))
    viaje = cliente.post("/api/viajes", json={"origen": {"lat": lat, "lon": lon}}).json()
    assert cliente.post(f"/api/viajes/{viaje['id']}/alerta").status_code == 422
    cancelado = cliente.post(f"/api/viajes/{viaje['id']}/cancelar").json()
    assert cancelado["estado"] == "cancelada"
    assert all(c.estado is not EstadoConductor.OFERTA_PENDIENTE for c in trabajador.simulador.despachador.conductores.values())


def test_ubicacion_automatica_y_cobertura(entorno_api_v3, malla):
    cliente, _ = entorno_api_v3
    lat, lon = malla.coordenadas(nodo_malla(2, 2))
    r = cliente.get(f"/api/ubicacion/ajustar?lat={lat + 0.0001}&lon={lon}").json()
    assert r["cubierto"] is True and (r["lat"], r["lon"]) == malla.coordenadas(nodo_malla(2, 2))
    fuera = cliente.get("/api/ubicacion/ajustar?lat=-12.0464&lon=-77.0428").json()
    assert fuera["cubierto"] is False and fuera["codigo"] == "fuera_de_cobertura"
    cerca = cliente.get(f"/api/conductores/cercanos?lat={lat}&lon={lon}&n=3").json()["conductores"]
    assert len(cerca) == 3 and cerca == sorted(cerca, key=lambda c: c["distancia_m"])
    assert cliente.get("/api/trafico").json()["modelo"] == "simulado_por_horario"


# --------------------------------------------- red metropolitana (datos reales)
pytestmark_lima = pytest.mark.skipif(not (LIMA / "lima_metropolitana.npz").exists(),
                                     reason="Red de Lima no preparada (python -m datos.red_metropolitana)")


@pytest.fixture(scope="module")
def lima():
    if not (LIMA / "lima_metropolitana.npz").exists():
        pytest.skip("Red de Lima no preparada")
    from algoritmos.grafo import GrafoVial

    return GrafoVial.cargar_compacto(LIMA / "lima_metropolitana.npz")


@pytestmark_lima
def test_poligono_propio_igual_a_shapely():
    from shapely.geometry import Point, shape

    datos = json.loads((LIMA / "limite_lima_metropolitana.geojson").read_text(encoding="utf-8"))
    propio = PoligonoCobertura.desde_geojson(datos)
    referencia = shape(datos["features"][0]["geometry"])
    r = random.Random(1)
    for _ in range(400):
        lat, lon = r.uniform(-12.6, -11.5), r.uniform(-77.3, -76.5)
        assert propio.contiene(lat, lon) == referencia.contains(Point(lon, lat))


@pytestmark_lima
def test_cobertura_metropolitana_y_distritos(lima):
    from simulacion.ubicacion import Distritos, UbicadorRed, cargar_poligono

    ubicador = UbicadorRed(lima, 250, None, cargar_poligono(LIMA / "limite_lima_metropolitana.geojson"),
                           "Lima Metropolitana")
    distritos = Distritos(LIMA / "distritos.geojson")
    assert len(distritos) == 50
    puntos = {"Miraflores": (-12.1218, -77.0304), "Lima": (-12.0464, -77.0300), "Comas": (-11.9446, -77.0626),
              "Villa El Salvador": (-12.2135, -76.9367), "Callao": (-12.0566, -77.1181)}
    for nombre, (lat, lon) in puntos.items():
        ubicador.ubicar(lat, lon)
        assert distritos.distrito_de(lat, lon) == nombre
    from simulacion.errores import FueraDeCobertura

    with pytest.raises(FueraDeCobertura):
        ubicador.ubicar(-12.12, -77.15)  # en el mar
    with pytest.raises(FueraDeCobertura):
        ubicador.ubicar(-13.41, -76.13)  # Chincha, fuera de Lima


@pytestmark_lima
def test_rutas_entre_distritos_y_rendimiento_metropolitano(lima):
    from algoritmos.dijkstra import ruta_mas_corta
    from simulacion.ubicacion import UbicadorRed

    ubicador = UbicadorRed(lima, 250)
    o, _ = ubicador.ubicar(-12.1218, -77.0304)   # Miraflores
    d, _ = ubicador.ubicar(-11.9446, -77.0626)   # Comas
    inicio = time.perf_counter()
    distancia, ruta, _ = ruta_mas_corta(lima.adyacencia, o, d)
    assert time.perf_counter() - inicio < 3.0
    assert ruta and 20_000 < distancia < 40_000
    assert all((a, b) in lima.aristas for a, b in zip(ruta, ruta[1:]))


@pytestmark_lima
def test_quadtree_metropolitano_exacto(lima):
    flota = generar_flota(lima, 3000, semilla=42, proporcion_ocupados=0.2)
    from estructuras.quadtree import Quadtree

    q = Quadtree(lima.limites(), 8, 18)
    for c in flota:
        q.insertar(c.id, c.lat, c.lon, c.esta_disponible)
    puntos = [(c.id, c.lat, c.lon, c.esta_disponible) for c in flota]
    r = random.Random(5)
    for _ in range(100):
        lat, lon = r.uniform(-12.3, -11.8), r.uniform(-77.15, -76.8)
        assert q.buscar_k_cercanos(lat, lon, 8) == buscar_k_cercanos_lineal(puntos, lat, lon, 8)
    q.verificar_consistencia()


def test_posicion_interpolada_coherente(malla):
    u, v = nodo_malla(0, 0), nodo_malla(0, 1)
    largo = malla.longitud_arista(u, v)
    lat, lon, rumbo = malla.punto_en_tramo(u, v, largo / 2)
    assert haversine_metros(lat, lon, *malla.coordenadas(u)) == pytest.approx(largo / 2, rel=1e-3)
    assert math.isclose(rumbo, 90, abs_tol=1)  # hacia el este
    geometria = malla.geometria_desde(u, [v, nodo_malla(0, 2)], largo / 2)
    assert geometria[0] == (lat, lon) and geometria[-1] == malla.coordenadas(nodo_malla(0, 2))
