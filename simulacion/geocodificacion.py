"""RF-08 — Ingreso del pasajero por dirección (texto) o por coordenadas.

* Coordenadas: se aceptan textos como ``-12.1211, -77.0297`` y se validan.
* Direcciones: se consulta Nominatim (OpenStreetMap) restringido al recuadro
  de cobertura (``viewbox`` + ``bounded=1``). Se respeta su política de uso:
  agente identificable, como máximo una petición por segundo y caché local en
  disco para no repetir consultas.
* Ambigüedad: si quedan varios lugares distintos (separados más de
  ``separacion_ambigua_m``) se lanza :class:`DireccionAmbigua` con las opciones
  para que el usuario elija; nunca se escoge "a ciegas".
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from config.ajustes import Ajustes
from estructuras.geografia import Rectangulo, haversine_metros, validar_coordenadas
from simulacion.errores import (CoordenadasInvalidas, DireccionAmbigua, DireccionNoEncontrada,
                                FueraDeCobertura, ServicioNoDisponible)

PATRON_COORDENADAS = re.compile(r"^\s*\(?\s*(-?\d{1,3}(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*\)?\s*$")


@dataclass
class ResultadoGeocodificacion:
    direccion: str
    lat: float
    lon: float
    tipo: str = ""
    importancia: float = 0.0

    def a_diccionario(self) -> dict:
        return asdict(self)


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto)


def interpretar_coordenadas(texto: str) -> tuple[float, float] | None:
    """Devuelve ``(lat, lon)`` si el texto parece un par de coordenadas, si no ``None``.

    Lanza :class:`CoordenadasInvalidas` si tiene forma de coordenadas pero
    están fuera de rango.
    """
    if texto is None:
        return None
    coincidencia = PATRON_COORDENADAS.match(texto)
    if not coincidencia:
        return None
    lat = float(coincidencia.group(1).replace(",", "."))
    lon = float(coincidencia.group(2).replace(",", "."))
    try:
        validar_coordenadas(lat, lon)
    except ValueError as error:
        raise CoordenadasInvalidas(str(error)) from error
    return lat, lon


class Geocodificador:
    def __init__(self, ajustes: Ajustes, limites: Rectangulo, cliente_http: Callable[[str, dict], list | dict] | None = None,
                 usar_cache: bool = True, separacion_ambigua_m: float = 400.0) -> None:
        self.ajustes = ajustes
        self.limites = limites
        self.separacion_ambigua_m = separacion_ambigua_m
        self.nombre_cobertura = getattr(ajustes, "nombre_cobertura", "Miraflores")
        self._cliente = cliente_http or self._cliente_nominatim
        self._usar_cache = usar_cache
        self._ruta_cache = Path(ajustes.ruta_cache_geocodificacion)
        self._cache: dict[str, list[dict]] = {}
        self._candado = threading.Lock()
        self._ultima_peticion = 0.0
        semilla = Path(__file__).resolve().parent.parent / "datos" / "cache_geocodificacion.json"
        origen = self._ruta_cache if self._ruta_cache.exists() else semilla  # caché versionada como semilla
        if usar_cache and origen.exists():
            try:
                self._cache = json.loads(origen.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._cache = {}

    # ----------------------------------------------------------------- HTTP
    def _cliente_nominatim(self, ruta: str, parametros: dict):
        import requests

        with self._candado:  # política de Nominatim: 1 petición por segundo
            espera = 1.0 - (time.monotonic() - self._ultima_peticion)
            if espera > 0:
                time.sleep(espera)
            try:
                respuesta = requests.get(
                    f"{self.ajustes.geocodificador_url}/{ruta}",
                    params=parametros,
                    headers={"User-Agent": self.ajustes.geocodificador_agente, "Accept-Language": "es"},
                    timeout=15,
                )
            except requests.RequestException as error:
                raise ServicioNoDisponible("El servicio de direcciones no está disponible ahora") from error
            finally:
                self._ultima_peticion = time.monotonic()
        if respuesta.status_code != 200:
            raise ServicioNoDisponible("El servicio de direcciones no respondió correctamente")
        return respuesta.json()

    def _guardar_cache(self) -> None:
        if not self._usar_cache:
            return
        try:
            self._ruta_cache.parent.mkdir(parents=True, exist_ok=True)
            self._ruta_cache.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------- búsqueda
    def buscar(self, texto: str, limite: int = 5) -> list[ResultadoGeocodificacion]:
        """Lugares que coinciden con el texto dentro de la zona de cobertura."""
        if texto is None or len(texto.strip()) < 3:
            raise DireccionNoEncontrada("Escribe una dirección de al menos 3 caracteres")
        coordenadas = interpretar_coordenadas(texto)
        if coordenadas is not None:
            lat, lon = coordenadas
            if not self.limites.contiene(lat, lon):
                raise FueraDeCobertura("Las coordenadas están fuera de la zona de cobertura")
            return [ResultadoGeocodificacion(f"{lat:.6f}, {lon:.6f}", lat, lon, "coordenadas", 1.0)]
        clave = normalizar(texto)
        if clave not in self._cache:
            r = self.limites
            consulta = texto if "lima" in clave else f"{texto}, Lima"
            datos = self._cliente("search", {
                "q": consulta, "format": "jsonv2", "limit": 10, "countrycodes": "pe",
                "viewbox": f"{r.lon_min},{r.lat_max},{r.lon_max},{r.lat_min}", "bounded": 1,
                "addressdetails": 0,
            })
            self._cache[clave] = [
                {"direccion": d.get("display_name", ""), "lat": float(d["lat"]), "lon": float(d["lon"]),
                 "tipo": d.get("type", ""), "importancia": float(d.get("importance") or 0.0)}
                for d in (datos or [])
            ]
            self._guardar_cache()
        resultados = [ResultadoGeocodificacion(**d) for d in self._cache[clave]]
        resultados = [r for r in resultados if self.limites.contiene(r.lat, r.lon)]
        return self._deduplicar(resultados)[:limite]

    def _deduplicar(self, resultados: list[ResultadoGeocodificacion]) -> list[ResultadoGeocodificacion]:
        """Une resultados que describen el mismo lugar (mismo nombre y cercanos)."""
        unicos: list[ResultadoGeocodificacion] = []
        for resultado in sorted(resultados, key=lambda r: -r.importancia):
            nombre = normalizar(resultado.direccion.split(",")[0])
            duplicado = any(
                normalizar(u.direccion.split(",")[0]) == nombre
                and haversine_metros(u.lat, u.lon, resultado.lat, resultado.lon) < self.separacion_ambigua_m
                for u in unicos
            )
            if not duplicado:
                unicos.append(resultado)
        return unicos

    def resolver(self, texto: str) -> ResultadoGeocodificacion:
        """Un único lugar o una excepción clara (no encontrado / ambiguo / fuera de cobertura)."""
        resultados = self.buscar(texto)
        if not resultados:
            raise DireccionNoEncontrada(f"No encontramos «{texto.strip()}» dentro de {self.nombre_cobertura}")
        if len(resultados) == 1:
            return resultados[0]
        primero = resultados[0]
        lejanos = [r for r in resultados[1:]
                   if haversine_metros(primero.lat, primero.lon, r.lat, r.lon) >= self.separacion_ambigua_m]
        if lejanos:
            raise DireccionAmbigua("La dirección coincide con varios lugares; elige uno",
                                   [r.a_diccionario() for r in resultados])
        return primero

    def inverso(self, lat: float, lon: float) -> str:
        """Dirección aproximada de unas coordenadas (o las coordenadas si no hay servicio)."""
        try:
            validar_coordenadas(lat, lon)
        except ValueError as error:
            raise CoordenadasInvalidas(str(error)) from error
        clave = f"inv:{lat:.5f},{lon:.5f}"
        if clave not in self._cache:
            try:
                datos = self._cliente("reverse", {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18})
            except ServicioNoDisponible:
                return f"{lat:.5f}, {lon:.5f}"
            nombre = (datos or {}).get("display_name") if isinstance(datos, dict) else None
            self._cache[clave] = [{"direccion": nombre or f"{lat:.5f}, {lon:.5f}", "lat": lat, "lon": lon,
                                   "tipo": "inverso", "importancia": 0.0}]
            self._guardar_cache()
        return self._cache[clave][0]["direccion"]
