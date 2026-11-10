"""RF-01 — Descarga, almacenamiento local y carga de la red vial.

osmnx y networkx se usan **solo** para descargar, guardar y cargar el grafo
(lo permite la guía). Ningún cálculo de rutas de la solución usa sus
funciones de ruta más corta: el grafo se convierte a la estructura propia
:class:`algoritmos.grafo.GrafoVial`.

Uso desde la línea de comandos::

    python -m datos.red_vial            # descarga solo si no existe el archivo
    python -m datos.red_vial --forzar   # vuelve a descargar
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from config.ajustes import Ajustes, ajustes_academicos, cargar_ajustes

registro = logging.getLogger("limago.red_vial")


def descargar_red(ajustes: Ajustes, reintentos_por_servidor: int = 2):
    """Descarga la red vial dirigida del lugar configurado.

    Se prueban varios servidores Overpass en orden. ``simplify=True`` deja como
    nodos solo intersecciones y extremos de calle; ``retain_all=False`` conserva
    el mayor componente conectado. osmnx calcula el atributo ``length`` (metros)
    y ``oneway``; el grafo resultante es un ``MultiDiGraph`` que respeta el
    sentido de circulación.
    """
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.cache_folder = str(Path(ajustes.ruta_grafo).parent / "cache_osmnx")
    ox.settings.requests_timeout = 180
    ox.settings.http_user_agent = ajustes.geocodificador_agente
    ultimo_error: Exception | None = None
    for url in ajustes.overpass_urls:
        ox.settings.overpass_url = url
        for intento in range(1, reintentos_por_servidor + 1):
            try:
                registro.info("Descargando '%s' desde %s (intento %d)", ajustes.lugar, url, intento)
                return ox.graph_from_place(
                    ajustes.lugar, network_type=ajustes.tipo_red, simplify=True, retain_all=False
                )
            except Exception as error:  # noqa: BLE001 - se reintenta con otro servidor
                ultimo_error = error
                registro.warning("Fallo con %s: %s", url, error)
                time.sleep(2 * intento)
    raise RuntimeError(f"No se pudo descargar la red vial: {ultimo_error}")


# Filtro "drive" de osmnx (osmnx._overpass._get_network_filter("drive")), aplicado en Python
# con la misma semántica que Overpass: expresiones regulares sin anclar y sensibles a mayúsculas.
FILTRO_DRIVE_EXCLUSIONES = {
    "area": r"yes",
    "access": r"private",
    "highway": r"abandoned|bridleway|bus_guideway|construction|corridor|cycleway|elevator|escalator|footway|no|"
               r"path|pedestrian|planned|platform|proposed|raceway|razed|rest_area|service|services|steps|track",
    "motor_vehicle": r"no",
    "motorcar": r"no",
    "service": r"alley|driveway|emergency_access|parking|parking_aisle|private",
}


def es_via_vehicular(etiquetas: dict[str, str]) -> bool:
    """``True`` si una vía OSM cumple el filtro ``network_type="drive"`` de osmnx."""
    import re

    if "highway" not in etiquetas:
        return False
    return not any(
        clave in etiquetas and re.search(patron, etiquetas[clave])
        for clave, patron in FILTRO_DRIVE_EXCLUSIONES.items()
    )


def descargar_red_api_osm(ajustes: Ajustes, tamano_recuadro: float = 0.008, pausa_s: float = 1.0):
    """Ruta alternativa de descarga cuando los servidores Overpass no responden.

    Descarga el XML oficial de OpenStreetMap por recuadros desde
    ``https://api.openstreetmap.org/api/0.6/map``, conserva solo las vías que
    cumplen el filtro ``drive`` de osmnx y construye el grafo con
    ``osmnx.graph_from_xml``. Después aplica **los mismos pasos** que
    ``osmnx.graph_from_polygon``: polígono del distrito con 500 m de margen,
    truncado, mayor componente débilmente conexa, simplificación, truncado al
    polígono exacto y nueva limpieza de componentes.
    """
    import xml.etree.ElementTree as ET

    import osmnx as ox
    import requests
    from osmnx import projection, simplification, truncate

    ox.settings.http_user_agent = ajustes.geocodificador_agente
    poligono = ox.geocode_to_gdf(ajustes.lugar).geometry.iloc[0]
    poligono_proj, crs_utm = projection.project_geometry(poligono)
    poligono_buffer, _ = projection.project_geometry(poligono_proj.buffer(500), crs=crs_utm, to_latlong=True)
    lon_min, lat_min, lon_max, lat_max = poligono_buffer.bounds

    nodos: dict[str, ET.Element] = {}
    vias: dict[str, ET.Element] = {}
    sesion = requests.Session()
    sesion.headers["User-Agent"] = ajustes.geocodificador_agente
    lat = lat_min
    while lat < lat_max:
        lon = lon_min
        while lon < lon_max:
            caja = f"{lon:.6f},{lat:.6f},{min(lon + tamano_recuadro, lon_max):.6f},{min(lat + tamano_recuadro, lat_max):.6f}"
            registro.info("API OSM: recuadro %s", caja)
            respuesta = sesion.get("https://api.openstreetmap.org/api/0.6/map", params={"bbox": caja}, timeout=180)
            respuesta.raise_for_status()
            raiz = ET.fromstring(respuesta.content)
            for elemento in raiz:
                if elemento.tag == "node":
                    nodos[elemento.get("id")] = elemento
                elif elemento.tag == "way":
                    etiquetas = {t.get("k"): t.get("v") for t in elemento.findall("tag")}
                    if es_via_vehicular(etiquetas):
                        vias[elemento.get("id")] = elemento
            time.sleep(pausa_s)
            lon += tamano_recuadro
        lat += tamano_recuadro

    usados = {nd.get("ref") for via in vias.values() for nd in via.findall("nd")}
    salida = ET.Element("osm", version="0.6", generator="LimaGo (API OSM 0.6)")
    for identificador in sorted(usados & nodos.keys(), key=int):
        salida.append(nodos[identificador])
    for identificador in sorted(vias, key=int):
        salida.append(vias[identificador])
    ruta_xml = Path(ajustes.ruta_grafo).with_suffix(".osm")
    ET.ElementTree(salida).write(ruta_xml, encoding="utf-8", xml_declaration=True)
    registro.info("XML vehicular guardado en %s (%d vías, %d nodos)", ruta_xml, len(vias), len(usados))

    grafo = ox.graph_from_xml(ruta_xml, bidirectional=False, simplify=False, retain_all=True)
    grafo = truncate.truncate_graph_polygon(grafo, poligono_buffer, truncate_by_edge=False)
    grafo = truncate.largest_component(grafo, strongly=False)
    grafo = simplification.simplify_graph(grafo)
    grafo = truncate.truncate_graph_polygon(grafo, poligono, truncate_by_edge=False)
    grafo = truncate.largest_component(grafo, strongly=False)
    return grafo


def guardar_limite(ajustes: Ajustes) -> Path:
    """Guarda el polígono oficial del distrito (OSM vía Nominatim) como GeoJSON para la web."""
    import osmnx as ox

    ox.settings.http_user_agent = ajustes.geocodificador_agente
    ruta = Path(ajustes.ruta_grafo).with_name("limite_distrito.geojson")
    ox.geocode_to_gdf(ajustes.lugar)[["geometry", "display_name"]].to_file(ruta, driver="GeoJSON")
    return ruta


def guardar_red(grafo, ruta: Path) -> None:
    import osmnx as ox

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(grafo, filepath=ruta)


def cargar_grafo_networkx(ajustes: Ajustes | None = None, forzar_descarga: bool = False):
    """Devuelve el ``MultiDiGraph`` de osmnx, descargándolo solo si hace falta."""
    import osmnx as ox

    ajustes = ajustes or cargar_ajustes()
    ruta = Path(ajustes.ruta_grafo)
    if ruta.exists() and not forzar_descarga:
        registro.info("Cargando red vial local: %s", ruta)
        return ox.load_graphml(ruta)
    try:
        grafo = descargar_red(ajustes)
    except RuntimeError as error:
        registro.warning("Overpass no disponible (%s); se usa la API oficial de OSM", error)
        grafo = descargar_red_api_osm(ajustes)
    guardar_red(grafo, ruta)
    registro.info("Red guardada en %s", ruta)
    return grafo


def cargar_red_vial(ajustes: Ajustes | None = None, forzar_descarga: bool = False):
    """Carga la red del escenario y la convierte a la estructura propia ``GrafoVial``.

    * ``.graphml`` (Miraflores, RF-01): se lee con osmnx y se convierte.
    * ``.npz`` (Lima Metropolitana, V3): formato compacto propio; si falta, se indica
      cómo prepararlo con ``python -m datos.red_metropolitana``.
    """
    from algoritmos.grafo import GrafoVial

    ajustes = ajustes or cargar_ajustes()
    ruta = Path(ajustes.ruta_grafo)
    if ruta.suffix == ".npz":
        if not ruta.exists():
            raise FileNotFoundError(f"No existe {ruta}. Prepárela con: python -m datos.red_metropolitana")
        return GrafoVial.cargar_compacto(ruta)
    return GrafoVial.desde_networkx(cargar_grafo_networkx(ajustes, forzar_descarga))


def _principal() -> None:
    parser = argparse.ArgumentParser(description="Prepara la red vial de LimaGo")
    parser.add_argument("--forzar", action="store_true", help="vuelve a descargar")
    parser.add_argument("--fuente", choices=["auto", "overpass", "api-osm"], default="auto",
                        help="auto: Overpass y, si falla, API oficial de OSM")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ajustes = ajustes_academicos()  # esta herramienta prepara la red académica de Miraflores (RF-01)
    if args.fuente == "api-osm" and (args.forzar or not Path(ajustes.ruta_grafo).exists()):
        guardar_red(descargar_red_api_osm(ajustes), Path(ajustes.ruta_grafo))
    elif args.fuente == "overpass" and (args.forzar or not Path(ajustes.ruta_grafo).exists()):
        guardar_red(descargar_red(ajustes), Path(ajustes.ruta_grafo))
    red = cargar_red_vial(ajustes, forzar_descarga=args.forzar and args.fuente == "auto")
    if args.forzar or not Path(ajustes.ruta_grafo).with_name("limite_distrito.geojson").exists():
        guardar_limite(ajustes)
    print(red.resumen())


if __name__ == "__main__":
    _principal()
