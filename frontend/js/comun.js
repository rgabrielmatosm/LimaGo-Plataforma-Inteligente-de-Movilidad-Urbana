/* LimaGo — utilidades de datos y mapa compartidas (API, formatos, flota, selector de lugar). */
"use strict";

const LimaGo = (() => {
  const ESTADOS_VIAJE = {
    buscando: "Buscando conductor",
    asignada: "Conductor en camino",
    esperando_recogida: "Tu conductor llegó",
    sin_aceptacion: "Sin conductor disponible",
    en_viaje: "En viaje",
    completada: "Completado",
    cancelada: "Cancelado",
    interrumpida: "Interrumpido",
    rechazada: "No atendido",
    sin_conductores: "Sin conductores",
    sin_ruta: "Sin ruta disponible",
  };
  const ESTADOS_CONDUCTOR = {
    disponible: "Disponible", desconectado: "Desconectado", oferta_pendiente: "Decidiendo una oferta",
    aceptado: "Aceptó un viaje", en_camino: "Ocupado · recogiendo", esperando_recogida: "Esperando al pasajero",
    en_viaje: "Ocupado · en viaje", finalizado: "Finalizando",
  };
  const COLORES = {
    disponible: "#16a34a", desconectado: "#94a3b8", oferta_pendiente: "#7c3aed", aceptado: "#7c3aed",
    en_camino: "#d97706", esperando_recogida: "#0ea5e9", en_viaje: "#dc2626", finalizado: "#64748b",
  };
  const NIVELES_TRAFICO = { fluido: "Tráfico fluido", moderado: "Tráfico moderado", alto: "Tráfico intenso", sin_ajuste: "Tráfico no considerado" };

  class ErrorApi extends Error {
    constructor(estado, cuerpo) {
      super((cuerpo && cuerpo.mensaje) || "No pudimos completar la operación. Inténtalo nuevamente.");
      this.estado = estado;
      this.codigo = cuerpo && cuerpo.codigo;
      this.opciones = (cuerpo && cuerpo.opciones) || [];
    }
  }

  async function api(ruta, opciones = {}) {
    const config = { ...opciones, headers: { "Content-Type": "application/json", ...(opciones.headers || {}) } };
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
  const parametro = (nombre) => new URLSearchParams(location.search).get(nombre);

  const minutos = (s) => (s == null ? "—" : s < 60 ? "< 1 min" : `${Math.round(s / 60)} min`);
  const distancia = (m) => (m == null ? "—" : m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1).replace(".", ",")} km`);
  const soles = (x) => (x == null ? "—" : `S/ ${Number(x).toFixed(2).replace(".", ",")}`);
  const fecha = (iso) => {
    if (!iso) return "—";
    const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
    return d.toLocaleString("es-PE", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };
  const hora = (h) => {
    if (h == null) return "—";
    const total = Math.round(h * 60) % 1440;
    return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  };
  const escapar = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const corto = (texto, n = 3) => String(texto || "").split(",").slice(0, n).join(",").trim();
  const codigoConductor = (id) => (id == null ? "—" : `LG-${String(id).padStart(5, "0")}`);

  function crearMapa(id, opciones = {}) {
    const mapa = L.map(id, { zoomControl: true, attributionControl: true, ...opciones }).setView([-12.06, -77.04], 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">colaboradores de OpenStreetMap</a>',
    }).addTo(mapa);
    return mapa;
  }

  let coberturaCache = null;
  async function cobertura() {
    if (!coberturaCache) coberturaCache = api("/cobertura");
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

  /* ------------------------------------------------------------------
     Vehículo animado. El servidor es la fuente de verdad de la posición: en cada
     actualización el marcador se desliza desde donde está hasta la nueva posición
     siguiendo la ruta vial que el servidor envió en la actualización anterior.
     Si la simulación está en pausa, no se anima (se fija la posición recibida). */
  const aMetros = (a, b) => {
    const r = 6371009, f1 = a[0] * Math.PI / 180, f2 = b[0] * Math.PI / 180;
    const df = f2 - f1, dl = (b[1] - a[1]) * Math.PI / 180;
    const h = Math.sin(df / 2) ** 2 + Math.cos(f1) * Math.cos(f2) * Math.sin(dl / 2) ** 2;
    return 2 * r * Math.asin(Math.min(1, Math.sqrt(h)));
  };
  const rumbo = (a, b) => {
    const f1 = a[0] * Math.PI / 180, f2 = b[0] * Math.PI / 180, dl = (b[1] - a[1]) * Math.PI / 180;
    const x = Math.sin(dl) * Math.cos(f2), y = Math.cos(f1) * Math.sin(f2) - Math.sin(f1) * Math.cos(f2) * Math.cos(dl);
    return (Math.atan2(x, y) * 180 / Math.PI + 360) % 360;
  };
  function proyectar(poli, p) {
    // índice del segmento y punto más cercano (aproximación plana local, suficiente a escala de calle)
    const k = Math.cos(p[0] * Math.PI / 180);
    let mejor = { i: 0, punto: poli[0], d: Infinity, t: 0 };
    for (let i = 0; i < poli.length - 1; i++) {
      const a = poli[i], b = poli[i + 1];
      const ax = a[1] * k, ay = a[0], bx = b[1] * k, by = b[0], px = p[1] * k, py = p[0];
      const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
      const t = l2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0;
      const q = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      const d = aMetros(q, p);
      if (d < mejor.d) mejor = { i, punto: q, d, t };
    }
    return mejor;
  }
  function caminoEntre(poli, desde, hasta) {
    if (!poli || poli.length < 2) return [desde, hasta];
    const a = proyectar(poli, desde), b = proyectar(poli, hasta);
    if (a.d > 60 || b.d > 60 || b.i < a.i || (b.i === a.i && b.t < a.t)) return [desde, hasta];
    return [desde, a.punto, ...poli.slice(a.i + 1, b.i + 1), b.punto, hasta];
  }

  class VehiculoAnimado {
    constructor(mapa, { codigo = "" } = {}) {
      this.mapa = mapa;
      this.codigo = codigo;
      this.marcador = null;
      this.ruta = null;
      this.cuadro = null;
      this.rumbo = 0;
    }
    icono() {
      return L.divIcon({ className: "", iconSize: [36, 36], iconAnchor: [18, 18],
        html: `<div class="marcador-vehiculo"><div class="flecha" style="transform:rotate(${this.rumbo}deg)">${Plantilla.icono("flecha")}</div></div>` });
    }
    girar(grados) {
      if (grados == null || Number.isNaN(grados)) return;
      this.rumbo = grados;
      const el = this.marcador && this.marcador.getElement();
      const flecha = el && el.querySelector(".flecha");
      if (flecha) flecha.style.transform = `rotate(${grados}deg)`;
    }
    actualizar(pos, rutaRestante, { pausado = false, duracionMs = 1000 } = {}) {
      const destino = [pos.lat, pos.lon];
      if (this.cuadro) cancelAnimationFrame(this.cuadro);
      if (!this.marcador) {
        this.marcador = L.marker(destino, { icon: this.icono(), zIndexOffset: 1000, keyboard: false }).addTo(this.mapa);
        if (this.codigo) this.marcador.bindTooltip(this.codigo);
        this.girar(pos.rumbo);
        this.ruta = rutaRestante;
        return;
      }
      const actual = this.marcador.getLatLng();
      const desde = [actual.lat, actual.lng];
      const salto = aMetros(desde, destino);
      if (pausado || salto < 0.5 || salto > 3000) {  // en pausa (o reconexión lejana) no se anima
        this.marcador.setLatLng(destino);
        this.girar(pos.rumbo);
        this.ruta = rutaRestante;
        return;
      }
      const camino = caminoEntre(this.ruta, desde, destino);
      const largos = camino.slice(1).map((p, i) => aMetros(camino[i], p));
      const total = largos.reduce((a, b) => a + b, 0) || 1;
      const inicio = performance.now();
      const paso = (ahora) => {
        const f = Math.min(1, (ahora - inicio) / duracionMs);
        let objetivo = f * total, i = 0;
        while (i < largos.length - 1 && objetivo > largos[i]) { objetivo -= largos[i]; i++; }
        const t = largos[i] ? Math.min(1, objetivo / largos[i]) : 1;
        const a = camino[i], b = camino[i + 1];
        this.marcador.setLatLng([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
        if (largos[i] > 0.5) this.girar(rumbo(a, b));
        if (f < 1) this.cuadro = requestAnimationFrame(paso);
        else { this.cuadro = null; if (pos.rumbo != null) this.girar(pos.rumbo); }
      };
      this.ruta = rutaRestante;
      this.cuadro = requestAnimationFrame(paso);
    }
    posicion() { return this.marcador ? this.marcador.getLatLng() : null; }
    quitar() { if (this.cuadro) cancelAnimationFrame(this.cuadro); if (this.marcador) this.mapa.removeLayer(this.marcador); this.marcador = null; }
  }

  function iconoPin(tipo) {
    return L.divIcon({ className: "", html: `<div class="marcador-pin ${tipo}"></div>`, iconSize: [22, 22], iconAnchor: [11, 22] });
  }
  function iconoAuto() {
    return L.divIcon({ className: "", html: `<div class="marcador-auto">${Plantilla.icono("auto")}</div>`, iconSize: [32, 32], iconAnchor: [16, 16] });
  }

  /* ------------------------------------------------------------------
     Selector de lugar: dirección (con sugerencias), coordenadas o mapa.
     HTML esperado dentro de `raiz`: pestañas [data-modo], paneles [data-panel],
     input[data-entrada="texto"], input[data-entrada="coordenadas"], ul.sugerencias,
     botón [data-accion="elegir-mapa"] y [data-seleccion]. */
  const PATRON_COORDENADAS = /^\(?\s*(-?\d{1,3}(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*\)?$/;

  class SelectorLugar {
    constructor(raiz, { nombre, mapa = null, tipoPin = "origen", alCambiar = () => {} } = {}) {
      this.raiz = raiz;
      this.nombre = nombre;
      this.mapa = mapa;
      this.tipoPin = tipoPin;
      this.alCambiar = alCambiar;
      this.modo = "direccion";
      this.valor = null;
      this.marcador = null;
      this.temporizador = null;
      this.texto = raiz.querySelector('[data-entrada="texto"]');
      this.coordenadas = raiz.querySelector('[data-entrada="coordenadas"]');
      this.lista = raiz.querySelector(".sugerencias");
      this.seleccion = raiz.querySelector("[data-seleccion]");
      raiz.querySelectorAll("[data-modo]").forEach((b) => b.addEventListener("click", () => this.cambiarModo(b.dataset.modo)));
      const botonMapa = raiz.querySelector('[data-accion="elegir-mapa"]');
      if (botonMapa) botonMapa.addEventListener("click", () => SelectorLugar.activarEleccion(this));
      if (this.texto) {
        this.texto.addEventListener("input", () => { this.valor = null; this.mostrar(""); this.programarBusqueda(); this.alCambiar(this); });
        this.texto.addEventListener("keydown", (e) => this.navegarLista(e));
        this.texto.addEventListener("blur", () => setTimeout(() => this.cerrarLista(), 200));
      }
      if (this.coordenadas) {
        this.coordenadas.addEventListener("input", () => { this.valor = null; this.coordenadas.removeAttribute("aria-invalid"); this.mostrar(""); });
        this.coordenadas.addEventListener("change", () => this.validarCoordenadas(true));
      }
    }
    static activarEleccion(selector) {
      if (!selector.mapa) return;
      SelectorLugar.enEleccion = selector;
      const aviso = document.getElementById("modo-mapa");
      if (aviso) { aviso.textContent = `Toca el mapa para marcar: ${selector.nombre}`; aviso.classList.remove("oculto"); }
      selector.mapa.getContainer().style.cursor = "crosshair";
      selector.mapa.getContainer().scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    static conectarMapa(mapa) {
      mapa.on("click", async (e) => {
        const selector = SelectorLugar.enEleccion;
        if (!selector || selector.mapa !== mapa) return;
        SelectorLugar.enEleccion = null;
        const aviso = document.getElementById("modo-mapa");
        if (aviso) aviso.classList.add("oculto");
        mapa.getContainer().style.cursor = "";
        const lat = +e.latlng.lat.toFixed(6), lon = +e.latlng.lng.toFixed(6);
        selector.fijar({ lat, lon, direccion: `${lat}, ${lon}` });
        try {
          const { direccion } = await api(`/geocodificar/inverso?lat=${lat}&lon=${lon}`);
          selector.fijar({ lat, lon, direccion });
        } catch (error) {
          selector.mostrar(error.message, "error");
        }
      });
    }
    cambiarModo(modo) {
      this.modo = modo;
      this.raiz.querySelectorAll("[data-modo]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.modo === modo)));
      this.raiz.querySelectorAll("[data-panel]").forEach((p) => p.classList.toggle("oculto", p.dataset.panel !== modo));
      if (modo === "mapa") SelectorLugar.activarEleccion(this);
    }
    programarBusqueda() {
      clearTimeout(this.temporizador);
      const q = this.texto.value.trim();
      if (q.length < 4 || PATRON_COORDENADAS.test(q)) { this.cerrarLista(); return; }
      this.temporizador = setTimeout(async () => {
        this.lista.innerHTML = '<li aria-disabled="true"><span class="girador" style="width:14px;height:14px"></span> Buscando…</li>';
        this.lista.classList.remove("oculto");
        try {
          const { resultados } = await api(`/geocodificar?q=${encodeURIComponent(q)}`);
          this.mostrarLista(resultados);
        } catch (e) {
          this.lista.innerHTML = `<li aria-disabled="true">${escapar(e.message)}</li>`;
        }
      }, 450);
    }
    mostrarLista(resultados) {
      this.resultados = resultados;
      this.indice = -1;
      this.lista.innerHTML = resultados.length
        ? resultados.map((r, i) => `<li role="option" data-i="${i}">${escapar(corto(r.direccion, 2))}<small>${escapar(corto(r.direccion.split(",").slice(2).join(","), 3))}</small></li>`).join("")
        : '<li aria-disabled="true">Sin coincidencias en la zona de cobertura</li>';
      this.lista.classList.remove("oculto");
      this.lista.querySelectorAll("li[data-i]").forEach((li) => li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        this.elegir(+li.dataset.i);
      }));
    }
    navegarLista(e) {
      const items = [...this.lista.querySelectorAll("li[data-i]")];
      if (e.key === "Escape") { this.cerrarLista(); return; }
      if (!items.length || this.lista.classList.contains("oculto")) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        this.indice = (this.indice + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((li, i) => li.setAttribute("aria-selected", String(i === this.indice)));
      } else if (e.key === "Enter" && this.indice >= 0) {
        e.preventDefault();
        this.elegir(this.indice);
      }
    }
    elegir(i) {
      const r = this.resultados[i];
      this.fijar({ lat: r.lat, lon: r.lon, direccion: r.direccion });
      this.texto.value = corto(r.direccion, 2);
      this.cerrarLista();
    }
    cerrarLista() { if (this.lista) this.lista.classList.add("oculto"); }
    validarCoordenadas(mostrarError) {
      const texto = this.coordenadas.value.trim();
      const m = texto.match(PATRON_COORDENADAS);
      const invalido = (msg) => { if (mostrarError) { this.mostrar(msg, "error"); this.coordenadas.setAttribute("aria-invalid", "true"); } return null; };
      if (!m) return texto ? invalido("Formato esperado: -12.1218, -77.0304") : null;
      const lat = parseFloat(m[1].replace(",", ".")), lon = parseFloat(m[2].replace(",", "."));
      if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return invalido("Coordenadas fuera de rango");
      this.fijar({ lat, lon, direccion: `${lat.toFixed(5)}, ${lon.toFixed(5)}` });
      return this.valor;
    }
    fijar(valor) {
      this.valor = valor;
      this.mostrar(`✓ ${corto(valor.direccion, 3)}`, "ok");
      if (this.mapa) {
        if (this.marcador) this.mapa.removeLayer(this.marcador);
        this.marcador = L.marker([valor.lat, valor.lon], { icon: iconoPin(this.tipoPin) }).bindTooltip(this.nombre).addTo(this.mapa);
      }
      this.alCambiar(this);
    }
    fijarTexto(texto) {
      if (!texto || !this.texto) return;
      this.cambiarModo("direccion");
      this.texto.value = texto;
    }
    mostrar(texto, tipo = "") {
      if (!this.seleccion) return;
      this.seleccion.textContent = texto;
      this.seleccion.className = `ayuda ${tipo}`;
    }
    datos() {
      if (this.valor) return { lat: this.valor.lat, lon: this.valor.lon, direccion: this.valor.direccion };
      if (this.modo === "direccion" && this.texto && this.texto.value.trim()) return { texto: this.texto.value.trim() };
      if (this.modo === "coordenadas" && this.coordenadas && this.coordenadas.value.trim()) {
        const v = this.validarCoordenadas(true);
        if (!v) throw new Error("Revisa las coordenadas ingresadas");
        return { lat: v.lat, lon: v.lon, direccion: v.direccion };
      }
      return null;
    }
    limpiar() {
      this.valor = null;
      if (this.texto) this.texto.value = "";
      if (this.coordenadas) this.coordenadas.value = "";
      this.mostrar("");
      if (this.marcador && this.mapa) { this.mapa.removeLayer(this.marcador); this.marcador = null; }
    }
  }

  /** HTML del selector de lugar (dirección / coordenadas / mapa). */
  function htmlSelector(id, etiqueta, ejemplo, conMapa = true) {
    return `
      <fieldset class="campo" style="border:0;padding:0;margin:0 0 8px" data-lugar="${id}">
        <legend class="etiqueta-campo" style="margin-bottom:6px">${etiqueta}</legend>
        <div class="pestanas" role="tablist" aria-label="Forma de indicar: ${escapar(etiqueta)}">
          <button type="button" role="tab" data-modo="direccion" aria-selected="true">Dirección</button>
          <button type="button" role="tab" data-modo="coordenadas" aria-selected="false">Coordenadas</button>
          ${conMapa ? '<button type="button" role="tab" data-modo="mapa" aria-selected="false">En el mapa</button>' : ""}
        </div>
        <div data-panel="direccion" style="position:relative">
          <label class="sr" for="${id}-texto">${etiqueta}: dirección</label>
          <input class="entrada" id="${id}-texto" data-entrada="texto" autocomplete="off" placeholder="${escapar(ejemplo)}" aria-autocomplete="list">
          <ul class="sugerencias oculto" role="listbox"></ul>
        </div>
        <div data-panel="coordenadas" class="oculto">
          <label class="sr" for="${id}-coordenadas">${etiqueta}: coordenadas</label>
          <input class="entrada" id="${id}-coordenadas" data-entrada="coordenadas" inputmode="decimal" placeholder="-12.1218, -77.0304">
          <span class="ayuda">Latitud y longitud separadas por coma.</span>
        </div>
        ${conMapa ? `<div data-panel="mapa" class="oculto"><button type="button" class="boton secundario bloque" data-accion="elegir-mapa">Tocar el punto en el mapa</button></div>` : ""}
        <span class="ayuda" data-seleccion aria-live="polite"></span>
      </fieldset>`;
  }

  return { api, ErrorApi, guardar, leer, borrar, parametro, minutos, distancia, soles, fecha, hora, escapar, corto,
    codigoConductor, crearMapa, cobertura, dibujarCobertura, CapaFlota, iconoPin, iconoAuto, SelectorLugar, htmlSelector,
    ESTADOS_VIAJE, ESTADOS_CONDUCTOR, COLORES, NIVELES_TRAFICO, VehiculoAnimado, caminoEntre, aMetros };
})();
