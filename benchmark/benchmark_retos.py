"""Retos B y C — Congestión 8:00 vs 15:00 y asignación de varios pasajeros.

Reto B: ``PARES_B`` pares origen–destino; para cada hora se calculan rutas de
tiempo mínimo con Dijkstra propio sobre los pesos dinámicos. Se mide el tiempo
medio, cuántas rutas cambian de trazado y, con una flota de 300, cuántas
asignaciones eligen otro conductor. Se genera un mapa folium del par cuya ruta
más cambia.

Reto C: ``ENSAYOS_C`` lotes de P pasajeros simultáneos sobre una flota de 300.
Se compara la espera total del algoritmo húngaro (óptima) con la estrategia
codiciosa por orden de llegada.

    python -m benchmark.benchmark_retos
"""
from __future__ import annotations

import random
import statistics
import time

from algoritmos.congestion import PesosDinamicos, factor_congestion
from algoritmos.dijkstra import ruta_mas_corta
from benchmark.utilidades import (AZUL, NARANJA, TEXTO_SECUNDARIO, CARPETA_RESULTADOS, entorno, estilo_graficos,
                                  guardar_json)
from config.ajustes import cargar_ajustes
from datos.red_vial import cargar_red_vial
from simulacion.despachador import Despachador
from simulacion.flota import generar_flota
from simulacion.modelos import Pasajero
from visualizacion.mapa_folium import generar_mapa_comparacion_rutas

PARES_B = 300
SEMILLA = 11
ENSAYOS_C = 40
TAMANOS_C = (3, 5, 10, 20)


def reto_b(grafo, ajustes) -> dict:
    principal = sorted(grafo.componente_principal())
    r = random.Random(SEMILLA)
    pares = [(r.choice(principal), r.choice(principal)) for _ in range(PARES_B)]
    pesos = PesosDinamicos(grafo)
    ady8, _ = pesos.adyacencias(8.0)
    ady15, _ = pesos.adyacencias(15.0)
    filas = []
    for o, d in pares:
        if o == d:
            continue
        t8, ruta8, _ = ruta_mas_corta(ady8, o, d)
        t15, ruta15, _ = ruta_mas_corta(ady15, o, d)
        filas.append({"t8": t8, "t15": t15, "cambia_ruta": ruta8 != ruta15, "ruta8": ruta8, "ruta15": ruta15,
                      "m8": grafo.longitud_ruta(ruta8), "m15": grafo.longitud_ruta(ruta15)})
    # asignaciones con la misma flota a ambas horas
    distintos = 0
    etas = {8.0: [], 15.0: []}
    puntos = [r.choice(principal) for _ in range(100)]
    for hora in (8.0, 15.0):
        flota = generar_flota(grafo, 300, ajustes.semilla, 0.0)
        desp = Despachador(grafo, flota, ajustes.con(congestion_activa=True))
        desp.hora_actual = hora
        for i, nodo in enumerate(puntos):
            lat, lon = grafo.coordenadas(nodo)
            pasajero = Pasajero(i, lat, lon, nodo=nodo)
            candidatos = desp.buscar_candidatos(pasajero)
            desp.calcular_eta(pasajero, candidatos)
            etas[hora].append(desp.elegir_mejor(candidatos))
    for a, b in zip(etas[8.0], etas[15.0]):
        distintos += a.conductor_id != b.conductor_id
    mas_cambio = max((f for f in filas if f["cambia_ruta"]), key=lambda f: f["t8"] - f["t15"], default=None)
    if mas_cambio:
        o, d = mas_cambio["ruta8"][0], mas_cambio["ruta8"][-1]
        generar_mapa_comparacion_rutas(
            grafo, [(f"08:00 · {mas_cambio['t8'] / 60:.1f} min · {mas_cambio['m8']:.0f} m", mas_cambio["ruta8"], "#dc2626"),
                    (f"15:00 · {mas_cambio['t15'] / 60:.1f} min · {mas_cambio['m15']:.0f} m", mas_cambio["ruta15"], "#2563eb")],
            ajustes.carpeta_mapas / "reto_b_congestion_8_vs_15.html",
            "Reto B · Misma solicitud a las 08:00 (rojo) y a las 15:00 (azul) — congestión simulada",
            [(*grafo.coordenadas(o), "Origen"), (*grafo.coordenadas(d), "Destino")])
    perfil = [{"hora": h / 2, "primary": factor_congestion("primary", h / 2),
               "residential": factor_congestion("residential", h / 2)} for h in range(0, 49)]
    return {
        "pares": len(filas),
        "tiempo_medio_8_s": statistics.fmean(f["t8"] for f in filas),
        "tiempo_medio_15_s": statistics.fmean(f["t15"] for f in filas),
        "incremento_medio_porcentual": 100 * (statistics.fmean(f["t8"] / f["t15"] for f in filas) - 1),
        "rutas_que_cambian": sum(f["cambia_ruta"] for f in filas),
        "asignaciones_con_otro_conductor": f"{distintos}/{len(puntos)}",
        "eta_media_asignacion_8_s": statistics.fmean(c.eta_s for c in etas[8.0]),
        "eta_media_asignacion_15_s": statistics.fmean(c.eta_s for c in etas[15.0]),
        "perfil_horario": perfil,
        "mapa": "mapas/reto_b_congestion_8_vs_15.html" if mas_cambio else None,
    }


def reto_c(grafo, ajustes) -> dict:
    principal = sorted(grafo.componente_principal())
    r = random.Random(SEMILLA + 1)
    filas = []
    for tamano in TAMANOS_C:
        mejoras, totales_opt, totales_cod, tiempos = [], [], [], []
        for ensayo in range(ENSAYOS_C):
            flota = generar_flota(grafo, 300, ajustes.semilla + ensayo, 0.2)
            desp = Despachador(grafo, flota, ajustes)
            # pasajeros concentrados (una zona de demanda), como a la salida de un evento
            centro = r.choice(principal)
            clat, clon = grafo.coordenadas(centro)
            pasajeros = []
            while len(pasajeros) < tamano:
                lat, lon = clat + r.uniform(-0.004, 0.004), clon + r.uniform(-0.004, 0.004)
                try:
                    pasajeros.append(desp.crear_pasajero(len(pasajeros), lat, lon))
                except ValueError:
                    continue
            inicio = time.perf_counter()
            optimo = desp.asignar_varios(pasajeros, estrategia="optima")
            tiempos.append((time.perf_counter() - inicio) * 1000)
            codicioso = desp.asignar_varios(pasajeros, estrategia="codiciosa")
            totales_opt.append(optimo["espera_total_s"])
            totales_cod.append(codicioso["espera_total_s"])
            mejoras.append(100 * (1 - optimo["espera_total_s"] / codicioso["espera_total_s"])
                           if codicioso["espera_total_s"] else 0.0)
            assert optimo["espera_total_s"] <= codicioso["espera_total_s"] + 1e-6
        filas.append({
            "pasajeros": tamano, "ensayos": ENSAYOS_C,
            "espera_total_media_optima_s": statistics.fmean(totales_opt),
            "espera_total_media_codiciosa_s": statistics.fmean(totales_cod),
            "mejora_media_porcentual": statistics.fmean(mejoras),
            "mejora_maxima_porcentual": max(mejoras),
            "ensayos_con_mejora": sum(m > 1e-9 for m in mejoras),
            "tiempo_medio_asignacion_optima_ms": statistics.fmean(tiempos),
        })
        print(f"Reto C P={tamano}: óptimo {filas[-1]['espera_total_media_optima_s']:.0f} s vs codicioso "
              f"{filas[-1]['espera_total_media_codiciosa_s']:.0f} s (mejora media {filas[-1]['mejora_media_porcentual']:.1f} %)")
    return {"filas": filas}


def main() -> dict:
    ajustes = cargar_ajustes()
    grafo = cargar_red_vial(ajustes)
    b = reto_b(grafo, ajustes)
    print(f"Reto B: {b['tiempo_medio_8_s']:.0f} s (8:00) vs {b['tiempo_medio_15_s']:.0f} s (15:00); "
          f"rutas que cambian {b['rutas_que_cambian']}/{b['pares']}; asignaciones distintas {b['asignaciones_con_otro_conductor']}")
    c = reto_c(grafo, ajustes)
    resultados = {"entorno": entorno(), "parametros": {"semilla": SEMILLA, "pares_b": PARES_B, "ensayos_c": ENSAYOS_C,
                                                       "tamanos_c": TAMANOS_C, "red": grafo.resumen()},
                  "reto_b": b, "reto_c": c}
    guardar_json("benchmark_retos.json", resultados)
    graficar(resultados)
    return resultados


def graficar(resultados: dict) -> None:
    plt = estilo_graficos()
    perfil = resultados["reto_b"]["perfil_horario"]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    horas = [p["hora"] for p in perfil]
    ax.plot(horas, [p["primary"] for p in perfil], color=NARANJA, label="Avenida principal (primary)")
    ax.plot(horas, [p["residential"] for p in perfil], color=AZUL, label="Calle residencial", linestyle="--")
    for h in (8, 15):
        ax.axvline(h, color=TEXTO_SECUNDARIO, linewidth=1, linestyle=":")
        ax.annotate(f"{h:02d}:00", (h, max(p["primary"] for p in perfil)), xytext=(4, 0),
                    textcoords="offset points", fontsize=8, color=TEXTO_SECUNDARIO)
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 3))
    ax.set_xlabel("Hora del día")
    ax.set_ylabel("Multiplicador del tiempo de viaje")
    ax.set_title("Reto B: perfil de congestión simulada por tipo de vía")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(CARPETA_RESULTADOS / "reto_b_perfil.png", dpi=160)
    plt.close(fig)

    filas = resultados["reto_c"]["filas"]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    x = list(range(len(filas)))
    ancho = 0.36
    ax.bar([i - ancho / 2 - 0.01 for i in x], [f["espera_total_media_codiciosa_s"] / 60 for f in filas],
                width=ancho, color=AZUL, label="Codiciosa (orden de llegada)")
    b2 = ax.bar([i + ancho / 2 + 0.01 for i in x], [f["espera_total_media_optima_s"] / 60 for f in filas],
                width=ancho, color=NARANJA, label="Óptima (algoritmo húngaro)")
    for barra, fila in zip(b2, filas):
        ax.annotate(f"−{fila['mejora_media_porcentual']:.1f} %", (barra.get_x() + barra.get_width() / 2, barra.get_height()),
                    xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, color=TEXTO_SECUNDARIO)
    ax.set_xticks(x, [f"{f['pasajeros']} pasajeros" for f in filas])
    ax.set_ylabel("Espera total media (min)")
    ax.set_title("Reto C: espera total de un lote de solicitudes simultáneas")
    ax.legend(loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(CARPETA_RESULTADOS / "reto_c_asignacion.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
