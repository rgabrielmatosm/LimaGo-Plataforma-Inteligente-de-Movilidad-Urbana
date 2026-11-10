"""Configuración central de LimaGo.

Hay dos **escenarios** (variable ``LIMAGO_ESCENARIO``):

* ``miraflores`` — escenario académico original (RF-01..RF-09, retos, benchmarks,
  mapas folium e informe). Sus valores son exactamente los de la V1 y son los
  valores por defecto de la clase :class:`Ajustes`, que usan las pruebas.
* ``lima`` — Lima Metropolitana (V3): aplicación principal. Activa el reloj de
  Lima para el tráfico por horario, el motor de aceptación de conductores, la
  espera en el punto de recogida, las desconexiones y las unidades de apoyo.

Cualquier parámetro se puede sobrescribir con variables de entorno
(ver ``.env.example``). Los scripts académicos usan :func:`ajustes_academicos`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DATOS = RAIZ_PROYECTO / "datos"


def _entero(nombre: str, defecto: int) -> int:
    valor = os.getenv(nombre)
    return int(valor) if valor not in (None, "") else defecto


def _decimal(nombre: str, defecto: float) -> float:
    valor = os.getenv(nombre)
    return float(valor) if valor not in (None, "") else defecto


def _booleano(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor in (None, ""):
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _texto(nombre: str, defecto: str) -> str:
    valor = os.getenv(nombre)
    return valor if valor not in (None, "") else defecto


@dataclass(frozen=True)
class Ajustes:
    # --- Escenario ---------------------------------------------------------
    escenario: str = "miraflores"
    nombre_cobertura: str = "Miraflores"

    # --- Red vial (RF-01) -------------------------------------------------
    lugar: str = "Miraflores, Lima, Peru"
    tipo_red: str = "drive"
    ruta_grafo: Path = DATOS / "miraflores.graphml"
    ruta_limite: Path = DATOS / "limite_distrito.geojson"
    ruta_distritos: Path | None = None
    # V3: validar la cobertura con el polígono real (Miraflores académico conserva el criterio de la V1).
    cobertura_por_poligono: bool = False
    overpass_urls: tuple[str, ...] = (
        "https://overpass-api.de/api",
        "https://overpass.private.coffee/api",
        "https://overpass.kumi.systems/api",
    )

    # --- Flota (RF-02) ----------------------------------------------------
    semilla: int = 42
    num_conductores: int = 300
    proporcion_ocupados: float = 0.2

    # --- Quadtree (RF-03) -------------------------------------------------
    capacidad_nodo: int = 8
    profundidad_maxima: int = 18

    # --- Búsqueda y ETA (RF-04 / RF-05) -------------------------------------
    k_candidatos: int = 5
    velocidad_promedio_kmh: float = 25.0
    distancia_maxima_conexion_m: float = 250.0

    # --- Simulación (RF-06) -----------------------------------------------
    segundos_por_turno: float = 30.0
    intervalo_real_turno_s: float = 1.5
    tasa_solicitudes_por_turno: float = 1.5
    hora_inicio_simulacion: float = 7.5
    # Radio máximo (m) de los destinos de la demanda simulada; None = cualquier intersección.
    radio_destino_simulado_m: float | None = None

    # --- Reto B: congestión / V3: tráfico automático ------------------------
    congestion_activa: bool = False
    # "simulado": el reloj avanza con los turnos; "lima": hora local real de Lima (America/Lima).
    reloj: str = "simulado"

    # --- V3: motor de aceptación y estados -----------------------------------
    motor_aceptacion: bool = False
    plazo_oferta_turnos: int = 2
    probabilidad_aceptacion: float = 0.8
    # (política, proporción) de la flota; la asignación usa una semilla propia.
    distribucion_politicas: tuple[tuple[str, float], ...] = (
        ("automatica", 0.30), ("probabilistica", 0.55), ("rechazo", 0.10), ("sin_respuesta", 0.05))
    turnos_espera_recogida: int = 0
    probabilidad_desconexion: float = 0.0
    probabilidad_reconexion: float = 0.0

    # --- V3: alertas de seguridad (simulación) -----------------------------
    unidades_apoyo: int = 0

    # --- V3: tarifa orientativa (soles) ------------------------------------
    tarifa_base: float = 3.50              # S/
    tarifa_por_km: float = 1.10            # S/ por km del viaje
    tarifa_por_minuto: float = 0.25        # S/ por minuto estimado del viaje
    tarifa_minima: float = 6.00            # S/
    tarifa_recogida_gratis_km: float = 1.5  # km de recogida sin costo
    tarifa_por_km_recogida: float = 0.60   # S/ por km de recogida adicional
    tarifa_tope_recogida: float = 4.00     # S/ máximo por recogida

    # --- Geocodificación (RF-08) -------------------------------------------
    geocodificador_url: str = "https://nominatim.openstreetmap.org"
    geocodificador_agente: str = "LimaGo-Proyecto-Academico/1.0"
    ruta_cache_geocodificacion: Path = DATOS / "cache_geocodificacion.json"

    # --- Persistencia -------------------------------------------------------
    url_base_datos: str = f"sqlite:///{DATOS / 'limago.db'}"

    # --- Centro de operaciones (V2) ---
    # Sin token configurado, las funciones administrativas quedan deshabilitadas.
    token_operaciones: str = ""

    # --- Salidas ------------------------------------------------------------
    carpeta_mapas: Path = RAIZ_PROYECTO / "mapas"
    carpeta_resultados: Path = RAIZ_PROYECTO / "benchmark" / "resultados"

    extra: dict = field(default_factory=dict)

    def con(self, **cambios) -> "Ajustes":
        """Devuelve una copia con los cambios indicados (útil en pruebas)."""
        return replace(self, **cambios)


ESCENARIOS: dict[str, dict] = {
    "miraflores": {},  # valores académicos de la V1
    "lima": {
        "escenario": "lima",
        "nombre_cobertura": "Lima Metropolitana",
        "lugar": "Lima Metropolitana, Peru",
        "ruta_grafo": DATOS / "lima" / "lima_metropolitana.npz",
        "ruta_limite": DATOS / "lima" / "limite_lima_metropolitana.geojson",
        "ruta_distritos": DATOS / "lima" / "distritos.geojson",
        "cobertura_por_poligono": True,
        "num_conductores": 2500,
        "k_candidatos": 8,
        "segundos_por_turno": 10.0,
        "intervalo_real_turno_s": 1.0,
        "tasa_solicitudes_por_turno": 0.6,
        "radio_destino_simulado_m": 6000.0,
        "congestion_activa": True,
        "reloj": "lima",
        "motor_aceptacion": True,
        "turnos_espera_recogida": 2,
        "probabilidad_desconexion": 0.002,
        "probabilidad_reconexion": 0.05,
        "unidades_apoyo": 30,
    },
}


def ajustes_escenario(nombre: str) -> Ajustes:
    if nombre not in ESCENARIOS:
        raise ValueError(f"Escenario desconocido: {nombre}. Opciones: {', '.join(ESCENARIOS)}")
    return Ajustes().con(**ESCENARIOS[nombre])


def ajustes_academicos() -> Ajustes:
    """Escenario académico de Miraflores, independiente de ``LIMAGO_ESCENARIO``.

    Lo usan los benchmarks, los mapas folium y el informe para que sus resultados
    no cambien al desplegar la aplicación metropolitana.
    """
    return ajustes_escenario("miraflores")


def cargar_ajustes() -> Ajustes:
    """Ajustes del escenario ``LIMAGO_ESCENARIO`` (por defecto ``lima``) más las variables ``LIMAGO_*``."""
    base = ajustes_escenario(_texto("LIMAGO_ESCENARIO", "lima"))
    ruta_grafo = os.getenv("LIMAGO_RUTA_GRAFO")
    return base.con(
        lugar=_texto("LIMAGO_LUGAR", base.lugar),
        ruta_grafo=Path(ruta_grafo) if ruta_grafo else base.ruta_grafo,
        semilla=_entero("LIMAGO_SEMILLA", base.semilla),
        num_conductores=_entero("LIMAGO_NUM_CONDUCTORES", base.num_conductores),
        proporcion_ocupados=_decimal("LIMAGO_PROPORCION_OCUPADOS", base.proporcion_ocupados),
        capacidad_nodo=_entero("LIMAGO_CAPACIDAD_NODO", base.capacidad_nodo),
        profundidad_maxima=_entero("LIMAGO_PROFUNDIDAD_MAXIMA", base.profundidad_maxima),
        k_candidatos=_entero("LIMAGO_K_CANDIDATOS", base.k_candidatos),
        velocidad_promedio_kmh=_decimal("LIMAGO_VELOCIDAD_KMH", base.velocidad_promedio_kmh),
        distancia_maxima_conexion_m=_decimal("LIMAGO_DISTANCIA_MAXIMA_CONEXION_M", base.distancia_maxima_conexion_m),
        segundos_por_turno=_decimal("LIMAGO_SEGUNDOS_POR_TURNO", base.segundos_por_turno),
        intervalo_real_turno_s=_decimal("LIMAGO_INTERVALO_REAL_TURNO_S", base.intervalo_real_turno_s),
        tasa_solicitudes_por_turno=_decimal("LIMAGO_SOLICITUDES_POR_TURNO", base.tasa_solicitudes_por_turno),
        hora_inicio_simulacion=_decimal("LIMAGO_HORA_INICIO", base.hora_inicio_simulacion),
        congestion_activa=_booleano("LIMAGO_CONGESTION_ACTIVA", base.congestion_activa),
        reloj=_texto("LIMAGO_RELOJ", base.reloj),
        motor_aceptacion=_booleano("LIMAGO_MOTOR_ACEPTACION", base.motor_aceptacion),
        plazo_oferta_turnos=_entero("LIMAGO_PLAZO_OFERTA_TURNOS", base.plazo_oferta_turnos),
        probabilidad_aceptacion=_decimal("LIMAGO_PROBABILIDAD_ACEPTACION", base.probabilidad_aceptacion),
        turnos_espera_recogida=_entero("LIMAGO_TURNOS_ESPERA_RECOGIDA", base.turnos_espera_recogida),
        unidades_apoyo=_entero("LIMAGO_UNIDADES_APOYO", base.unidades_apoyo),
        tarifa_base=_decimal("LIMAGO_TARIFA_BASE", base.tarifa_base),
        tarifa_por_km=_decimal("LIMAGO_TARIFA_POR_KM", base.tarifa_por_km),
        tarifa_por_minuto=_decimal("LIMAGO_TARIFA_POR_MINUTO", base.tarifa_por_minuto),
        tarifa_minima=_decimal("LIMAGO_TARIFA_MINIMA", base.tarifa_minima),
        tarifa_recogida_gratis_km=_decimal("LIMAGO_TARIFA_RECOGIDA_GRATIS_KM", base.tarifa_recogida_gratis_km),
        tarifa_por_km_recogida=_decimal("LIMAGO_TARIFA_POR_KM_RECOGIDA", base.tarifa_por_km_recogida),
        tarifa_tope_recogida=_decimal("LIMAGO_TARIFA_TOPE_RECOGIDA", base.tarifa_tope_recogida),
        geocodificador_url=_texto("LIMAGO_GEOCODIFICADOR_URL", base.geocodificador_url),
        geocodificador_agente=_texto("LIMAGO_GEOCODIFICADOR_AGENTE", base.geocodificador_agente),
        url_base_datos=_texto("LIMAGO_URL_BASE_DATOS", base.url_base_datos),
        token_operaciones=_texto("LIMAGO_TOKEN_OPERACIONES", base.token_operaciones),
        ruta_cache_geocodificacion=Path(_texto("LIMAGO_RUTA_CACHE_GEOCODIFICACION",
                                               str(base.ruta_cache_geocodificacion))),
    )
