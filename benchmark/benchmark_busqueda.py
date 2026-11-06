"""RF-09 (parte 1) y Reto D — Búsqueda lineal vs Quadtree (y vs H3 experimental).

Escalas exigidas: 300, 3 000 y 30 000 conductores sobre la red real de Miraflores.

Metodología
-----------
* Flota generada con ``generar_flota`` (semilla fija) sobre intersecciones; 20 % ocupados.
* ``CONSULTAS`` pasajeros en posiciones uniformes dentro del recuadro de la red
  (otra semilla fija). k = 5.
* Para cada escala se mide el tiempo total de responder todas las consultas,
  ``REPETICIONES`` veces, con el GC desactivado; se reporta la mediana.
* Antes de medir se verifica que el Quadtree (y H3) devuelven **exactamente** los
  mismos k candidatos que la búsqueda lineal en todas las consultas.
* Escenario adicional "uniforme": conductores en posiciones continuas al azar
  (sin coincidencias en intersecciones) para aislar el efecto de los puntos repetidos.

    python -m benchmark.benchmark_busqueda
"""
from __future__ import annotations

import random
import time

from benchmark.utilidades import (AQUA, AZUL, NARANJA, TEXTO_SECUNDARIO, CARPETA_RESULTADOS, cronometrar,
                                  entorno, estilo_graficos, guardar_json)
from config.ajustes import cargar_ajustes
from datos.red_vial import cargar_red_vial
from estructuras.busqueda_lineal import buscar_k_cercanos_lineal
from estructuras.quadtree import Quadtree
from simulacion.flota import generar_flota

ESCALAS = (300, 3_000, 30_000)
CONSULTAS = 400
REPETICIONES = 5
K = 5
SEMILLA_FLOTA = 42
SEMILLA_CONSULTAS = 2026


def preparar(grafo, n: int, escenario: str, limites):
    if escenario == "intersecciones":
        flota = generar_flota(grafo, n, SEMILLA_FLOTA, 0.2)
        return [(c.id, c.lat, c.lon, c.esta_disponible) for c in flota]
    r = random.Random(SEMILLA_FLOTA)
    return [(i, r.uniform(limites.lat_min, limites.lat_max), r.uniform(limites.lon_min, limites.lon_max),
             r.random() >= 0.2) for i in range(1, n + 1)]


def main(consultas: int = CONSULTAS, repeticiones: int = REPETICIONES) -> dict:
    import h3

    from experimental.indice_h3 import IndiceH3

    ajustes = cargar_ajustes()
    grafo = cargar_red_vial(ajustes)
    limites = grafo.limites()
    r = random.Random(SEMILLA_CONSULTAS)
    puntos_consulta = [(r.uniform(limites.lat_min, limites.lat_max), r.uniform(limites.lon_min, limites.lon_max))
                       for _ in range(consultas)]
    resultados = {"entorno": entorno(), "parametros": {
        "escalas": ESCALAS, "consultas": consultas, "repeticiones": repeticiones, "k": K,
        "semilla_flota": SEMILLA_FLOTA, "semilla_consultas": SEMILLA_CONSULTAS, "proporcion_ocupados": 0.2,
        "capacidad_nodo": ajustes.capacidad_nodo, "profundidad_maxima": ajustes.profundidad_maxima,
        "resolucion_h3": 9, "h3_version": h3.__version__, "red": grafo.resumen()}, "escenarios": {}}

    for escenario in ("intersecciones", "uniforme"):
        filas = []
        for n in ESCALAS:
            puntos = preparar(grafo, n, escenario, limites)
            inicio = time.perf_counter()
            arbol = Quadtree(limites, ajustes.capacidad_nodo, ajustes.profundidad_maxima)
            for cid, lat, lon, disp in puntos:
                arbol.insertar(cid, lat, lon, disp)
            construccion_qt = (time.perf_counter() - inicio) * 1000
            inicio = time.perf_counter()
            indice_h3 = IndiceH3(9)
            for cid, lat, lon, disp in puntos:
                indice_h3.insertar(cid, lat, lon, disp)
            construccion_h3 = (time.perf_counter() - inicio) * 1000

            iguales_qt = iguales_h3 = 0
            distancias_qt = distancias_h3 = nodos_visitados = 0
            for lat, lon in puntos_consulta:
                referencia = buscar_k_cercanos_lineal(puntos, lat, lon, K)
                iguales_qt += arbol.buscar_k_cercanos(lat, lon, K) == referencia
                distancias_qt += arbol.ultima_busqueda.distancias_calculadas
                nodos_visitados += arbol.ultima_busqueda.nodos_visitados
                iguales_h3 += indice_h3.buscar_k_cercanos(lat, lon, K) == referencia
                distancias_h3 += indice_h3.distancias_calculadas

            t_lineal = cronometrar(lambda: [buscar_k_cercanos_lineal(puntos, la, lo, K) for la, lo in puntos_consulta],
                                   repeticiones)
            t_qt = cronometrar(lambda: [arbol.buscar_k_cercanos(la, lo, K) for la, lo in puntos_consulta], repeticiones)
            t_h3 = cronometrar(lambda: [indice_h3.buscar_k_cercanos(la, lo, K) for la, lo in puntos_consulta],
                               repeticiones)
            fila = {
                "conductores": n,
                "lineal_ms_por_consulta": t_lineal["mediana_ms"] / consultas,
                "quadtree_ms_por_consulta": t_qt["mediana_ms"] / consultas,
                "h3_ms_por_consulta": t_h3["mediana_ms"] / consultas,
                "aceleracion_quadtree": t_lineal["mediana_ms"] / t_qt["mediana_ms"],
                "aceleracion_h3": t_lineal["mediana_ms"] / t_h3["mediana_ms"],
                "detalle_lineal": t_lineal, "detalle_quadtree": t_qt, "detalle_h3": t_h3,
                "construccion_quadtree_ms": construccion_qt, "construccion_h3_ms": construccion_h3,
                "profundidad_quadtree": arbol.profundidad(), "nodos_quadtree": arbol.contar_nodos(),
                "celdas_h3_ocupadas": len(indice_h3.celdas),
                "distancias_promedio_lineal": n, "distancias_promedio_quadtree": distancias_qt / consultas,
                "distancias_promedio_h3": distancias_h3 / consultas,
                "nodos_visitados_promedio_quadtree": nodos_visitados / consultas,
                "resultados_identicos_quadtree": f"{iguales_qt}/{consultas}",
                "resultados_identicos_h3": f"{iguales_h3}/{consultas}",
            }
            filas.append(fila)
            print(f"[{escenario}] n={n:>6}: lineal {fila['lineal_ms_por_consulta']:.4f} ms | "
                  f"quadtree {fila['quadtree_ms_por_consulta']:.4f} ms (x{fila['aceleracion_quadtree']:.1f}) | "
                  f"h3 {fila['h3_ms_por_consulta']:.4f} ms | iguales QT {iguales_qt}/{consultas} H3 {iguales_h3}/{consultas}")
        resultados["escenarios"][escenario] = filas
    guardar_json("benchmark_busqueda.json", resultados)
    graficar(resultados)
    return resultados


def graficar(resultados: dict) -> None:
    plt = estilo_graficos()
    filas = resultados["escenarios"]["intersecciones"]
    n = [f["conductores"] for f in filas]

    fig, ax = plt.subplots(figsize=(7, 4.2))
    series = [("Búsqueda lineal", "lineal_ms_por_consulta", AZUL, "o"),
              ("Quadtree propio", "quadtree_ms_por_consulta", NARANJA, "s"),
              ("H3 (experimental)", "h3_ms_por_consulta", AQUA, "^")]
    for nombre, clave, color, marcador in series:
        y = [f[clave] for f in filas]
        ax.plot(n, y, marker=marcador, color=color, label=nombre)
        ax.annotate(f"{y[-1]:.3f} ms", (n[-1], y[-1]), textcoords="offset points", xytext=(6, 0),
                    va="center", fontsize=8, color=TEXTO_SECUNDARIO)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(n, [f"{x:,}".replace(",", " ") for x in n])
    ax.set_xlabel("Conductores en la flota (escala logarítmica)")
    ax.set_ylabel("Tiempo por consulta k=5 (ms, log)")
    ax.set_title("k vecinos más cercanos: tiempo por consulta")
    ax.legend(loc="upper left")
    ax.set_xlim(200, 80_000)
    fig.tight_layout()
    fig.savefig(CARPETA_RESULTADOS / "busqueda_tiempos.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for nombre, clave, color, marcador in [("Búsqueda lineal", "distancias_promedio_lineal", AZUL, "o"),
                                           ("Quadtree propio", "distancias_promedio_quadtree", NARANJA, "s"),
                                           ("H3 (experimental)", "distancias_promedio_h3", AQUA, "^")]:
        y = [f[clave] for f in filas]
        ax.plot(n, y, marker=marcador, color=color, label=nombre)
        ax.annotate(f"{y[-1]:,.0f}".replace(",", " "), (n[-1], y[-1]), textcoords="offset points",
                    xytext=(6, 0), va="center", fontsize=8, color=TEXTO_SECUNDARIO)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(n, [f"{x:,}".replace(",", " ") for x in n])
    ax.set_xlabel("Conductores en la flota (escala logarítmica)")
    ax.set_ylabel("Distancias Haversine calculadas por consulta (log)")
    ax.set_title("Trabajo por consulta: la poda descarta casi toda la flota")
    ax.legend(loc="upper left")
    ax.set_xlim(200, 80_000)
    fig.tight_layout()
    fig.savefig(CARPETA_RESULTADOS / "busqueda_distancias.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
