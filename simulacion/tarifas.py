"""Tarifas orientativas y estimación de viajes (V2, ampliado en la V3).

**Importante:** LimaGo es una simulación. La tarifa es una *estimación* en soles
(S/) calculada con una fórmula fija y documentada; no existe cobro ni pasarela de
pago, y no corresponde a precios de ninguna empresa real. Las distancias y los
tiempos sí son calculados: salen de las rutas por calles del Dijkstra propio.

    total = max(mínima, base + recorrido + tiempo + recogida)

=============  =========================================================  ======
Componente     Cálculo                                                    Unidad
=============  =========================================================  ======
base           ``tarifa_base``                                            S/
recorrido      ``tarifa_por_km`` × km del viaje (ruta origen → destino)   S/
tiempo         ``tarifa_por_minuto`` × minutos estimados del viaje        S/
recogida       ``tarifa_por_km_recogida`` × max(0, km de recogida −       S/
               ``tarifa_recogida_gratis_km``), con tope
               ``tarifa_tope_recogida``
=============  =========================================================  ======

**Congestión sin doble conteo:** la hora punta solo afecta al componente de
*tiempo* (los minutos salen de los pesos horarios del grafo). La distancia es la
de la ruta y no se multiplica por ningún factor de tráfico.

Rango mostrado: [0,9 · total ; 1,15 · total], redondeado hacia arriba a 0,10.
La tarifa se **fija al confirmar** (ver ``docs/MEJORAS_V3.md``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from algoritmos.congestion import PesosDinamicos
from algoritmos.dijkstra import eta_segundos, ruta_mas_corta
from algoritmos.grafo import GrafoVial
from simulacion.errores import ErrorLimaGo
from simulacion.ubicacion import UbicadorRed

MONEDA = "PEN"
# Valores por defecto (iguales a los de config.ajustes.Ajustes); se pueden pasar otros parámetros.
BASE = 3.50
POR_KM = 1.10
POR_MINUTO = 0.25
MINIMA = 6.00
RECOGIDA_GRATIS_KM = 1.5
POR_KM_RECOGIDA = 0.60
TOPE_RECOGIDA = 4.00
FACTOR_MIN, FACTOR_MAX = 0.90, 1.15


class SinRuta(ErrorLimaGo):
    codigo = "sin_ruta"


def _redondear(valor: float) -> float:
    return round(math.ceil(valor * 10 - 1e-9) / 10, 2)


def parametros_tarifa(ajustes=None) -> dict:
    if ajustes is None:
        return {"base": BASE, "por_km": POR_KM, "por_minuto": POR_MINUTO, "minima": MINIMA,
                "recogida_gratis_km": RECOGIDA_GRATIS_KM, "por_km_recogida": POR_KM_RECOGIDA,
                "tope_recogida": TOPE_RECOGIDA}
    return {"base": ajustes.tarifa_base, "por_km": ajustes.tarifa_por_km, "por_minuto": ajustes.tarifa_por_minuto,
            "minima": ajustes.tarifa_minima, "recogida_gratis_km": ajustes.tarifa_recogida_gratis_km,
            "por_km_recogida": ajustes.tarifa_por_km_recogida, "tope_recogida": ajustes.tarifa_tope_recogida}


def calcular_tarifa(distancia_m: float, duracion_s: float, distancia_recogida_m: float = 0.0,
                    parametros: dict | None = None) -> dict:
    """Tarifa orientativa (S/) a partir de distancia del viaje (m), duración (s) y distancia de recogida (m)."""
    if distancia_m < 0 or duracion_s < 0 or distancia_recogida_m < 0:
        raise ValueError("La distancia y la duración deben ser no negativas")
    p = parametros or parametros_tarifa()
    km = distancia_m / 1000
    minutos = duracion_s / 60
    recorrido = p["por_km"] * km
    tiempo = p["por_minuto"] * minutos
    recogida = min(p["tope_recogida"], p["por_km_recogida"] * max(0.0, distancia_recogida_m / 1000 - p["recogida_gratis_km"]))
    bruta = p["base"] + recorrido + tiempo + recogida
    estimada = max(p["minima"], bruta)
    return {
        "moneda": MONEDA,
        "estimada": _redondear(estimada),
        "total": _redondear(estimada),
        "minima": _redondear(max(p["minima"], estimada * FACTOR_MIN)),
        "maxima": _redondear(estimada * FACTOR_MAX),
        "desglose": {"base": round(p["base"], 2), "recorrido": round(recorrido, 2), "tiempo": round(tiempo, 2),
                     "recogida": round(recogida, 2), "ajuste_minimo": round(max(0.0, p["minima"] - bruta), 2),
                     # nombres de la V2 (compatibilidad)
                     "por_km": round(recorrido, 2), "por_minuto": round(tiempo, 2), "tarifa_minima": p["minima"]},
        "unidades": {"moneda": "S/ (soles)", "distancia": "km", "tiempo": "minutos"},
        "datos": {"km_viaje": round(km, 3), "minutos_viaje": round(minutos, 2),
                  "km_recogida": round(distancia_recogida_m / 1000, 3)},
    }


@dataclass
class Estimacion:
    distancia_m: float
    duracion_s: float
    ruta: list[int]
    tarifa: dict


def estimar_viaje(grafo: GrafoVial, ubicador: UbicadorRed, origen: tuple[float, float], destino: tuple[float, float],
                  velocidad_kmh: float, hora: float | None = None, pesos: PesosDinamicos | None = None,
                  distancia_recogida_m: float = 0.0, parametros: dict | None = None) -> Estimacion:
    """Ruta más corta por calles entre dos puntos, duración y tarifa orientativa.

    Sin ``hora``: ruta de menor distancia y duración con la velocidad promedio.
    Con ``hora``: ruta de menor tiempo con los pesos de congestión simulada de esa hora (Reto B / V3).
    """
    nodo_o, _ = ubicador.ubicar(*origen)
    nodo_d, _ = ubicador.ubicar(*destino)
    if hora is not None:
        pesos = pesos or PesosDinamicos(grafo)
        adyacencia, _ = pesos.adyacencias(hora)
        duracion, ruta, _ = ruta_mas_corta(adyacencia, nodo_o, nodo_d)
        distancia = grafo.longitud_ruta(ruta) if ruta else math.inf
    else:
        distancia, ruta, _ = ruta_mas_corta(grafo.adyacencia, nodo_o, nodo_d)
        duracion = eta_segundos(distancia, velocidad_kmh)
    if ruta is None:
        raise SinRuta("No encontramos una ruta por calles entre esos puntos")
    return Estimacion(distancia, duracion, ruta, calcular_tarifa(distancia, duracion, distancia_recogida_m, parametros))
