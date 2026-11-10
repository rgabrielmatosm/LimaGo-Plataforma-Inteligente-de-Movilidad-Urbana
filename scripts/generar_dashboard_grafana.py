"""Genera docker/grafana/dashboards/limago.json (dashboard aprovisionado automáticamente).

Todas las consultas usan métricas reales expuestas por la API (/metrics) y el worker (:9100).

    python -m scripts.generar_dashboard_grafana
"""
import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus-limago"}
SALIDA = Path(__file__).resolve().parent.parent / "docker" / "grafana" / "dashboards" / "limago.json"
paneles = []
_id = 0


def panel(tipo, titulo, consultas, x, y, w, h, unidad="short", extra=None, descripcion=""):
    global _id
    _id += 1
    p = {"id": _id, "type": tipo, "title": titulo, "description": descripcion, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": [{"refId": chr(65 + i), "datasource": DS, "expr": expr, "legendFormat": leyenda}
                     for i, (expr, leyenda) in enumerate(consultas)],
         "fieldConfig": {"defaults": {"unit": unidad}, "overrides": []},
         "options": {}}
    if tipo == "timeseries":
        p["fieldConfig"]["defaults"]["custom"] = {"lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}
        p["options"] = {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}
    if tipo == "stat":
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "area",
                        "textMode": "value_and_name"}
    if extra:
        for clave, valor in extra.items():
            p["fieldConfig"]["defaults"][clave] = valor
    paneles.append(p)


disponibilidad = {"mappings": [{"type": "value", "options": {"0": {"text": "Caído", "color": "red"},
                                                              "1": {"text": "Activo", "color": "green"}}}],
                  "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": None},
                                                               {"color": "green", "value": 1}]}}
panel("stat", "Disponibilidad de servicios", [("up", "{{job}}")], 0, 0, 8, 4, extra=disponibilidad,
      descripcion="1 = Prometheus pudo leer las métricas del servicio")
panel("stat", "Base de datos y worker", [("limago_base_datos_disponible", "base de datos"),
                                         ("limago_worker_activo", "latido del worker")], 8, 0, 6, 4,
      extra=disponibilidad)
neutro = {"color": {"mode": "fixed", "fixedColor": "#2bb3a6"}, "decimals": 0, "unit": "none",
          "thresholds": {"mode": "absolute", "steps": [{"color": "#2bb3a6", "value": None}]}}
si_no = dict(neutro, mappings=[{"type": "value", "options": {"0": {"text": "No"}, "1": {"text": "Sí"}}}])
panel("stat", "Turno de la simulación", [("limago_turno_actual", "turno")], 14, 0, 4, 4, extra=neutro)
panel("stat", "Estado de la simulación", [("limago_simulacion_en_pausa", "en pausa"),
                                          ("limago_congestion_activa", "hora punta")], 18, 0, 6, 4, extra=si_no)
panel("timeseries", "Conductores por estado", [("limago_conductores", "{{estado}}")], 0, 4, 12, 8)
panel("timeseries", "Asignaciones por minuto", [("sum by (canal, resultado) (rate(limago_asignaciones_total[2m])) * 60",
                                                 "{{canal}} · {{resultado}}")], 12, 4, 12, 8)
panel("timeseries", "Peticiones HTTP por segundo", [(
    'sum by (ruta) (rate(limago_http_peticiones_total{ruta!="/metrics"}[1m]))', "{{ruta}}")], 0, 12, 12, 8, "reqps")
panel("timeseries", "Latencia HTTP p95", [(
    'histogram_quantile(0.95, sum by (le, ruta) (rate(limago_http_duracion_segundos_bucket{ruta=~"/api.*"}[5m])))',
    "{{ruta}}")], 12, 12, 12, 8, "s")
panel("timeseries", "Errores HTTP por segundo", [(
    'sum by (codigo, ruta) (rate(limago_http_peticiones_total{codigo=~"4..|5.."}[5m]))', "{{codigo}} {{ruta}}")],
      0, 20, 12, 8, "reqps")
panel("timeseries", "ETA medio de asignación (tiempo simulado)", [(
    "sum by (canal) (rate(limago_eta_asignacion_segundos_sum[5m])) / "
    "sum by (canal) (rate(limago_eta_asignacion_segundos_count[5m]))", "{{canal}}")], 12, 20, 12, 8, "s")
panel("timeseries", "Turnos por minuto y duración del turno p95", [
    ("rate(limago_turnos_total[1m]) * 60", "turnos/min"),
    ("histogram_quantile(0.95, sum by (le) (rate(limago_duracion_turno_segundos_bucket[5m]))) * 1000",
     "duración p95 (ms)")], 0, 28, 12, 8)
panel("timeseries", "Tiempo de cálculo de una asignación p95", [(
    "histogram_quantile(0.95, sum by (le) (rate(limago_tiempo_calculo_asignacion_segundos_bucket[5m])))",
    "p95")], 12, 28, 12, 8, "s")
panel("timeseries", "Comandos del worker por minuto", [(
    "sum by (tipo, resultado) (rate(limago_comandos_total[5m])) * 60", "{{tipo}} · {{resultado}}")], 0, 36, 12, 8)
panel("timeseries", "Viajes completados por minuto y solicitudes activas", [
    ("rate(limago_viajes_completados_total[5m]) * 60", "completados/min"),
    ("limago_solicitudes_activas", "activas")], 12, 36, 12, 8)
# --- V3: motor de aceptación y alertas simuladas ---
panel("timeseries", "Ofertas a conductores por minuto (V3)", [(
    "sum by (resultado) (rate(limago_ofertas_total[5m])) * 60", "{{resultado}}")], 0, 44, 12, 8,
      descripcion="Resultado de cada oferta: aceptada, rechazada, vencida o sin aceptación")
panel("timeseries", "Asignación operativa vs óptimo académico (V3)", [(
    "sum by (coincide) (increase(limago_aceptacion_coincide_academico_total[15m]))", "coincide = {{coincide}}")],
      12, 44, 6, 8, descripcion="¿El conductor que aceptó es el de menor ETA entre los k candidatos?")
panel("stat", "Alertas simuladas (última hora)", [(
    "sum by (estado) (increase(limago_alertas_total[1h]))", "{{estado}}")], 18, 44, 6, 8, extra=neutro,
      descripcion="Alertas de seguridad de demostración; no se conectan con servicios de emergencia reales")

tablero = {"uid": "limago-operacion", "title": "LimaGo · Operación", "tags": ["limago"], "timezone": "browser",
           "schemaVersion": 39, "version": 1, "refresh": "10s", "time": {"from": "now-30m", "to": "now"},
           "editable": False, "panels": paneles, "templating": {"list": []}, "annotations": {"list": []}}
SALIDA.write_text(json.dumps(tablero, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Dashboard con {len(paneles)} paneles: {SALIDA}")
