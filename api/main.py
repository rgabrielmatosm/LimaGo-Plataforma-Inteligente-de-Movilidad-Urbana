"""API REST de LimaGo (FastAPI).

El backend **no** contiene la flota: encola comandos para el worker y lee la
instantánea que este publica (ver ``api/persistencia.py``). Sí carga la red
vial en modo solo lectura para geocodificar, validar cobertura y convertir
rutas (listas de intersecciones) en polilíneas para el mapa.

    uvicorn api.main:app --reload
"""
from __future__ import annotations

import hmac
import json
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api import metricas
from api.persistencia import BaseDatos, ahora
from algoritmos.congestion import PesosDinamicos
from config.ajustes import RAIZ_PROYECTO, cargar_ajustes
from datos.red_vial import cargar_red_vial
from simulacion.errores import DireccionAmbigua, ErrorLimaGo, FueraDeCobertura, ServicioNoDisponible
from simulacion.geocodificacion import Geocodificador
from simulacion.tarifas import FACTOR_MAX, FACTOR_MIN, MONEDA, estimar_viaje, parametros_tarifa
from simulacion.reloj import hora_lima, nivel_trafico
from simulacion.ubicacion import Distritos, UbicadorRed, cargar_poligono
from algoritmos.congestion import tiempo_arista
from estructuras.quadtree import Quadtree

TIEMPO_ESPERA_COMANDO_S = float(os.getenv("LIMAGO_ESPERA_COMANDO_S", "15"))


class Contexto:
    ajustes = None
    bd: BaseDatos | None = None
    grafo = None
    geocodificador: Geocodificador | None = None
    limite_geojson: dict | None = None
    red_geojson: dict | None = None
    ubicador: UbicadorRed | None = None
    pesos: PesosDinamicos | None = None
    distritos: Distritos | None = None
    distritos_geojson: dict | None = None
    cache_estado: dict | None = None
    cache_cercanos: tuple | None = None


ctx = Contexto()


def configurar(ajustes=None, grafo=None, geocodificador=None) -> None:
    """Inicializa dependencias (se llama al arrancar o desde las pruebas)."""
    ctx.ajustes = ajustes or cargar_ajustes()
    ctx.bd = BaseDatos(ctx.ajustes.url_base_datos)
    ctx.bd.crear_tablas()
    ctx.grafo = grafo if grafo is not None else cargar_red_vial(ctx.ajustes)
    ctx.geocodificador = geocodificador or Geocodificador(ctx.ajustes, ctx.grafo.limites())
    ruta_limite = Path(ctx.ajustes.ruta_limite)
    ctx.limite_geojson = _simplificado(json.loads(ruta_limite.read_text(encoding="utf-8"))) if ruta_limite.exists() else None
    ctx.red_geojson = None
    poligono = cargar_poligono(ruta_limite) if ctx.ajustes.cobertura_por_poligono else None
    ctx.ubicador = UbicadorRed(ctx.grafo, ctx.ajustes.distancia_maxima_conexion_m, None, poligono,
                               ctx.ajustes.nombre_cobertura)
    ctx.pesos = PesosDinamicos(ctx.grafo)
    ctx.distritos = Distritos(ctx.ajustes.ruta_distritos)
    ruta_d = ctx.ajustes.ruta_distritos
    ctx.distritos_geojson = json.loads(Path(ruta_d).read_text(encoding="utf-8")) if ruta_d and Path(ruta_d).exists() else None
    ctx.cache_estado = None
    ctx.cache_cercanos = None


def _simplificado(geojson: dict, tolerancia: float = 0.0004) -> dict:
    """Versión liviana del límite para el navegador (el original se usa para validar cobertura)."""
    try:
        from shapely.geometry import mapping, shape
    except ImportError:  # pragma: no cover
        return geojson
    for f in geojson.get("features", []):
        f["geometry"] = mapping(shape(f["geometry"]).simplify(tolerancia, preserve_topology=True))
    return geojson


@asynccontextmanager
async def ciclo_vida(_app: FastAPI):
    if ctx.bd is None:
        configurar()
    yield


app = FastAPI(title="LimaGo API", version="2.0.0", lifespan=ciclo_vida,
              description="Solicitud de viajes, seguimiento, historial, tarifas y operación de LimaGo.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def medir_peticiones(request: Request, call_next):
    """Cuenta peticiones y mide su latencia agrupando por plantilla de ruta (p. ej. /api/viajes/{solicitud_id})."""
    inicio = time.perf_counter()
    codigo = 500
    try:
        respuesta = await call_next(request)
        codigo = respuesta.status_code
        return respuesta
    finally:
        ruta = request.scope.get("route")
        plantilla = getattr(ruta, "path", None) or ("/api/otra" if request.url.path.startswith("/api") else "estatico")
        if plantilla.startswith("/") and not plantilla.startswith(("/api", "/metrics")):
            plantilla = "estatico"
        metricas.HTTP_PETICIONES.labels(request.method, plantilla, str(codigo)).inc()
        metricas.HTTP_DURACION.labels(request.method, plantilla).observe(time.perf_counter() - inicio)


# ------------------------------------------------------------------ errores
@app.exception_handler(ErrorLimaGo)
async def manejar_error_dominio(_request, error: ErrorLimaGo):
    estado = 503 if isinstance(error, ServicioNoDisponible) else 422
    contenido = {"codigo": error.codigo, "mensaje": str(error)}
    if isinstance(error, DireccionAmbigua):
        estado = 409
        contenido["opciones"] = error.opciones
    return JSONResponse(status_code=estado, content=contenido)


@app.exception_handler(HTTPException)
async def manejar_http(_request, error: HTTPException):
    contenido = error.detail if isinstance(error.detail, dict) else {"codigo": "error", "mensaje": str(error.detail)}
    return JSONResponse(status_code=error.status_code, content=contenido)


@app.exception_handler(RequestValidationError)
async def manejar_validacion(_request, error: RequestValidationError):
    return JSONResponse(status_code=422, content={"codigo": "datos_invalidos",
                                                  "mensaje": "Revisa los datos ingresados",
                                                  "detalles": jsonable_encoder(error.errors())})


def _limpiar(valor):
    """JSON no admite infinito/NaN: se reemplazan por ``None``."""
    if isinstance(valor, float) and (math.isinf(valor) or math.isnan(valor)):
        return None
    if isinstance(valor, dict):
        return {k: _limpiar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_limpiar(v) for v in valor]
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return valor


# ---------------------------------------------------------------- modelos
class Lugar(BaseModel):
    texto: str | None = Field(default=None, max_length=200, description="Dirección o coordenadas en texto")
    lat: float | None = None
    lon: float | None = None
    direccion: str | None = Field(default=None, max_length=300)


class SolicitudViaje(BaseModel):
    origen: Lugar | None = None
    destino: Lugar | None = None
    cotizacion_id: str | None = Field(default=None, max_length=40, pattern="^[0-9a-f]+$")


class AccionSimulacion(BaseModel):
    turnos: int | None = Field(default=None, ge=1, le=500)
    semilla: int | None = Field(default=None, ge=0, le=2**31 - 1)
    num_conductores: int | None = Field(default=None, ge=1, le=30000)


class Lote(BaseModel):
    pasajeros: list[Lugar] = Field(min_length=1, max_length=50)
    estrategia: str = Field(default="optima", pattern="^(optima|codiciosa)$")


class LoteAleatorio(BaseModel):
    cantidad: int = Field(default=5, ge=2, le=30)
    estrategia: str = Field(default="optima", pattern="^(optima|codiciosa)$")


class Configuracion(BaseModel):
    congestion_activa: bool | None = None
    hora: float | None = Field(default=None, ge=0, lt=24)
    tasa_solicitudes_por_turno: float | None = Field(default=None, ge=0, le=50)
    k_candidatos: int | None = Field(default=None, ge=1, le=50)
    reloj_lima: bool | None = None


class Cotizacion(BaseModel):
    origen: Lugar
    destino: Lugar


class EstimacionTarifa(BaseModel):
    origen: Lugar
    destino: Lugar
    hora: float | None = Field(default=None, ge=0, lt=24, description="Hora de salida (aplica hora punta)")


def verificar_operador(authorization: str | None = Header(default=None)) -> None:
    """Las funciones administrativas exigen ``Authorization: Bearer <LIMAGO_TOKEN_OPERACIONES>``."""
    esperado = ctx.ajustes.token_operaciones
    if not esperado:
        raise HTTPException(503, detail={"codigo": "operaciones_deshabilitadas",
                                         "mensaje": "El acceso de operadores no está configurado en este servidor"})
    recibido = (authorization or "").removeprefix("Bearer ").strip()
    if not recibido or not hmac.compare_digest(recibido.encode(), esperado.encode()):
        raise HTTPException(401, detail={"codigo": "no_autorizado", "mensaje": "Código de acceso incorrecto"})


# ------------------------------------------------------------- utilidades
def _resolver_lugar(lugar: Lugar) -> dict:
    if lugar.lat is not None and lugar.lon is not None:
        texto = lugar.direccion or lugar.texto or f"{lugar.lat:.5f}, {lugar.lon:.5f}"
        resultado = ctx.geocodificador.buscar(f"{lugar.lat}, {lugar.lon}")[0]
        return {"lat": resultado.lat, "lon": resultado.lon, "direccion": texto}
    if not lugar.texto:
        raise HTTPException(422, detail={"codigo": "ubicacion_vacia", "mensaje": "Indica una dirección o coordenadas"})
    resultado = ctx.geocodificador.resolver(lugar.texto)
    return {"lat": resultado.lat, "lon": resultado.lon, "direccion": resultado.direccion}


def _esperar_comando(comando_id: int) -> dict:
    limite = time.monotonic() + TIEMPO_ESPERA_COMANDO_S
    while time.monotonic() < limite:
        comando = ctx.bd.obtener_comando(comando_id)
        if comando and comando["estado"] != "pendiente":
            if comando["estado"] == "error":
                raise HTTPException(422, detail={"codigo": comando["error_codigo"], "mensaje": comando["error_mensaje"]})
            return comando["resultado"]
        time.sleep(0.05)
    raise HTTPException(503, detail={"codigo": "servicio_ocupado", "comando_id": comando_id,
                                     "mensaje": "El servicio está tardando más de lo normal. Inténtalo de nuevo."})


def _leer_estado() -> dict | None:
    """Instantánea del worker, releída solo cuando cambia su versión (la de Lima pesa ~1 MB)."""
    version = ctx.bd.version_estado()
    if version is None:
        return None
    if ctx.cache_estado is None or ctx.cache_estado["version"] != version:
        ctx.cache_estado = ctx.bd.leer_estado()
    else:
        ctx.cache_estado["latido_en"] = ctx.bd.latido_estado() or ctx.cache_estado["latido_en"]
    return ctx.cache_estado


def _estado_publico() -> dict:
    estado = _leer_estado()
    if estado is None:
        raise HTTPException(503, detail={"codigo": "iniciando", "mensaje": "El servicio se está iniciando"})
    return estado


def _worker_activo(estado: dict | None) -> bool:
    return bool(estado) and ahora() - estado["latido_en"] < timedelta(seconds=15)


def _segundos_restantes(nodo: int, ruta: list[int], avance_m: float, inst: dict) -> float:
    """ETA restante con los pesos horarios si hay congestión; si no, con la velocidad promedio."""
    tramos = list(zip([nodo] + ruta, ruta))
    if not (inst.get("configuracion") or {}).get("congestion_activa"):
        metros = ctx.grafo.longitud_ruta([nodo] + ruta) - avance_m
        return max(0.0, metros) / (ctx.ajustes.velocidad_promedio_kmh / 3.6)
    hora = ctx.pesos.redondear_hora(inst["hora_simulada"])
    total = 0.0
    for i, (a, b) in enumerate(tramos):
        datos = ctx.grafo.aristas[(a, b)]
        t = tiempo_arista(datos, hora)
        total += t * (1 - avance_m / datos.longitud) if i == 0 and datos.longitud else t
    return max(0.0, total)


def _seguimiento(solicitud: dict, instantanea: dict | None) -> dict:
    datos = _limpiar(dict(solicitud))
    datos["conductor"] = None
    datos["ruta_restante"] = []
    datos["oferta"] = None
    if instantanea:
        datos["simulacion"] = {"en_pausa": instantanea["en_pausa"], "turno": instantanea["turno"],
                               "intervalo_real_s": ctx.ajustes.intervalo_real_turno_s}
        oferta = next((o for o in instantanea.get("ofertas", []) if o["solicitud_id"] == solicitud["id"]), None)
        if oferta and oferta.get("conductor_id") is not None:
            datos["oferta"] = {"conductor": f"LG-{oferta['conductor_id']:05d}", "numero": oferta["indice"] + 1,
                               "total": len(oferta["candidatos"]),
                               "rechazos": sum(i["resultado"] in ("rechaza", "vencida") for i in oferta["intentos"])}
    if instantanea and solicitud.get("conductor_id"):
        conductor = next((c for c in instantanea["conductores"] if c["id"] == solicitud["conductor_id"]), None)
        if conductor:
            lat, lon, rumbo = conductor["lat"], conductor["lon"], None
            if conductor["ruta"]:
                lat, lon, rumbo = ctx.grafo.punto_en_tramo(conductor["nodo"], conductor["ruta"][0], conductor["avance_m"])
            datos["conductor"] = {"id": conductor["id"], "codigo": conductor["codigo"], "lat": lat, "lon": lon,
                                  "rumbo": rumbo, "estado": conductor["estado"]}
            datos["metros_totales_fase"] = (solicitud.get("distancia_calles_m") if conductor["estado"] == "en_camino"
                                            else solicitud.get("distancia_viaje_m"))
            if conductor.get("solicitud_id") == solicitud["id"]:
                restante = [conductor["nodo"]] + conductor["ruta"]
                datos["ruta_restante"] = [list(p) for p in ctx.grafo.geometria_desde(
                    conductor["nodo"], conductor["ruta"], conductor.get("avance_m", 0.0))]
                metros = ctx.grafo.longitud_ruta(restante) - conductor.get("avance_m", 0.0)
                datos["metros_restantes"] = max(0.0, metros)
                datos["segundos_restantes"] = _segundos_restantes(conductor["nodo"], conductor["ruta"],
                                                                  conductor.get("avance_m", 0.0), instantanea)
    return datos


# --------------------------------------------------------------- endpoints
@app.get("/api/salud")
def salud():
    estado = _leer_estado()
    return {"estado": "ok", "base_datos": ctx.bd.comprobar(), "worker_activo": _worker_activo(estado),
            "turno": estado["turno"] if estado else None, "red": ctx.grafo.resumen(),
            "escenario": ctx.ajustes.escenario, "cobertura": ctx.ajustes.nombre_cobertura}


_CACHE_ESTATICO = "public, max-age=3600"  # datos que solo cambian al preparar de nuevo la red vial
_cobertura_calculada: dict = {}


@app.get("/api/cobertura")
def cobertura(response: Response):
    response.headers["Cache-Control"] = _CACHE_ESTATICO
    clave = id(ctx.grafo)
    if clave not in _cobertura_calculada:  # sumar ~400 000 tramos en cada visita sería innecesario
        _cobertura_calculada.clear()
        _cobertura_calculada[clave] = _cobertura()
    return _cobertura_calculada[clave]


def _cobertura() -> dict:
    r = ctx.grafo.limites()
    return {"nombre": ctx.ajustes.nombre_cobertura, "escenario": ctx.ajustes.escenario,
            "distritos": ctx.distritos.nombres() if ctx.distritos else [], "limites": {"lat_min": r.lat_min, "lat_max": r.lat_max,
                                                      "lon_min": r.lon_min, "lon_max": r.lon_max},
            "centro": {"lat": r.lat_centro, "lon": r.lon_centro}, "poligono": ctx.limite_geojson,
            "intersecciones": ctx.grafo.num_nodos, "km_de_vias": round(sum(
                d.longitud for d in ctx.grafo.aristas.values()) / 1000, 1)}


@app.get("/api/cobertura/verificar")
def verificar_cobertura(lat: float, lon: float):
    """¿Se puede recoger en este punto? Usa el mismo criterio que la asignación real."""
    try:
        _, distancia = ctx.ubicador.ubicar(lat, lon)
    except ErrorLimaGo as error:
        return {"cubierto": False, "codigo": error.codigo, "mensaje": str(error)}
    return {"cubierto": True, "distancia_a_via_m": round(distancia, 1),
            "mensaje": "Recogemos en este punto"}


@app.get("/api/distritos")
def distritos(response: Response):
    response.headers["Cache-Control"] = _CACHE_ESTATICO
    return ctx.distritos_geojson or {"type": "FeatureCollection", "features": []}


@app.get("/api/ubicacion/ajustar")
def ajustar_ubicacion(lat: float, lon: float):
    """Ubicación del navegador → punto de recojo sobre la vía más cercana, dirección y distrito."""
    try:
        nodo, distancia = ctx.ubicador.ubicar(lat, lon)
    except ErrorLimaGo as error:
        return {"cubierto": False, "codigo": error.codigo, "mensaje": str(error)}
    vlat, vlon = ctx.grafo.coordenadas(nodo)
    try:
        direccion = ctx.geocodificador.inverso(vlat, vlon)
    except ErrorLimaGo:
        direccion = f"{vlat:.5f}, {vlon:.5f}"
    return {"cubierto": True, "lat": vlat, "lon": vlon, "original": {"lat": lat, "lon": lon},
            "distancia_a_via_m": round(distancia, 1), "direccion": direccion,
            "distrito": ctx.distritos.distrito_de(vlat, vlon) if ctx.distritos else None}


@app.get("/api/conductores/cercanos")
def conductores_cercanos(lat: float, lon: float, n: int = Query(default=6, ge=1, le=30)):
    """Conductores disponibles más cercanos a un punto (Quadtree propio sobre la instantánea publicada)."""
    estado = _estado_publico()
    if ctx.cache_cercanos is None or ctx.cache_cercanos[0] != estado["version"]:
        indice = Quadtree(ctx.grafo.limites(), ctx.ajustes.capacidad_nodo, ctx.ajustes.profundidad_maxima)
        for c in estado["instantanea"]["conductores"]:
            indice.insertar(c["id"], c["lat"], c["lon"], c["estado"] == "disponible")
        ctx.cache_cercanos = (estado["version"], indice)
    indice = ctx.cache_cercanos[1]
    if not indice.limites.contiene(lat, lon):
        return {"conductores": []}
    return {"conductores": [{"id": cid, "codigo": f"LG-{cid:05d}", "lat": indice.obtener_posicion(cid)[0],
                             "lon": indice.obtener_posicion(cid)[1], "distancia_m": round(d, 1)}
                            for d, cid in indice.buscar_k_cercanos(lat, lon, n)]}


@app.get("/api/trafico")
def trafico():
    """Tráfico **simulado por horario** (no es tráfico en tiempo real)."""
    estado = _leer_estado()
    inst = estado["instantanea"] if estado else {}
    configuracion = inst.get("configuracion") or {}
    hora = inst.get("hora_simulada", hora_lima())
    activo = configuracion.get("congestion_activa", ctx.ajustes.congestion_activa)
    return {"hora": hora, "reloj": configuracion.get("reloj", ctx.ajustes.reloj), "activo": activo,
            "nivel": nivel_trafico(hora) if activo else "sin_ajuste", "modelo": "simulado_por_horario",
            "fuente_real": None,
            "aviso": "Estimación con un modelo horario simulado; no proviene de sensores ni de tráfico en tiempo real."}


@app.get("/metrics", include_in_schema=False)
def metricas_prometheus():
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    try:
        metricas.BASE_DATOS_DISPONIBLE.set(1 if ctx.bd.comprobar() else 0)
        estado = ctx.bd.leer_estado()
        metricas.WORKER_ACTIVO.set(1 if _worker_activo(estado) else 0)
        metricas.SOLICITUDES_ACTIVAS.set(len(ctx.bd.solicitudes_activas()))
    except Exception:  # noqa: BLE001 - la caída de la base de datos también es una métrica
        metricas.BASE_DATOS_DISPONIBLE.set(0)
    return Response(generate_latest(metricas.REGISTRO_API), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/estadisticas")
def estadisticas():
    """Indicadores públicos calculados con la flota publicada y las solicitudes registradas."""
    estado = _leer_estado()
    inst = estado["instantanea"] if estado else None
    return _limpiar({
        "escenario_simulado": True,
        "conductores": inst["conteo"] if inst else None,
        "turno": inst["turno"] if inst else None,
        "hora_simulada": inst["hora_simulada"] if inst else None,
        "servicio": ctx.bd.estadisticas(),
        "pasajeros": ctx.bd.estadisticas("app"),
    })


@app.get("/api/tarifas")
def tarifas():
    return {"moneda": MONEDA, **parametros_tarifa(ctx.ajustes),
            "rango": {"factor_minimo": FACTOR_MIN, "factor_maximo": FACTOR_MAX},
            "velocidad_promedio_kmh": ctx.ajustes.velocidad_promedio_kmh, "es_estimacion": True}


@app.post("/api/tarifas/estimar")
def estimar_tarifa(datos: EstimacionTarifa):
    origen = _resolver_lugar(datos.origen)
    destino = _resolver_lugar(datos.destino)
    estimacion = estimar_viaje(ctx.grafo, ctx.ubicador, (origen["lat"], origen["lon"]), (destino["lat"], destino["lon"]),
                               ctx.ajustes.velocidad_promedio_kmh, datos.hora, ctx.pesos,
                               parametros=parametros_tarifa(ctx.ajustes))
    return {"origen": origen, "destino": destino, "hora": datos.hora,
            "distancia_m": round(estimacion.distancia_m, 1), "duracion_s": round(estimacion.duracion_s, 1),
            "tarifa": estimacion.tarifa, "es_estimacion": True,
            "ruta": [list(p) for p in ctx.grafo.geometria_ruta(estimacion.ruta)]}


@app.get("/api/red")
def red_vial():
    if ctx.red_geojson is None:
        caracteristicas = []
        for (u, v), datos in ctx.grafo.aristas.items():
            puntos = datos.geometria or [ctx.grafo.coordenadas(u), ctx.grafo.coordenadas(v)]
            caracteristicas.append({"type": "Feature", "properties": {"nombre": datos.nombre, "tipo": datos.tipo_via,
                                                                     "sentido_unico": datos.sentido_unico},
                                    "geometry": {"type": "LineString",
                                                 "coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in puntos]}})
        ctx.red_geojson = {"type": "FeatureCollection", "features": caracteristicas}
    return ctx.red_geojson


@app.get("/api/geocodificar")
def geocodificar(q: str = Query(min_length=1, max_length=200)):
    return {"resultados": [r.a_diccionario() for r in ctx.geocodificador.buscar(q)]}


@app.get("/api/geocodificar/inverso")
def geocodificar_inverso(lat: float, lon: float):
    if not ctx.grafo.limites().contiene(lat, lon):
        raise FueraDeCobertura("La ubicación está fuera de la zona de cobertura de Miraflores")
    return {"direccion": ctx.geocodificador.inverso(lat, lon), "lat": lat, "lon": lon}


@app.post("/api/viajes/cotizar")
def cotizar_viaje(datos: Cotizacion):
    """Ruta, duración con el tráfico simulado de la hora actual, recogida estimada y tarifa (válida 5 min)."""
    origen = _resolver_lugar(datos.origen)
    destino = _resolver_lugar(datos.destino)
    return _limpiar(_esperar_comando(ctx.bd.encolar_comando("cotizar", {"origen": origen, "destino": destino})))


@app.post("/api/viajes", status_code=201)
def solicitar_viaje(solicitud: SolicitudViaje):
    cotizacion = None
    if solicitud.cotizacion_id:
        fila = ctx.bd.obtener_cotizacion(solicitud.cotizacion_id)
        if fila is None:
            raise HTTPException(404, detail={"codigo": "cotizacion_no_encontrada", "mensaje": "La cotización no existe"})
        if ahora() - fila["creada_en"] > timedelta(seconds=fila["datos"].get("vigencia_s", 300)):
            raise HTTPException(410, detail={"codigo": "cotizacion_vencida",
                                             "mensaje": "La tarifa venció. Vuelve a calcularla para continuar."})
        if not ctx.bd.marcar_cotizacion_usada(solicitud.cotizacion_id):
            raise HTTPException(409, detail={"codigo": "cotizacion_usada", "mensaje": "Este viaje ya fue solicitado"})
        cotizacion = fila["datos"]
        origen, destino = cotizacion["origen"], cotizacion["destino"]
    else:
        if solicitud.origen is None:
            raise HTTPException(422, detail={"codigo": "ubicacion_vacia", "mensaje": "Indica tu punto de recojo"})
        origen = _resolver_lugar(solicitud.origen)
        destino = _resolver_lugar(solicitud.destino) if solicitud.destino and (
            solicitud.destino.texto or solicitud.destino.lat is not None) else None
    comando_id = ctx.bd.encolar_comando("solicitar_viaje", {"origen": origen, "destino": destino,
                                                            "cotizacion": cotizacion})
    try:
        resultado = _esperar_comando(comando_id)
    except HTTPException:
        metricas.SOLICITUDES_API.labels("error").inc()
        raise
    viaje = obtener_viaje(resultado["solicitud_id"])
    metricas.SOLICITUDES_API.labels(viaje["estado"]).inc()
    return viaje


@app.get("/api/viajes")
def historial(canal: str = Query(default="app", pattern="^(app|simulacion|operaciones|todos)$"),
              limite: int = Query(default=50, ge=1, le=500),
              estado: str | None = Query(default=None, pattern="^[a-z_]+(,[a-z_]+)*$",
                                         description="Estados separados por comas"),
              antes_de: int | None = Query(default=None, ge=1, description="Paginación: ids menores a este")):
    estados = estado.split(",") if estado else None
    filas = ctx.bd.listar_solicitudes(None if canal == "todos" else canal, limite, estados, antes_de)
    for fila in filas:
        fila.pop("ruta_recogida", None)
        fila.pop("ruta_viaje", None)
    return {"solicitudes": _limpiar(filas)}


@app.get("/api/viajes/{solicitud_id}")
def obtener_viaje(solicitud_id: int):
    solicitud = ctx.bd.obtener_solicitud(solicitud_id)
    if solicitud is None:
        raise HTTPException(404, detail={"codigo": "no_encontrada", "mensaje": "No existe esa solicitud"})
    estado = _leer_estado()
    return _seguimiento(solicitud, estado["instantanea"] if estado else None)


@app.post("/api/viajes/{solicitud_id}/cancelar")
def cancelar_viaje(solicitud_id: int):
    solicitud = ctx.bd.obtener_solicitud(solicitud_id)
    if solicitud is None:
        raise HTTPException(404, detail={"codigo": "no_encontrada", "mensaje": "No existe esa solicitud"})
    if solicitud["estado"] not in ("buscando", "asignada", "esperando_recogida"):
        raise HTTPException(409, detail={"codigo": "no_cancelable", "mensaje": "Este viaje ya no puede cancelarse"})
    _esperar_comando(ctx.bd.encolar_comando("cancelar_viaje", {"solicitud_id": solicitud_id}))
    return obtener_viaje(solicitud_id)


@app.post("/api/viajes/{solicitud_id}/alerta", status_code=201)
def alerta_viaje(solicitud_id: int):
    """Alerta de seguridad **de demostración**: notifica al centro de operaciones (no a servicios reales)."""
    if ctx.bd.obtener_solicitud(solicitud_id) is None:
        raise HTTPException(404, detail={"codigo": "no_encontrada", "mensaje": "No existe esa solicitud"})
    return _esperar_comando(ctx.bd.encolar_comando("alerta", {"solicitud_id": solicitud_id}))


@app.post("/api/viajes/lote", status_code=201, dependencies=[Depends(verificar_operador)])
def solicitar_lote(lote: Lote):
    pasajeros = [_resolver_lugar(p) for p in lote.pasajeros]
    return _esperar_comando(ctx.bd.encolar_comando("asignar_lote", {"pasajeros": pasajeros,
                                                                    "estrategia": lote.estrategia}))


@app.get("/api/flota")
def flota(detalle: bool = True):
    """Conteo de la flota; con ``detalle=false`` omite las posiciones (la portada solo muestra cifras)."""
    estado = _estado_publico()
    inst = estado["instantanea"]
    if not detalle:
        return {"version": estado["version"], "turno": inst["turno"], "en_pausa": inst["en_pausa"],
                "conteo": inst["conteo"], "worker_activo": _worker_activo(estado)}
    return {"version": estado["version"], "turno": inst["turno"], "en_pausa": inst["en_pausa"],
            "hora_simulada": inst["hora_simulada"], "conteo": inst["conteo"], "semilla": inst["semilla"],
            "worker_activo": _worker_activo(estado),
            "conductores": [{"id": c["id"], "codigo": c["codigo"], "lat": c["lat"], "lon": c["lon"],
                             "estado": c["estado"]} for c in inst["conductores"]]}


@app.get("/api/operaciones/sesion", dependencies=[Depends(verificar_operador)])
def sesion_operador():
    return {"autorizado": True}


@app.get("/api/operaciones/resumen", dependencies=[Depends(verificar_operador)])
def resumen_operaciones():
    estado = _estado_publico()
    inst = estado["instantanea"]
    posiciones = {c["id"]: c for c in inst["conductores"]}
    activas = []
    for fila in sorted(ctx.bd.solicitudes_activas(), key=lambda f: f["id"], reverse=True):
        conductor = posiciones.get(fila["conductor_id"])
        activas.append({k: fila[k] for k in ("id", "canal", "estado", "origen_texto", "origen_lat", "origen_lon",
                                             "destino_lat", "destino_lon", "conductor_id", "eta_s", "creada_en")}
                       | {"conductor": {k: conductor[k] for k in ("lat", "lon", "estado")} if conductor else None})
    return _limpiar({
        "version": estado["version"], "turno": inst["turno"], "en_pausa": inst["en_pausa"],
        "hora_simulada": inst["hora_simulada"], "semilla": inst["semilla"], "conteo": inst["conteo"],
        "worker_activo": _worker_activo(estado), "configuracion": inst.get("configuracion"),
        "activas": activas[:200], "total_activas": len(activas), "estadisticas": ctx.bd.estadisticas(),
        "aceptacion": ctx.bd.estadisticas_aceptacion(), "ofertas_vigentes": len(inst.get("ofertas", [])),
        "rutas_pendientes": inst.get("rutas_pendientes", 0), "alertas_abiertas": ctx.bd.contar_alertas_abiertas(),
        "escenario": ctx.ajustes.escenario,
    })


@app.get("/api/operaciones/alertas", dependencies=[Depends(verificar_operador)])
def alertas_operaciones():
    estado = _leer_estado()
    unidades = estado["instantanea"].get("unidades_apoyo", []) if estado else []
    return _limpiar({"alertas": ctx.bd.listar_alertas(), "unidades": unidades})


class Atencion(BaseModel):
    nota: str = Field(default="", max_length=300)


@app.post("/api/operaciones/alertas/{alerta_id}/atender", dependencies=[Depends(verificar_operador)])
def atender_alerta(alerta_id: int, datos: Atencion | None = None):
    return _esperar_comando(ctx.bd.encolar_comando("atender_alerta", {"alerta_id": alerta_id,
                                                                      "nota": (datos or Atencion()).nota}))


@app.post("/api/operaciones/configurar", dependencies=[Depends(verificar_operador)])
def configurar_escenario(datos: Configuracion):
    return _esperar_comando(ctx.bd.encolar_comando("configurar", datos.model_dump(exclude_none=True)))


@app.post("/api/operaciones/lote", status_code=201, dependencies=[Depends(verificar_operador)])
def lote_aleatorio(datos: LoteAleatorio):
    return _esperar_comando(ctx.bd.encolar_comando("lote_aleatorio", datos.model_dump()))


@app.post("/api/operaciones/{accion}", dependencies=[Depends(verificar_operador)])
def operar(accion: str, datos: AccionSimulacion | None = None):
    if accion not in {"pausar", "reanudar", "avanzar", "reiniciar"}:
        raise HTTPException(404, detail={"codigo": "accion_desconocida", "mensaje": "Acción no disponible"})
    datos = datos or AccionSimulacion()
    return _esperar_comando(ctx.bd.encolar_comando(accion, datos.model_dump(exclude_none=True)))


# Servir el frontend cuando no hay Nginx delante (ejecución local sin Docker).
_CARPETA_FRONTEND = RAIZ_PROYECTO / "frontend"
if os.getenv("LIMAGO_SERVIR_FRONTEND", "1") == "1" and _CARPETA_FRONTEND.exists():
    app.mount("/", StaticFiles(directory=_CARPETA_FRONTEND, html=True), name="frontend")
