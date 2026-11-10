# Arquitectura de LimaGo

## Capas

```
            Navegador (HTML/CSS/JS + Leaflet)
                       │  HTTP
             ┌─────────▼─────────┐
             │ frontend · Nginx  │  sirve frontend/, reenvía /api → backend
             └─────────┬─────────┘
             ┌─────────▼─────────┐        ┌──────────────────────┐
             │ backend · FastAPI │◄──────►│ postgres             │
             │ geocodifica,      │ SQL    │ comandos (cola)      │
             │ valida, encola    │        │ solicitudes (hist.)  │
             └───────────────────┘        │ estado_simulacion    │
                                          └──────────▲───────────┘
                                                     │ SQL
                                          ┌──────────┴───────────┐
                                          │ worker               │
                                          │ Simulador            │
                                          │  └ Despachador       │
                                          │     ├ Quadtree       │
                                          │     └ Dijkstra       │
                                          └──────────▲───────────┘
                                                     │ /metrics (:9100)
   ┌──────────────┐  consulta   ┌──────────────┐     │
   │ grafana      │────────────►│ prometheus   │─────┘ y backend /metrics (:8000)
   │ :3000 (local)│             │ :9090 (local)│
   └──────────────┘             └──────────────┘
```

Los algoritmos (`estructuras/`, `algoritmos/`, `simulacion/`) no importan nada de `api/` ni de la base de datos: se prueban directamente con pytest y se usan igual desde los scripts de benchmark y de mapas.

## Mecanismo de coordinación backend ↔ worker

Problema: el backend y el worker son procesos distintos (contenedores distintos). Si cada uno tuviera su propia flota en memoria habría dos versiones que divergen.

Solución (`api/persistencia.py`, `api/worker.py`):

1. **El worker es el único dueño de la flota.** Solo él tiene en memoria el `Simulador`, el `Despachador`, el Quadtree y la lista de conductores, y solo él los modifica.
2. **Cola de comandos.** El backend no toca la flota: inserta una fila en `comandos` (`solicitar_viaje`, `cancelar_viaje`, `asignar_lote`, `pausar`, `reanudar`, `avanzar`, `reiniciar`) y espera hasta 15 s a que el worker la marque `hecho` o `error`.
3. **Un solo consumidor, en orden.** El worker toma los comandos pendientes por `id` creciente y los ejecuta uno por uno. Dos solicitudes simultáneas se serializan: es imposible asignar el mismo conductor dos veces. Además, `Despachador.solicitar_viaje` usa un candado y verifica la disponibilidad antes de ocupar al conductor.
4. **Instantánea versionada.** Tras cada turno o comando, el worker reescribe la fila única de `estado_simulacion` (turno, hora, flota completa, estado del generador aleatorio) e incrementa `version`. El backend responde `/api/flota` y el seguimiento de viajes leyendo esa fila.
5. **Latido.** El worker actualiza `latido_en` cada 2 s; el *health check* del contenedor (`python -m api.salud_worker`) falla si pasa más de 20 s sin latido.
6. **Persistencia.** Al reiniciarse, el worker restaura la instantánea (incluido el estado del generador aleatorio), así que la simulación continúa exactamente donde quedó. Verificado con `docker compose restart worker`.

El backend también carga la red vial, pero **solo para lectura** (validar cobertura, geocodificar y convertir listas de intersecciones en polilíneas). No contiene conductores.

## Docker Compose

| Servicio | Imagen | Redes | Volumen | Health check |
|---|---|---|---|---|
| `frontend` | `nginx:1.27-alpine` + `frontend/` | interna, externa (puerto 8080) | — | `wget http://127.0.0.1/` |
| `backend` | `python:3.12-slim` + código | interna, externa (Nominatim) | `cache_geocodificacion` | `GET /api/salud` |
| `worker` | misma imagen que backend | solo interna | — | latido en PostgreSQL |
| `postgres` | `postgres:16-alpine` | solo interna | `datos_postgres` | `pg_isready` |
| `prometheus` (V2) | `prom/prometheus:v2.55.1` | interna, externa (puerto en 127.0.0.1) | `datos_prometheus` | `/-/healthy` |
| `grafana` (V2) | `grafana/grafana:11.3.0` | interna, externa (puerto en 127.0.0.1) | `datos_grafana` | `/api/health` |

La red `interna` está marcada `internal: true`: PostgreSQL y el worker no tienen salida a Internet.

## Monitoreo (V2)

- **Qué se mide** (`api/metricas.py`): peticiones HTTP por ruta, método y código; latencia (histograma); disponibilidad de la base de datos y latido del worker; solicitudes activas; turnos ejecutados y su duración; asignaciones por canal y resultado; ETA asignado; tiempo de cálculo de cada asignación; comandos procesados; viajes completados; conductores por estado; turno, pausa y hora punta.
- **Dónde**: la API publica `GET /metrics` (puerto 8000, red interna) y el worker `:9100/metrics` (red interna). Nginx **no** reenvía `/metrics`, así que no son públicas.
- **Prometheus** (`docker/prometheus/prometheus.yml`) lee `backend:8000` y `worker:9100` cada 10 s y guarda 7 días.
- **Grafana** se aprovisiona sola: datasource (`docker/grafana/provisioning/datasources/`) y el dashboard «LimaGo · Operación» con 14 paneles (`docker/grafana/dashboards/limago.json`, generado por `scripts/generar_dashboard_grafana.py`). Todas las consultas usan métricas reales; no hay valores fijos.
- Estas métricas sirven para operar el servicio. **No sustituyen** a los benchmarks académicos de RF-09 (`benchmark/`).

## Autorización del centro de operaciones (V2)

Las rutas `/api/operaciones/*` y `/api/viajes/lote` exigen `Authorization: Bearer <LIMAGO_TOKEN_OPERACIONES>` (comparación en tiempo constante con `hmac.compare_digest`). Si el código no está configurado, esas funciones responden 503 y quedan deshabilitadas. La página `operaciones.html` guarda el código solo en `sessionStorage` (se borra al cerrar la pestaña) y no aparece en la navegación principal (solo en la franja inferior del footer).

## ¿Redis? Evaluado y descartado

Se evaluó Redis (colas, pub/sub) para la coordinación backend ↔ worker. No se agregó porque:

1. PostgreSQL ya es la cola de comandos con un único consumidor y la fuente de la instantánea versionada; introducir Redis crearía **otra** fuente de estado que habría que mantener consistente.
2. La latencia de la cola actual (sondeo cada 50 ms) es imperceptible frente al tiempo de un turno (1,5 s), y está medida en Grafana.
3. No hay caché que justificar: la red vial está en memoria y las búsquedas de direcciones ya tienen caché en disco.
4. Redis GEO está prohibido como sustituto del Quadtree.

Si en el futuro hiciera falta empujar eventos en tiempo real al navegador, la alternativa sin servicio nuevo sería `LISTEN/NOTIFY` de PostgreSQL.

## Capas del código (V2)

| Capa | Ubicación |
|---|---|
| Presentación | `frontend/` (`js/plantilla.js` cabecera y footer comunes, `js/comun.js` API y selector de lugar) |
| API | `api/main.py` |
| Lógica de negocio | `simulacion/tarifas.py` (tarifas orientativas), `simulacion/ubicacion.py` (cobertura) |
| Algoritmos | `estructuras/`, `algoritmos/` (sin cambios de comportamiento respecto a la V1) |
| Simulación | `simulacion/turnos.py`, `simulacion/despachador.py`, `api/worker.py` |
| Persistencia | `api/persistencia.py` (con migración ligera de columnas nuevas) |
| Observabilidad | `api/metricas.py`, `docker/prometheus/`, `docker/grafana/` |

## Flujo de una solicitud

1. `viaje.html` → `POST /api/viajes` con texto o coordenadas.
2. El backend geocodifica (Nominatim, restringido a Miraflores, 1 petición/s, caché en disco). Si la dirección es ambigua responde 409 con opciones; si no existe, 422.
3. El backend encola `solicitar_viaje` y espera.
4. El worker ubica al pasajero en la intersección más cercana con un Quadtree de intersecciones (rechaza puntos a más de 250 m de una vía), obtiene los *k* candidatos con el Quadtree de conductores, ejecuta un Dijkstra inverso, elige el menor ETA, ocupa al conductor y registra la solicitud.
5. El navegador consulta `GET /api/viajes/{id}` cada 1,5 s y dibuja la posición del conductor y la ruta restante.
6. En cada turno el conductor avanza; al recoger al pasajero la solicitud pasa a `en_viaje` y al llegar al destino a `completada`, y el conductor queda disponible.

## Ampliación V3

```
Navegador ──► Nginx (estáticos, gzip, Cache-Control) ──► FastAPI (lecturas, cotizaciones, comandos)
                                                            │  cola de comandos + instantánea versionada
                                                            ▼
                                     PostgreSQL ◄──── Worker (único dueño de la flota)
                                                            │ turno: reloj de Lima → conexiones → ofertas
                                                            │ (MotorAceptacion) → recogida/espera → viaje → demanda
                                                            ▼
                                     Quadtree propio · Dijkstra propio (grafo inverso) · UnidadesApoyo (Quadtree)
```

- **Escenarios:** `config/ajustes.py:ESCENARIOS` define `miraflores` (académico, valores del informe) y `lima` (comercial). `LIMAGO_ESCENARIO` elige uno; benchmarks, mapas e informe usan siempre `ajustes_academicos()`.
- **Red metropolitana:** se prepara una vez (`datos/red_metropolitana.py`) y se guarda en formato compacto `.npz`; backend y worker la cargan en 2–3 s (~0,5 GB cada uno).
- **Cotizaciones:** el backend calcula ruta, duración (con el tráfico de la hora) y tarifa, y guarda la cotización en la tabla `cotizaciones` (5 min). Confirmar envía el comando `solicitar` con esa cotización: el precio no cambia después.
- **Ofertas:** con el motor activo, el worker obtiene los k candidatos (Quadtree + Dijkstra inverso, igual que la función académica), guarda el óptimo académico y ofrece el viaje en orden de ETA. Cada conductor pasa a `oferta_pendiente`; su decisión se resuelve en turnos posteriores según su política. El resultado (`oferta_aceptada`, `oferta_rechaza`, `oferta_vencida`, `sin_aceptacion`) se persiste en `solicitudes.intentos`.
- **Estados:** la tabla `TRANSICIONES` de `simulacion/modelos.py` es la única autoridad; `Despachador.cambiar_estado` la valida.
- **Seguimiento:** `GET /api/viajes/{id}` devuelve la posición interpolada y el rumbo del conductor sobre la geometría del tramo, la ruta restante y el estado de la simulación (en pausa, turno, intervalo real). El navegador solo anima entre dos respuestas.
- **Alertas:** comando `alerta` → fila en `alertas` (deduplicada por viaje) → `UnidadesApoyo.asignar_mas_cercana` (Quadtree propio sobre unidades simuladas) → operaciones la ve en `/api/operaciones/alertas` y la atiende. No hay integración con servicios reales.
- **Caché HTTP:** ver [`CDN_Y_RENDIMIENTO.md`](CDN_Y_RENDIMIENTO.md).
