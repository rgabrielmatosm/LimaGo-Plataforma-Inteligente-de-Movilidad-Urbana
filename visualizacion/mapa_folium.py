"""RF-07 — Mapas interactivos HTML con folium.

Cada mapa muestra: pasajero, conductores coloreados por estado, los k
candidatos (con distancia recta, distancia por calles y ETA), el conductor
seleccionado y la ruta asignada sobre la geometría real de las calles.
"""
from __future__ import annotations

from pathlib import Path

import folium

from simulacion.despachador import Despachador, ResultadoAsignacion

COLORES_ESTADO = {"disponible": "#16a34a", "en_camino": "#f59e0b", "en_viaje": "#dc2626"}
NOMBRES_ESTADO = {"disponible": "Disponible", "en_camino": "Ocupado (en camino)", "en_viaje": "Ocupado (en viaje)"}


def _leyenda(k: int) -> str:
    filas = "".join(
        f'<div><span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:{color};margin-right:6px"></span>{NOMBRES_ESTADO[estado]}</div>'
        for estado, color in COLORES_ESTADO.items()
    )
    return f"""
    <div style="position:fixed;bottom:24px;left:24px;z-index:9999;background:white;padding:10px 14px;
                border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.25);font:13px/1.5 system-ui,sans-serif">
      <b>Leyenda</b>{filas}
      <div><span style="display:inline-block;width:12px;height:12px;border:3px solid #2563eb;border-radius:50%;
           margin-right:6px"></span>Candidato (k = {k})</div>
      <div><span style="color:#7c3aed;font-weight:bold">★</span> Conductor seleccionado (menor ETA)</div>
      <div><span style="display:inline-block;width:18px;height:4px;background:#7c3aed;margin-right:6px;
           vertical-align:middle"></span>Ruta asignada por calles</div>
      <div>🧍 Pasajero</div>
    </div>"""


def generar_mapa_asignacion(despachador: Despachador, resultado: ResultadoAsignacion, ruta_salida: Path,
                            titulo: str = "", dibujar_red: bool = True) -> Path:
    pasajero = resultado.pasajero
    mapa = folium.Map(location=[pasajero.lat, pasajero.lon], zoom_start=16, tiles="OpenStreetMap",
                      control_scale=True)
    if titulo:
        mapa.get_root().html.add_child(folium.Element(
            f'<div style="position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:9999;'
            f'background:white;padding:8px 16px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.25);'
            f'font:600 15px system-ui,sans-serif">{titulo}</div>'))

    if dibujar_red:
        capa_red = folium.FeatureGroup(name="Red vial (OSM)", show=False)
        for (u, v), datos in despachador.grafo.aristas.items():
            puntos = datos.geometria or [despachador.grafo.coordenadas(u), despachador.grafo.coordenadas(v)]
            folium.PolyLine(puntos, color="#64748b", weight=1, opacity=0.5).add_to(capa_red)
        capa_red.add_to(mapa)

    ids_candidatos = {c.conductor_id for c in resultado.candidatos}
    capas = {estado: folium.FeatureGroup(name=NOMBRES_ESTADO[estado]) for estado in COLORES_ESTADO}
    for conductor in despachador.conductores.values():
        if conductor.id in ids_candidatos:
            continue
        estado = conductor.estado.value
        folium.CircleMarker(
            [conductor.lat, conductor.lon], radius=4, color=COLORES_ESTADO[estado], fill=True,
            fill_opacity=0.85, weight=1, tooltip=f"{conductor.codigo} · {NOMBRES_ESTADO[estado]}",
        ).add_to(capas[estado])
    for capa in capas.values():
        capa.add_to(mapa)

    capa_candidatos = folium.FeatureGroup(name=f"Candidatos (k = {len(resultado.candidatos)})")
    for posicion, candidato in enumerate(sorted(resultado.candidatos, key=lambda c: c.distancia_recta_m), start=1):
        conductor = despachador.conductores[candidato.conductor_id]
        eta = "inaccesible" if not candidato.alcanzable else f"{candidato.eta_s / 60:.1f} min"
        calles = "—" if not candidato.alcanzable else f"{candidato.distancia_calles_m:.0f} m"
        texto = (f"<b>{conductor.codigo}</b><br>#{posicion} en línea recta: {candidato.distancia_recta_m:.0f} m"
                 f"<br>Por calles: {calles}<br>ETA: {eta}")
        if resultado.seleccionado and candidato.conductor_id == resultado.seleccionado.conductor_id:
            folium.Marker([conductor.lat, conductor.lon], tooltip=f"Seleccionado: {conductor.codigo}",
                          popup=folium.Popup(texto + "<br><b>Seleccionado (menor ETA)</b>", max_width=260),
                          icon=folium.Icon(color="purple", icon="star")).add_to(capa_candidatos)
        else:
            folium.CircleMarker([conductor.lat, conductor.lon], radius=9, color="#2563eb", weight=3,
                                fill=True, fill_color=COLORES_ESTADO["disponible"], fill_opacity=0.9,
                                popup=folium.Popup(texto, max_width=260),
                                tooltip=f"Candidato {conductor.codigo}").add_to(capa_candidatos)
    capa_candidatos.add_to(mapa)

    if resultado.ruta_coordenadas:
        folium.PolyLine(resultado.ruta_coordenadas, color="#7c3aed", weight=6, opacity=0.85,
                        tooltip="Ruta asignada").add_to(mapa)

    detalle = resultado.mensaje
    if resultado.seleccionado:
        detalle += (f"<br>ETA {resultado.seleccionado.eta_s / 60:.1f} min · "
                    f"{resultado.seleccionado.distancia_calles_m:.0f} m por calles")
    folium.Marker([pasajero.lat, pasajero.lon], tooltip="Pasajero",
                  popup=folium.Popup(f"<b>Pasajero</b><br>{pasajero.direccion}<br>{detalle}", max_width=300),
                  icon=folium.Icon(color="black", icon="user")).add_to(mapa)

    mapa.get_root().html.add_child(folium.Element(_leyenda(len(resultado.candidatos))))
    folium.LayerControl(collapsed=True).add_to(mapa)
    limites = [[pasajero.lat, pasajero.lon]] + [
        [despachador.conductores[c.conductor_id].lat, despachador.conductores[c.conductor_id].lon]
        for c in resultado.candidatos]
    if len(limites) > 1:
        mapa.fit_bounds(limites, padding=(40, 40))
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    mapa.save(str(ruta_salida))
    return ruta_salida


def generar_mapa_comparacion_rutas(grafo, rutas: list[tuple[str, list[int], str]], ruta_salida: Path,
                                   titulo: str = "", marcadores: list[tuple[float, float, str]] | None = None) -> Path:
    """Mapa con varias rutas superpuestas (Retos A y B): ``rutas = [(nombre, nodos, color), ...]``."""
    todos = [grafo.coordenadas(n) for _, ruta, _ in rutas for n in ruta]
    centro = todos[0] if todos else (-12.12, -77.03)
    mapa = folium.Map(location=centro, zoom_start=15, control_scale=True)
    for nombre, ruta, color in rutas:
        folium.PolyLine(grafo.geometria_ruta(ruta), color=color, weight=6, opacity=0.8, tooltip=nombre).add_to(
            folium.FeatureGroup(name=nombre).add_to(mapa))
    for lat, lon, texto in marcadores or []:
        folium.Marker([lat, lon], tooltip=texto).add_to(mapa)
    if titulo:
        mapa.get_root().html.add_child(folium.Element(
            f'<div style="position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:9999;'
            f'background:white;padding:8px 16px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.25);'
            f'font:600 14px system-ui,sans-serif">{titulo}</div>'))
    folium.LayerControl(collapsed=False).add_to(mapa)
    if todos:
        mapa.fit_bounds([list(p) for p in todos], padding=(40, 40))
    mapa.save(str(ruta_salida))
    return Path(ruta_salida)
