# Matriz de cumplimiento y trazabilidad

Documento base: *Proyecto Integrador N.° 2 — Asignación del conductor más cercano* (4 páginas).
Fecha de la auditoría: 2026-11-06. Entorno de verificación: Linux x86_64, Python 3.13.18, Docker Engine 29.9.2 / Compose v5.6.1.

**Estados**

- **VERIFICADO**: se ejecutó y se comprobó el resultado (prueba automatizada, ejecución real o inspección del artefacto generado).
- **IMPLEMENTADO SIN VERIFICAR**: el código o la configuración existen, pero no se pudo ejecutar en este entorno; se indica por qué.
- **PENDIENTE**: depende del equipo o de algo que no puede hacerse desde el código.

Evidencias principales: `python -m pytest -q` → **52 passed** (0 omitidas); `benchmark/resultados/*.json` y `*.png`; `mapas/*.html`; `informe.pdf` (3 páginas); `docker compose ps` con los 4 servicios *healthy*.

---

## 1. Requerimientos funcionales

| Req. | Descripción | Código | Prueba / evidencia | Resultado | Estado |
|---|---|---|---|---|---|
| RF-01 | Cargar la red vial desde OSM y guardarla localmente | `datos/red_vial.py` (`descargar_red`, `descargar_red_api_osm`, `cargar_red_vial`); `algoritmos/grafo.py` (`GrafoVial.desde_networkx`) | Ejecución de `python -m datos.red_vial --fuente api-osm`; `tests/test_simulacion.py::test_red_real_cargada_y_dirigida`; [`datos/README.md`](../datos/README.md) | `datos/miraflores.graphml`: 1 368 intersecciones, 2 670 tramos dirigidos (1 833 de sentido único). Se recarga sin red en < 1 s. | VERIFICADO (vía API oficial de OSM) |
| RF-01 (variante) | Descarga por Overpass con `graph_from_place` | `datos/red_vial.py:descargar_red` | Intentos reales con overpass-api.de, overpass.private.coffee y overpass.kumi.systems | Los tres servidores cortaron o no respondieron desde este entorno | IMPLEMENTADO SIN VERIFICAR |
| RF-02 | Flota configurable (300 por defecto) en intersecciones, estado disponible/ocupado, semilla fija | `simulacion/flota.py:generar_flota`; `simulacion/modelos.py:Conductor`; `config/ajustes.py` | `test_flota_reproducible_y_sobre_intersecciones`; `test_pausa_reinicio_y_reproducibilidad` | Misma semilla ⇒ misma flota; semilla distinta ⇒ otra; todos en nodos de la componente fuerte | VERIFICADO |
| RF-03 | Quadtree propio: insertar, eliminar, buscar en rectángulo, actualizar posición | `estructuras/quadtree.py` (`NodoQuadtree`, `Quadtree.insertar:136`, `eliminar:180`, `actualizar_posicion:221`, `buscar_rectangulo:253`) | `tests/test_quadtree.py` (14 pruebas: vacío, subdivisión, duplicados, coincidentes, casi coincidentes, bordes, fusión, rectángulo, 3 000 actualizaciones) | Invariantes comprobados con `verificar_consistencia()` | VERIFICADO |
| RF-04 | k disponibles más cercanos con Quadtree + heap; Haversine propio | `Quadtree.buscar_k_cercanos:272`; `estructuras/geografia.py:haversine_metros`, `Rectangulo.distancia_minima_metros`; referencia `estructuras/busqueda_lineal.py` | `test_k_cercanos_exactos_frente_a_busqueda_lineal` (300 consultas), `test_k_cercanos_poda_el_espacio`, `test_conductores_no_disponibles_se_excluyen`, `test_haversine_valores_conocidos`, `test_cota_inferior_de_rectangulo_es_valida`; benchmark | 400/400 resultados idénticos a la lineal en cada escala; 173 distancias por consulta con 30 000 conductores | VERIFICADO |
| RF-05 | Dijkstra propio, ETA con velocidad configurable, asignar menor ETA | `algoritmos/dijkstra.py`; `simulacion/despachador.py` (`calcular_eta:181`, `elegir_mejor:205`, `solicitar_viaje:213`) | `tests/test_rutas.py` (9 pruebas); `test_seleccion_por_menor_eta_no_por_linea_recta`; `test_conductor_que_no_puede_llegar`; `mapas/resumen_mapas.json` | En 3 de 4 mapas el asignado no es el más cercano en línea recta; inaccesibles ⇒ ETA ∞ y estado `sin_ruta` | VERIFICADO |
| RF-06 | Simulación por turnos con Quadtree siempre actualizado | `simulacion/turnos.py` (`avanzar_turno:131`, `_mover:156`, `reiniciar:75`, `instantanea:187`); `Despachador.mover_conductor` | `test_simulacion_mantiene_quadtree_consistente` (60 turnos, sin saltos imposibles), `test_ciclo_de_vida_de_un_viaje`, `test_instantanea_restaura_exactamente`, `test_simulacion_real_300_conductores` | Pausa, continuar, avanzar y reiniciar probados por API y desde la web | VERIFICADO |
| RF-07 | Mapas folium: pasajero, conductores por estado, k candidatos, ruta; ≥ 3 asignaciones | `visualizacion/mapa_folium.py`; `scripts/generar_mapas.py` | `mapas/asignacion_1..4_*.html`; `test_mapa_folium_con_todos_los_elementos`; captura de pantalla revisada | 4 mapas de asignaciones distintas + mapa del Reto B | VERIFICADO |
| RF-08 | Pasajero por dirección (texto) o coordenadas | `simulacion/geocodificacion.py` (`interpretar_coordenadas:49`, `Geocodificador.resolver:165`); `Despachador.ubicar_en_red:140`; `frontend/viaje.html` (pestañas Dirección / Coordenadas / En el mapa) | `test_ingreso_por_coordenadas_y_validacion`, `test_direccion_encontrada_ambigua_y_no_encontrada`, `test_pasajero_sin_conexion_vial`, `test_validacion_de_coordenadas`, `test_errores_de_ubicacion_y_controles`; prueba en navegador | Consultas reales a Nominatim desde el proceso local (Parque Kennedy, Larcomar, Óvalo Gutiérrez, Av. José Larco 1150); ambigüedad ⇒ lista de opciones; fuera de cobertura y sin conexión vial con mensajes claros | VERIFICADO |
| RF-09 | Benchmark lineal vs Quadtree (300/3 000/30 000) y Dijkstra vs networkx; gráficos matplotlib | `benchmark/benchmark_busqueda.py`, `benchmark/benchmark_rutas.py`, `benchmark/utilidades.py` | `benchmark/resultados/benchmark_busqueda.json`, `benchmark_rutas.json`, `busqueda_tiempos.png`, `busqueda_distancias.png`, `rutas_tiempos.png`; `test_dijkstra_igual_a_networkx_en_malla`, `test_dijkstra_igual_a_networkx_en_miraflores` | ×4,2 / ×29,0 / ×84,2; 300/300 distancias idénticas (dif. máx. 0 m) | VERIFICADO |

## 2. Restricciones técnicas

| Restricción | Cómo se cumple | Evidencia | Estado |
|---|---|---|---|
| Quadtree, Dijkstra y Haversine propios; `heapq` permitido | `estructuras/quadtree.py`, `algoritmos/dijkstra.py`, `estructuras/geografia.py` | Revisión de código; pruebas frente a referencias | VERIFICADO |
| osmnx/networkx solo para descargar, cargar, guardar y validar | Usados en `datos/red_vial.py`, `GrafoVial.desde_networkx`, benchmarks y pruebas | `test_solucion_principal_sin_librerias_prohibidas` (análisis AST) | VERIFICADO |
| Prohibido: rutas de networkx/osmnx, KDTree, rtree, STRtree, h3 o índices hechos | Ubicación del pasajero con un Quadtree propio de intersecciones (no `nearest_nodes`); h3 solo en `experimental/` | Misma prueba AST sobre `estructuras/`, `algoritmos/`, `simulacion/`, `api/`, `datos/`, `visualizacion/` | VERIFICADO |
| Clases `Conductor`, `Pasajero`, `NodoQuadtree`, `Quadtree`, `Despachador` | `simulacion/modelos.py`, `estructuras/quadtree.py`, `simulacion/despachador.py` | Revisión de código | VERIFICADO |
| Métodos en español y snake_case | Todos los métodos públicos (`insertar`, `buscar_k_cercanos`, `solicitar_viaje`, `avanzar_turno`, ...) | Revisión de código; pyflakes sin advertencias | VERIFICADO |
| Semilla fija y configurable | `LIMAGO_SEMILLA` (42); generador propio del simulador serializado en la instantánea | `test_pausa_reinicio_y_reproducibilidad`, `test_instantanea_restaura_exactamente` | VERIFICADO |
| Python 3.11 o superior | Probado en 3.13 (local) y 3.12 (Docker) | Ejecuciones reales | VERIFICADO (3.11 no probado explícitamente) |
| Distrito ≥ 3 km² | Miraflores: 9,45 km² | `datos/limite_distrito.geojson` | VERIFICADO |

## 3. Entregables

| Entregable | Ubicación | Evidencia | Estado |
|---|---|---|---|
| README con instalación, ejecución y ejemplos | `README.md` | Comandos usados en esta auditoría | VERIFICADO |
| Commits de todos los integrantes | Historial de Git | Debe hacerlo cada integrante con su cuenta ([`docs/CONTRIBUCION.md`](CONTRIBUCION.md)) | PENDIENTE |
| Pytest ≥ 10 casos con Quadtree vacío, mismo punto, sin disponibles, sin conexión vial | `tests/` (52 pruebas) | `test_quadtree_vacio`, `test_conductores_en_el_mismo_punto_no_subdividen_infinitamente`, `test_conductores_no_disponibles_se_excluyen`, `test_estado_actualizado_y_sin_asignacion_duplicada`, `test_pasajero_sin_conexion_vial` | VERIFICADO |
| Informe de 3 a 5 páginas: diseño, Big-O, benchmark con gráficos, comparación con H3 | `informe.pdf` (generado por `scripts/generar_informe.py` desde los JSON) | 3 páginas, revisado visualmente | VERIFICADO |
| Respuestas a las 3 preguntas de investigación | `informe.pdf`, sección 7 | Revisión del PDF | VERIFICADO |
| Mapas HTML de ≥ 3 asignaciones | `mapas/` | 4 mapas + resumen JSON | VERIFICADO |
| Demostración en vivo | Docker Compose + `presentacion/index.html` (guion) | Flujo completo probado en navegador contra el stack Docker | VERIFICADO (la demo en clase es responsabilidad del equipo) |
| Organización mínima del repositorio | `datos/`, `estructuras/`, `algoritmos/`, `simulacion/`, `mapas/`, `benchmark/`, `tests/`, `informe.pdf`, `README.md` | `ls` | VERIFICADO |

## 4. Retos opcionales

| Reto | Código | Prueba / evidencia | Resultado | Estado |
|---|---|---|---|---|
| A — A* y nodos explorados | `algoritmos/a_estrella.py` | `test_a_estrella_igual_coste_y_menos_nodos`, `test_a_estrella_admisible_con_pesos_en_tiempo`; `benchmark_rutas.json`, `a_estrella_nodos.png` | Mismo coste en 300/300 pares; 208 frente a 678 nodos (−69,3 %) | VERIFICADO |
| B — Pesos dinámicos 8:00 vs 15:00 | `algoritmos/congestion.py`; `Despachador._adyacencias` (`LIMAGO_CONGESTION_ACTIVA`) | `test_congestion_hora_punta_cambia_pesos_y_eta`; `benchmark_retos.json`, `reto_b_perfil.png`, `mapas/reto_b_congestion_8_vs_15.html` | 8,6 min frente a 4,4 min de media; 215/300 rutas cambian; 9/100 asignaciones eligen otro conductor (congestión simulada) | VERIFICADO |
| C — Varios pasajeros minimizando la espera total | `algoritmos/asignacion_multiple.py`; `Despachador.asignar_varios`, `confirmar_asignaciones`; `POST /api/viajes/lote` | `test_hungaro_optimo_frente_a_fuerza_bruta_y_codicioso`, `test_ejemplo_donde_codicioso_falla`, `test_asignacion_multiple_en_despachador`, `test_cancelacion_y_lote`; `reto_c_asignacion.png` | Óptimo validado contra fuerza bruta; −1,2 % a −8,3 % de espera total frente a la codiciosa | VERIFICADO |
| D — H3 frente a Quadtree | `experimental/indice_h3.py` (aislado) | `test_indice_h3_experimental_igual_a_lineal`; columnas H3 de `benchmark_busqueda.json` | Resultados idénticos a la lineal; 2,76 ms frente a 0,15 ms del Quadtree con 30 000 conductores | VERIFICADO |

## 5. Requisitos adicionales del encargo

| Requisito | Código / configuración | Evidencia | Estado |
|---|---|---|---|
| Interfaz comercial en español, sin explicaciones técnicas | `frontend/` (inicio, viaje, historial, operaciones) | Revisión de textos y capturas; ninguna mención a Quadtree, Dijkstra, Docker, etc. en las páginas | VERIFICADO |
| Solicitud por dirección, coordenadas y mapa conectada al backend | `frontend/js/viaje.js` | Prueba Playwright: las tres formas, errores de cobertura y dirección inexistente; sin errores de consola | VERIFICADO |
| Seguimiento por turnos, cancelación, historial | `viaje.js`, `historial.html`, `api/main.py` | Prueba Playwright (estado pasa de «en camino» a «en viaje»); `test_flujo_completo_solicitud_seguimiento_historial`, `test_cancelacion_y_lote` | VERIFICADO |
| Responsive | `frontend/css/estilos.css` | Captura a 390 px sin desplazamiento horizontal | VERIFICADO |
| Transparencia sobre datos simulados | Pie de todas las páginas, informe y README | Revisión | VERIFICADO |
| Docker Compose: frontend, backend, postgres, worker; volúmenes, redes internas, healthchecks | `compose.yaml`, `docker/*.Dockerfile`, `docker/nginx.conf`, `.env.example` | `docker compose up --build -d` → 4 servicios *healthy*; solicitud por `http://localhost:8080`; PostgreSQL con solicitudes registradas | VERIFICADO (Linux) |
| Coordinación explícita backend ↔ worker y una sola versión de la flota | `api/persistencia.py`, `api/worker.py`, [`docs/ARQUITECTURA.md`](ARQUITECTURA.md) | `test_solicitudes_concurrentes_no_comparten_conductor`; `docker compose restart worker` ⇒ «Simulación restaurada en el turno 12» | VERIFICADO |
| Docker Desktop en Windows 10/11 y PowerShell | `compose.yaml`, `scripts/iniciar_docker.ps1`, `scripts/iniciar_local.ps1`, README | No hay Windows en este entorno | IMPLEMENTADO SIN VERIFICAR |
| Geocodificación en vivo desde el contenedor `backend` | Red `externa` en `compose.yaml` | En este sandbox los contenedores no resuelven DNS externos; funcionó con la caché. Fuera del contenedor la consulta en vivo sí se verificó | IMPLEMENTADO SIN VERIFICAR |
| Presentación HTML independiente (demo, arquitectura, algoritmos, complejidades, benchmarks, retos, preguntas, ejercicios) | `presentacion/index.html` (19 diapositivas) | Abierta en navegador, sin errores de consola | VERIFICADO |
| `.gitignore`, `.env.example`, sin secretos | Raíz del repositorio | `.env` ignorado; solo valores de ejemplo | VERIFICADO |
| Sustentación individual (explicar y modificar código) | Guía de preguntas y ejercicios en la presentación | Depende de cada integrante | PENDIENTE |
| Fechas de hitos | — | El documento las deja en blanco; las fija el docente | PENDIENTE |

## 6. Correspondencia con la rúbrica (20 puntos)

| Criterio (pts) | Qué pide el nivel «Logrado» | Dónde se evidencia |
|---|---|---|
| Estructuras propias (5) | Quadtree, Dijkstra y Haversine propios, correctos y con la nomenclatura | Secciones 1–2; `tests/test_quadtree.py`, `tests/test_rutas.py`; prueba AST de librerías prohibidas |
| Funcionalidad completa (4) | RF-01 a RF-09, con mapa y simulación demostrados en vivo | Sección 1; web + centro de operaciones; `mapas/` |
| Complejidad y benchmark (3) | Big-O justificado por operación, contrastado con mediciones, gráficos interpretados | `informe.pdf` secciones 3–5; `benchmark/resultados/` |
| Pruebas automatizadas (2) | ≥ 10 casos con casos límite; todos pasan | 52 pruebas, todas pasan |
| Repositorio y calidad (2) | README claro, instalación reproducible, commits de todos, código modular | README, Docker, módulos separados; commits del equipo **pendientes** |
| Sustentación individual (4) | Explicar cualquier parte y resolver la modificación en vivo | `presentacion/index.html` (preguntas difíciles y ejercicios); **depende de cada integrante** |
| Retos opcionales (+2) | A*, hora punta, varios pasajeros, H3 | Sección 4 |

## 7. Bloqueos externos encontrados y cómo resolverlos

1. **Overpass no respondía** desde el entorno de desarrollo (cortes de conexión y tiempos de espera). Se resolvió con la ruta alternativa de la API oficial de OSM, aplicando el mismo filtro y los mismos pasos de osmnx. Para probar la ruta Overpass en otro equipo: `python -m datos.red_vial --forzar --fuente overpass`.
2. **Windows/Docker Desktop no disponible** en este entorno. Para verificarlo: en Windows con Docker Desktop, `powershell -ExecutionPolicy Bypass -File scripts\iniciar_docker.ps1` y abrir `http://localhost:8080`.
3. **Contenedores sin DNS externo** en este sandbox (solo afecta a direcciones nuevas en Docker). En Docker Desktop el servicio `backend` sale a Internet por la red `externa`; para comprobarlo, buscar una dirección que no esté en la caché, por ejemplo «Avenida Arequipa 4500».
4. **Commits de los integrantes**: cada miembro debe aportar desde su cuenta; no se fabricaron commits a nombre de nadie.
