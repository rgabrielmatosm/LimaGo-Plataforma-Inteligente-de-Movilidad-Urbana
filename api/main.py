"""API REST de LimaGo (FastAPI).

El backend **no** contiene la flota: encola comandos para el worker y lee la
instantánea que este publica (ver ``api/persistencia.py``). Sí carga la red
vial en modo solo lectura para geocodificar, validar cobertura y convertir
rutas (listas de intersecciones) en polilíneas para el mapa.

    uvicorn api.main:app --reload
"""
from __future__ import annotations

import json
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.persistencia import BaseDatos, ahora
from config.ajustes import RAIZ_PROYECTO, cargar_ajustes
from datos.red_vial import cargar_red_vial
from simulacion.errores import DireccionAmbigua, ErrorLimaGo, FueraDeCobertura, ServicioNoDisponible
from simulacion.geocodificacion import Geocodificador

TIEMPO_ESPERA_COMANDO_S = float(os.getenv("LIMAGO_ESPERA_COMANDO_S", "15"))


class Contexto:
    ajustes = None
    bd: BaseDatos | None = None
    grafo = None
    geocodificador: Geocodificador | None = None
    limite_geojson: dict | None = None
    red_geojson: dict | None = None


ctx = Contexto()


def configurar(ajustes=None, grafo=None, geocodificador=None) -> None:
    """Inicializa dependencias (se llama al arrancar o desde las pruebas)."""
    ctx.ajustes = ajustes or cargar_ajustes()
    ctx.bd = BaseDatos(ctx.ajustes.url_base_datos)
    ctx.bd.crear_tablas()
    ctx.grafo = grafo if grafo is not None else cargar_red_vial(ctx.ajustes)
    ctx.geocodificador = geocodificador or Geocodificador(ctx.ajustes, ctx.grafo.limites())
    ruta_limite = Path(ctx.ajustes.ruta_grafo).with_name("limite_distrito.geojson")
    ctx.limite_geojson = json.loads(ruta_limite.read_text(encoding="utf-8")) if ruta_limite.exists() else None
    ctx.red_geojson = None


@asynccontextmanager
async def ciclo_vida(_app: FastAPI):
    if ctx.bd is None:
        configurar()
    yield


app = FastAPI(title="LimaGo API", version="1.0.0", lifespan=ciclo_vida,
              description="Solicitud de viajes, seguimiento e historial de LimaGo.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
    origen: Lugar
    destino: Lugar | None = None


class AccionSimulacion(BaseModel):
    turnos: int | None = Field(default=None, ge=1, le=500)
    semilla: int | None = Field(default=None, ge=0, le=2**31 - 1)
    num_conductores: int | None = Field(default=None, ge=1, le=30000)


class Lote(BaseModel):
    pasajeros: list[Lugar] = Field(min_length=1, max_length=50)
    estrategia: str = Field(default="optima", pattern="^(optima|codiciosa)$")


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


def _estado_publico() -> dict:
    estado = ctx.bd.leer_estado()
    if estado is None:
        raise HTTPException(503, detail={"codigo": "iniciando", "mensaje": "El servicio se está iniciando"})
    return estado


def _worker_activo(estado: dict | None) -> bool:
    return bool(estado) and ahora() - estado["latido_en"] < timedelta(seconds=15)


def _seguimiento(solicitud: dict, instantanea: dict | None) -> dict:
    datos = _limpiar(dict(solicitud))
    datos["conductor"] = None
    datos["ruta_restante"] = []
    if instantanea and solicitud.get("conductor_id"):
        conductor = next((c for c in instantanea["conductores"] if c["id"] == solicitud["conductor_id"]), None)
        if conductor:
            datos["conductor"] = {k: conductor[k] for k in ("id", "codigo", "lat", "lon", "estado")}
            if conductor.get("solicitud_id") == solicitud["id"]:
                restante = [conductor["nodo"]] + conductor["ruta"]
                datos["ruta_restante"] = [list(p) for p in ctx.grafo.geometria_ruta(restante)]
                metros = ctx.grafo.longitud_ruta(restante) - conductor.get("avance_m", 0.0)
                datos["metros_restantes"] = max(0.0, metros)
                datos["segundos_restantes"] = max(0.0, metros) / (ctx.ajustes.velocidad_promedio_kmh / 3.6)
    return datos


# --------------------------------------------------------------- endpoints
@app.get("/api/salud")
def salud():
    estado = ctx.bd.leer_estado()
    return {"estado": "ok", "base_datos": ctx.bd.comprobar(), "worker_activo": _worker_activo(estado),
            "turno": estado["turno"] if estado else None, "red": ctx.grafo.resumen()}


@app.get("/api/cobertura")
def cobertura():
    r = ctx.grafo.limites()
    return {"nombre": "Miraflores, Lima", "limites": {"lat_min": r.lat_min, "lat_max": r.lat_max,
                                                      "lon_min": r.lon_min, "lon_max": r.lon_max},
            "centro": {"lat": r.lat_centro, "lon": r.lon_centro}, "poligono": ctx.limite_geojson,
            "intersecciones": ctx.grafo.num_nodos, "km_de_vias": round(sum(
                d.longitud for d in ctx.grafo.aristas.values()) / 1000, 1)}


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


@app.post("/api/viajes", status_code=201)
def solicitar_viaje(solicitud: SolicitudViaje):
    origen = _resolver_lugar(solicitud.origen)
    destino = _resolver_lugar(solicitud.destino) if solicitud.destino and (
        solicitud.destino.texto or solicitud.destino.lat is not None) else None
    comando_id = ctx.bd.encolar_comando("solicitar_viaje", {"origen": origen, "destino": destino})
    resultado = _esperar_comando(comando_id)
    return obtener_viaje(resultado["solicitud_id"])


@app.get("/api/viajes")
def historial(canal: str = Query(default="app", pattern="^(app|simulacion|todos)$"),
              limite: int = Query(default=50, ge=1, le=500)):
    filas = ctx.bd.listar_solicitudes(None if canal == "todos" else canal, limite)
    for fila in filas:
        fila.pop("ruta_recogida", None)
        fila.pop("ruta_viaje", None)
    return {"solicitudes": _limpiar(filas)}


@app.get("/api/viajes/{solicitud_id}")
def obtener_viaje(solicitud_id: int):
    solicitud = ctx.bd.obtener_solicitud(solicitud_id)
    if solicitud is None:
        raise HTTPException(404, detail={"codigo": "no_encontrada", "mensaje": "No existe esa solicitud"})
    estado = ctx.bd.leer_estado()
    return _seguimiento(solicitud, estado["instantanea"] if estado else None)


@app.post("/api/viajes/{solicitud_id}/cancelar")
def cancelar_viaje(solicitud_id: int):
    solicitud = ctx.bd.obtener_solicitud(solicitud_id)
    if solicitud is None:
        raise HTTPException(404, detail={"codigo": "no_encontrada", "mensaje": "No existe esa solicitud"})
    if solicitud["estado"] != "asignada":
        raise HTTPException(409, detail={"codigo": "no_cancelable", "mensaje": "Este viaje ya no puede cancelarse"})
    _esperar_comando(ctx.bd.encolar_comando("cancelar_viaje", {"solicitud_id": solicitud_id}))
    return obtener_viaje(solicitud_id)


@app.post("/api/viajes/lote", status_code=201)
def solicitar_lote(lote: Lote):
    pasajeros = [_resolver_lugar(p) for p in lote.pasajeros]
    return _esperar_comando(ctx.bd.encolar_comando("asignar_lote", {"pasajeros": pasajeros,
                                                                    "estrategia": lote.estrategia}))


@app.get("/api/flota")
def flota():
    estado = _estado_publico()
    inst = estado["instantanea"]
    return {"version": estado["version"], "turno": inst["turno"], "en_pausa": inst["en_pausa"],
            "hora_simulada": inst["hora_simulada"], "conteo": inst["conteo"], "semilla": inst["semilla"],
            "worker_activo": _worker_activo(estado),
            "conductores": [{"id": c["id"], "codigo": c["codigo"], "lat": c["lat"], "lon": c["lon"],
                             "estado": c["estado"]} for c in inst["conductores"]]}


@app.post("/api/operaciones/{accion}")
def operar(accion: str, datos: AccionSimulacion | None = None):
    if accion not in {"pausar", "reanudar", "avanzar", "reiniciar"}:
        raise HTTPException(404, detail={"codigo": "accion_desconocida", "mensaje": "Acción no disponible"})
    datos = datos or AccionSimulacion()
    return _esperar_comando(ctx.bd.encolar_comando(accion, datos.model_dump(exclude_none=True)))


# Servir el frontend cuando no hay Nginx delante (ejecución local sin Docker).
_CARPETA_FRONTEND = RAIZ_PROYECTO / "frontend"
if os.getenv("LIMAGO_SERVIR_FRONTEND", "1") == "1" and _CARPETA_FRONTEND.exists():
    app.mount("/", StaticFiles(directory=_CARPETA_FRONTEND, html=True), name="frontend")
