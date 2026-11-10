"""Genera los mapas folium obligatorios (RF-07) en ``mapas/``.

Se ejecuta una simulación con semilla fija; entre solicitud y solicitud avanzan
turnos para que la flota cambie. Las tres direcciones se ingresan como texto y
se geocodifican (RF-08); la caché ``datos/cache_geocodificacion.json`` permite
regenerar los mapas sin conexión.

    python -m scripts.generar_mapas
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.ajustes import ajustes_academicos  # noqa: E402
from datos.red_vial import cargar_red_vial  # noqa: E402
from simulacion.geocodificacion import Geocodificador  # noqa: E402
from simulacion.turnos import Simulador  # noqa: E402
from visualizacion.mapa_folium import generar_mapa_asignacion  # noqa: E402

SOLICITUDES = [
    ("asignacion_1_parque_kennedy", "Parque Kennedy, Miraflores", 3),
    ("asignacion_2_larcomar", "Larcomar, Miraflores", 17),
    ("asignacion_3_ovalo_gutierrez", "Óvalo Gutiérrez, Miraflores", 25),
    ("asignacion_4_coordenadas_huaca_pucllana", "-12.11103, -77.03366", 15),
]


def main() -> list[dict]:
    ajustes = ajustes_academicos()
    grafo = cargar_red_vial(ajustes)
    simulador = Simulador(grafo, ajustes)
    geocodificador = Geocodificador(ajustes, simulador.despachador.limites)
    resumen = []
    for nombre, texto, turnos_previos in SOLICITUDES:
        for _ in range(turnos_previos):
            simulador.avanzar_turno()
        lugar = geocodificador.resolver(texto)
        solicitud_id = simulador.nuevo_id_solicitud()
        pasajero = simulador.despachador.crear_pasajero(solicitud_id, lugar.lat, lugar.lon, lugar.direccion)
        resultado = simulador.solicitar_viaje(pasajero, solicitud_id)
        ruta = ajustes.carpeta_mapas / f"{nombre}.html"
        titulo = f"LimaGo · {texto} · turno {simulador.turno}"
        generar_mapa_asignacion(simulador.despachador, resultado, ruta, titulo)
        mas_cercano = min(resultado.candidatos, key=lambda c: c.distancia_recta_m)
        fila = {
            "mapa": str(ruta.relative_to(ajustes.carpeta_mapas.parent)),
            "entrada": texto,
            "direccion": lugar.direccion,
            "turno": simulador.turno,
            "estado": resultado.estado,
            "seleccionado": resultado.seleccionado.a_diccionario() if resultado.seleccionado else None,
            "mas_cercano_en_linea_recta": mas_cercano.a_diccionario(),
            "candidatos": [c.a_diccionario() for c in resultado.candidatos],
            "conteo_flota": simulador.despachador.conteo_estados(),
        }
        resumen.append(fila)
        print(f"{ruta.name}: {resultado.mensaje}; ETA "
              f"{resultado.seleccionado.eta_s / 60:.1f} min" if resultado.seleccionado else resultado.mensaje)
    (ajustes.carpeta_mapas / "resumen_mapas.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2),
                                                             encoding="utf-8")
    return resumen


if __name__ == "__main__":
    main()
