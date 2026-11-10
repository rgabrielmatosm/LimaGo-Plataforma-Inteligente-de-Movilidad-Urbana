"""RF-09 (parte 2) y Reto A — Dijkstra propio vs networkx, y A* vs Dijkstra.

* ``PARES`` pares origen–destino al azar (semilla fija) dentro de la mayor
  componente fuertemente conexa de Miraflores.
* Igualdad de distancias: |propio − networkx| ≤ 1e-6 m. Justificación: ambos
  suman los mismos atributos ``length`` (float64); la única fuente de diferencia
  es el orden de las sumas, cuyo error relativo es del orden de 1e-16 × número
  de tramos (< 1e-9 m en rutas de pocos km). 1e-6 m (una micra) deja un margen
  amplio sin ocultar errores reales (un tramo mal elegido cambia metros).
* Tiempos: mediana de ``REPETICIONES`` ejecuciones de todo el lote, GC desactivado.
* A*: misma ruta (mismo coste) y número de nodos expandidos frente a Dijkstra con parada temprana.
* Despacho: un Dijkstra sobre el grafo invertido frente a k Dijkstra directos.

    python -m benchmark.benchmark_rutas
"""
from __future__ import annotations

import random
import statistics

import networkx as nx

from algoritmos.a_estrella import a_estrella, heuristica_haversine
from algoritmos.dijkstra import dijkstra, distancias_hacia_destino, ruta_mas_corta
from benchmark.utilidades import (AQUA, AZUL, NARANJA, TEXTO_SECUNDARIO, CARPETA_RESULTADOS, cronometrar, entorno,
                                  estilo_graficos, guardar_json)
from config.ajustes import ajustes_academicos
from datos.red_vial import cargar_grafo_networkx
from algoritmos.grafo import GrafoVial

PARES = 300
REPETICIONES = 5
SEMILLA = 7
TOLERANCIA_M = 1e-6


def main(pares: int = PARES, repeticiones: int = REPETICIONES) -> dict:
    ajustes = ajustes_academicos()
    grafo_nx = cargar_grafo_networkx(ajustes)
    grafo = GrafoVial.desde_networkx(grafo_nx)
    principal = sorted(grafo.componente_principal())
    r = random.Random(SEMILLA)
    lote = [(r.choice(principal), r.choice(principal)) for _ in range(pares)]

    # --- corrección -------------------------------------------------------
    diferencias, explorados_d, explorados_a, longitudes = [], [], [], []
    for origen, destino in lote:
        propio, ruta, exp_d = ruta_mas_corta(grafo.adyacencia, origen, destino)
        referencia = nx.shortest_path_length(grafo_nx, origen, destino, weight="length")
        coste_a, ruta_a, exp_a = a_estrella(grafo.adyacencia, origen, destino,
                                            heuristica_haversine(grafo.nodos, destino))
        diferencias.append(abs(propio - referencia))
        assert abs(coste_a - propio) <= TOLERANCIA_M, "A* debe dar el mismo coste que Dijkstra"
        explorados_d.append(exp_d)
        explorados_a.append(exp_a)
        longitudes.append(propio)
    iguales = sum(d <= TOLERANCIA_M for d in diferencias)
    # verificación completa de un origen (todas las distancias)
    origen_completo = principal[0]
    completo_propio = dijkstra(grafo.adyacencia, origen_completo).distancias
    completo_nx = nx.single_source_dijkstra_path_length(grafo_nx, origen_completo, weight="length")
    dif_completo = max(abs(completo_propio[n] - completo_nx[n]) for n in completo_nx)

    # --- tiempos ------------------------------------------------------------
    t_propio = cronometrar(lambda: [ruta_mas_corta(grafo.adyacencia, o, d) for o, d in lote], repeticiones)
    t_nx = cronometrar(lambda: [nx.shortest_path_length(grafo_nx, o, d, weight="length") for o, d in lote],
                       repeticiones)
    t_a = cronometrar(lambda: [a_estrella(grafo.adyacencia, o, d, heuristica_haversine(grafo.nodos, d))
                               for o, d in lote], repeticiones)
    t_completo_propio = cronometrar(lambda: dijkstra(grafo.adyacencia, origen_completo), repeticiones * 4)
    t_completo_nx = cronometrar(lambda: nx.single_source_dijkstra_path_length(grafo_nx, origen_completo,
                                                                              weight="length"), repeticiones * 4)

    # --- despacho: 1 Dijkstra inverso vs k Dijkstra directos -----------------
    k = ajustes.k_candidatos
    despachos = [(r.choice(principal), [r.choice(principal) for _ in range(k)]) for _ in range(100)]
    for pasajero, candidatos in despachos[:20]:
        inverso = distancias_hacia_destino(grafo.inversa, pasajero, candidatos)
        for c in candidatos:
            assert abs(inverso.distancias[c] - ruta_mas_corta(grafo.adyacencia, c, pasajero)[0]) <= TOLERANCIA_M
    t_inverso = cronometrar(lambda: [distancias_hacia_destino(grafo.inversa, p, cs) for p, cs in despachos],
                            repeticiones)
    t_directos = cronometrar(lambda: [[ruta_mas_corta(grafo.adyacencia, c, p) for c in cs] for p, cs in despachos],
                             repeticiones)

    resultados = {
        "entorno": entorno(),
        "parametros": {"pares": pares, "repeticiones": repeticiones, "semilla": SEMILLA,
                       "tolerancia_m": TOLERANCIA_M, "red": grafo.resumen(),
                       "nodos_componente_principal": len(principal)},
        "correccion": {
            "pares_identicos": f"{iguales}/{pares}",
            "diferencia_maxima_m": max(diferencias),
            "diferencia_maxima_origen_completo_m": dif_completo,
            "longitud_media_ruta_m": statistics.fmean(longitudes),
        },
        "tiempos": {
            "dijkstra_propio_ms_por_par": t_propio["mediana_ms"] / pares,
            "networkx_ms_por_par": t_nx["mediana_ms"] / pares,
            "a_estrella_ms_por_par": t_a["mediana_ms"] / pares,
            "dijkstra_completo_propio_ms": t_completo_propio["mediana_ms"],
            "dijkstra_completo_networkx_ms": t_completo_nx["mediana_ms"],
            "detalle": {"propio": t_propio, "networkx": t_nx, "a_estrella": t_a,
                        "completo_propio": t_completo_propio, "completo_networkx": t_completo_nx},
        },
        "a_estrella": {
            "nodos_explorados_dijkstra_promedio": statistics.fmean(explorados_d),
            "nodos_explorados_a_estrella_promedio": statistics.fmean(explorados_a),
            "reduccion_porcentual": 100 * (1 - sum(explorados_a) / sum(explorados_d)),
            "mismo_coste_en_todos": True,
            "muestras": [{"longitud_m": L, "dijkstra": d, "a_estrella": a}
                         for L, d, a in zip(longitudes, explorados_d, explorados_a)],
        },
        "despacho": {
            "k": k, "solicitudes": len(despachos),
            "dijkstra_inverso_unico_ms_por_solicitud": t_inverso["mediana_ms"] / len(despachos),
            "k_dijkstra_directos_ms_por_solicitud": t_directos["mediana_ms"] / len(despachos),
        },
    }
    guardar_json("benchmark_rutas.json", resultados)
    print(f"Distancias idénticas: {iguales}/{pares}, diferencia máx {max(diferencias):.2e} m")
    print(f"Dijkstra propio {resultados['tiempos']['dijkstra_propio_ms_por_par']:.3f} ms/par | networkx "
          f"{resultados['tiempos']['networkx_ms_por_par']:.3f} ms/par | A* {resultados['tiempos']['a_estrella_ms_por_par']:.3f} ms/par")
    print(f"Nodos explorados: Dijkstra {resultados['a_estrella']['nodos_explorados_dijkstra_promedio']:.1f} | "
          f"A* {resultados['a_estrella']['nodos_explorados_a_estrella_promedio']:.1f} "
          f"(-{resultados['a_estrella']['reduccion_porcentual']:.1f} %)")
    print(f"Despacho: inverso único {resultados['despacho']['dijkstra_inverso_unico_ms_por_solicitud']:.3f} ms | "
          f"k directos {resultados['despacho']['k_dijkstra_directos_ms_por_solicitud']:.3f} ms")
    graficar(resultados)
    return resultados


def graficar(resultados: dict) -> None:
    plt = estilo_graficos()
    t = resultados["tiempos"]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    etiquetas = ["Dijkstra propio\n(parada temprana)", "networkx\n(shortest_path_length)", "A* propio"]
    valores = [t["dijkstra_propio_ms_por_par"], t["networkx_ms_por_par"], t["a_estrella_ms_por_par"]]
    barras = ax.barh(etiquetas, valores, color=[AZUL, NARANJA, AQUA], height=0.55)
    for barra, valor in zip(barras, valores):
        ax.annotate(f"{valor:.3f} ms", (valor, barra.get_y() + barra.get_height() / 2), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, color=TEXTO_SECUNDARIO)
    ax.set_xlabel("Tiempo medio por par origen–destino (ms)")
    ax.set_title(f"Ruta más corta en Miraflores ({resultados['correccion']['pares_identicos']} distancias idénticas)")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(valores) * 1.3)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(CARPETA_RESULTADOS / "rutas_tiempos.png", dpi=160)
    plt.close(fig)

    muestras = resultados["a_estrella"]["muestras"]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    x = [m["longitud_m"] / 1000 for m in muestras]
    ax.scatter(x, [m["dijkstra"] for m in muestras], s=22, color=AZUL, label="Dijkstra", marker="o",
               edgecolors="#fcfcfb", linewidths=0.8)
    ax.scatter(x, [m["a_estrella"] for m in muestras], s=22, color=NARANJA, label="A* (heurística Haversine)",
               marker="s", edgecolors="#fcfcfb", linewidths=0.8)
    a = resultados["a_estrella"]
    ax.set_xlabel("Longitud de la ruta más corta (km)")
    ax.set_ylabel("Nodos expandidos")
    ax.set_title(f"Reto A: A* expande {a['reduccion_porcentual']:.0f} % menos nodos con el mismo coste")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(CARPETA_RESULTADOS / "a_estrella_nodos.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
