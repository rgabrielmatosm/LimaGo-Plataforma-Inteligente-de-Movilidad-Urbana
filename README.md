# LimaGo — Plataforma Inteligente de Movilidad Urbana

**Proyecto Integrador N.° 2 · Asignación del conductor más cercano** · Algoritmos y Estructura de Datos II

LimaGo es una aplicación de movilidad urbana (estilo Uber, Cabify o InDrive) que funciona sobre la **red vial real de Miraflores, Lima**, descargada de OpenStreetMap. Cuando un pasajero pide un viaje:

1. un **Quadtree propio** y un **heap** obtienen los *k* conductores disponibles más cercanos en línea recta (fórmula de **Haversine** propia);
2. un **Dijkstra propio** calcula la distancia real por calles de esos *k* candidatos respetando los sentidos de circulación;
3. se asigna el conductor con **menor tiempo estimado de llegada (ETA)**, que no siempre es el más cercano en línea recta.

La flota y la demanda son **simuladas** (semilla fija y reproducible); las calles, distancias y sentidos son reales.

| Entregable | Ubicación |
|---|---|
| Código de los algoritmos | `estructuras/`, `algoritmos/`, `simulacion/` |
| Red vial descargada | `datos/miraflores.graphml` (procedimiento en [`datos/README.md`](datos/README.md)) |
| Mapas folium (≥ 3 asignaciones) | `mapas/*.html` |
| Benchmark y gráficos | `benchmark/` y `benchmark/resultados/` |
| Pruebas pytest | `tests/` |
| Informe técnico (3–5 págs.) | [`informe.pdf`](informe.pdf) |
| Presentación para la sustentación | [`presentacion/index.html`](presentacion/index.html) |
| Matriz de cumplimiento | [`docs/MATRIZ_CUMPLIMIENTO.md`](docs/MATRIZ_CUMPLIMIENTO.md) |
| Arquitectura y coordinación | [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) |
| Trabajo en equipo con ramas | [`docs/CONTRIBUCION.md`](docs/CONTRIBUCION.md) |

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

Arquitectura: `frontend` (Nginx) · `backend` (FastAPI) · `worker` (simulación por turnos) · `postgres` (persistencia). Detalles en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

```powershell
Copy-Item .env.example .env
```

Edite `.env` y cambie `POSTGRES_PASSWORD`. Luego:

```powershell
docker compose up --build -d
```

```powershell
docker compose ps
```

Cuando los cuatro servicios aparezcan como `healthy`, abra **http://localhost:8080**.

O todo en un paso (crea `.env` con una contraseña aleatoria):

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

Usa SQLite (`datos/limago.db`) en lugar de PostgreSQL. Necesita dos terminales con el entorno activado:

```powershell
python -m api.worker
```

```powershell
python -m uvicorn api.main:app --port 8000
```

Abra **http://localhost:8000** (la API sirve también el frontend). Atajo: `powershell -ExecutionPolicy Bypass -File scripts\iniciar_local.ps1`.

### Páginas

| Página | Para qué |
|---|---|
| `index.html` | Inicio, cobertura y conductores disponibles |
| `viaje.html` | Pedir un viaje por **dirección**, **coordenadas** o **tocando el mapa**; seguimiento en vivo; cancelar |
| `historial.html` | Solicitudes con conductor, ETA, estado y resultado |
| `operaciones.html` | Centro de operaciones (enlace «Acceso operadores» en el pie): pausar, continuar, avanzar turnos y reiniciar el escenario |

### API principal

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/salud` | Estado de la API, la base de datos y el worker |
| GET | `/api/geocodificar?q=` | Busca direcciones dentro de Miraflores |
| POST | `/api/viajes` | Solicita un viaje (`{"origen": {"texto": "Parque Kennedy"}, "destino": {"lat": -12.13, "lon": -77.03}}`) |
| GET | `/api/viajes/{id}` | Estado, conductor y ruta restante |
| GET | `/api/viajes?canal=app` | Historial |
| POST | `/api/viajes/lote` | Varios pasajeros a la vez (Reto C) |
| GET | `/api/flota` | Posiciones y estados de la flota |
| POST | `/api/operaciones/{pausar,reanudar,avanzar,reiniciar}` | Control de la simulación |

Documentación interactiva: `http://localhost:8000/docs`.

## 5. Preparación de los datos OSM

La red ya está en `datos/miraflores.graphml`; no hace falta descargarla. Para regenerarla:

```powershell
python -m datos.red_vial --forzar
```

Procedimiento completo, ruta alternativa (API oficial de OSM) y estadísticas en [`datos/README.md`](datos/README.md).

## 6. Pruebas

```powershell
python -m pytest -q
```

Cubren Quadtree vacío, conductores coincidentes, bordes, inserción, eliminación, búsqueda rectangular, actualización, k candidatos exactos frente a búsqueda lineal, conductores no disponibles, Haversine, Dijkstra frente a networkx (malla sintética y Miraflores), reconstrucción de rutas, sentido único, destinos inaccesibles, selección por menor ETA, pasajero sin conexión vial, flota reproducible, simulación por turnos, solicitudes concurrentes, congestión, A*, asignación múltiple, H3, geocodificación y la integración API + worker + base de datos. Además, una prueba analiza el código para garantizar que la solución no usa librerías prohibidas.

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

## 9. Configuración

Todos los parámetros se cambian con variables `LIMAGO_*` (ver [`.env.example`](.env.example) y `config/ajustes.py`): semilla, número de conductores, proporción de ocupados, *k*, velocidad promedio, capacidad y profundidad del Quadtree, duración del turno, demanda simulada, hora inicial y congestión.

```powershell
$env:LIMAGO_NUM_CONDUCTORES = "3000"; $env:LIMAGO_K_CANDIDATOS = "8"; python -m api.worker
```

## 10. Solución de problemas frecuentes

| Problema | Solución |
|---|---|
| `POSTGRES_PASSWORD` requerido al hacer `docker compose up` | Falta el archivo `.env`: `Copy-Item .env.example .env`. |
| El puerto 8080 está ocupado | Cambie `LIMAGO_PUERTO_WEB` en `.env`. |
| `docker compose` no responde en Windows | Abra Docker Desktop y espere a que diga *Engine running*; verifique WSL 2 (`wsl --status`). |
| «El servicio está tardando más de lo normal» | El worker no está corriendo: `docker compose logs worker` o inicie `python -m api.worker`. |
| «El servicio de direcciones no está disponible» | Sin acceso a `nominatim.openstreetmap.org`. Use coordenadas o el mapa; las direcciones ya buscadas funcionan desde la caché. |
| No se ve el mapa base | El navegador necesita acceso a `tile.openstreetmap.org`. |
| `Activate.ps1 no se puede cargar` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| Error al instalar `osmnx`/`geopandas` en Windows | Actualice pip (`python -m pip install --upgrade pip`) y use Python 3.11–3.13 de 64 bits. |
| La descarga de OSM falla | No es necesaria: la red está en `datos/`. Si fuerza la descarga, se intenta Overpass y luego la API oficial de OSM. |
| Quiero empezar el escenario de cero | Centro de operaciones → Reiniciar, o `docker compose down -v`. |

## 11. Estructura del repositorio

```
├── datos/            red vial descargada (RF-01) y su procedimiento
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
├── docker/           Dockerfiles y configuración de Nginx
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
