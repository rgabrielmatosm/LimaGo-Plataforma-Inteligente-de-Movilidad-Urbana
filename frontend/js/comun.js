/* LimaGo — utilidades compartidas por todas las páginas. */
"use strict";

const LimaGo = (() => {
  const ESTADOS_VIAJE = {
    asignada: "Conductor en camino",
    en_viaje: "En viaje",
    completada: "Completado",
    cancelada: "Cancelado",
    interrumpida: "Interrumpido",
    rechazada: "No disponible",
    sin_conductores: "Sin conductores",
    sin_ruta: "Sin ruta disponible",
  };
  const ESTADOS_CONDUCTOR = { disponible: "Disponible", en_camino: "Ocupado · recogiendo", en_viaje: "Ocupado · en viaje" };
  const COLORES = { disponible: "#16a34a", en_camino: "#d97706", en_viaje: "#dc2626" };

  class ErrorApi extends Error {
    constructor(estado, cuerpo) {
      super((cuerpo && cuerpo.mensaje) || "No pudimos completar la operación. Inténtalo nuevamente.");
      this.estado = estado;
      this.codigo = cuerpo && cuerpo.codigo;
      this.opciones = (cuerpo && cuerpo.opciones) || [];
    }
  }

  async function api(ruta, opciones = {}) {
    const config = { headers: { "Content-Type": "application/json" }, ...opciones };
    if (config.body && typeof config.body !== "string") config.body = JSON.stringify(config.body);
    let respuesta;
    try {
      respuesta = await fetch(`/api${ruta}`, config);
    } catch (e) {
      throw new ErrorApi(0, { mensaje: "Sin conexión con LimaGo. Revisa tu red e inténtalo de nuevo." });
    }
    const cuerpo = await respuesta.json().catch(() => null);
    if (!respuesta.ok) throw new ErrorApi(respuesta.status, cuerpo);
    return cuerpo;
  }

  const guardar = (clave, valor) => { try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) { /* sin almacenamiento */ } };
  const leer = (clave) => { try { return JSON.parse(localStorage.getItem(clave)); } catch (e) { return null; } };
  const borrar = (clave) => { try { localStorage.removeItem(clave); } catch (e) { /* sin almacenamiento */ } };

  const minutos = (s) => (s == null ? "—" : s < 60 ? "< 1 min" : `${Math.round(s / 60)} min`);
  const distancia = (m) => (m == null ? "—" : m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`);
  const fecha = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
    return d.toLocaleString("es-PE", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };
  const hora = (h) => {
    if (h == null) return "—";
    const total = Math.round(h * 60) % 1440;
    return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  };
  const escapar = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const corto = (texto, n = 3) => String(texto || "").split(",").slice(0, n).join(",").trim();

  function crearMapa(id, opciones = {}) {
    const mapa = L.map(id, { zoomControl: true, attributionControl: true, ...opciones }).setView([-12.1211, -77.0297], 14);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>',
    }).addTo(mapa);
    return mapa;
  }

  let coberturaCache = null;
  async function cobertura() {
    if (!coberturaCache) coberturaCache = await api("/cobertura");
    return coberturaCache;
  }

  async function dibujarCobertura(mapa, ajustar = true) {
    const datos = await cobertura();
    let capa = null;
    if (datos.poligono) {
      capa = L.geoJSON(datos.poligono, { style: { color: "#0f766e", weight: 2, fillColor: "#0f766e", fillOpacity: 0.06, dashArray: "6 6" }, interactive: false }).addTo(mapa);
      if (ajustar) mapa.fitBounds(capa.getBounds(), { padding: [16, 16] });
    } else if (ajustar) {
      const l = datos.limites;
      mapa.fitBounds([[l.lat_min, l.lon_min], [l.lat_max, l.lon_max]]);
    }
    return { datos, capa };
  }

  class CapaFlota {
    constructor(mapa, { soloDisponibles = false, radio = 5 } = {}) {
      this.mapa = mapa;
      this.capa = L.layerGroup().addTo(mapa);
      this.marcadores = new Map();
      this.soloDisponibles = soloDisponibles;
      this.radio = radio;
      this.ocultos = new Set();
    }
    actualizar(conductores) {
      const vistos = new Set();
      for (const c of conductores) {
        if (this.ocultos.has(c.id) || (this.soloDisponibles && c.estado !== "disponible")) continue;
        vistos.add(c.id);
        const estilo = { color: "#ffffff", weight: 1.5, fillColor: COLORES[c.estado], fillOpacity: 0.95, radius: this.radio };
        let m = this.marcadores.get(c.id);
        if (!m) {
          m = L.circleMarker([c.lat, c.lon], estilo).addTo(this.capa);
          this.marcadores.set(c.id, m);
        } else {
          m.setLatLng([c.lat, c.lon]);
          m.setStyle(estilo);
        }
        m.bindTooltip(`${c.codigo} · ${ESTADOS_CONDUCTOR[c.estado]}`);
      }
      for (const [id, m] of this.marcadores) {
        if (!vistos.has(id)) { this.capa.removeLayer(m); this.marcadores.delete(id); }
      }
    }
  }

  function iconoPin(tipo) {
    return L.divIcon({ className: "", html: `<div class="marcador-pin ${tipo}"></div>`, iconSize: [22, 22], iconAnchor: [11, 22] });
  }
  function iconoAuto() {
    return L.divIcon({
      className: "",
      html: '<div class="marcador-auto"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M5 11l1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11v6a1 1 0 0 1-1 1h-1a1 1 0 0 1-1-1v-1H8v1a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-6zm2.2-1h9.6l-1-3H8.2l-1 3zM7.5 14a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zm9 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"/></svg></div>',
      iconSize: [30, 30], iconAnchor: [15, 15],
    });
  }

  function iniciarCabecera() {
    const boton = document.querySelector(".menu-movil");
    const nav = document.querySelector(".navegacion");
    if (boton && nav) boton.addEventListener("click", () => {
      const abierta = nav.classList.toggle("abierta");
      boton.setAttribute("aria-expanded", String(abierta));
    });
  }
  document.addEventListener("DOMContentLoaded", iniciarCabecera);

  return { api, ErrorApi, guardar, leer, borrar, minutos, distancia, fecha, hora, escapar, corto, crearMapa, cobertura,
    dibujarCobertura, CapaFlota, iconoPin, iconoAuto, ESTADOS_VIAJE, ESTADOS_CONDUCTOR, COLORES };
})();
