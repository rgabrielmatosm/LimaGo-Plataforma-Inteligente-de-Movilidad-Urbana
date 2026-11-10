# CDN, Nginx y caché del navegador en LimaGo

> **Estado actual: LimaGo no usa un CDN.** Los archivos estáticos los sirve Nginx (contenedor `frontend`) y el navegador los guarda en caché según las cabeceras configuradas en `docker/nginx.conf`. Los mapas base se cargan desde los servidores de teselas de OpenStreetMap, que son un servicio externo y no un CDN contratado por el proyecto.

## 1. ¿Qué es un CDN?

Una *Content Delivery Network* es una red de servidores repartidos geográficamente (puntos de presencia) que guardan copias de los recursos de un sitio. Cuando un usuario los pide, responde el servidor más cercano en lugar del servidor de origen. Ejemplos: Cloudflare, Amazon CloudFront, Fastly, Akamai.

Ofrece sobre todo:
- **menor latencia** para usuarios lejos del origen;
- **descarga del origen**, porque la mayoría de peticiones de archivos estáticos no llegan al servidor;
- protección ante picos de tráfico y ataques de denegación de servicio, y certificados TLS gestionados.

## 2. Diferencias con Nginx y con la caché del navegador

| | Caché del navegador | Nginx (origen) | CDN |
|---|---|---|---|
| Dónde está | En el dispositivo del usuario | En nuestro servidor (contenedor `frontend`) | En servidores del proveedor, cerca del usuario |
| Para quién sirve | Solo para ese usuario, en visitas repetidas | Para todos; es el origen | Para todos los usuarios de una región |
| Qué controla | `Cache-Control`, `ETag` que envía el origen | Compresión, cabeceras, proxy de la API | Sus propias reglas, basadas en las cabeceras del origen |
| Costo | Ninguno | Ya existe | Servicio externo, dominio público y DNS |

Las tres capas son complementarias: un CDN también respeta las cabeceras `Cache-Control` que define Nginx.

## 3. Qué recursos de LimaGo podrían distribuirse

| Recurso | Tamaño aprox. | ¿Apto para CDN? |
|---|---|---|
| `vendor/leaflet/*` (JS, CSS, íconos) | ~170 KB | Sí: no cambia entre versiones |
| `css/estilos.css`, `js/*.js` | ~120 KB en total | Sí, con versión en la URL (`?v=3`) |
| `img/logo.svg` | < 1 KB | Sí |
| Páginas HTML | ~5–11 KB cada una | Con caché corta o revalidación |
| `/api/cobertura`, `/api/distritos` (GeoJSON) | 30 KB y 154 KB (10 KB medido y ~42 KB estimado con gzip) | Posible, con caché de 1 h |
| Resto de `/api/*` (viajes, flota, seguimiento) | — | **No**: son dinámicos y por usuario |
| Teselas del mapa | — | Ya las sirve OpenStreetMap |

## 4. Lo que sí se implementó (V3)

En `docker/nginx.conf`:

- **Compresión gzip** de CSS, JS, JSON, GeoJSON y SVG, también en respuestas de la API (`gzip_proxied any`). Medido en Docker: `/api/cobertura` pasa de 30 239 a 10 401 bytes.
- **Caché del navegador por tipo de recurso:**
  - HTML: `Cache-Control: no-cache` + `ETag` → siempre se revalida, así una nueva versión aparece al recargar.
  - `css/` y `js/`: `public, max-age=604800` (7 días). Las páginas los piden con `?v=3`; al publicar una versión nueva se cambia ese número y el navegador descarga los archivos nuevos.
  - `vendor/` e `img/`: `public, max-age=2592000, immutable` (30 días).
  - API: sin caché, salvo `/api/cobertura` y `/api/distritos` (`public, max-age=3600`), que solo cambian al preparar de nuevo la red. Además el backend calcula la cobertura una sola vez y no en cada visita.
- La portada pide solo el conteo de la flota (`/api/flota?detalle=false`) en lugar de las posiciones de los 2 500 conductores.
- Cabecera `Permissions-Policy: geolocation=(self)`: solo el propio sitio puede pedir la ubicación.

Comprobado con `curl -I` contra el contenedor (ver `docs/MEJORAS_V3.md`, sección 5).

## 5. ¿Conviene incorporar un CDN?

**Hoy no.** LimaGo se ejecuta en `localhost` o en un único servidor para una demostración académica:
- con un solo origen cercano y pocos usuarios, la latencia ganada sería mínima;
- los recursos estáticos ya se comprimen y quedan en la caché del navegador tras la primera visita;
- lo costoso es la API dinámica (rutas, seguimiento), que un CDN no puede almacenar;
- exigiría un dominio público, DNS y una cuenta en un proveedor.

**Cuándo sí convendría:** si el sitio se publica en Internet con usuarios en varias ciudades o con picos de tráfico. Pasos previstos (no realizados):
1. publicar el contenedor `frontend` como origen con HTTPS;
2. apuntar el dominio al CDN (por ejemplo, Cloudflare en modo proxy);
3. respetar las cabeceras actuales: el CDN guardaría `vendor/`, `img/`, `css/`, `js/` y los GeoJSON, y nunca el resto de `/api/*`;
4. al publicar una versión, cambiar `?v=` o purgar la caché del CDN.

## 6. Limitaciones

- Un CDN no acelera el cálculo de rutas ni la simulación: eso depende del backend y del worker.
- Con datos por usuario (seguimiento de viajes) hay que asegurarse de que el CDN no guarde respuestas privadas; por eso la API no lleva cabeceras de caché pública.
- Las teselas de OpenStreetMap tienen su propia política de uso; para un servicio real con mucho tráfico habría que usar un proveedor de teselas propio o contratado.
