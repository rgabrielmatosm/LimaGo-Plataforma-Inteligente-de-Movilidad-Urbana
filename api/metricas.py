"""Métricas Prometheus de LimaGo (V2).

Hay dos registros separados porque la API y el worker son procesos distintos:

* ``REGISTRO_API``: lo expone el backend en ``GET /metrics``.
* ``REGISTRO_WORKER``: lo expone el worker en ``:9100/metrics``.

Todos los valores se miden en el momento en que ocurren (peticiones, turnos,
asignaciones); no hay métricas fijas ni simuladas. Estas métricas sirven para
operar el servicio y **no** sustituyen a los benchmarks académicos (RF-09).
"""
from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# ------------------------------------------------------------------ API
REGISTRO_API = CollectorRegistry()

HTTP_PETICIONES = Counter("limago_http_peticiones_total", "Peticiones HTTP atendidas por la API",
                          ["metodo", "ruta", "codigo"], registry=REGISTRO_API)
HTTP_DURACION = Histogram("limago_http_duracion_segundos", "Latencia de las peticiones HTTP",
                          ["metodo", "ruta"], registry=REGISTRO_API,
                          buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20))
SOLICITUDES_API = Counter("limago_api_solicitudes_viaje_total",
                          "Solicitudes de viaje recibidas por la API según su resultado",
                          ["resultado"], registry=REGISTRO_API)
BASE_DATOS_DISPONIBLE = Gauge("limago_base_datos_disponible", "1 si la base de datos responde", registry=REGISTRO_API)
WORKER_ACTIVO = Gauge("limago_worker_activo", "1 si el worker envió un latido en los últimos 15 s",
                      registry=REGISTRO_API)
SOLICITUDES_ACTIVAS = Gauge("limago_solicitudes_activas", "Viajes asignados o en curso registrados",
                            registry=REGISTRO_API)

# --------------------------------------------------------------- worker
REGISTRO_WORKER = CollectorRegistry()

TURNOS = Counter("limago_turnos_total", "Turnos de simulación ejecutados", registry=REGISTRO_WORKER)
DURACION_TURNO = Histogram("limago_duracion_turno_segundos", "Tiempo de cómputo de un turno",
                           registry=REGISTRO_WORKER,
                           buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1))
ASIGNACIONES = Counter("limago_asignaciones_total", "Resultados de asignación de conductores",
                       ["canal", "resultado"], registry=REGISTRO_WORKER)
ETA_ASIGNACION = Histogram("limago_eta_asignacion_segundos", "ETA del conductor asignado (tiempo simulado)",
                           ["canal"], registry=REGISTRO_WORKER,
                           buckets=(15, 30, 60, 90, 120, 180, 240, 300, 450, 600, 900))
TIEMPO_ASIGNACION = Histogram("limago_tiempo_calculo_asignacion_segundos",
                              "Tiempo de cómputo de una asignación (búsqueda + rutas)", registry=REGISTRO_WORKER,
                              buckets=(0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1))
COMANDOS = Counter("limago_comandos_total", "Comandos procesados por el worker", ["tipo", "resultado"],
                   registry=REGISTRO_WORKER)
VIAJES_COMPLETADOS = Counter("limago_viajes_completados_total", "Viajes que llegaron a destino",
                             registry=REGISTRO_WORKER)
OFERTAS = Counter("limago_ofertas_total", "Ofertas a conductores por resultado (V3)", ["resultado"],
                  registry=REGISTRO_WORKER)
ACEPTACION_COINCIDE = Counter("limago_aceptacion_coincide_academico_total",
                              "¿El conductor que aceptó es el óptimo académico (menor ETA en k)?", ["coincide"],
                              registry=REGISTRO_WORKER)
ALERTAS = Counter("limago_alertas_total", "Alertas de seguridad simuladas", ["estado"], registry=REGISTRO_WORKER)
CONDUCTORES = Gauge("limago_conductores", "Conductores por estado", ["estado"], registry=REGISTRO_WORKER)
TURNO_ACTUAL = Gauge("limago_turno_actual", "Número de turno de la simulación", registry=REGISTRO_WORKER)
EN_PAUSA = Gauge("limago_simulacion_en_pausa", "1 si la simulación está en pausa", registry=REGISTRO_WORKER)
CONGESTION_ACTIVA = Gauge("limago_congestion_activa", "1 si los pesos por hora punta están activos",
                          registry=REGISTRO_WORKER)


def registrar_asignacion(canal: str, resultado) -> None:
    """Registra el resultado de una ``ResultadoAsignacion`` del Despachador."""
    ASIGNACIONES.labels(canal, resultado.estado).inc()
    TIEMPO_ASIGNACION.observe(resultado.tiempo_ms / 1000)
    if resultado.seleccionado is not None:
        ETA_ASIGNACION.labels(canal).observe(resultado.seleccionado.eta_s)


def actualizar_estado_simulacion(simulador) -> None:
    for estado, cantidad in simulador.despachador.conteo_estados().items():
        CONDUCTORES.labels(estado).set(cantidad)
    TURNO_ACTUAL.set(simulador.turno)
    EN_PAUSA.set(1 if simulador.en_pausa else 0)
    CONGESTION_ACTIVA.set(1 if simulador.ajustes.congestion_activa else 0)
