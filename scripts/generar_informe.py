"""Genera ``informe.pdf`` (3–5 páginas) a partir de los resultados reales de los benchmarks.

Todas las cifras se leen de ``benchmark/resultados/*.json`` y ``mapas/resumen_mapas.json``;
si se vuelven a ejecutar los benchmarks, basta con regenerar el informe.

    python -m scripts.generar_informe
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_JUSTIFY  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,  # noqa: E402
                                TableStyle)

RES = RAIZ / "benchmark" / "resultados"
MARCA = colors.HexColor("#0f766e")
GRIS = colors.HexColor("#52514e")
FONDO = colors.HexColor("#eef2f0")


FUENTES_CANDIDATAS = [  # (regular, negrita, cursiva, negrita cursiva) con soporte de griego y símbolos
    ["/usr/share/fonts/truetype/liberation/LiberationSans-" + v + ".ttf"
     for v in ("Regular", "Bold", "Italic", "BoldItalic")],
    ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf",
     "C:/Windows/Fonts/arialbi.ttf"],
    ["/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial Italic.ttf",
     "/Library/Fonts/Arial Bold Italic.ttf"],
]


def registrar_fuentes() -> tuple[str, str]:
    """Registra una fuente TrueType Unicode; las fuentes base de PDF no tienen letras griegas."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for rutas in FUENTES_CANDIDATAS:
        if all(Path(r).exists() for r in rutas):
            for nombre, ruta in zip(("Texto", "Texto-Negrita", "Texto-Cursiva", "Texto-NegritaCursiva"), rutas):
                pdfmetrics.registerFont(TTFont(nombre, ruta))
            addMapping("Texto", 0, 0, "Texto")
            addMapping("Texto", 1, 0, "Texto-Negrita")
            addMapping("Texto", 0, 1, "Texto-Cursiva")
            addMapping("Texto", 1, 1, "Texto-NegritaCursiva")
            return "Texto", "Texto-Negrita"
    return "Helvetica", "Helvetica-Bold"


FUENTE, FUENTE_NEGRITA = "Helvetica", "Helvetica-Bold"


def cargar(nombre: str) -> dict:
    return json.loads((RES / nombre).read_text(encoding="utf-8"))


def num(x: float, d: int = 2) -> str:
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def estilos():
    base = getSampleStyleSheet()
    cuerpo = ParagraphStyle("cuerpo", parent=base["Normal"], fontName=FUENTE, fontSize=9.2, leading=12,
                            alignment=TA_JUSTIFY, spaceAfter=4)
    return {
        "titulo": ParagraphStyle("titulo", parent=base["Title"], fontName=FUENTE_NEGRITA, fontSize=15, leading=18,
                                 textColor=MARCA, spaceAfter=2),
        "sub": ParagraphStyle("sub", parent=cuerpo, alignment=1, textColor=GRIS, fontSize=8.5, spaceAfter=6),
        "h1": ParagraphStyle("h1", parent=base["Heading2"], fontName=FUENTE_NEGRITA, fontSize=11, leading=13,
                             textColor=MARCA, spaceBefore=6, spaceAfter=3),
        "cuerpo": cuerpo,
        "nota": ParagraphStyle("nota", parent=cuerpo, fontSize=7.6, leading=9.4, textColor=GRIS),
        "celda": ParagraphStyle("celda", parent=cuerpo, fontSize=7.6, leading=9.2, alignment=0, spaceAfter=0),
    }


def tabla(filas, anchos, e, cabecera=True):
    datos = [[Paragraph(str(c), e["celda"]) for c in fila] for fila in filas]
    t = Table(datos, colWidths=anchos, repeatRows=1 if cabecera else 0)
    estilo = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d5dad7")),
              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    if cabecera:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), FONDO)]
    t.setStyle(TableStyle(estilo))
    return t


def figuras(rutas, ancho_total, alto):
    ancho = ancho_total / len(rutas)
    return Table([[Image(str(RES / r), width=ancho - 0.2 * cm, height=alto) for r in rutas]],
                 colWidths=[ancho] * len(rutas))


def construir(salida: Path) -> None:
    global FUENTE, FUENTE_NEGRITA
    FUENTE, FUENTE_NEGRITA = registrar_fuentes()
    e = estilos()
    b = cargar("benchmark_busqueda.json")
    r = cargar("benchmark_rutas.json")
    x = cargar("benchmark_retos.json")
    mapas = json.loads((RAIZ / "mapas" / "resumen_mapas.json").read_text(encoding="utf-8"))
    inter = b["escenarios"]["intersecciones"]
    unif = b["escenarios"]["uniforme"]
    p = b["parametros"]
    ent = b["entorno"]
    P = lambda t, s="cuerpo": Paragraph(t, e[s])  # noqa: E731
    h = []

    h += [P("LimaGo — Asignación del conductor más cercano", "titulo"),
          P("Proyecto Integrador N.° 2 · Algoritmos y Estructura de Datos II · Informe técnico", "sub")]

    h += [P("1. Contexto y datos", "h1"), P(
        f"LimaGo asigna conductores sobre la red vial real de Miraflores (Lima), descargada de OpenStreetMap "
        f"(relación 1944770, 9,45 km²) y guardada en <i>datos/miraflores.graphml</i>: {p['red']}. "
        "La flota es simulada (300 conductores por defecto, semilla 42) y siempre se ubica en intersecciones de la "
        "mayor componente fuertemente conexa (1 300 nodos), de modo que todo conductor puede llegar a todo punto. "
        "El flujo de asignación tiene dos etapas, como en los sistemas reales: (1) un Quadtree propio con un heap "
        "obtiene los <i>k</i> = 5 conductores disponibles más cercanos en línea recta (Haversine propio); (2) un único "
        "Dijkstra propio sobre el grafo invertido, desde el pasajero, da la distancia por calles de los <i>k</i> "
        "candidatos respetando los sentidos de circulación; se asigna el de menor ETA (velocidad media configurable, "
        "25 km/h por defecto).")]

    h += [P("2. Diseño del Quadtree", "h1"), P(
        "Es un Quadtree de puntos por región (<i>x</i> = longitud, <i>y</i> = latitud) con las clases "
        "<b>NodoQuadtree</b> y <b>Quadtree</b>. Cada nodo es hoja (lista de entradas) o interno (exactamente cuatro "
        "hijos NO, NE, SO, SE) y guarda dos contadores de su subárbol: <i>total</i> y <i>disponibles</i>. Así la "
        "búsqueda descarta ramas sin conductores libres sin visitarlas y la eliminación sabe cuándo fusionar. Un "
        "diccionario <i>id → entrada</i> permite eliminar, mover y cambiar disponibilidad en O(<i>h</i>) sin recorrer "
        "el árbol. <b>Bordes:</b> los rectángulos son cerrados, pero cada punto va a un único hijo por la regla "
        "<i>lon ≥ centro → este, lat ≥ centro → norte</i>; ningún punto se duplica ni se pierde. "
        f"<b>Subdivisión acotada:</b> una hoja se divide solo si supera la capacidad ({p['capacidad_nodo']}) y su "
        f"profundidad es menor que {p['profundidad_maxima']}; si todos sus puntos tienen coordenadas idénticas no se "
        "divide (dividir nunca los separaría) y actúa como <i>cubeta</i>. Al eliminar, un nodo interno con "
        "<i>total</i> ≤ capacidad se fusiona en hoja. <b>k vecinos exactos:</b> búsqueda <i>best-first</i> "
        "(Hjaltason y Samet, 1999) con un min-heap de nodos ordenados por una cota inferior de distancia y un "
        "max-heap de tamaño <i>k</i> con los mejores candidatos. La cota es rigurosa sobre la esfera: "
        "R·|Δφ| fuera del rango de latitudes y R·asin(cos φ·sin Δλ) (distancia a un meridiano completo) fuera del "
        "de longitudes; se toma el máximo. Cuando la menor cota pendiente supera la <i>k</i>-ésima distancia, "
        "ningún nodo restante puede mejorar el resultado y la búsqueda termina. La exactitud se verificó contra la "
        "búsqueda lineal en todas las consultas del benchmark y en las pruebas automatizadas.")]

    big_o = [
        ["Operación", "Costo", "Justificación"],
        ["Haversine", "O(1)", "Número fijo de operaciones trigonométricas."],
        ["insertar", "O(h) amortizado", "Descenso por un camino raíz-hoja; la división reparte ≤ c+1 puntos. h ≤ profundidad "
                                        "máxima (18); con datos dispersos h ≈ log<sub>4</sub> n."],
        ["eliminar", "O(h + c)", "Camino hasta la hoja vía diccionario; la fusión recoge ≤ c puntos."],
        ["actualizar_posicion", "O(h + c)", "Misma hoja: O(h); si cambia de hoja, eliminar + insertar."],
        ["cambiar_disponibilidad", "O(h)", "Ajusta el contador de los nodos del camino."],
        ["buscar_rectangulo", "O(h + v + m)", "v nodos que intersectan el rectángulo, m resultados; peor caso O(n)."],
        ["buscar_k_cercanos", "O((v + d) log v + d log k)", "v nodos visitados y d distancias calculadas; con datos "
                                                            "dispersos v, d ≈ O(log n + k); peor caso (todos coincidentes) O(n log k)."],
        ["Búsqueda lineal (referencia)", "O(n log k)", "Calcula n distancias y mantiene un heap de tamaño k."],
        ["Dijkstra (heap, borrado perezoso)", "O((V + E) log V)", "Cada arista se relaja una vez; cada push/pop cuesta O(log V). "
                                                                  "Con parada temprana explora solo hasta asentar los objetivos."],
        ["A* (Reto A)", "O((V + E) log V) peor caso", "Igual que Dijkstra; la heurística reduce los nodos expandidos."],
        ["Despacho completo", "O(log n + k log k + (V'+E') log V')", "Quadtree + un Dijkstra inverso que se detiene al asentar los k nodos."],
        ["Húngaro (Reto C)", "O(p² m)", "p pasajeros, m conductores candidatos (p ≤ m)."],
    ]
    h += [P("3. Análisis de complejidad (n conductores, c capacidad, h altura)", "h1"),
          KeepTogether(tabla(big_o, [4.1 * cm, 4.1 * cm, 9.7 * cm], e))]

    h += [P("4. Metodología experimental", "h1"), P(
        f"Equipo: {ent['procesador']}, {ent['nucleos_logicos']} núcleos lógicos, {ent['sistema']}, Python {ent['python']}, "
        f"networkx {ent['networkx']}, osmnx {ent['osmnx']} (fecha UTC {ent['fecha_utc'][:10]}). "
        f"<b>Búsqueda:</b> escalas exactas de {', '.join(f'{n:,}'.replace(',', ' ') for n in p['escalas'])} conductores; "
        f"{p['consultas']} pasajeros uniformes en el recuadro de la red (semilla {p['semilla_consultas']}), k = {p['k']}, "
        f"20 % de ocupados, semilla de flota {p['semilla_flota']}. Cada lote se repitió {p['repeticiones']} veces con el "
        "recolector de basura desactivado y se reporta la mediana (robusta ante interrupciones del sistema operativo). "
        "Antes de medir se comparó cada respuesta con la búsqueda lineal. Escenario <i>intersecciones</i>: flota del "
        "RF-02 (muchos conductores comparten intersección); escenario <i>uniforme</i>: posiciones continuas al azar, "
        f"para aislar el efecto de los puntos coincidentes. <b>Rutas:</b> {r['parametros']['pares']} pares origen–destino "
        f"(semilla {r['parametros']['semilla']}); igualdad con networkx si |Δ| ≤ {r['parametros']['tolerancia_m']} m: ambos "
        "suman los mismos <i>length</i> en float64 y solo puede variar el orden de la suma (error relativo del orden de 10<super>-16</super>); "
        "una micra deja margen sin ocultar un tramo mal elegido, que cambiaría metros.")]

    filas = [["Conductores", "Lineal (ms)", "Quadtree (ms)", "Aceleración", "Distancias QT", "Idénticos",
              "Uniforme: QT (ms) / acel.", "H3 (ms)"]]
    for a, u in zip(inter, unif):
        filas.append([f"{a['conductores']:,}".replace(",", " "), num(a["lineal_ms_por_consulta"], 4),
                      num(a["quadtree_ms_por_consulta"], 4), f"×{num(a['aceleracion_quadtree'], 1)}",
                      num(a["distancias_promedio_quadtree"], 1), a["resultados_identicos_quadtree"],
                      f"{num(u['quadtree_ms_por_consulta'], 4)} / ×{num(u['aceleracion_quadtree'], 1)}",
                      num(a["h3_ms_por_consulta"], 4)])
    h += [KeepTogether([P("5. Resultados", "h1"), P("<b>Tabla 1.</b> Tiempo mediano por consulta k = 5 (escenario "
                                                    "intersecciones salvo la penúltima columna).", "nota"),
                        tabla(filas, [1.8 * cm, 1.8 * cm, 2 * cm, 1.8 * cm, 2 * cm, 1.7 * cm, 3.3 * cm, 1.5 * cm], e)]),
          Spacer(1, 4), figuras(["busqueda_tiempos.png", "busqueda_distancias.png"], 17.9 * cm, 5.0 * cm)]

    a300, a3k, a30k = inter
    h += [P(
        f"<b>Interpretación.</b> La búsqueda lineal crece proporcionalmente a n (×{num(a30k['lineal_ms_por_consulta'] / a300['lineal_ms_por_consulta'], 0)} "
        f"de 300 a 30 000), como predice O(n log k). El Quadtree crece mucho más despacio "
        f"(×{num(a30k['quadtree_ms_por_consulta'] / a300['quadtree_ms_por_consulta'], 1)} en el mismo rango): calcula en promedio "
        f"{num(a300['distancias_promedio_quadtree'], 0)}, {num(a3k['distancias_promedio_quadtree'], 0)} y "
        f"{num(a30k['distancias_promedio_quadtree'], 0)} distancias frente a 300, 3 000 y 30 000. Con 300 conductores la "
        f"ventaja es solo ×{num(a300['aceleracion_quadtree'], 1)}: la flota es tan pequeña que el costo de recorrer nodos y "
        "manejar dos heaps pesa casi tanto como recorrer la lista; el índice no es gratis y solo compensa al crecer n. "
        f"En el escenario de intersecciones con 30 000 conductores la aceleración (×{num(a30k['aceleracion_quadtree'], 0)}) es "
        f"menor que en el uniforme (×{num(unif[2]['aceleracion_quadtree'], 0)}) porque ~23 conductores comparten cada intersección: "
        "las cubetas coincidentes obligan a calcular todas sus distancias. No se observó ningún caso en que la lineal "
        "fuera más rápida, pero la brecha a 300 conductores es pequeña. "
        f"<b>Dijkstra:</b> {r['correccion']['pares_identicos']} distancias idénticas a networkx (diferencia máxima "
        f"{r['correccion']['diferencia_maxima_m']:.1e} m; también en un árbol completo desde un origen). El Dijkstra propio con "
        f"parada temprana tardó {num(r['tiempos']['dijkstra_propio_ms_por_par'], 3)} ms por par y networkx "
        f"{num(r['tiempos']['networkx_ms_por_par'], 3)} ms; la diferencia se explica porque networkx opera sobre el "
        "MultiDiGraph con diccionarios de atributos y nuestra lista de adyacencia ya trae el peso mínimo de cada par de nodos. "
        f"El árbol completo: {num(r['tiempos']['dijkstra_completo_propio_ms'], 2)} ms (propio) frente a "
        f"{num(r['tiempos']['dijkstra_completo_networkx_ms'], 2)} ms. En el despacho, un Dijkstra inverso único costó "
        f"{num(r['despacho']['dijkstra_inverso_unico_ms_por_solicitud'], 2)} ms frente a "
        f"{num(r['despacho']['k_dijkstra_directos_ms_por_solicitud'], 2)} ms de k Dijkstra directos.")]

    m_dif = [m for m in mapas if m["seleccionado"]["conductor_id"] != m["mas_cercano_en_linea_recta"]["conductor_id"]]
    ej = m_dif[0]
    h += [P(
        f"<b>Mapas (RF-07).</b> Se generaron {len(mapas)} mapas folium en <i>mapas/</i>. En {len(m_dif)} de ellos el "
        f"conductor asignado no es el más cercano en línea recta; p. ej., en «{ej['entrada']}» el más cercano estaba a "
        f"{num(ej['mas_cercano_en_linea_recta']['distancia_recta_m'], 0)} m con ETA de "
        f"{num(ej['mas_cercano_en_linea_recta']['eta_s'], 0)} s, y el elegido a {num(ej['seleccionado']['distancia_recta_m'], 0)} m "
        f"con ETA de {num(ej['seleccionado']['eta_s'], 0)} s.")]

    xa = r["a_estrella"]
    xb = x["reto_b"]
    filas_c = x["reto_c"]["filas"]
    h += [KeepTogether([P("6. Retos opcionales", "h1"), figuras(["a_estrella_nodos.png", "reto_c_asignacion.png"],
                                                                17.9 * cm, 4.6 * cm)]), P(
        f"<b>A. A*.</b> Heurística h(n) = Haversine(n, destino), admisible porque osmnx mide <i>length</i> como suma de "
        "arcos de círculo máximo con el mismo radio (6 371 009 m) y consistente por la desigualdad triangular esférica. "
        f"Mismo coste que Dijkstra en los {r['parametros']['pares']} pares y {num(xa['nodos_explorados_a_estrella_promedio'], 0)} "
        f"nodos expandidos de media frente a {num(xa['nodos_explorados_dijkstra_promedio'], 0)} "
        f"(−{num(xa['reduccion_porcentual'], 1)} %). "
        f"<b>B. Hora punta.</b> Congestión <i>simulada</i> (no hay datos de tráfico real): cada tramo cuesta "
        "longitud / velocidad libre del tipo de vía × factor horario con picos a las 8:00 y 18:30, más intenso en vías "
        f"principales. Cambia los pesos del grafo: tiempo medio de {num(xb['tiempo_medio_8_s'] / 60, 1)} min a las 8:00 frente a "
        f"{num(xb['tiempo_medio_15_s'] / 60, 1)} min a las 15:00; {xb['rutas_que_cambian']} de {xb['pares']} rutas cambian de "
        f"trazado y {xb['asignaciones_con_otro_conductor']} asignaciones eligen otro conductor (mapa "
        "<i>mapas/reto_b_congestion_8_vs_15.html</i>). "
        "<b>C. Varios pasajeros.</b> Matriz de ETA (unión de los k candidatos de cada pasajero, un Dijkstra inverso por "
        "pasajero) resuelta con el algoritmo húngaro propio, validado contra fuerza bruta; un conductor nunca recibe dos "
        f"solicitudes. Frente a la estrategia codiciosa por orden de llegada, la espera total baja "
        f"{num(filas_c[0]['mejora_media_porcentual'], 1)} % con {filas_c[0]['pasajeros']} pasajeros y "
        f"{num(filas_c[-1]['mejora_media_porcentual'], 1)} % con {filas_c[-1]['pasajeros']} (demanda concentrada, "
        f"{filas_c[-1]['ensayos']} ensayos): cuanto más compiten por los mismos conductores, más importa optimizar en conjunto. "
        f"<b>D. H3.</b> Índice experimental aislado en <i>experimental/</i> (resolución {p['resolucion_h3']}, arista media "
        "≈ 201 m) con búsqueda por anillos y una cota de parada conservadora. Dio resultados idénticos a la lineal "
        f"({inter[2]['resultados_identicos_h3']}), pero fue más lento que el Quadtree: {num(inter[2]['h3_ms_por_consulta'], 3)} ms "
        f"frente a {num(inter[2]['quadtree_ms_por_consulta'], 3)} ms con 30 000 conductores, porque la resolución es fija "
        "(una celda densa no se subdivide) y cada anillo exige llamadas a la librería.")]

    h += [P("7. Comparación con H3 de Uber y preguntas de investigación", "h1"), P(
        "<b>¿Por qué hexágonos?</b> En una malla hexagonal los seis vecinos de una celda comparten arista y sus centros "
        "están a la misma distancia; en una malla cuadrada hay ocho vecinos a dos distancias distintas (lado y diagonal). "
        "Por eso los anillos de hexágonos aproximan mejor un círculo, los suavizados y agregaciones por vecindad (oferta y "
        "demanda, precios dinámicos) no tienen sesgos direccionales y las celdas cubren el planeta con poca distorsión "
        "(H3 usa un icosaedro y necesita 12 pentágonos por resolución). El costo es que la jerarquía es aproximada: los "
        "7 hijos no cubren exactamente al padre, a diferencia del Quadtree, que es exacto y adaptativo a la densidad. "
        "<b>¿Qué pasa si muchos conductores se concentran en un punto?</b> Un Quadtree ingenuo se subdividiría sin fin, "
        "porque dividir nunca separa puntos idénticos. Nuestra política lo evita: profundidad máxima y cubetas para "
        "coordenadas idénticas (probado con 500 conductores en el mismo punto). El costo se traslada a la búsqueda: "
        "toda la cubeta debe examinarse, lo que explica la menor aceleración del escenario de intersecciones. "
        "<b>¿Por qué el más cercano en línea recta no siempre llega primero?</b> Porque el auto circula por calles con "
        "sentido único, manzanas, vías sin retorno y velocidades distintas: Miraflores tiene "
        "1 833 de 2 670 tramos de sentido único. Un conductor a una cuadra pero en contra del tránsito puede necesitar "
        "rodear la manzana. Por eso se toman k candidatos y se decide por la distancia real por calles (ETA).")]

    h += [P("8. Conclusiones y limitaciones", "h1"), P(
        "El índice espacial reduce el trabajo de cada búsqueda de O(n) a unas pocas decenas o cientos de distancias, con "
        "resultados exactos, y su ventaja crece con la flota; con flotas pequeñas la diferencia es modesta. La segunda "
        "etapa con Dijkstra propio es indispensable: el criterio de línea recta se equivoca con frecuencia en una red con "
        "muchos sentidos únicos. Limitaciones: la flota, la demanda y la congestión son simuladas; las posiciones se "
        "discretizan en intersecciones; elegir entre k candidatos no garantiza el ETA mínimo global; los tiempos dependen "
        "del equipo y deben reproducirse con <i>python -m benchmark.benchmark_busqueda</i>.")]

    refs = [
        "Boeing, G. (2017). OSMnx: New methods for acquiring, constructing, analyzing, and visualizing complex street networks. <i>Computers, Environment and Urban Systems</i>, 65, 126–139.",
        "Dijkstra, E. W. (1959). A note on two problems in connexion with graphs. <i>Numerische Mathematik</i>, 1, 269–271.",
        "Finkel, R. A. y Bentley, J. L. (1974). Quad trees: a data structure for retrieval on composite keys. <i>Acta Informatica</i>, 4, 1–9.",
        "Hart, P. E., Nilsson, N. J. y Raphael, B. (1968). A formal basis for the heuristic determination of minimum cost paths. <i>IEEE Trans. Systems Science and Cybernetics</i>, 4(2), 100–107.",
        "Hjaltason, G. R. y Samet, H. (1999). Distance browsing in spatial databases. <i>ACM Transactions on Database Systems</i>, 24(2), 265–318.",
        "Kuhn, H. W. (1955). The Hungarian method for the assignment problem. <i>Naval Research Logistics Quarterly</i>, 2, 83–97.",
        "Samet, H. (1984). The quadtree and related hierarchical data structures. <i>ACM Computing Surveys</i>, 16(2), 187–260.",
        "Sinnott, R. W. (1984). Virtues of the Haversine. <i>Sky and Telescope</i>, 68(2), 159.",
        "Uber Technologies (2018). H3: Uber's Hexagonal Hierarchical Spatial Index. https://www.uber.com/blog/h3/ · Documentación: https://h3geo.org/docs/",
        "Datos viales © colaboradores de OpenStreetMap, licencia ODbL. https://www.openstreetmap.org/copyright",
    ]
    h += [P("Referencias", "h1")] + [P(t, "nota") for t in refs]

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont(FUENTE, 7.5)
        canvas.setFillColor(GRIS)
        canvas.drawString(1.6 * cm, 1.0 * cm, "LimaGo · Informe técnico · Proyecto Integrador N.° 2")
        canvas.drawRightString(A4[0] - 1.6 * cm, 1.0 * cm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(salida), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm,
                            bottomMargin=1.6 * cm, title="LimaGo — Informe técnico", author="Equipo LimaGo",
                            subject="Asignación del conductor más cercano")
    doc.build(h, onFirstPage=pie, onLaterPages=pie)


if __name__ == "__main__":
    destino = RAIZ / "informe.pdf"
    construir(destino)
    print(f"Informe generado: {destino}")
