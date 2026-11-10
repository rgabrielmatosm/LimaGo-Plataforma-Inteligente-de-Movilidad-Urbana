"""V3 — Preparación reproducible de la red vial de Lima Metropolitana.

Fuentes (todas de OpenStreetMap, © colaboradores de OSM, ODbL):

1. **Límite oficial**: relación OSM 12933390 «Lima Metropolitan Area»
   (provincia de Lima + Callao, ~2 850 km²), obtenida con
   ``osmnx.geocode_to_gdf`` (Nominatim).
2. **Núcleo de la red**: extracto «Lima» de BBBike
   (``download.bbbike.org/osm/bbbike/Lima/Lima.osm.pbf``, recuadro
   lat −12,417…−11,7 / lon −77,263…−76,556), leído con ``osmium``.
3. **Franjas fuera del extracto** (extremo norte y sur del área): API oficial
   de OSM (``/api/0.6/map``) por recuadros de 0,04°, divididos si la API
   responde que hay demasiados datos. Son ~30 peticiones con pausa de 1 s.

Los servidores Overpass y Geofabrik no respondían desde el entorno de desarrollo;
por eso se usa esta combinación, documentada en ``datos/README.md``.

Después se aplican **los mismos pasos que** ``osmnx.graph_from_polygon``:
filtro ``drive`` de osmnx, polígono con 500 m de margen, truncado, mayor
componente débilmente conexa, simplificación, truncado al polígono exacto y
nueva limpieza. El resultado se guarda en formato compacto propio
(``datos/lima/lima_metropolitana.npz``) para cargarlo en segundos.

    python -m datos.red_metropolitana            # prepara solo lo que falte
    python -m datos.red_metropolitana --forzar   # vuelve a descargar todo
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from config.ajustes import RAIZ_PROYECTO
from datos.red_vial import es_via_vehicular

registro = logging.getLogger("limago.red_metropolitana")

CARPETA = RAIZ_PROYECTO / "datos" / "lima"
RUTA_PBF = RAIZ_PROYECTO / "datos" / "fuentes" / "Lima.bbbike.osm.pbf"
URL_PBF = "https://download.bbbike.org/osm/bbbike/Lima/Lima.osm.pbf"
RECUADRO_PBF = (-77.263, -12.417, -76.556, -11.7)  # lon_min, lat_min, lon_max, lat_max
RELACION_LIMA = 12933390
AGENTE = "LimaGo-Proyecto-Academico/1.0"
RUTA_COMPACTA = CARPETA / "lima_metropolitana.npz"
RUTA_LIMITE = CARPETA / "limite_lima_metropolitana.geojson"
RUTA_DISTRITOS = CARPETA / "distritos.geojson"
RUTA_INFORME = CARPETA / "preparacion.json"


def progreso(paso: int, total: int, mensaje: str) -> None:
    """Indicador de progreso legible en la terminal y en los logs de Docker."""
    print(f"[{paso}/{total}] {mensaje}", flush=True)


# ----------------------------------------------------------------- límite
def obtener_poligono():
    import osmnx as ox

    ox.settings.http_user_agent = AGENTE
    gdf = ox.geocode_to_gdf(f"R{RELACION_LIMA}", by_osmid=True)
    CARPETA.mkdir(parents=True, exist_ok=True)
    gdf[["geometry", "display_name"]].to_file(RUTA_LIMITE, driver="GeoJSON")
    return gdf.geometry.iloc[0]


def poligono_con_margen(poligono, metros: float = 500):
    from osmnx import projection

    proyectado, crs = projection.project_geometry(poligono)
    ampliado, _ = projection.project_geometry(proyectado.buffer(metros), crs=crs, to_latlong=True)
    return ampliado


# ------------------------------------------------------------ núcleo (PBF)
def descargar_pbf(forzar: bool = False) -> Path:
    import requests

    if RUTA_PBF.exists() and not forzar:
        return RUTA_PBF
    RUTA_PBF.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(URL_PBF, headers={"User-Agent": AGENTE}, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        leido = 0
        with open(RUTA_PBF, "wb") as f:
            for bloque in r.iter_content(1 << 20):
                f.write(bloque)
                leido += len(bloque)
                if total:
                    print(f"\r      descargado {leido / total:5.1%}", end="", flush=True)
    print()
    return RUTA_PBF


def leer_vias_pbf(ruta: Path) -> tuple[dict, dict]:
    """Vías vehiculares (filtro ``drive`` de osmnx) y sus nodos, leídas del PBF."""
    import osmium

    nodos: dict[int, tuple[float, float]] = {}
    vias: dict[int, dict] = {}
    for objeto in osmium.FileProcessor(str(ruta)).with_locations().with_filter(osmium.filter.KeyFilter("highway")):
        if not objeto.is_way():
            continue
        etiquetas = {t.k: t.v for t in objeto.tags}
        if not es_via_vehicular(etiquetas):
            continue
        referencias = []
        for n in objeto.nodes:
            if not n.location.valid():
                continue
            nodos[n.ref] = (n.location.lat, n.location.lon)
            referencias.append(n.ref)
        if len(referencias) >= 2:
            vias[objeto.id] = {"nodos": referencias, "etiquetas": etiquetas}
    return nodos, vias


# ------------------------------------------------- franjas (API de OSM)
def recuadros_franjas(poligono_ampliado, tamano: float = 0.04) -> list[tuple[float, float, float, float]]:
    from shapely.geometry import box

    resto = poligono_ampliado.difference(box(*RECUADRO_PBF))
    if resto.is_empty:
        return []
    x0, y0, x1, y1 = resto.bounds
    cajas = []
    y = y0
    while y < y1:
        x = x0
        while x < x1:
            caja = (x, y, min(x + tamano, x1), min(y + tamano, y1))
            if box(*caja).intersects(resto):
                cajas.append(caja)
            x += tamano
        y += tamano
    return cajas


def descargar_recuadro_api(sesion, caja, nodos: dict, vias: dict, pausa: float = 1.0) -> int:
    """Descarga un recuadro; si la API indica demasiados datos (HTTP 400) lo divide en cuatro."""
    respuesta = sesion.get("https://api.openstreetmap.org/api/0.6/map",
                           params={"bbox": ",".join(f"{c:.6f}" for c in caja)}, timeout=180)
    time.sleep(pausa)
    if respuesta.status_code == 400 and (caja[2] - caja[0]) > 0.005:
        xm, ym = (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2
        return sum(descargar_recuadro_api(sesion, c, nodos, vias, pausa) for c in (
            (caja[0], caja[1], xm, ym), (xm, caja[1], caja[2], ym),
            (caja[0], ym, xm, caja[3]), (xm, ym, caja[2], caja[3])))
    respuesta.raise_for_status()
    raiz = ET.fromstring(respuesta.content)
    for e in raiz:
        if e.tag == "node":
            nodos[int(e.get("id"))] = (float(e.get("lat")), float(e.get("lon")))
    for e in raiz:
        if e.tag == "way":
            etiquetas = {t.get("k"): t.get("v") for t in e.findall("tag")}
            if es_via_vehicular(etiquetas):
                referencias = [int(nd.get("ref")) for nd in e.findall("nd") if int(nd.get("ref")) in nodos]
                if len(referencias) >= 2:
                    vias.setdefault(int(e.get("id")), {"nodos": referencias, "etiquetas": etiquetas})
    return 1


# --------------------------------------------------------------- grafo
def escribir_xml(nodos: dict, vias: dict, ruta: Path) -> None:
    usados = {n for v in vias.values() for n in v["nodos"]}
    with open(ruta, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="LimaGo V3">\n')
        for n in sorted(usados):
            lat, lon = nodos[n]
            f.write(f'<node id="{n}" lat="{lat:.7f}" lon="{lon:.7f}"/>\n')
        for identificador in sorted(vias):
            via = vias[identificador]
            f.write(f'<way id="{identificador}">')
            f.write("".join(f'<nd ref="{n}"/>' for n in via["nodos"]))
            for k, v in via["etiquetas"].items():
                f.write(f'<tag k="{_xml(k)}" v="{_xml(v)}"/>')
            f.write("</way>\n")
        f.write("</osm>\n")


def _xml(texto: str) -> str:
    return (texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def construir_grafo(ruta_xml: Path, poligono, poligono_ampliado):
    """Misma secuencia que ``osmnx.graph_from_polygon`` (ver docstring del módulo)."""
    import osmnx as ox
    from osmnx import simplification, truncate

    grafo = ox.graph_from_xml(ruta_xml, bidirectional=False, simplify=False, retain_all=True)
    grafo = truncate.truncate_graph_polygon(grafo, poligono_ampliado, truncate_by_edge=False)
    grafo = truncate.largest_component(grafo, strongly=False)
    grafo = simplification.simplify_graph(grafo)
    grafo = truncate.truncate_graph_polygon(grafo, poligono, truncate_by_edge=False)
    return truncate.largest_component(grafo, strongly=False)


# ------------------------------------------------------------ distritos
def extraer_distritos(ruta_pbf: Path, poligono) -> list[dict]:
    """Límites distritales (admin_level 8) contenidos en el extracto, simplificados (~20 m)."""
    import osmium
    from shapely import wkb

    fabrica = osmium.geom.WKBFactory()
    distritos = []
    procesador = osmium.FileProcessor(str(ruta_pbf)).with_areas(osmium.filter.KeyFilter("boundary"))
    for objeto in procesador:
        if not objeto.is_area() or objeto.from_way():
            continue
        etiquetas = {t.k: t.v for t in objeto.tags}
        if etiquetas.get("boundary") != "administrative" or etiquetas.get("admin_level") != "8" or "name" not in etiquetas:
            continue
        try:
            geometria = wkb.loads(fabrica.create_multipolygon(objeto), hex=True)
        except Exception:  # noqa: BLE001 - multipolígono incompleto en el borde del extracto
            continue
        if not geometria.is_valid or geometria.representative_point().within(poligono) is False:
            continue
        distritos.append({"nombre": etiquetas["name"], "relacion": objeto.orig_id(),
                          "geometria": geometria.simplify(0.0002, preserve_topology=True)})
    return distritos


#: 43 distritos de la provincia de Lima + 7 de la Provincia Constitucional del Callao.
DISTRITOS_ESPERADOS = (
    "Ancón", "Ate", "Barranco", "Breña", "Carabayllo", "Chaclacayo", "Chorrillos", "Cieneguilla", "Comas",
    "El Agustino", "Independencia", "Jesús María", "La Molina", "La Victoria", "Lima", "Lince", "Los Olivos",
    "Lurigancho", "Lurín", "Magdalena del Mar", "Miraflores", "Pachacámac", "Pucusana", "Pueblo Libre",
    "Puente Piedra", "Punta Hermosa", "Punta Negra", "Rímac", "San Bartolo", "San Borja", "San Isidro",
    "San Juan de Lurigancho", "San Juan de Miraflores", "San Luis", "San Martín de Porres", "San Miguel",
    "Santa Anita", "Santa María del Mar", "Santa Rosa", "Santiago de Surco", "Surquillo", "Villa El Salvador",
    "Villa María del Triunfo",
    "Callao", "Bellavista", "Carmen de La Legua-Reynoso", "La Perla", "La Punta", "Ventanilla", "Mi Perú",
)


def completar_distritos(distritos: list[dict], poligono) -> list[str]:
    """Los distritos que cruzan el borde del extracto llegan incompletos: se piden a Nominatim (1 consulta c/u)."""
    import osmnx as ox

    ox.settings.http_user_agent = AGENTE
    presentes = {d["nombre"] for d in distritos}
    agregados = []
    for nombre in DISTRITOS_ESPERADOS:
        if nombre in presentes:
            continue
        provincia = "Callao" if nombre in ("Ventanilla", "Mi Perú", "La Punta", "La Perla", "Bellavista",
                                           "Carmen de La Legua-Reynoso") else "Lima"
        gdf = None
        for consulta in (f"{nombre}, Provincia de {provincia}, Peru", f"{nombre}, {provincia}, Peru"):
            try:
                candidato = ox.geocode_to_gdf(consulta)
            except Exception:  # noqa: BLE001 - se prueba la siguiente forma de la consulta
                time.sleep(1)
                continue
            geometria = candidato.geometry.iloc[0]
            if geometria.geom_type in ("Polygon", "MultiPolygon") and geometria.representative_point().within(poligono):
                gdf = candidato
                break
            time.sleep(1)
        if gdf is None:
            print(f"      ! no se pudo completar el distrito {nombre}")
            continue
        geometria = gdf.geometry.iloc[0]
        distritos.append({"nombre": nombre, "relacion": int(gdf["osm_id"].iloc[0]),
                          "geometria": geometria.simplify(0.0002, preserve_topology=True)})
        agregados.append(nombre)
        time.sleep(1)
    return agregados


def guardar_distritos(distritos: list[dict]) -> None:
    from shapely.geometry import mapping

    caracteristicas = [{"type": "Feature", "properties": {"nombre": d["nombre"], "relacion_osm": d["relacion"]},
                        "geometry": mapping(d["geometria"])} for d in sorted(distritos, key=lambda d: d["nombre"])]
    RUTA_DISTRITOS.write_text(json.dumps({"type": "FeatureCollection", "features": caracteristicas},
                                         ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------- principal
def preparar(forzar: bool = False) -> dict:
    from algoritmos.grafo import GrafoVial

    total = 7
    inicio = time.time()
    CARPETA.mkdir(parents=True, exist_ok=True)
    progreso(1, total, "Límite oficial de Lima Metropolitana (OSM relación 12933390)…")
    poligono = obtener_poligono()
    ampliado = poligono_con_margen(poligono)
    progreso(2, total, "Extracto de OpenStreetMap del núcleo de Lima (BBBike)…")
    ruta_pbf = descargar_pbf(forzar)
    progreso(3, total, "Leyendo vías vehiculares del extracto…")
    nodos, vias = leer_vias_pbf(ruta_pbf)
    vias_pbf = len(vias)
    print(f"      {vias_pbf:,} vías y {len(nodos):,} nodos")
    cajas = recuadros_franjas(ampliado)
    progreso(4, total, f"Franjas norte y sur desde la API oficial de OSM ({len(cajas)} recuadros)…")
    import requests

    sesion = requests.Session()
    sesion.headers["User-Agent"] = AGENTE
    peticiones = 0
    for i, caja in enumerate(cajas, 1):
        peticiones += descargar_recuadro_api(sesion, caja, nodos, vias)
        print(f"\r      recuadro {i}/{len(cajas)}", end="", flush=True)
    print(f"\n      +{len(vias) - vias_pbf:,} vías nuevas en las franjas ({peticiones} peticiones)")
    progreso(5, total, "Construyendo el grafo con la secuencia de osmnx (puede tardar varios minutos)…")
    ruta_xml = CARPETA / "lima_drive.osm"
    escribir_xml(nodos, vias, ruta_xml)
    grafo_nx = construir_grafo(ruta_xml, poligono, ampliado)
    progreso(6, total, "Convirtiendo al grafo propio y guardando en formato compacto…")
    grafo = GrafoVial.desde_networkx(grafo_nx)
    grafo.guardar_compacto(RUTA_COMPACTA)
    progreso(7, total, "Límites distritales…")
    distritos = extraer_distritos(ruta_pbf, poligono)
    agregados = completar_distritos(distritos, poligono)
    print(f"      {len(distritos)} distritos ({len(agregados)} completados con Nominatim: {', '.join(agregados)})")
    guardar_distritos(distritos)
    informe = {
        "fecha_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fuentes": {"limite": f"OSM relación {RELACION_LIMA}", "nucleo": URL_PBF,
                    "franjas": "https://api.openstreetmap.org/api/0.6/map", "recuadros_franjas": len(cajas),
                    "peticiones_api": peticiones},
        "nodos": grafo.num_nodos, "aristas": grafo.num_aristas,
        "km_de_tramos": round(sum(d.longitud for d in grafo.aristas.values()) / 1000, 1),
        "componente_fuerte": len(grafo.componente_principal()),
        "distritos": len(distritos), "distritos_completados_nominatim": agregados, "segundos": round(time.time() - inicio, 1),
        "tamano_npz_mb": round(RUTA_COMPACTA.stat().st_size / 1e6, 1),
    }
    RUTA_INFORME.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(informe, ensure_ascii=False, indent=2))
    return informe


def _principal() -> None:
    parser = argparse.ArgumentParser(description="Prepara la red vial de Lima Metropolitana")
    parser.add_argument("--forzar", action="store_true", help="vuelve a descargar y reconstruir todo")
    parser.add_argument("--solo-distritos", action="store_true", help="rehace solo los límites distritales")
    args = parser.parse_args()
    if args.solo_distritos:
        import geopandas as gpd

        poligono = gpd.read_file(RUTA_LIMITE).geometry.iloc[0]
        distritos = extraer_distritos(descargar_pbf(), poligono)
        agregados = completar_distritos(distritos, poligono)
        guardar_distritos(distritos)
        informe = json.loads(RUTA_INFORME.read_text(encoding="utf-8"))
        informe.update(distritos=len(distritos), distritos_completados_nominatim=agregados)
        RUTA_INFORME.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{len(distritos)} distritos; completados con Nominatim: {agregados}")
        return
    logging.basicConfig(level=logging.WARNING)
    if RUTA_COMPACTA.exists() and not args.forzar:
        print(f"La red ya está preparada: {RUTA_COMPACTA} (use --forzar para rehacerla)")
        sys.exit(0)
    preparar(args.forzar)


if __name__ == "__main__":
    _principal()
