"""V3 — rendimiento sobre la red de Lima Metropolitana (152 mil intersecciones).

No reemplaza a los benchmarks académicos (RF-09), que siguen midiéndose sobre
Miraflores con ``ajustes_academicos()``. Este script responde a otra pregunta:
¿las estructuras propias siguen siendo correctas y suficientemente rápidas al
escalar a toda la ciudad?

* Carga del grafo compacto (.npz) y memoria del proceso.
* Quadtree propio vs búsqueda lineal (k = 8) con 300 / 3 000 / 30 000 conductores
  sobre intersecciones reales de Lima: tiempos y resultados idénticos.
* Dijkstra propio por rangos de distancia en línea recta; para una muestra se
  compara la distancia con networkx (solo como referencia de verificación).
* Despacho completo: un Dijkstra sobre el grafo invertido desde el pasajero
  hasta los k candidatos del Quadtree.

    python -m benchmark.benchmark_metropolitano
Resultados en benchmark/resultados/benchmark_metropolitano.json (archivo aparte).
"""
from __future__ import annotations

import random
import resource
import statistics
import sys
import time

from algoritmos.dijkstra import distancias_hacia_destino, ruta_mas_corta
from algoritmos.grafo import GrafoVial
from benchmark.utilidades import cronometrar, entorno, guardar_json
from config.ajustes import ajustes_escenario
from estructuras.busqueda_lineal import buscar_k_cercanos_lineal
from estructuras.geografia import haversine_metros
from estructuras.quadtree import Quadtree
from simulacion.flota import generar_flota

SEMILLA = 11
K = 8
TAMANOS = (300, 3_000, 30_000)
CONSULTAS = 300
RANGOS_KM = ((0, 3), (3, 8), (8, 15), (15, 25), (25, 40))
PARES_POR_RANGO = 12
PARES_NETWORKX = 20
TOLERANCIA_M = 1e-6


def _memoria_mb() -> float:
    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return pico / 1024 / (1024 if sys.platform == "darwin" else 1)


def _pares_por_rango(grafo: GrafoVial, principal: list[int], r: random.Random) -> dict:
    pares = {rango: [] for rango in RANGOS_KM}
    intentos = 0
    while any(len(v) < PARES_POR_RANGO for v in pares.values()) and intentos < 200_000:
        intentos += 1
        a, b = r.choice(principal), r.choice(principal)
        km = haversine_metros(*grafo.coordenadas(a), *grafo.coordenadas(b)) / 1000
        for rango in RANGOS_KM:
            if rango[0] <= km < rango[1] and len(pares[rango]) < PARES_POR_RANGO:
                pares[rango].append((a, b))
    return pares


def main() -> dict:
    ajustes = ajustes_escenario("lima")
    inicio = time.perf_counter()
    grafo = GrafoVial.cargar_compacto(ajustes.ruta_grafo)
    carga_s = time.perf_counter() - inicio
    principal = sorted(grafo.componente_principal())
    limites = grafo.limites()
    r = random.Random(SEMILLA)
    print(f"Grafo: {grafo.num_nodos} nodos, {grafo.num_aristas} aristas, carga {carga_s:.2f} s")

    # --- Quadtree vs lineal ------------------------------------------------
    busqueda = []
    consultas = [grafo.coordenadas(r.choice(principal)) for _ in range(CONSULTAS)]
    for n in TAMANOS:
        flota = generar_flota(grafo, n, semilla=SEMILLA, proporcion_ocupados=0.2)
        q = Quadtree(limites, ajustes.capacidad_nodo, ajustes.profundidad_maxima)
        t0 = time.perf_counter()
        for c in flota:
            q.insertar(c.id, c.lat, c.lon, c.esta_disponible)
        construccion_ms = (time.perf_counter() - t0) * 1000
        puntos = [(c.id, c.lat, c.lon, c.esta_disponible) for c in flota]
        iguales = sum(q.buscar_k_cercanos(la, lo, K) == buscar_k_cercanos_lineal(puntos, la, lo, K)
                      for la, lo in consultas)
        t_q = cronometrar(lambda: [q.buscar_k_cercanos(la, lo, K) for la, lo in consultas], 3)
        t_l = cronometrar(lambda: [buscar_k_cercanos_lineal(puntos, la, lo, K) for la, lo in consultas], 3)
        fila = {"conductores": n, "construccion_ms": construccion_ms,
                "quadtree_ms_por_consulta": t_q["mediana_ms"] / CONSULTAS,
                "lineal_ms_por_consulta": t_l["mediana_ms"] / CONSULTAS,
                "aceleracion": t_l["mediana_ms"] / t_q["mediana_ms"],
                "resultados_identicos": f"{iguales}/{CONSULTAS}", "profundidad": q.profundidad()}
        busqueda.append(fila)
        print(f"[quadtree] n={n:>6}: {fila['quadtree_ms_por_consulta']:.4f} ms vs lineal "
              f"{fila['lineal_ms_por_consulta']:.4f} ms (x{fila['aceleracion']:.1f}) iguales {fila['resultados_identicos']}")

    # --- Dijkstra por rangos de distancia -----------------------------------
    rutas = []
    pares = _pares_por_rango(grafo, principal, r)
    for (km_min, km_max), lista in pares.items():
        tiempos, explorados, metros = [], [], []
        for a, b in lista:
            t0 = time.perf_counter()
            distancia, _, exp = ruta_mas_corta(grafo.adyacencia, a, b)
            tiempos.append((time.perf_counter() - t0) * 1000)
            explorados.append(exp)
            metros.append(distancia)
        fila = {"rango_km_linea_recta": [km_min, km_max], "pares": len(lista),
                "mediana_ms": statistics.median(tiempos), "maximo_ms": max(tiempos),
                "nodos_explorados_mediana": statistics.median(explorados),
                "distancia_calles_km_mediana": statistics.median(metros) / 1000}
        rutas.append(fila)
        print(f"[dijkstra] {km_min:>2}-{km_max:<2} km: mediana {fila['mediana_ms']:.1f} ms, "
              f"máx {fila['maximo_ms']:.1f} ms, {fila['nodos_explorados_mediana']:.0f} nodos")

    # --- Verificación con networkx (muestra) ---------------------------------
    import networkx as nx

    g = nx.DiGraph()
    for (u, v), datos in grafo.aristas.items():
        g.add_edge(u, v, length=datos.longitud)
    muestra = [p for lista in pares.values() for p in lista][:PARES_NETWORKX]
    diferencias = []
    for a, b in muestra:
        propio, _, _ = ruta_mas_corta(grafo.adyacencia, a, b)
        diferencias.append(abs(propio - nx.shortest_path_length(g, a, b, weight="length")))
    del g
    verificacion = {"pares": len(muestra), "iguales": sum(d <= TOLERANCIA_M for d in diferencias),
                    "diferencia_maxima_m": max(diferencias)}
    print(f"[networkx] distancias iguales {verificacion['iguales']}/{verificacion['pares']}")

    # --- Despacho completo ---------------------------------------------------
    flota = generar_flota(grafo, 2500, semilla=SEMILLA, proporcion_ocupados=0.2)
    q = Quadtree(limites, ajustes.capacidad_nodo, ajustes.profundidad_maxima)
    for c in flota:
        q.insertar(c.id, c.lat, c.lon, c.esta_disponible)
    por_id = {c.id: c for c in flota}
    tiempos = []
    for _ in range(60):
        pasajero = r.choice(principal)
        t0 = time.perf_counter()
        candidatos = q.buscar_k_cercanos(*grafo.coordenadas(pasajero), K, solo_disponibles=True)
        nodos = {por_id[cid].nodo for _, cid in candidatos}
        distancias_hacia_destino(grafo.inversa, pasajero, nodos)
        tiempos.append((time.perf_counter() - t0) * 1000)
    despacho = {"conductores": 2500, "k": K, "solicitudes": len(tiempos),
                "mediana_ms": statistics.median(tiempos), "p95_ms": sorted(tiempos)[int(0.95 * len(tiempos)) - 1]}
    print(f"[despacho] mediana {despacho['mediana_ms']:.1f} ms, p95 {despacho['p95_ms']:.1f} ms")

    resultados = {"entorno": entorno(), "grafo": {"nodos": grafo.num_nodos, "aristas": grafo.num_aristas,
                                                  "componente_principal": len(principal), "carga_s": carga_s},
                  "busqueda": busqueda, "rutas": rutas, "verificacion_networkx": verificacion,
                  "despacho": despacho, "memoria_pico_mb": _memoria_mb()}
    guardar_json("benchmark_metropolitano.json", resultados)
    print(f"Memoria pico del proceso: {resultados['memoria_pico_mb']:.0f} MB")
    return resultados


if __name__ == "__main__":
    main()
