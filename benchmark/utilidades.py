"""Utilidades comunes de los benchmarks: medición, entorno y estilo de gráficos."""
from __future__ import annotations

import gc
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

CARPETA_RESULTADOS = RAIZ / "benchmark" / "resultados"

# Paleta categórica (3 primeros espacios de una paleta validada para daltonismo,
# todos los pares). El aqua tiene contraste < 3:1: por eso cada serie lleva
# marcador distinto y etiquetas directas.
AZUL, NARANJA, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SUPERFICIE, TEXTO, TEXTO_SECUNDARIO, REJILLA = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def entorno() -> dict:
    import networkx
    import osmnx

    return {
        "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "implementacion": platform.python_implementation(),
        "sistema": platform.platform(),
        "procesador": platform.processor() or platform.machine(),
        "nucleos_logicos": os.cpu_count(),
        "networkx": networkx.__version__,
        "osmnx": osmnx.__version__,
    }


def cronometrar(funcion, repeticiones: int) -> dict:
    """Ejecuta ``funcion`` ``repeticiones`` veces con el recolector de basura desactivado.

    Devuelve tiempos en milisegundos (mediana, media, desviación, mínimo).
    La mediana es el valor principal: es robusta ante interrupciones del sistema.
    """
    tiempos = []
    for _ in range(repeticiones):
        gc.collect()
        gc.disable()
        try:
            inicio = time.perf_counter_ns()
            funcion()
            tiempos.append((time.perf_counter_ns() - inicio) / 1e6)
        finally:
            gc.enable()
    return {
        "mediana_ms": statistics.median(tiempos),
        "media_ms": statistics.fmean(tiempos),
        "desviacion_ms": statistics.stdev(tiempos) if len(tiempos) > 1 else 0.0,
        "minimo_ms": min(tiempos),
        "repeticiones": repeticiones,
    }


def guardar_json(nombre: str, datos: dict) -> Path:
    CARPETA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_RESULTADOS / nombre
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta


def estilo_graficos():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
        "axes.edgecolor": REJILLA, "axes.labelcolor": TEXTO_SECUNDARIO, "axes.titlecolor": TEXTO,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.labelsize": 10,
        "xtick.color": TEXTO_SECUNDARIO, "ytick.color": TEXTO_SECUNDARIO,
        "axes.grid": True, "axes.axisbelow": True, "grid.color": REJILLA, "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False, "legend.fontsize": 9, "font.size": 10,
        "lines.linewidth": 2, "lines.markersize": 8,
    })
    return plt
