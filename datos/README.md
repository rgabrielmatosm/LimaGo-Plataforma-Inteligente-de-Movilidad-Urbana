# Datos de la red vial (RF-01)

| Archivo | Contenido | ¿Se versiona? |
|---|---|---|
| `miraflores.graphml` | Grafo dirigido de calles vehiculares de Miraflores (osmnx). Se carga sin conexión. | Sí |
| `limite_distrito.geojson` | Polígono oficial del distrito (relación OSM 1944770) para mostrar la cobertura. | Sí |
| `cache_geocodificacion.json` | Caché de búsquedas de direcciones (Nominatim). Permite la demo sin Internet para las direcciones ya buscadas. | Sí |
| `miraflores.osm` | XML intermedio cuando se usa la ruta alternativa de descarga. | No (se regenera) |
| `cache_osmnx/`, `limago.db` | Cachés y base SQLite local. | No |

## Procedimiento

```bash
python -m datos.red_vial            # carga local; descarga solo si falta el archivo
python -m datos.red_vial --forzar   # vuelve a descargar
python -m datos.red_vial --forzar --fuente api-osm   # fuerza la ruta alternativa
```

1. **Descarga.** `osmnx.graph_from_place("Miraflores, Lima, Peru", network_type="drive", simplify=True, retain_all=False)` usando servidores Overpass (se prueban varios en orden).
2. **Ruta alternativa.** Si ningún servidor Overpass responde, se descarga el XML oficial desde `https://api.openstreetmap.org/api/0.6/map` por recuadros de 0,008°, se conservan solo las vías que cumplen **el mismo filtro `drive` de osmnx** (`datos/red_vial.py: FILTRO_DRIVE_EXCLUSIONES`) y se construye el grafo con `osmnx.graph_from_xml`. Después se repiten exactamente los pasos de `osmnx.graph_from_polygon`: polígono del distrito con 500 m de margen, truncado, mayor componente débilmente conexa, simplificación, truncado al polígono exacto y nueva limpieza.
3. **Almacenamiento.** `osmnx.save_graphml` → `datos/miraflores.graphml`. Se conservan el sentido de circulación (`oneway`, aristas dirigidas), la conectividad y las longitudes en metros (`length`).
4. **Carga.** `osmnx.load_graphml` y conversión inmediata a la estructura propia `algoritmos.grafo.GrafoVial` (listas de adyacencia directa e inversa). Ningún cálculo de rutas de la solución usa funciones de networkx/osmnx.

## Red actual

La red incluida en el repositorio se obtuvo el 2026-11-06 con la ruta alternativa (API oficial de OSM), porque los servidores Overpass no respondían desde el entorno de desarrollo:

- 1 368 intersecciones, 2 670 tramos dirigidos (1 833 de sentido único), 227,4 km de tramos.
- Mayor componente fuertemente conexa: 1 300 intersecciones (la flota se ubica solo ahí).
- Área del distrito: 9,45 km² (≥ 3 km² exigidos).

Datos © colaboradores de OpenStreetMap, licencia ODbL.
