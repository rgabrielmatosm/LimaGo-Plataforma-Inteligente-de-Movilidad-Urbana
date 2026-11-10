# LimaGo V3.0 — mejoras y su origen

Este documento separa tres cosas que no deben confundirse:

1. lo que **exige el documento del profesor** (`Proyecto_2_Conductor_Cercano.docx`), que sigue siendo la fuente de verdad;
2. el **feedback observado en la grabación de la revisión**, que inspira mejoras pero **no** es una obligación formal;
3. las **mejoras propuestas por el equipo** para que la aplicación sea creíble como servicio de movilidad.

La V3 no reemplaza ninguna pieza académica: el Quadtree, Haversine, heap, Dijkstra, A*, la asignación múltiple (húngaro) y H3 aislado siguen siendo los mismos, y los benchmarks, mapas folium e informe se ejecutan siempre sobre el escenario académico de Miraflores (`ajustes_academicos()`).

---

## 1. Requisitos originales del profesor (sin cambios)

| Requisito | Estado en V3 | Evidencia |
|---|---|---|
| RF-01 red vial de OSM con OSMnx | Se conserva Miraflores (`datos/miraflores.graphml`). Lima se prepara con la misma secuencia de `osmnx.graph_from_polygon` | `datos/red_vial.py`, `datos/red_metropolitana.py` |
| RF-02/RF-03 Quadtree propio con k vecinos exactos | Sin cambios; también indexa la flota metropolitana y las unidades de apoyo | `estructuras/quadtree.py`; `test_quadtree_metropolitano_exacto` |
| RF-04 Haversine propia | Sin cambios | `estructuras/geografia.py` |
| RF-05 Dijkstra propio con heap | Sin cambios; es el único algoritmo de rutas de la aplicación | `algoritmos/dijkstra.py` |
| RF-06 asignación por menor ETA entre k | **La función académica no cambió** (`Despachador.asignar`). El motor de aceptación es una capa comercial adicional que guarda el óptimo académico para compararlo | `test_funcion_academica_sigue_asignando_menor_eta`, `estadisticas_aceptacion` |
| RF-07 mapas folium | Mismo resultado que V1: asignaciones, ETA y conteos idénticos (solo aparecen los estados nuevos con valor 0) | verificación descrita en la sección 5 |
| RF-08 simulación por turnos | Se conserva; Lima añade estados y reloj | `simulacion/turnos.py` |
| RF-09 benchmarks 300/3 000/30 000 y Dijkstra vs networkx | Sin cambios de resultado (400/400 y 300/300 idénticos). El benchmark metropolitano va en un archivo aparte | `benchmark/benchmark_metropolitano.py` |
| Retos A–D | Sin cambios | `benchmark/benchmark_retos.py` |

## 2. Feedback observado en la grabación

Comentarios del profesor durante la revisión, interpretados como **criterios de mejora de experiencia y arquitectura**:

| # | Comentario | Cómo se atendió |
|---|---|---|
| 1 | Reducir los datos que debe introducir el usuario | Ubicación del navegador con permiso (se pide una sola vez; si se niega, nada se bloquea). El pasajero solo escribe el destino. No configura tráfico, algoritmos ni k. |
| 2 | Aceptar direcciones exactas, no solo puntos predefinidos | Autocompletado de direcciones reales (Nominatim) en toda Lima, coordenadas o clic en el mapa; desambiguación cuando hay varios resultados; ajuste a la vía más cercana con aviso. |
| 3 | Calcular automáticamente el tráfico y las condiciones horarias | Reloj de Lima (`America/Lima`, respaldo UTC−5). El nivel de tráfico se deriva de la hora sin intervención. **Es un modelo horario simulado, no tráfico real**, y así se indica en la interfaz y en `/api/trafico`. Se mantienen los escenarios académicos 8:00 y 15:00 (hora fija desde operaciones). |
| 4 | Automatizar procesos manuales | Ofertas secuenciales con plazo, aceptación/rechazo/vencimiento, recogida, inicio y fin de viaje, desconexión/reconexión de conductores y asignación de unidades de apoyo ocurren solos en el worker. |
| 5 | Comprender herramientas de infraestructura web, incluido CDN | Evaluación en [`CDN_Y_RENDIMIENTO.md`](CDN_Y_RENDIMIENTO.md). **No se configuró un CDN**; se optimizaron caché HTTP y compresión en Nginx. |
| 6 | Idea adicional: alarma con notificaciones por proximidad | Botón «Alerta de seguridad» durante un viaje activo: se registra, se deduplica, notifica al centro de operaciones y el **Quadtree propio** elige la unidad de apoyo simulada más cercana. **No hay conexión con Policía Nacional, SAMU, serenazgo ni servicios reales.** |

## 3. Mejoras propuestas por el equipo

### Cobertura metropolitana
- Red de los 50 distritos (43 de Lima + 7 del Callao): 152 441 intersecciones, 401 998 tramos dirigidos, 33 084 km. Fuentes: extracto BBBike + franjas de la API oficial de OSM para completar el límite (relación OSM 12933390). Formato compacto `.npz` propio (15 MB, carga en 2–3 s).
- Cobertura por **polígono real** (point-in-polygon propio por *ray casting*, verificado contra shapely en 400 puntos), no por rectángulo.
- Distritos desde OSM `admin_level=8`; 4 completados con Nominatim (Ancón, Carabayllo, Pucusana, Santa María del Mar).
- Escenarios configurables: `LIMAGO_ESCENARIO=lima` (por defecto) o `miraflores` (académico).

### Flujo comercial
Inicio → ubicación detectada o escrita → destino → **cotización** (ruta, duración, desglose, `cotizacion_id`) → **confirmación** → búsqueda («Buscando conductor») → oferta al conductor de menor ETA → si rechaza o no responde, al siguiente → aceptación → conductor en camino → conductor llegó (espera) → a bordo → completado → historial.

### Estados del conductor y motor de aceptación
- Estados explícitos: `desconectado`, `disponible`, `oferta_pendiente`, `aceptado`, `en_camino`, `esperando_recogida`, `en_viaje`, `finalizado` (el estado «ocupado» es una propiedad derivada). Las transiciones válidas están en una tabla (`TRANSICIONES`) y cualquier otra lanza `TransicionInvalida`.
- Políticas por conductor: automática, probabilística reproducible, rechaza, no responde, no disponible. La decisión se deriva de `(semilla, solicitud, conductor)`: el mismo escenario produce las mismas decisiones.
- Sin doble asignación: el worker es el único dueño de la flota; un conductor con oferta pendiente no recibe otra.

### Animación
El backend calcula posición interpolada y rumbo sobre la geometría del tramo; el frontend solo interpola entre dos posiciones del servidor a lo largo de la ruta restante (`requestAnimationFrame`). En pausa el vehículo se detiene. El pasajero solo ve a su conductor; el centro de operaciones puede ver toda la flota.

### Tarifa dinámica (soles)
`total = máx(mínima, base + por_km × km_viaje + por_minuto × minutos_viaje + recogida)`, con `recogida = min(tope, por_km_recogida × máx(0, km_recogida − km_gratis))`.
Valores por defecto: base S/ 3,50 · S/ 1,10 por km · S/ 0,25 por minuto · mínima S/ 6,00 · recogida gratis hasta 1,5 km, luego S/ 0,60 por km con tope de S/ 4,00.
- **Sin doble conteo de congestión:** el tráfico solo cambia los minutos (tiempo por calles con pesos dinámicos); la distancia no se multiplica por ningún factor.
- **Regla de recálculo:** el precio queda **fijado al confirmar** a partir de la cotización (vigente 5 minutos). Si la cotización vence, se pide otra. Durante el viaje no se recalcula.
- No se presentan como precios de otras empresas. No hay pagos ni datos de pago.

### Operaciones
Panel de alertas con aviso inmediato y botón «Atender»; unidades de apoyo en el mapa; aceptación operativa frente al óptimo académico (coincidencia, espera extra, ofertas por solicitud); conteo de todos los estados; reloj de Lima u hora fija; métricas Prometheus nuevas (`limago_ofertas_total`, `limago_aceptacion_coincide_academico_total`, `limago_alertas_total`) con paneles en Grafana.

## 4. Servicios evaluados y no incorporados

| Opción | Decisión | Motivo |
|---|---|---|
| Proveedor de tráfico real (Google, TomTom, HERE, Waze) | No | Requiere claves de pago y su uso sustituiría el modelo propio que se evalúa. La interfaz deja preparado el campo `fuente_real: null`. |
| Redis (cola o GEO) | No | La cola de comandos en PostgreSQL basta para el volumen; Redis GEO sustituiría al Quadtree, lo que está prohibido. |
| Servicio de geocodificación propio (Nominatim/Photon local) | No | Importar Perú requiere varios GB y horas; se usa Nominatim público con caché y límite de 1 petición/s. |
| Servicio de notificaciones / mensajería (WebSocket, push, SMS) | No | La consulta periódica (1–2 s) basta para la demostración; SMS o push a personas reales sería engañoso en un servicio simulado. |
| CDN | No (por ahora) | Ver [`CDN_Y_RENDIMIENTO.md`](CDN_Y_RENDIMIENTO.md). |

Se mantienen los **6 servicios** de Docker Compose.

## 5. Verificación realizada (equipo de desarrollo, 7-nov-2026)

| Comprobación | Resultado |
|---|---|
| `pytest` | 86 pruebas pasan (65 previas + 21 de la V3) |
| Mapas folium regenerados | Asignaciones, ETA y conteos idénticos a la V1; solo se añaden los estados nuevos con valor 0 |
| Benchmarks académicos | Quadtree 400/400 y Dijkstra = networkx 300/300, como en la V1 |
| Benchmark metropolitano | Quadtree 300/300 idéntico al lineal; Dijkstra = networkx 20/20; despacho mediana 1,1 ms |
| Prueba de punta a punta (Playwright, local y Docker) | 30/30: ubicación concedida (Comas) y negada, cotización Comas → Miraflores, aceptación, animación, pausa y reanudación, alerta y deduplicación, atención en operaciones, 10 páginas en móvil sin desbordamiento, 50 distritos, enlaces internos, historial y ausencia de errores de JavaScript |
| Docker Compose | 6 servicios `healthy`; Prometheus lee backend, worker y a sí mismo; Grafana responde; backend ~510 MB y worker ~580 MB |
| Reinicio del worker | La simulación se restauró en el mismo turno y siguió avanzando |

### Pendiente o no verificable aquí
- Rendimiento en Windows con Docker Desktop: no se probó en ese sistema; se recomienda asignar ≥ 4 GB a Docker.
- La calidad de las direcciones depende de Nominatim/OSM; en zonas con pocos números de puerta se devuelve la calle o el barrio.
- Prueba con un teléfono real (GPS físico): solo se probó con geolocalización emulada.
- La presentación y el informe PDF académicos describen la V1/V2; la sección V3 de la presentación resume estas mejoras.
