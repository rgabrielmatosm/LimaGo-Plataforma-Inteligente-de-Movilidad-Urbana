# LimaGo — Plataforma Inteligente de Movilidad Urbana

**Proyecto Integrador N.° 2 · Asignación del conductor más cercano** · Algoritmos y Estructura de Datos II

LimaGo es una aplicación demostrativa de movilidad urbana que funciona sobre la **red vial real de Lima Metropolitana** (V3) y conserva **Miraflores** como escenario académico y de benchmark, ambos descargados de OpenStreetMap. Cuando un pasajero pide un viaje:

1. un **Quadtree propio** y un **heap** obtienen los *k* conductores disponibles más cercanos en línea recta (fórmula de **Haversine** propia);
2. un **Dijkstra propio** calcula la distancia real por calles de esos *k* candidatos respetando los sentidos de circulación;
3. se asigna el conductor con **menor tiempo estimado de llegada (ETA)**, que no siempre es el más cercano en línea recta.

La flota y la demanda son **simuladas** (semilla fija y reproducible); las calles, distancias y sentidos son reales.

**Versión 3.0 (rama `feature/limago-v3`):** cobertura de los **50 distritos de Lima Metropolitana** (provincias de Lima y Callao; 152 441 intersecciones, 33 084 km de tramos) con límite poligonal real; ubicación del navegador con permiso; flujo comercial cotizar → confirmar → ofertas → aceptación → seguimiento; **motor de aceptación** con políticas por conductor; estados explícitos del conductor; vehículo animado sobre la ruta; **tarifa dinámica en soles** con desglose; tráfico automático por la **hora de Lima** (modelo horario, no tráfico real); **alerta de seguridad simulada**; centro de operaciones ampliado; caché HTTP y compresión. Detalle y separación entre requisitos del profesor, feedback y mejoras del equipo: [`docs/MEJORAS_V3.md`](docs/MEJORAS_V3.md).

**Versión 2.0:** sitio web multipágina (inicio, pedir viaje, seguimiento, historial, cobertura, tarifas, ayuda, nosotros, información legal), footer corporativo compartido, modo claro/oscuro, centro de operaciones protegido con código, tarifas orientativas, y monitoreo con Prometheus y Grafana. Los algoritmos y entregables académicos de la versión 1 se conservan sin cambios de comportamiento (referencia recuperable: etiqueta Git local `v1.0-base`).

| Entregable | Ubicación |
|---|---|
| Código de los algoritmos | `estructuras/`, `algoritmos/`, `simulacion/` |
| Red vial descargada | `datos/miraflores.graphml` (académica) y `datos/lima/` (V3) — procedimiento en [`datos/README.md`](datos/README.md) |
| Mapas folium (≥ 3 asignaciones) | `mapas/*.html` |
| Benchmark y gráficos | `benchmark/` y `benchmark/resultados/` |
| Pruebas pytest | `tests/` |
| Informe técnico (3–5 págs.) | [`informe.pdf`](informe.pdf) |
| Presentación para la sustentación | [`presentacion/index.html`](presentacion/index.html) |
| Matriz de cumplimiento | [`docs/MATRIZ_CUMPLIMIENTO.md`](docs/MATRIZ_CUMPLIMIENTO.md) |
| Arquitectura, coordinación y monitoreo | [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) |
| Trabajo en equipo con ramas | [`docs/CONTRIBUCION.md`](docs/CONTRIBUCION.md) |
| Mejoras V3 (requisitos / feedback / equipo) | [`docs/MEJORAS_V3.md`](docs/MEJORAS_V3.md) |
| Caché, CDN y rendimiento | [`docs/CDN_Y_RENDIMIENTO.md`](docs/CDN_Y_RENDIMIENTO.md) |

---

## 1. Requisitos previos

- **Windows 10/11** (también funciona en macOS y Linux).
- **Python 3.11 o superior** (probado con 3.12 en Docker y 3.13 en local). En Windows: instalar desde python.org marcando *Add python.exe to PATH*.
- **Git**.
- Para el despliegue completo: **Docker Desktop** con WSL 2 activado.
- Conexión a Internet solo para buscar direcciones nuevas (Nominatim) y ver el mapa base. La red vial ya está en el repositorio.

## 2. Instalación en Windows (PowerShell)

```powershell
git clone https://github.com/rgabrielmatosm/LimaGo-Plataforma-Inteligente-de-Movilidad-Urbana.git
```

```powershell
cd LimaGo-Plataforma-Inteligente-de-Movilidad-Urbana
```

```powershell
py -3 -m venv .venv
```

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
python -m pip install -r requirements-dev.txt
```

> Si PowerShell bloquea la activación del entorno: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

En macOS/Linux use `python3 -m venv .venv` y `source .venv/bin/activate`.

## 3. Ejecución con Docker Compose (recomendada)

Seis servicios: `frontend` (Nginx) · `backend` (FastAPI) · `worker` (simulación por turnos) · `postgres` (persistencia) · `prometheus` (métricas) · `grafana` (paneles). Detalles en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

```powershell
Copy-Item .env.example .env
```

Este paso es **opcional**: si no existe `.env`, Docker usa los valores por defecto y todas las contraseñas son **`LimaGoPass`** (PostgreSQL, código del centro de operaciones y Grafana con usuario `admin`). Son contraseñas de demostración: cámbielas en `.env` si publica el sitio fuera de su equipo. Requiere Docker Compose 2.24 o superior (incluido en Docker Desktop actual). `LIMAGO_ESCENARIO=lima` (por defecto) levanta la aplicación metropolitana; `miraflores` el escenario académico del informe.

> **Si vienes de la V2:** vuelve a copiar `.env.example`. Un `.env` de la V2 define `LIMAGO_NUM_CONDUCTORES=300`, `LIMAGO_SEGUNDOS_POR_TURNO=30`, etc., que reemplazarían los valores del escenario de Lima. `scripts\iniciar_docker.ps1` lo detecta y avisa.

La red de Lima ocupa ~0,5 GB de memoria por proceso (backend y worker, límite de 1,5 GB cada uno en `compose.yaml`): asigne al menos **4 GB** a Docker Desktop. El primer arranque tarda ~30 s mientras se carga la red. Luego:

```powershell
docker compose up --build -d
```

```powershell
docker compose ps
```

Cuando los seis servicios aparezcan como `healthy`:

| Servicio | Dirección | Acceso |
|---|---|---|
| Sitio web | **http://localhost:8080** | Público |
| Centro de operaciones | http://localhost:8080/operaciones.html | Código `LIMAGO_TOKEN_OPERACIONES` |
| Grafana (dashboard «LimaGo · Operación») | http://localhost:3000 | Usuario y contraseña `GRAFANA_ADMIN_*` |
| Prometheus | http://localhost:9090 | Solo desde el propio equipo |

Grafana y Prometheus se publican solo en `127.0.0.1`. Las métricas (`/metrics`) no se exponen por el puerto web.

O todo en un paso (crea `.env` con contraseñas aleatorias):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\iniciar_docker.ps1
```

Comandos útiles:

```powershell
docker compose logs -f worker
```

```powershell
docker compose down
```

```powershell
docker compose down -v
```

(`down -v` borra también el volumen de PostgreSQL: historial e instantánea de la simulación.)

## 4. Ejecución local sin Docker

Usa SQLite (`datos/limago.db`) en lugar de PostgreSQL. El escenario por defecto es Lima (`$env:LIMAGO_ESCENARIO = "miraflores"` para el académico). Defina un código de operador (si no, el centro de operaciones queda deshabilitado) y use dos terminales con el entorno activado:

```powershell
$env:LIMAGO_TOKEN_OPERACIONES = "elige-un-codigo"
```

```powershell
python -m api.worker
```

```powershell
python -m uvicorn api.main:app --port 8000
```

En la segunda terminal defina también `$env:LIMAGO_TOKEN_OPERACIONES` con el mismo valor. Abra **http://localhost:8000** (la API sirve también el frontend). Atajo: `powershell -ExecutionPolicy Bypass -File scripts\iniciar_local.ps1`. El worker expone sus métricas en `http://localhost:9100/metrics` (`LIMAGO_PUERTO_METRICAS_WORKER=0` lo desactiva).

### Páginas

Cabecera y footer se generan desde un único archivo (`frontend/js/plantilla.js`); cada página solo declara `data-cabecera` y `data-pie`.

| Página | Para qué |
|---|---|
| `index.html` | Inicio: destino rápido, conductores disponibles cercanos, cifras del escenario, beneficios, cobertura, preguntas frecuentes |
| `viaje.html` | Ubicación del navegador (con permiso, sin volver a preguntar) o dirección/coordenadas/mapa; destino con sugerencias; cotización con desglose; confirmación y búsqueda de un conductor que acepte |
| `seguimiento.html` | Línea de tiempo de 5 pasos, vehículo animado sobre la ruta con orientación, ETA, alerta de seguridad simulada y cancelación |
| `historial.html` | Mis viajes: filtros por estado, búsqueda, tarjetas o tabla; detalle con distritos, ofertas enviadas y tarifa confirmada |
| `cobertura.html` | Límite metropolitano, capa de distritos, lista buscable de los 50 distritos y verificador «¿Llegamos a tu punto?» |
| `tarifas.html` | Cotización con el tráfico de la hora de Lima y desglose (base, recorrido, tiempo, recogida) |
| `ayuda.html` | Centro de ayuda con buscador |
| `nosotros.html` | Concepto del servicio y aviso de simulación |
| `legal.html` | Privacidad, términos de uso e información de la simulación |
| `operaciones.html` | Centro de operaciones (código de operador): flota completa por estado, unidades de apoyo, alertas con «Atender», aceptación operativa vs óptimo académico, pausa/avance/reinicio, reloj de Lima u hora fija (8:00/15:00), demanda, k y lotes |

### API principal

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/salud` | Estado de la API, la base de datos y el worker |
| GET | `/api/geocodificar?q=` | Busca direcciones dentro de la zona de cobertura del escenario |
| GET | `/api/ubicacion/ajustar?lat=&lon=` | V3: ubicación del navegador → punto sobre la vía más cercana, dirección y distrito |
| GET | `/api/conductores/cercanos?lat=&lon=&n=` | V3: conductores disponibles más cercanos (Quadtree propio) |
| GET | `/api/trafico` | V3: nivel de tráfico estimado por la hora de Lima (modelo horario, indica que no es tráfico real) |
| GET | `/api/distritos` | V3: GeoJSON de los 50 distritos |
| POST | `/api/viajes/cotizar` | V3: ruta, duración, tarifa con desglose y `cotizacion_id` (vigente 5 min) |
| POST | `/api/viajes` | Solicita un viaje; en V3 con `{"cotizacion_id": "..."}` (404 si no existe, 410 si venció, 409 si ya se usó) |
| POST | `/api/viajes/{id}/alerta` | V3: alerta de seguridad simulada (deduplicada; solo con viaje activo) |
| GET | `/api/viajes/{id}` | Estado, conductor y ruta restante |
| GET | `/api/viajes?canal=app` | Historial |
| POST | `/api/viajes/lote` | Varios pasajeros a la vez (Reto C) |
| GET | `/api/viajes?canal=app&estado=asignada,en_viaje&antes_de=` | Historial con filtros y paginación |
| POST | `/api/viajes/{id}/cancelar` | Cancela mientras se busca conductor, va en camino o espera al pasajero |
| GET | `/api/flota` | Posiciones y estados de la flota (`?detalle=false`: solo conteo) |
| GET | `/api/estadisticas` | Indicadores públicos calculados en vivo |
| GET | `/api/cobertura`, `/api/cobertura/verificar?lat=&lon=` | Zona de servicio y verificación de un punto |
| GET / POST | `/api/tarifas`, `/api/tarifas/estimar` | Fórmula y estimación con ruta real (opcional `hora`) |
| GET | `/metrics` | Métricas Prometheus de la API (no publicado por Nginx) |

Operaciones (requieren `Authorization: Bearer <LIMAGO_TOKEN_OPERACIONES>`):

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/operaciones/sesion`, `/api/operaciones/resumen` | Validar código; indicadores y solicitudes activas |
| POST | `/api/operaciones/{pausar,reanudar,avanzar,reiniciar}` | Control de la simulación |
| POST | `/api/operaciones/configurar` | Hora punta, hora fija del escenario o `reloj_lima`, demanda y k |
| GET / POST | `/api/operaciones/alertas`, `/api/operaciones/alertas/{id}/atender` | Alertas y unidades de apoyo simuladas |
| POST | `/api/operaciones/lote`, `/api/viajes/lote` | Varios pasajeros a la vez (Reto C) |

Documentación interactiva: `http://localhost:8000/docs`.

## 5. Preparación de los datos OSM

La red académica ya está en `datos/miraflores.graphml` y la metropolitana en `datos/lima/lima_metropolitana.npz` (15 MB, formato compacto propio); no hace falta descargarlas. Para regenerarlas:

```powershell
python -m datos.red_vial --forzar
```

```powershell
python -m pip install -r requirements-preparacion.txt
```

```powershell
python -m datos.red_metropolitana --forzar
```

La preparación de Lima descarga ~30 MB (BBBike + API de OSM), tarda ~2–3 min y necesita ~2,5 GB de memoria; la aplicación solo carga el `.npz` (2–3 s).

Procedimiento completo, ruta alternativa (API oficial de OSM) y estadísticas en [`datos/README.md`](datos/README.md).

## 6. Pruebas

```powershell
python -m pytest -q
```

Cubren Quadtree vacío, conductores coincidentes, bordes, inserción, eliminación, búsqueda rectangular, actualización, k candidatos exactos frente a búsqueda lineal, conductores no disponibles, Haversine, Dijkstra frente a networkx (malla sintética y Miraflores), reconstrucción de rutas, sentido único, destinos inaccesibles, selección por menor ETA, pasajero sin conexión vial, flota reproducible, simulación por turnos, solicitudes concurrentes, congestión, A*, asignación múltiple, H3, geocodificación y la integración API + worker + base de datos. Además, una prueba analiza el código para garantizar que la solución no usa librerías prohibidas. La V2 añade pruebas de tarifas, cobertura, estadísticas, autorización de operaciones, configuración del escenario, lotes, métricas, migración de la base de datos, enlaces internos rotos y ausencia de términos técnicos en las páginas públicas La V3 añade 21 pruebas: transiciones de estado, conductores desconectados, aceptar/rechazar/vencer ofertas, reproducibilidad, concurrencia sin doble asignación, función académica intacta, pausa, tarifas y unidades, congestión sin doble conteo, reloj de Lima, cotización y confirmación, alertas, ubicación y cobertura poligonal (polígono propio = shapely en 400 puntos), los 50 distritos, ruta Miraflores → Comas, Quadtree metropolitano exacto, posición interpolada y recuperación tras reinicio (86 pruebas en total). Las que usan la red de Lima se omiten si falta `datos/lima/lima_metropolitana.npz`.

## 7. Mapas folium (RF-07)

```powershell
python -m scripts.generar_mapas
```

Genera en `mapas/` cuatro asignaciones distintas (Parque Kennedy, Larcomar, Óvalo Gutiérrez y una por coordenadas) con pasajero, conductores coloreados por estado, los *k* candidatos, el seleccionado y la ruta. El resumen queda en `mapas/resumen_mapas.json`. El mapa del Reto B (`mapas/reto_b_congestion_8_vs_15.html`) lo genera el benchmark de retos.

## 8. Benchmarks (RF-09 y retos)

```powershell
python -m benchmark.benchmark_busqueda
```

```powershell
python -m benchmark.benchmark_rutas
```

```powershell
python -m benchmark.benchmark_retos
```

Resultados (JSON con condiciones experimentales, semillas y tiempos) y gráficos PNG en `benchmark/resultados/`. Para regenerar el informe con los nuevos números:

```powershell
python -m scripts.generar_informe
```

Resultados obtenidos en el equipo de desarrollo (mediana de 5 repeticiones, 400 consultas, k = 5):

| Conductores | Lineal | Quadtree | Aceleración | Resultados idénticos |
|---|---|---|---|---|
| 300 | 0,137 ms | 0,032 ms | ×4,2 | 400/400 |
| 3 000 | 1,418 ms | 0,049 ms | ×29,0 | 400/400 |
| 30 000 | 12,824 ms | 0,152 ms | ×84,2 | 400/400 |

Dijkstra propio frente a networkx: 300/300 distancias idénticas (diferencia máxima 0 m). Los tiempos dependen del equipo: vuelva a medir en el suyo.

**V3 — red de Lima Metropolitana** (archivo aparte, no altera los resultados académicos):

```powershell
python -m benchmark.benchmark_metropolitano
```

| Medición (152 441 intersecciones) | Resultado en el equipo de desarrollo |
|---|---|
| Carga del grafo compacto | 2,3 s · memoria pico del proceso 600 MB |
| Quadtree vs lineal, 300 / 3 000 / 30 000 conductores (k = 8) | ×3,3 / ×27,2 / ×232,8 · 300/300 idénticos en los tres |
| Dijkstra propio, mediana por distancia en línea recta | 0–3 km 3 ms · 3–8 km 29 ms · 8–15 km 60 ms · 15–25 km 149 ms · 25–40 km 287 ms |
| Dijkstra propio vs networkx (muestra) | 20/20 distancias idénticas |
| Despacho completo (Quadtree + Dijkstra inverso, 2 500 conductores, k = 8) | mediana 1,1 ms · p95 8,8 ms |

## 9. Configuración

`LIMAGO_ESCENARIO` elige el escenario (`lima` o `miraflores`, definidos en `config/ajustes.py`). Sobre él, las variables `LIMAGO_*` (ver [`.env.example`](.env.example)) cambian semilla, número de conductores, *k*, demanda, duración del turno, reloj (`lima` o `simulado`), hora inicial, congestión, motor de aceptación (plazo y probabilidad), unidades de apoyo y los parámetros de la tarifa. Una variable vacía conserva el valor del escenario. Benchmarks, mapas folium e informe usan siempre el escenario académico de Miraflores, independientemente de `LIMAGO_ESCENARIO`.

```powershell
$env:LIMAGO_NUM_CONDUCTORES = "3000"; $env:LIMAGO_K_CANDIDATOS = "8"; python -m api.worker
```

## 10. Solución de problemas frecuentes

| Problema | Solución |
|---|---|
| `POSTGRES_PASSWORD` requerido o `env file .env not found` | Versión antigua del proyecto o de Docker: use esta versión (contraseñas por defecto `LimaGoPass`) y actualice Docker Desktop. |
| El puerto 8080 está ocupado | Cambie `LIMAGO_PUERTO_WEB` en `.env`. |
| `docker compose` no responde en Windows | Abra Docker Desktop y espere a que diga *Engine running*; verifique WSL 2 (`wsl --status`). |
| «El servicio está tardando más de lo normal» | El worker no está corriendo: `docker compose logs worker` o inicie `python -m api.worker`. |
| «El servicio de direcciones no está disponible» | Sin acceso a `nominatim.openstreetmap.org`. Use coordenadas o el mapa; las direcciones ya buscadas funcionan desde la caché. |
| No se ve el mapa base | El navegador necesita acceso a `tile.openstreetmap.org`. |
| `Activate.ps1 no se puede cargar` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| Error al instalar `osmnx`/`geopandas` en Windows | Actualice pip (`python -m pip install --upgrade pip`) y use Python 3.11–3.13 de 64 bits. |
| La descarga de OSM falla | No es necesaria: la red está en `datos/`. Si fuerza la descarga, se intenta Overpass y luego la API oficial de OSM. |
| «El acceso de operadores no está configurado» | Defina `LIMAGO_TOKEN_OPERACIONES` en `.env` (Docker) o en la terminal (local) y reinicie el backend. |
| Grafana pide contraseña / no abre | Use `GRAFANA_ADMIN_USER` y `GRAFANA_ADMIN_PASSWORD` de `.env`; solo responde en `http://localhost:3000` del mismo equipo. |
| Paneles de Grafana sin datos | Espere 1–2 minutos (las tasas usan ventanas de 1–5 min) y use el sitio para generar tráfico. |
| El backend o el worker se reinician solos en Docker | Falta memoria: asigne ≥ 4 GB a Docker Desktop (Settings → Resources) o use `LIMAGO_ESCENARIO=miraflores`. |
| El navegador no pregunta por la ubicación | Ya respondiste antes (se recuerda en el navegador) o el sitio no se abrió con `localhost`/HTTPS. Escribe la dirección o marca el punto. |
| Se ven 300 conductores en Lima | Tu `.env` es de la V2: vuelve a copiar `.env.example`. |
| `container limago-backend-1 is unhealthy` y en `docker compose logs backend` aparece `password authentication failed` | La base de datos se creó antes con otra contraseña. Esta versión usa un volumen nuevo (`datos_postgres_v3`); si cambia `POSTGRES_PASSWORD` después, ejecute `docker compose down -v` y vuelva a levantar. |
| Quiero empezar el escenario de cero | Centro de operaciones → Reiniciar, o `docker compose down -v`. |

## 11. Estructura del repositorio

```
├── datos/            red vial de Miraflores (RF-01), red de Lima (datos/lima) y sus procedimientos
├── estructuras/      Quadtree propio, Haversine y búsqueda lineal de referencia
├── algoritmos/       grafo propio, Dijkstra, A*, congestión, algoritmo húngaro
├── simulacion/       Conductor, Pasajero, flota, Despachador, turnos, geocodificación
├── visualizacion/    mapas folium
├── experimental/     índice H3 (Reto D), aislado de la solución principal
├── mapas/            mapas HTML generados (RF-07)
├── benchmark/        benchmarks y resultados (RF-09)
├── tests/            pruebas pytest
├── api/              FastAPI, worker y persistencia
├── frontend/         sitio comercial (HTML/CSS/JS + Leaflet)
├── config/           parámetros configurables
├── docker/           Dockerfiles, Nginx, Prometheus y aprovisionamiento de Grafana
├── scripts/          generación de mapas e informe, scripts de PowerShell
├── docs/             arquitectura, matriz de cumplimiento, contribución
├── presentacion/     presentación HTML para la sustentación
├── compose.yaml
├── informe.pdf
└── README.md
```

## 12. Trabajo en equipo

Cada integrante debe registrar sus propios commits desde su propia cuenta. El flujo de ramas, la convención de mensajes y la forma de repartir módulos están en [`docs/CONTRIBUCION.md`](docs/CONTRIBUCION.md).

---

Datos viales © colaboradores de OpenStreetMap (ODbL). Leaflet © sus autores (BSD-2). Proyecto académico sin fines comerciales.
