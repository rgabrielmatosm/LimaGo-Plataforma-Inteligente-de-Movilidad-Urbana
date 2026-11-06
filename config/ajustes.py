"""Configuración central de LimaGo.

Todos los parámetros se pueden sobrescribir con variables de entorno
(ver ``.env.example``). Los valores por defecto reproducen exactamente los
escenarios descritos en el informe y en la sustentación.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent


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
    # --- Red vial (RF-01) -------------------------------------------------
    lugar: str = "Miraflores, Lima, Peru"
    tipo_red: str = "drive"
    ruta_grafo: Path = RAIZ_PROYECTO / "datos" / "miraflores.graphml"
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

    # --- Reto B: congestión -------------------------------------------------
    congestion_activa: bool = False

    # --- Geocodificación (RF-08) -------------------------------------------
    geocodificador_url: str = "https://nominatim.openstreetmap.org"
    geocodificador_agente: str = "LimaGo-Proyecto-Academico/1.0"
    ruta_cache_geocodificacion: Path = RAIZ_PROYECTO / "datos" / "cache_geocodificacion.json"

    # --- Persistencia -------------------------------------------------------
    url_base_datos: str = f"sqlite:///{RAIZ_PROYECTO / 'datos' / 'limago.db'}"

    # --- Salidas ------------------------------------------------------------
    carpeta_mapas: Path = RAIZ_PROYECTO / "mapas"
    carpeta_resultados: Path = RAIZ_PROYECTO / "benchmark" / "resultados"

    extra: dict = field(default_factory=dict)

    def con(self, **cambios) -> "Ajustes":
        """Devuelve una copia con los cambios indicados (útil en pruebas)."""
        return replace(self, **cambios)


def cargar_ajustes() -> Ajustes:
    """Construye los ajustes leyendo las variables de entorno ``LIMAGO_*``."""
    base = Ajustes()
    ruta_grafo = os.getenv("LIMAGO_RUTA_GRAFO")
    return Ajustes(
        lugar=_texto("LIMAGO_LUGAR", base.lugar),
        ruta_grafo=Path(ruta_grafo) if ruta_grafo else base.ruta_grafo,
        semilla=_entero("LIMAGO_SEMILLA", base.semilla),
        num_conductores=_entero("LIMAGO_NUM_CONDUCTORES", base.num_conductores),
        proporcion_ocupados=_decimal("LIMAGO_PROPORCION_OCUPADOS", base.proporcion_ocupados),
        capacidad_nodo=_entero("LIMAGO_CAPACIDAD_NODO", base.capacidad_nodo),
        profundidad_maxima=_entero("LIMAGO_PROFUNDIDAD_MAXIMA", base.profundidad_maxima),
        k_candidatos=_entero("LIMAGO_K_CANDIDATOS", base.k_candidatos),
        velocidad_promedio_kmh=_decimal("LIMAGO_VELOCIDAD_KMH", base.velocidad_promedio_kmh),
        distancia_maxima_conexion_m=_decimal(
            "LIMAGO_DISTANCIA_MAXIMA_CONEXION_M", base.distancia_maxima_conexion_m
        ),
        segundos_por_turno=_decimal("LIMAGO_SEGUNDOS_POR_TURNO", base.segundos_por_turno),
        intervalo_real_turno_s=_decimal("LIMAGO_INTERVALO_REAL_TURNO_S", base.intervalo_real_turno_s),
        tasa_solicitudes_por_turno=_decimal(
            "LIMAGO_SOLICITUDES_POR_TURNO", base.tasa_solicitudes_por_turno
        ),
        hora_inicio_simulacion=_decimal("LIMAGO_HORA_INICIO", base.hora_inicio_simulacion),
        congestion_activa=_booleano("LIMAGO_CONGESTION_ACTIVA", base.congestion_activa),
        geocodificador_url=_texto("LIMAGO_GEOCODIFICADOR_URL", base.geocodificador_url),
        geocodificador_agente=_texto("LIMAGO_GEOCODIFICADOR_AGENTE", base.geocodificador_agente),
        url_base_datos=_texto("LIMAGO_URL_BASE_DATOS", base.url_base_datos),
        ruta_cache_geocodificacion=Path(_texto("LIMAGO_RUTA_CACHE_GEOCODIFICACION",
                                               str(base.ruta_cache_geocodificacion))),
    )
