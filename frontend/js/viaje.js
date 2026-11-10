/* LimaGo V3 — solicitud en pocos pasos: ubicación automática (con permiso), destino, tarifa, confirmación y búsqueda
   de un conductor que acepte. Todo cálculo (ruta, tráfico, tarifa, ofertas) lo hace el servidor. */
"use strict";

(async () => {
  const $ = (s, r = document) => r.querySelector(s);
  const GEO = "limago.geo";  // "concedida" | "denegada" | "preguntada": evita pedir el permiso repetidamente
  $("#selector-origen").outerHTML = LimaGo.htmlSelector("origen", "Punto de recojo", "Ej.: Av. Arequipa 2450, Lince");
  $("#selector-destino").outerHTML = LimaGo.htmlSelector("destino", "¿A dónde vas?", "Ej.: Jockey Plaza o Av. La Marina 2000");

  const mapa = LimaGo.crearMapa("mapa");
  LimaGo.dibujarCobertura(mapa, false).catch(() => {});
  LimaGo.SelectorLugar.conectarMapa(mapa);
  const capaCercanos = L.layerGroup().addTo(mapa);
  const capaRuta = L.layerGroup().addTo(mapa);
  let origen = null;          // {lat, lon, direccion, distrito}
  let marcadorOrigen = null, marcadorGps = null;
  let cotizacion = null, viajeId = null, temporizador = null;

  const selectorOrigen = new LimaGo.SelectorLugar($('[data-lugar="origen"]'), {
    nombre: "Punto de recojo", mapa, tipoPin: "origen",
    alCambiar: (s) => { if (s.valor) ajustar(s.valor.lat, s.valor.lon, s.valor.direccion, true); },
  });
  const selectorDestino = new LimaGo.SelectorLugar($('[data-lugar="destino"]'), {
    nombre: "Destino", mapa, tipoPin: "destino",
    alCambiar: (s) => { if (s.valor && origen) cotizar(); },
  });

  const mensaje = (texto, tipo = "error") => { $("#mensaje").innerHTML = texto ? `<div class="aviso ${tipo}">${LimaGo.escapar(texto)}</div>` : ""; };
  function vista(id) {
    for (const p of ["paso-lugares", "paso-cotizacion", "paso-busqueda", "paso-sin-conductor"]) $(`#${p}`).classList.toggle("oculto", p !== id);
  }
  function editarOrigen(abrir, motivo = "") {
    $("#editor-origen").classList.toggle("oculto", !abrir);
    $("#cambiar-origen").textContent = abrir ? "Listo" : "Cambiar";
    if (motivo) { $("#origen-texto-resumen").textContent = "Indica tu punto de recojo"; $("#origen-detalle").textContent = motivo; }
    if (abrir) setTimeout(() => $("#origen-texto").focus(), 50);
  }
  $("#cambiar-origen").addEventListener("click", () => editarOrigen($("#editor-origen").classList.contains("oculto")));

  // ---------------------------------------------------------------- ubicación
  async function ajustar(lat, lon, direccion = null, manual = false) {
    try {
      const r = await LimaGo.api(`/ubicacion/ajustar?lat=${lat}&lon=${lon}`);
      if (!r.cubierto) {
        editarOrigen(true, r.mensaje);
        if (manual) selectorOrigen.mostrar(r.mensaje, "error");
        return;
      }
      origen = { lat: r.lat, lon: r.lon, direccion: manual && direccion ? direccion : r.direccion, distrito: r.distrito };
      $("#origen-texto-resumen").textContent = LimaGo.corto(origen.direccion, 2);
      $("#origen-detalle").textContent = [r.distrito, r.distancia_a_via_m > 15 ? `ajustado a la vía más cercana (${Math.round(r.distancia_a_via_m)} m)` : ""]
        .filter(Boolean).join(" · ");
      if (marcadorOrigen) mapa.removeLayer(marcadorOrigen);
      if (selectorOrigen.marcador) { mapa.removeLayer(selectorOrigen.marcador); selectorOrigen.marcador = null; }
      marcadorOrigen = L.marker([r.lat, r.lon], { icon: LimaGo.iconoPin("origen") }).bindTooltip("Recojo").addTo(mapa);
      mapa.setView([r.lat, r.lon], 16);
      editarOrigen(false);
      refrescarCercanos();
      if (selectorDestino.valor) cotizar();
      else setTimeout(() => $("#destino-texto").focus(), 50);
    } catch (e) {
      editarOrigen(true, e.message);
    }
  }

  async function detectarUbicacion(porClic = false) {
    if (!("geolocation" in navigator)) { editarOrigen(true, "Tu navegador no permite detectar la ubicación."); return; }
    let permiso = null;
    try { permiso = (await navigator.permissions.query({ name: "geolocation" })).state; } catch (e) { /* no soportado */ }
    const previo = LimaGo.leer(GEO);
    if (!porClic && (permiso === "denied" || previo === "denegada" || (permiso !== "granted" && previo === "preguntada"))) {
      editarOrigen(true, permiso === "denied" || previo === "denegada"
        ? "Sin permiso de ubicación: escribe o marca tu punto de recojo." : "Escribe o marca tu punto de recojo.");
      return;
    }
    if (permiso !== "granted") LimaGo.guardar(GEO, "preguntada");
    $("#origen-texto-resumen").textContent = "Detectando tu ubicación…";
    navigator.geolocation.getCurrentPosition((p) => {
      LimaGo.guardar(GEO, "concedida");
      const { latitude: lat, longitude: lon } = p.coords;
      if (marcadorGps) mapa.removeLayer(marcadorGps);
      marcadorGps = L.marker([lat, lon], { icon: L.divIcon({ className: "", html: '<div class="marcador-gps"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }) })
        .bindTooltip("Tu ubicación").addTo(mapa);
      ajustar(lat, lon);
    }, (error) => {
      if (error.code === 1) LimaGo.guardar(GEO, "denegada");
      editarOrigen(true, error.code === 1 ? "Sin permiso de ubicación: escribe o marca tu punto de recojo."
        : "No pudimos obtener tu ubicación. Escribe o marca tu punto de recojo.");
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  }
  $("#usar-ubicacion").addEventListener("click", () => detectarUbicacion(true));

  async function refrescarCercanos() {
    if (!origen || !$("#paso-busqueda").classList.contains("oculto")) return;
    try {
      const { conductores } = await LimaGo.api(`/conductores/cercanos?lat=${origen.lat}&lon=${origen.lon}&n=8`);
      capaCercanos.clearLayers();
      for (const c of conductores) L.circleMarker([c.lat, c.lon], { radius: 6, color: "#fff", weight: 2, fillColor: "#16a34a", fillOpacity: 1 })
        .bindTooltip(`${c.codigo} · a ${LimaGo.distancia(c.distancia_m)}`).addTo(capaCercanos);
    } catch (e) { /* reintenta luego */ }
  }

  // --------------------------------------------------------------- cotización
  function mostrarOpciones(opciones, selector = selectorDestino) {
    const caja = $("#opciones");
    const lista = $(".sugerencias", caja);
    lista.innerHTML = opciones.map((o, i) => `<li role="option" tabindex="0" data-i="${i}">${LimaGo.escapar(LimaGo.corto(o.direccion, 2))}<small>${LimaGo.escapar(LimaGo.corto(o.direccion.split(",").slice(2).join(","), 3))}</small></li>`).join("");
    caja.classList.remove("oculto");
    lista.querySelectorAll("li").forEach((li) => {
      const elegir = () => { const o = opciones[+li.dataset.i]; caja.classList.add("oculto"); mensaje(""); selector.fijar({ lat: o.lat, lon: o.lon, direccion: o.direccion }); };
      li.addEventListener("click", elegir);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter") elegir(); });
    });
  }

  async function cotizar() {
    mensaje("");
    let destino;
    try { destino = selectorDestino.datos(); } catch (e) { mensaje(e.message); return; }
    if (!origen) {
      const texto = !selectorOrigen.valor && selectorOrigen.texto.value.trim();
      if (texto) {  // recojo escrito: se busca y, si hay varias coincidencias, se pide elegir
        try {
          const { resultados } = await LimaGo.api(`/geocodificar?q=${encodeURIComponent(texto)}`);
          if (resultados.length === 1) selectorOrigen.fijar(resultados[0]);
          else if (resultados.length > 1) { mensaje("Elige tu punto de recojo:", "info"); mostrarOpciones(resultados, selectorOrigen); }
          else mensaje("No encontramos ese punto de recojo en la zona de cobertura.");
        } catch (e) { mensaje(e.message); }
        return;
      }
      mensaje("Primero indica tu punto de recojo."); editarOrigen(true); return;
    }
    if (!destino) { mensaje("Escribe tu destino, pega coordenadas o márcalo en el mapa."); $("#destino-texto").focus(); return; }
    const boton = $("#ver-tarifa");
    boton.setAttribute("aria-busy", "true");
    boton.innerHTML = '<span class="girador" style="width:16px;height:16px"></span> Calculando ruta y tarifa…';
    try {
      cotizacion = await LimaGo.api("/viajes/cotizar", { method: "POST", body: { origen, destino } });
      pintarCotizacion();
    } catch (e) {
      if (e.estado === 409 && e.opciones.length) { mensaje(e.message, "info"); mostrarOpciones(e.opciones); }
      else mensaje(e.message);
    } finally {
      boton.removeAttribute("aria-busy");
      boton.textContent = "Ver tarifa";
    }
  }
  $("#ver-tarifa").addEventListener("click", cotizar);

  function pintarCotizacion() {
    const c = cotizacion, t = c.tarifa, d = t.desglose;
    vista("paso-cotizacion");
    $("#cot-origen").textContent = LimaGo.corto(c.origen.direccion, 2) + (c.origen.distrito ? ` · ${c.origen.distrito}` : "");
    $("#cot-destino").textContent = LimaGo.corto(c.destino.direccion, 2) + (c.destino.distrito ? ` · ${c.destino.distrito}` : "");
    $("#cot-precio").textContent = LimaGo.soles(t.total);
    $("#cot-distancia").textContent = LimaGo.distancia(c.distancia_m);
    $("#cot-duracion").textContent = LimaGo.minutos(c.duracion_s);
    $("#cot-recogida").textContent = c.recogida.eta_s != null ? `~${LimaGo.minutos(c.recogida.eta_s)}` : "Sin conductores";
    const nivel = c.trafico.nivel;
    $("#cot-trafico").className = `chip-trafico ${nivel}`;
    $("#cot-trafico").textContent = `${LimaGo.NIVELES_TRAFICO[nivel] || nivel} · ${LimaGo.hora(c.trafico.hora)}`;
    $("#cot-desglose").innerHTML = `
      <li><span>Tarifa base</span><span>${LimaGo.soles(d.base)}</span></li>
      <li><span>Recorrido (${LimaGo.distancia(c.distancia_m)})</span><span>${LimaGo.soles(d.recorrido)}</span></li>
      <li><span>Tiempo (${LimaGo.minutos(c.duracion_s)})</span><span>${LimaGo.soles(d.tiempo)}</span></li>
      ${d.recogida > 0 ? `<li><span>Recogida (${LimaGo.distancia(c.recogida.distancia_m)})</span><span>${LimaGo.soles(d.recogida)}</span></li>` : ""}
      ${d.ajuste_minimo > 0 ? `<li><span>Ajuste a tarifa mínima</span><span>${LimaGo.soles(d.ajuste_minimo)}</span></li>` : ""}
      <li class="total"><span>Total estimado</span><span>${LimaGo.soles(t.total)}</span></li>`;
    $("#cot-nota").textContent = "Monto orientativo en soles: no es un cobro. El tráfico se estima con un modelo por horario, no en tiempo real. La tarifa se mantiene al confirmar.";
    capaRuta.clearLayers();
    const linea = L.polyline(c.ruta, { color: "#0f766e", weight: 6, opacity: 0.9 }).addTo(capaRuta);
    L.marker([c.destino.lat, c.destino.lon], { icon: LimaGo.iconoPin("destino") }).bindTooltip("Destino").addTo(capaRuta);
    mapa.fitBounds(linea.getBounds(), { padding: [50, 50] });
    if (selectorDestino.marcador) { mapa.removeLayer(selectorDestino.marcador); selectorDestino.marcador = null; }
    $("#confirmar").disabled = c.recogida.conductores_cerca === 0;
    if (c.recogida.conductores_cerca === 0) $("#cot-nota").textContent = "Ahora no hay conductores disponibles cerca. Inténtalo en unos minutos.";
  }
  $("#volver").addEventListener("click", () => { capaRuta.clearLayers(); vista("paso-lugares"); });

  // -------------------------------------------------------- confirmación
  $("#confirmar").addEventListener("click", async () => {
    const boton = $("#confirmar");
    boton.setAttribute("aria-busy", "true");
    try {
      const viaje = await LimaGo.api("/viajes", { method: "POST", body: { cotizacion_id: cotizacion.id } });
      viajeId = viaje.id;
      LimaGo.guardar("limago.viaje", viajeId);
      vista("paso-busqueda");
      capaCercanos.clearLayers();
      seguirBusqueda(viaje);
      temporizador = setInterval(async () => { try { seguirBusqueda(await LimaGo.api(`/viajes/${viajeId}`)); } catch (e) { /* reintenta */ } }, 1000);
    } catch (e) {
      if (e.codigo === "cotizacion_vencida") { Plantilla.notificar("La tarifa venció; la recalculamos.", "info"); await cotizar(); }
      else Plantilla.notificar(e.message, "error");
    } finally {
      boton.removeAttribute("aria-busy");
    }
  });

  function seguirBusqueda(v) {
    if (["asignada", "esperando_recogida", "en_viaje"].includes(v.estado)) {
      clearInterval(temporizador);
      Plantilla.notificar(`${LimaGo.codigoConductor(v.conductor_id)} aceptó tu viaje.`, "exito");
      location.href = `seguimiento.html?id=${v.id}`;
      return;
    }
    if (v.estado === "buscando") {
      const o = v.oferta;
      $("#busqueda-texto").textContent = o ? `Esperando respuesta de ${o.conductor} (${o.numero} de ${o.total})…` : "Enviando tu solicitud a conductores cercanos…";
      $("#busqueda-detalle").textContent = o && o.rechazos ? `${o.rechazos} conductor${o.rechazos > 1 ? "es" : ""} no pudo tomar el viaje; seguimos buscando.` : "";
      if (v.simulacion && v.simulacion.en_pausa) $("#busqueda-detalle").textContent = "El servicio está en pausa momentáneamente.";
      return;
    }
    clearInterval(temporizador);
    LimaGo.borrar("limago.viaje");
    if (v.estado === "cancelada") { vista("paso-cotizacion"); return; }
    $("#sin-conductor-texto").textContent = v.mensaje || LimaGo.ESTADOS_VIAJE[v.estado] || "No encontramos conductor.";
    vista("paso-sin-conductor");
  }

  $("#cancelar-busqueda").addEventListener("click", async () => {
    try {
      await LimaGo.api(`/viajes/${viajeId}/cancelar`, { method: "POST" });
      clearInterval(temporizador);
      LimaGo.borrar("limago.viaje");
      Plantilla.notificar("Solicitud cancelada.", "info");
      vista("paso-lugares");
    } catch (e) { Plantilla.notificar(e.message, "error"); }
  });
  $("#reintentar").addEventListener("click", () => { vista("paso-lugares"); cotizar(); });

  // ------------------------------------------------------------- inicio
  const destinoParam = LimaGo.parametro("destino"), origenParam = LimaGo.parametro("origen");
  if (destinoParam) selectorDestino.fijarTexto(destinoParam);
  if (origenParam) { editarOrigen(true); selectorOrigen.fijarTexto(origenParam); }
  else detectarUbicacion();
  setInterval(refrescarCercanos, 4000);
})();
