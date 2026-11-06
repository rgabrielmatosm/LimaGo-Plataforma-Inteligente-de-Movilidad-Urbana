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
                                          └──────────────────────┘
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

La red `interna` está marcada `internal: true`: PostgreSQL y el worker no tienen salida a Internet. No se agregaron Prometheus ni Grafana porque no son necesarios para los requisitos.

## Flujo de una solicitud

1. `viaje.html` → `POST /api/viajes` con texto o coordenadas.
2. El backend geocodifica (Nominatim, restringido a Miraflores, 1 petición/s, caché en disco). Si la dirección es ambigua responde 409 con opciones; si no existe, 422.
3. El backend encola `solicitar_viaje` y espera.
4. El worker ubica al pasajero en la intersección más cercana con un Quadtree de intersecciones (rechaza puntos a más de 250 m de una vía), obtiene los *k* candidatos con el Quadtree de conductores, ejecuta un Dijkstra inverso, elige el menor ETA, ocupa al conductor y registra la solicitud.
5. El navegador consulta `GET /api/viajes/{id}` cada 1,5 s y dibuja la posición del conductor y la ruta restante.
6. En cada turno el conductor avanza; al recoger al pasajero la solicitud pasa a `en_viaje` y al llegar al destino a `completada`, y el conductor queda disponible.
