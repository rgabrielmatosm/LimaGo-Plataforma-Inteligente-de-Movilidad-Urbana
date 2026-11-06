/* LimaGo — solicitud de viaje, asignación y seguimiento en vivo. */
"use strict";

(async () => {
  const $ = (s, r = document) => r.querySelector(s);
  const mapa = LimaGo.crearMapa("mapa");
  const flota = new LimaGo.CapaFlota(mapa);
  const capaViaje = L.layerGroup().addTo(mapa);
  const marcadores = { origen: null, destino: null };
  let lugarEnEleccion = null;   // "origen" | "destino" mientras se elige en el mapa
  let viajeActual = LimaGo.leer("limago.viaje");
  let ultimoEstado = null;
  let marcadorConductor = null;
  let lineaRuta = null;

  LimaGo.dibujarCobertura(mapa).catch(() => {});

  // ------------------------------------------------------------ selector de lugar
  class SelectorLugar {
    constructor(nombre) {
      this.nombre = nombre;
      this.raiz = document.querySelector(`[data-lugar="${nombre}"]`);
      this.modo = "direccion";
      this.valor = null; // {lat, lon, direccion} confirmado o {texto}
      this.texto = $('[data-entrada="texto"]', this.raiz);
      this.coordenadas = $('[data-entrada="coordenadas"]', this.raiz);
      this.lista = $(".sugerencias", this.raiz);
      this.seleccion = $("[data-seleccion]", this.raiz);
      this.temporizador = null;
      this.raiz.querySelectorAll('[role="tab"]').forEach((b) => b.addEventListener("click", () => this.cambiarModo(b.dataset.modo)));
      $('[data-accion="elegir-mapa"]', this.raiz).addEventListener("click", () => activarEleccion(this.nombre));
      this.texto.addEventListener("input", () => { this.valor = null; this.mostrarSeleccion(""); this.programarBusqueda(); });
      this.texto.addEventListener("keydown", (e) => { if (e.key === "Escape") this.cerrarLista(); });
      this.texto.addEventListener("blur", () => setTimeout(() => this.cerrarLista(), 200));
      this.coordenadas.addEventListener("input", () => { this.valor = null; this.validarCoordenadas(false); });
      this.coordenadas.addEventListener("change", () => this.validarCoordenadas(true));
    }
    cambiarModo(modo) {
      this.modo = modo;
      this.raiz.querySelectorAll('[role="tab"]').forEach((b) => b.setAttribute("aria-selected", String(b.dataset.modo === modo)));
      this.raiz.querySelectorAll("[data-panel]").forEach((p) => p.classList.toggle("oculto", p.dataset.panel !== modo));
      if (modo === "mapa") activarEleccion(this.nombre);
    }
    programarBusqueda() {
      clearTimeout(this.temporizador);
      const q = this.texto.value.trim();
      if (q.length < 4) { this.cerrarLista(); return; }
      this.temporizador = setTimeout(async () => {
        try {
          const { resultados } = await LimaGo.api(`/geocodificar?q=${encodeURIComponent(q)}`);
          this.mostrarLista(resultados);
        } catch (e) {
          this.mostrarLista([]);
        }
      }, 450);
    }
    mostrarLista(resultados) {
      this.lista.innerHTML = resultados.length
        ? resultados.map((r, i) => `<li role="option" data-i="${i}">${LimaGo.escapar(LimaGo.corto(r.direccion, 2))}<small>${LimaGo.escapar(LimaGo.corto(r.direccion.split(",").slice(2).join(","), 3))}</small></li>`).join("")
        : '<li aria-disabled="true">Sin coincidencias en Miraflores</li>';
      this.lista.classList.remove("oculto");
      this.lista.querySelectorAll("li[data-i]").forEach((li) => li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const r = resultados[+li.dataset.i];
        this.fijar({ lat: r.lat, lon: r.lon, direccion: r.direccion });
        this.texto.value = LimaGo.corto(r.direccion, 2);
        this.cerrarLista();
      }));
    }
    cerrarLista() { this.lista.classList.add("oculto"); }
    validarCoordenadas(mostrarError) {
      const texto = this.coordenadas.value.trim();
      const m = texto.match(/^\(?\s*(-?\d{1,3}(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:[.,]\d+)?)\s*\)?$/);
      if (!m) {
        if (mostrarError && texto) this.mostrarSeleccion("Formato esperado: -12.1218, -77.0304", true);
        return null;
      }
      const lat = parseFloat(m[1].replace(",", ".")), lon = parseFloat(m[2].replace(",", "."));
      if (Math.abs(lat) > 90 || Math.abs(lon) > 180) {
        this.mostrarSeleccion("Coordenadas fuera de rango", true);
        return null;
      }
      this.fijar({ lat, lon, direccion: `${lat.toFixed(5)}, ${lon.toFixed(5)}` });
      return this.valor;
    }
    fijar(valor) {
      this.valor = valor;
      this.mostrarSeleccion(`✓ ${LimaGo.corto(valor.direccion, 3)}`);
      ponerMarcador(this.nombre, valor);
    }
    mostrarSeleccion(texto, error = false) {
      this.seleccion.textContent = texto;
      this.seleccion.style.color = error ? "var(--peligro)" : "";
    }
    datos() {
      if (this.valor) return { lat: this.valor.lat, lon: this.valor.lon, direccion: this.valor.direccion };
      if (this.modo === "direccion" && this.texto.value.trim()) return { texto: this.texto.value.trim() };
      if (this.modo === "coordenadas" && this.coordenadas.value.trim()) {
        const v = this.validarCoordenadas(true);
        if (!v) throw new Error("Revisa las coordenadas ingresadas");
        return { lat: v.lat, lon: v.lon, direccion: v.direccion };
      }
      return null;
    }
    limpiar() {
      this.valor = null; this.texto.value = ""; this.coordenadas.value = ""; this.mostrarSeleccion("");
      if (marcadores[this.nombre]) { mapa.removeLayer(marcadores[this.nombre]); marcadores[this.nombre] = null; }
    }
  }
  const selectores = { origen: new SelectorLugar("origen"), destino: new SelectorLugar("destino") };

  function ponerMarcador(nombre, valor) {
    if (marcadores[nombre]) mapa.removeLayer(marcadores[nombre]);
    marcadores[nombre] = L.marker([valor.lat, valor.lon], { icon: LimaGo.iconoPin(nombre) })
      .bindTooltip(nombre === "origen" ? "Recojo" : "Destino").addTo(mapa);
  }

  function activarEleccion(nombre) {
    lugarEnEleccion = nombre;
    $("#modo-mapa").textContent = nombre === "origen" ? "Toca el mapa para marcar tu punto de recojo" : "Toca el mapa para marcar tu destino";
    $("#modo-mapa").classList.remove("oculto");
    mapa.getContainer().style.cursor = "crosshair";
  }

  mapa.on("click", async (e) => {
    if (!lugarEnEleccion) return;
    const selector = selectores[lugarEnEleccion];
    lugarEnEleccion = null;
    $("#modo-mapa").classList.add("oculto");
    mapa.getContainer().style.cursor = "";
    const lat = +e.latlng.lat.toFixed(6), lon = +e.latlng.lng.toFixed(6);
    selector.fijar({ lat, lon, direccion: `${lat}, ${lon}` });
    try {
      const { direccion } = await LimaGo.api(`/geocodificar/inverso?lat=${lat}&lon=${lon}`);
      selector.fijar({ lat, lon, direccion });
    } catch (error) {
      selector.mostrarSeleccion(error.message, true);
    }
  });

  // ------------------------------------------------------------ solicitud
  function mostrarMensaje(destino, texto, tipo = "error") {
    $(destino).innerHTML = texto ? `<div class="aviso ${tipo}">${LimaGo.escapar(texto)}</div>` : "";
  }

  function mostrarOpciones(nombre, opciones) {
    const caja = $("#opciones");
    const lista = $(".sugerencias", caja);
    lista.innerHTML = opciones.map((o, i) => `<li role="option" data-i="${i}">${LimaGo.escapar(LimaGo.corto(o.direccion, 2))}<small>${LimaGo.escapar(LimaGo.corto(o.direccion.split(",").slice(2).join(","), 3))}</small></li>`).join("");
    caja.classList.remove("oculto");
    lista.querySelectorAll("li").forEach((li) => li.addEventListener("click", () => {
      const o = opciones[+li.dataset.i];
      selectores[nombre].fijar({ lat: o.lat, lon: o.lon, direccion: o.direccion });
      caja.classList.add("oculto");
      mostrarMensaje("#mensaje", "");
    }));
  }

  $("#formulario").addEventListener("submit", async (e) => {
    e.preventDefault();
    mostrarMensaje("#mensaje", "");
    $("#opciones").classList.add("oculto");
    let origen, destino;
    try {
      origen = selectores.origen.datos();
      destino = selectores.destino.datos();
    } catch (error) {
      mostrarMensaje("#mensaje", error.message);
      return;
    }
    if (!origen) { mostrarMensaje("#mensaje", "Indica tu punto de recojo: escribe una dirección, coordenadas o márcalo en el mapa."); return; }
    const boton = $("#pedir");
    boton.disabled = true;
    boton.textContent = "Buscando tu conductor…";
    try {
      const viaje = await LimaGo.api("/viajes", { method: "POST", body: { origen, destino } });
      if (viaje.estado === "asignada") {
        viajeActual = viaje.id;
        LimaGo.guardar("limago.viaje", viajeActual);
        mostrarViaje(viaje);
      } else {
        mostrarMensaje("#mensaje", viaje.mensaje || LimaGo.ESTADOS_VIAJE[viaje.estado]);
      }
    } catch (error) {
      if (error.estado === 409 && error.opciones.length) {
        const nombre = origen.texto && !selectores.origen.valor ? "origen" : "destino";
        mostrarMensaje("#mensaje", error.message, "info");
        mostrarOpciones(nombre, error.opciones);
      } else {
        mostrarMensaje("#mensaje", error.message);
      }
    } finally {
      boton.disabled = false;
      boton.textContent = "Pedir LimaGo";
    }
  });

  // ------------------------------------------------------------ seguimiento
  function pasoActual(viaje) {
    if (viaje.estado === "completada") return 4;
    if (viaje.estado === "en_viaje") return 3;
    if (viaje.estado === "asignada") return 2;
    return 0;
  }

  function mostrarViaje(viaje) {
    $("#formulario").classList.add("oculto");
    $("#viaje").classList.remove("oculto");
    const etiqueta = $("#viaje-estado");
    etiqueta.className = `etiqueta estado-${viaje.estado}`;
    etiqueta.textContent = LimaGo.ESTADOS_VIAJE[viaje.estado] || viaje.estado;
    $("#viaje-conductor").textContent = viaje.conductor_id ? `Conductor LG-${String(viaje.conductor_id).padStart(5, "0")}` : "—";
    $("#viaje-id").textContent = `#${viaje.id}`;
    $("#viaje-candidatos").textContent = (viaje.candidatos || []).length || "—";
    const activo = viaje.estado === "asignada" || viaje.estado === "en_viaje";
    const restante = viaje.segundos_restantes;
    if (viaje.estado === "asignada") {
      $("#viaje-eta").textContent = LimaGo.minutos(restante ?? viaje.eta_s);
      $("#viaje-eta-texto").textContent = "para llegar a ti";
      $("#viaje-detalle").textContent = "Va hacia tu punto de recojo";
      $("#viaje-distancia").textContent = LimaGo.distancia(viaje.metros_restantes ?? viaje.distancia_calles_m);
    } else if (viaje.estado === "en_viaje") {
      $("#viaje-eta").textContent = LimaGo.minutos(restante);
      $("#viaje-eta-texto").textContent = "a tu destino";
      $("#viaje-detalle").textContent = "Viaje en curso";
      $("#viaje-distancia").textContent = LimaGo.distancia(viaje.metros_restantes);
    } else {
      $("#viaje-eta").textContent = viaje.estado === "completada" ? "✓" : "—";
      $("#viaje-eta-texto").textContent = LimaGo.ESTADOS_VIAJE[viaje.estado] || "";
      $("#viaje-detalle").textContent = viaje.mensaje || "";
    }
    const paso = pasoActual(viaje);
    $("#linea-tiempo").querySelectorAll("li").forEach((li, i) => {
      li.classList.toggle("hecho", i < paso - 1 || (paso === 4 && i === 3));
      li.classList.toggle("actual", i === paso - 1 && paso !== 4);
    });
    $("#viaje-direcciones").textContent = `Recojo: ${LimaGo.corto(viaje.origen_texto, 2) || "—"}` +
      (viaje.destino_texto ? ` · Destino: ${LimaGo.corto(viaje.destino_texto, 2)}` : "");
    $("#cancelar").classList.toggle("oculto", viaje.estado !== "asignada");
    $("#nuevo").classList.toggle("oculto", activo);
    if (!activo && ultimoEstado && ultimoEstado !== viaje.estado) {
      mostrarMensaje("#viaje-mensaje", viaje.estado === "completada" ? "¡Llegaste! Gracias por viajar con LimaGo." : (viaje.mensaje || ""),
        viaje.estado === "completada" ? "exito" : "info");
    }
    ultimoEstado = viaje.estado;
    dibujarViaje(viaje, activo);
  }

  function dibujarViaje(viaje, activo) {
    if (viaje.origen_lat != null && !marcadores.origen) ponerMarcador("origen", { lat: viaje.origen_lat, lon: viaje.origen_lon });
    if (viaje.destino_lat != null && !marcadores.destino) ponerMarcador("destino", { lat: viaje.destino_lat, lon: viaje.destino_lon });
    const ruta = viaje.ruta_restante && viaje.ruta_restante.length ? viaje.ruta_restante : (activo ? viaje.ruta_recogida : []);
    const color = viaje.estado === "en_viaje" ? "#f26b3a" : "#0f766e";
    if (lineaRuta) capaViaje.removeLayer(lineaRuta);
    lineaRuta = ruta && ruta.length > 1 ? L.polyline(ruta, { color, weight: 6, opacity: 0.85 }).addTo(capaViaje) : null;
    if (viaje.conductor && activo) {
      flota.ocultos = new Set([viaje.conductor.id]);
      const pos = [viaje.conductor.lat, viaje.conductor.lon];
      if (!marcadorConductor) {
        marcadorConductor = L.marker(pos, { icon: LimaGo.iconoAuto(), zIndexOffset: 1000 }).addTo(capaViaje);
        const limites = L.latLngBounds([pos, [viaje.origen_lat, viaje.origen_lon]]);
        if (lineaRuta) limites.extend(lineaRuta.getBounds());
        mapa.fitBounds(limites, { padding: [60, 60], maxZoom: 17 });
      } else {
        marcadorConductor.setLatLng(pos);
      }
      marcadorConductor.bindTooltip(viaje.conductor.codigo);
    } else {
      flota.ocultos = new Set();
      if (marcadorConductor) { capaViaje.removeLayer(marcadorConductor); marcadorConductor = null; }
    }
  }

  async function refrescarViaje() {
    if (!viajeActual) return;
    try {
      mostrarViaje(await LimaGo.api(`/viajes/${viajeActual}`));
    } catch (error) {
      if (error.estado === 404) { reiniciarFormulario(); }
    }
  }

  async function refrescarFlota() {
    try { flota.actualizar((await LimaGo.api("/flota")).conductores); } catch (e) { /* reintenta en el siguiente ciclo */ }
  }

  function reiniciarFormulario() {
    viajeActual = null;
    ultimoEstado = null;
    LimaGo.borrar("limago.viaje");
    capaViaje.clearLayers();
    lineaRuta = null;
    marcadorConductor = null;
    flota.ocultos = new Set();
    selectores.origen.limpiar();
    selectores.destino.limpiar();
    mostrarMensaje("#viaje-mensaje", "");
    $("#viaje").classList.add("oculto");
    $("#formulario").classList.remove("oculto");
  }

  $("#cancelar").addEventListener("click", async () => {
    if (!viajeActual) return;
    try {
      mostrarViaje(await LimaGo.api(`/viajes/${viajeActual}/cancelar`, { method: "POST" }));
    } catch (error) {
      mostrarMensaje("#viaje-mensaje", error.message);
    }
  });
  $("#nuevo").addEventListener("click", reiniciarFormulario);

  await refrescarFlota();
  await refrescarViaje();
  setInterval(refrescarFlota, 2000);
  setInterval(refrescarViaje, 1500);
})();
