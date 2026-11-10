"""Pruebas de las funcionalidades de la V2: tarifas, cobertura, estadísticas, operaciones protegidas,
configuración del escenario, lotes, métricas, migración y frontend (enlaces y textos públicos)."""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from api import main as api_main
from api.persistencia import BaseDatos
from simulacion.tarifas import BASE, MINIMA, POR_KM, POR_MINUTO, SinRuta, calcular_tarifa, estimar_viaje
from simulacion.turnos import Simulador
from simulacion.ubicacion import UbicadorRed
from tests.conftest import LAT0, LON0, PASO, nodo_malla

RAIZ = Path(__file__).resolve().parent.parent
FRONTEND = RAIZ / "frontend"


# ------------------------------------------------------------ lógica de negocio
def test_tarifa_formula_y_minimo():
    t = calcular_tarifa(5000, 600)  # 5 km, 10 min
    assert t["estimada"] == pytest.approx(round(BASE + POR_KM * 5 + POR_MINUTO * 10, 1), abs=0.11)
    assert t["minima"] <= t["estimada"] <= t["maxima"]
    assert calcular_tarifa(100, 30)["estimada"] == MINIMA
    with pytest.raises(ValueError):
        calcular_tarifa(-1, 10)


def test_estimacion_usa_ruta_real_y_hora_punta(malla):
    ubicador = UbicadorRed(malla, 250)
    o, d = malla.coordenadas(nodo_malla(0, 0)), malla.coordenadas(nodo_malla(5, 5))
    normal = estimar_viaje(malla, ubicador, o, d, 36.0)
    assert normal.distancia_m == pytest.approx(malla.longitud_ruta(normal.ruta))
    assert normal.duracion_s == pytest.approx(normal.distancia_m / 10)
    punta = estimar_viaje(malla, ubicador, o, d, 36.0, hora=8.0)
    tarde = estimar_viaje(malla, ubicador, o, d, 36.0, hora=15.0)
    assert punta.duracion_s > tarde.duracion_s
    assert punta.tarifa["estimada"] >= tarde.tarifa["estimada"]


def test_estimacion_sin_ruta(malla):
    ubicador = UbicadorRed(malla, 250, nodos_validos=set(malla.nodos))
    with pytest.raises(SinRuta):
        estimar_viaje(malla, ubicador, malla.coordenadas(999), malla.coordenadas(nodo_malla(3, 3)), 30)


def test_configuracion_del_escenario_se_conserva(malla, ajustes_prueba):
    sim = Simulador(malla, ajustes_prueba)
    configuracion = sim.configurar(congestion_activa=True, hora=8.0, tasa_solicitudes_por_turno=2.0, k_candidatos=4)
    assert configuracion["congestion_activa"] and sim.despachador.pesos_dinamicos is not None
    assert sim.hora_simulada == 8.0 and sim.despachador.ajustes.k_candidatos == 4
    copia = Simulador.desde_instantanea(malla, ajustes_prueba, sim.instantanea())
    assert copia.configuracion() == sim.configuracion()
    with pytest.raises(ValueError):
        sim.configurar(k_candidatos=0)
    sim.configurar(congestion_activa=False)
    assert sim.despachador.pesos_dinamicos is None


def test_migracion_agrega_columnas_nuevas(tmp_path):
    url = f"sqlite:///{tmp_path / 'v1.db'}"
    motor = create_engine(url)
    with motor.begin() as c:  # tabla con el esquema de la V1 (sin columnas nuevas)
        c.execute(text("CREATE TABLE solicitudes (id INTEGER PRIMARY KEY, canal VARCHAR(20) NOT NULL, "
                       "estado VARCHAR(30) NOT NULL, creada_en DATETIME NOT NULL, actualizada_en DATETIME NOT NULL)"))
    bd = BaseDatos(url)
    bd.crear_tablas()
    bd.insertar_solicitud(id=1, canal="app", estado="asignada", tarifa_estimada=9.5, eta_s=60)
    assert bd.obtener_solicitud(1)["tarifa_estimada"] == 9.5
    assert bd.estadisticas()["eta_media_s"] == 60


# ------------------------------------------------------------------- API
def test_tarifas_cobertura_y_estadisticas(entorno_api, malla):
    cliente, _ = entorno_api
    assert cliente.get("/api/tarifas").json()["es_estimacion"] is True
    o, d = malla.coordenadas(nodo_malla(0, 0)), malla.coordenadas(nodo_malla(4, 4))
    r = cliente.post("/api/tarifas/estimar", json={"origen": {"lat": o[0], "lon": o[1]},
                                                   "destino": {"lat": d[0], "lon": d[1]}, "hora": 8})
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["distancia_m"] > 0 and datos["tarifa"]["estimada"] >= MINIMA and len(datos["ruta"]) > 2
    assert cliente.get(f"/api/cobertura/verificar?lat={o[0]}&lon={o[1]}").json()["cubierto"] is True
    fuera = cliente.get("/api/cobertura/verificar?lat=-12.0464&lon=-77.0428").json()
    assert fuera["cubierto"] is False and fuera["codigo"] == "fuera_de_cobertura"
    lejos = cliente.get(f"/api/cobertura/verificar?lat={LAT0 + 2.5 * PASO}&lon={LON0 + 2.5 * PASO}").json()
    assert lejos["codigo"] == "sin_conexion_vial"
    viaje = cliente.post("/api/viajes", json={"origen": {"lat": o[0], "lon": o[1]},
                                              "destino": {"lat": d[0], "lon": d[1]}}).json()
    assert viaje["tarifa_estimada"] >= MINIMA and viaje["distancia_viaje_m"] > 0
    stats = cliente.get("/api/estadisticas").json()
    assert stats["escenario_simulado"] is True and stats["pasajeros"]["total"] >= 1
    assert sum(stats["conductores"].values()) == 10
    filtrado = cliente.get("/api/viajes?canal=todos&estado=asignada,en_viaje").json()["solicitudes"]
    assert all(s["estado"] in {"asignada", "en_viaje"} for s in filtrado)


def test_operaciones_requieren_token(entorno_api):
    cliente, _ = entorno_api
    sin = {"Authorization": ""}
    assert cliente.post("/api/operaciones/pausar", headers=sin).status_code == 401
    assert cliente.post("/api/operaciones/pausar", headers={"Authorization": "Bearer otro"}).status_code == 401
    assert cliente.get("/api/operaciones/resumen", headers=sin).status_code == 401
    assert cliente.post("/api/viajes/lote", headers=sin, json={"pasajeros": [{"lat": LAT0, "lon": LON0}]}).status_code == 401
    assert cliente.get("/api/operaciones/sesion").json()["autorizado"] is True


def test_operaciones_deshabilitadas_sin_token_configurado(entorno_api):
    cliente, _ = entorno_api
    original = api_main.ctx.ajustes
    api_main.ctx.ajustes = original.con(token_operaciones="")
    try:
        r = cliente.post("/api/operaciones/pausar")
        assert r.status_code == 503 and r.json()["codigo"] == "operaciones_deshabilitadas"
    finally:
        api_main.ctx.ajustes = original


def test_resumen_configuracion_y_lote_aleatorio(entorno_api):
    cliente, trabajador = entorno_api
    r = cliente.post("/api/operaciones/configurar", json={"congestion_activa": True, "hora": 8.0,
                                                          "tasa_solicitudes_por_turno": 0, "k_candidatos": 4})
    assert r.status_code == 200, r.text
    assert r.json()["configuracion"]["congestion_activa"] is True
    assert cliente.post("/api/operaciones/configurar", json={"hora": 30}).status_code == 422
    lote = cliente.post("/api/operaciones/lote", json={"cantidad": 4, "estrategia": "optima"}).json()
    assert len(lote["solicitudes"]) == 4 and lote["espera_total_s"] <= lote["espera_total_alternativa_s"] + 1e-6
    resumen = cliente.get("/api/operaciones/resumen").json()
    assert resumen["configuracion"]["k_candidatos"] == 4 and resumen["total_activas"] >= 1
    assert {a["canal"] for a in resumen["activas"]} <= {"app", "operaciones", "simulacion"}
    trabajador.simulador.despachador.verificar_consistencia()


def test_metricas_prometheus(entorno_api):
    cliente, trabajador = entorno_api
    cliente.get("/api/flota")
    cliente.get("/api/viajes/999999")
    texto = cliente.get("/metrics").text
    assert 'limago_http_peticiones_total{codigo="200",metodo="GET",ruta="/api/flota"}' in texto
    assert 'ruta="/api/viajes/{solicitud_id}"' in texto and 'codigo="404"' in texto
    assert "limago_base_datos_disponible 1.0" in texto and "limago_worker_activo 1.0" in texto
    from prometheus_client import generate_latest

    from api import metricas
    trabajador.ejecutar("avanzar", {"turnos": 2})
    trabajador.publicar()
    worker = generate_latest(metricas.REGISTRO_WORKER).decode()
    assert "limago_turnos_total" in worker and 'limago_conductores{estado="disponible"}' in worker


# --------------------------------------------------------------- frontend
class _Enlaces(HTMLParser):
    def __init__(self):
        super().__init__()
        self.enlaces = []

    def handle_starttag(self, etiqueta, atributos):
        for nombre, valor in atributos:
            if nombre in {"href", "src"} and valor:
                self.enlaces.append(valor)


def _archivos_web():
    return sorted(FRONTEND.glob("*.html")) + sorted((FRONTEND / "js").glob("*.js"))


def test_sin_enlaces_internos_rotos():
    rotos = []
    for archivo in _archivos_web():
        texto = archivo.read_text(encoding="utf-8")
        if archivo.suffix == ".html":
            lector = _Enlaces()
            lector.feed(texto)
            enlaces = lector.enlaces
        else:  # enlaces dentro de plantillas JS: href="pagina.html"
            enlaces = re.findall(r'href="([^"$]+)"', texto)
        for enlace in enlaces:
            if enlace.startswith(("http:", "https:", "mailto:", "#", "data:", "/api")):
                continue
            destino = (FRONTEND / enlace.split("#")[0].split("?")[0]).resolve()
            if not destino.exists():
                rotos.append(f"{archivo.name} → {enlace}")
    assert not rotos, rotos


class _TextoVisible(HTMLParser):
    """Texto que ve el público: contenido y atributos legibles (no clases, ids ni código)."""

    def __init__(self):
        super().__init__()
        self.partes, self._ignorar = [], 0

    def handle_starttag(self, etiqueta, atributos):
        if etiqueta in {"script", "style"}:
            self._ignorar += 1
        self.partes += [v for n, v in atributos if n in {"placeholder", "title", "alt", "aria-label", "content"} and v]

    def handle_endtag(self, etiqueta):
        if etiqueta in {"script", "style"}:
            self._ignorar -= 1

    def handle_data(self, datos):
        if not self._ignorar:
            self.partes.append(datos)


def test_paginas_publicas_sin_terminos_tecnicos():
    prohibidos = re.compile(r"quadtree|dijkstra|haversine|\bheap\b|big-?o|python|fastapi|docker|postgres|osmnx|"
                            r"networkx|algoritmo|benchmark|pytest|r[uú]brica|prometheus|grafana", re.IGNORECASE)
    fuentes = {a.name: a.read_text(encoding="utf-8") for a in sorted(FRONTEND.glob("*.html"))}
    plantilla = (FRONTEND / "js" / "plantilla.js").read_text(encoding="utf-8")
    fuentes["plantilla.js"] = "".join(re.findall(r"`([^`]*)`", plantilla))  # HTML de la cabecera y el pie
    for nombre, contenido in fuentes.items():
        lector = _TextoVisible()
        lector.feed(contenido)
        encontrados = prohibidos.findall(" ".join(lector.partes))
        assert not encontrados, f"{nombre}: {encontrados}"


def test_todas_las_paginas_usan_cabecera_y_pie_compartidos():
    for archivo in FRONTEND.glob("*.html"):
        texto = archivo.read_text(encoding="utf-8")
        assert "js/plantilla.js" in texto, archivo.name
        assert 'data-pie' in texto and 'data-cabecera' in texto, archivo.name
