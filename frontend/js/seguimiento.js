/* LimaGo V3 — seguimiento en vivo. Posición, ruta restante, ETA y estados vienen del servidor; el navegador solo
   anima el vehículo entre dos posiciones consecutivas siguiendo la ruta vial recibida. */
"use strict";

(async () => {
  const $ = (s) => document.querySelector(s);
  document.querySelectorAll("[data-icono]").forEach((n) => { n.innerHTML = Plantilla.icono(n.dataset.icono); });
  const mapa = LimaGo.crearMapa("mapa");
  LimaGo.dibujarCobertura(mapa, false).catch(() => {});
  const capa = L.layerGroup().addTo(mapa);
  let vehiculo = null, linea = null, pinOrigen = null, pinDestino = null;
  let idViaje = parseInt(LimaGo.parametro("id") || LimaGo.leer("limago.viaje") || "", 10) || null;
  let ultimoEstado = null, centrado = false, temporizador = null, ultimaActualizacion = 0, seguir = true;
  const ACTIVOS = new Set(["buscando", "asignada", "esperando_recogida", "en_viaje"]);
  const CON_CONDUCTOR = new Set(["asignada", "esperando_recogida", "en_viaje"]);
  mapa.on("dragstart", () => { seguir = false; });  // si el usuario mueve el mapa, deja de centrarse en el auto

  function mostrarBuscador() {
    $("#buscar-viaje").classList.remove("oculto");
    $("#viaje").classList.add("oculto");
    cargarActivos();
  }

  async function cargarActivos() {
    try {
      const { solicitudes } = await LimaGo.api("/viajes?canal=app&estado=buscando,asignada,esperando_recogida,en_viaje&limite=10");
      $("#activos").innerHTML = solicitudes.length
        ? solicitudes.map((s) => `<a class="tarjeta plana" style="display:flex;justify-content:space-between;gap:10px;padding:12px 14px;margin-bottom:8px;text-decoration:none;color:inherit" href="seguimiento.html?id=${s.id}">
            <span><strong>#${s.id}</strong> · ${LimaGo.escapar(LimaGo.corto(s.origen_texto, 2) || "Recojo")}<br><span class="ayuda">${LimaGo.fecha(s.creada_en)}</span></span>
            <span class="etiqueta estado-${s.estado}">${LimaGo.ESTADOS_VIAJE[s.estado]}</span></a>`).join("")
        : `<div class="vacio">${Plantilla.icono("vacio")}<p>No hay viajes activos en este momento.</p></div>`;
    } catch (e) {
      $("#activos").innerHTML = `<div class="aviso error">${LimaGo.escapar(e.message)}</div>`;
    }
  }

  $("#form-numero").addEventListener("submit", (e) => {
    e.preventDefault();
    const valor = $("#numero").value.trim();
    if (!/^\d+$/.test(valor)) {
      $("#numero").setAttribute("aria-invalid", "true");
      $("#numero-ayuda").textContent = "Ingresa solo números.";
      $("#numero-ayuda").className = "ayuda error";
      return;
    }
    location.href = `seguimiento.html?id=${valor}`;
  });

  const PASO = { buscando: 1, asignada: 2, esperando_recogida: 3, en_viaje: 4, completada: 5 };

  function pintar(v) {
    $("#buscar-viaje").classList.add("oculto");
    $("#viaje").classList.remove("oculto");
    const activo = ACTIVOS.has(v.estado), pausado = v.simulacion && v.simulacion.en_pausa;
    $("#estado").className = `etiqueta estado-${v.estado}`;
    $("#estado").textContent = (LimaGo.ESTADOS_VIAJE[v.estado] || v.estado) + (pausado && activo ? " · servicio en pausa" : "");
    $("#numero-viaje").textContent = `Solicitud #${v.id}`;
    $("#conductor").textContent = v.conductor_id && CON_CONDUCTOR.has(v.estado) || v.estado === "completada"
      ? `Conductor ${LimaGo.codigoConductor(v.conductor_id)}` : "Buscando conductor";
    $("#tarifa").textContent = v.tarifa_estimada != null ? LimaGo.soles(v.tarifa_estimada) : "—";
    $("#hora").textContent = LimaGo.fecha(v.creada_en);
    const lugar = (t, d) => [LimaGo.corto(t, 2), d].filter(Boolean).join(" · ");
    $("#direcciones").textContent = `Recojo: ${lugar(v.origen_texto, v.distrito_origen) || "—"}` +
      (v.destino_lat != null ? ` · Destino: ${lugar(v.destino_texto, v.distrito_destino) || "punto marcado"}` : "");

    const total = v.metros_totales_fase, falta = v.metros_restantes;
    const pct = CON_CONDUCTOR.has(v.estado) && total ? Math.max(0, Math.min(100, Math.round(100 * (1 - falta / total))))
      : v.estado === "esperando_recogida" ? 100 : v.estado === "completada" ? 100 : 0;
    $("#barra div").style.width = `${pct}%`;
    $("#barra").setAttribute("aria-valuenow", String(pct));
    $("#progreso-valor").textContent = CON_CONDUCTOR.has(v.estado) || v.estado === "completada" ? `${pct} %` : "";

    if (v.estado === "buscando") {
      const o = v.oferta;
      $("#detalle").textContent = o ? `Esperando respuesta de ${o.conductor} (${o.numero} de ${o.total})` : "Enviando tu solicitud…";
      $("#eta").textContent = "…"; $("#eta-texto").textContent = "buscando";
      $("#progreso-texto").textContent = "Buscando conductor"; $("#restante").textContent = "—";
    } else if (v.estado === "asignada") {
      $("#detalle").textContent = "Va hacia tu punto de recojo";
      $("#eta").textContent = LimaGo.minutos(v.segundos_restantes ?? v.eta_s);
      $("#eta-texto").textContent = "para llegar a ti";
      $("#progreso-texto").textContent = "Camino a recogerte";
      $("#restante").textContent = LimaGo.distancia(falta ?? v.distancia_calles_m);
    } else if (v.estado === "esperando_recogida") {
      $("#detalle").textContent = "Está en el punto de recojo";
      $("#eta").textContent = "Llegó"; $("#eta-texto").textContent = "te espera";
      $("#progreso-texto").textContent = "Tu conductor llegó"; $("#restante").textContent = "0 m";
    } else if (v.estado === "en_viaje") {
      $("#detalle").textContent = "Viaje en curso";
      $("#eta").textContent = LimaGo.minutos(v.segundos_restantes);
      $("#eta-texto").textContent = "a tu destino";
      $("#progreso-texto").textContent = "Rumbo a tu destino";
      $("#restante").textContent = LimaGo.distancia(falta);
    } else {
      $("#detalle").textContent = v.mensaje || "";
      $("#eta").textContent = v.estado === "completada" ? "✓" : "—";
      $("#eta-texto").textContent = LimaGo.ESTADOS_VIAJE[v.estado] || "";
      $("#progreso-texto").textContent = v.estado === "completada" ? "Recorrido terminado" : "Viaje no activo";
      $("#restante").textContent = v.estado === "completada" ? "0 m" : "—";
    }
    const p = PASO[v.estado] || 0;
    document.querySelectorAll("#linea li").forEach((li, i) => {
      li.classList.toggle("hecho", i < p - 1 || p === 5);
      li.classList.toggle("actual", i === p - 1 && p !== 5);
    });
    $("#cancelar").classList.toggle("oculto", !["buscando", "asignada", "esperando_recogida"].includes(v.estado));
    $("#alerta").classList.toggle("oculto", !CON_CONDUCTOR.has(v.estado));
    $("#alerta-nota").classList.toggle("oculto", !CON_CONDUCTOR.has(v.estado));
    $("#nuevo").classList.toggle("oculto", activo);

    if (ultimoEstado && ultimoEstado !== v.estado) {
      const mensajes = { asignada: [`${LimaGo.codigoConductor(v.conductor_id)} aceptó tu viaje.`, "exito"],
        esperando_recogida: ["Tu conductor llegó al punto de recojo.", "exito"], en_viaje: ["¡Buen viaje!", "exito"],
        completada: ["Llegaste a tu destino. Gracias por viajar con LimaGo.", "exito"], cancelada: ["El viaje fue cancelado.", "info"],
        sin_aceptacion: ["Ningún conductor cercano aceptó el viaje.", "advertencia"], interrumpida: ["El servicio se interrumpió.", "advertencia"] };
      const [texto, tipo] = mensajes[v.estado] || [LimaGo.ESTADOS_VIAJE[v.estado], "info"];
      Plantilla.notificar(texto, tipo);
    }
    if (!activo) LimaGo.borrar("limago.viaje");
    ultimoEstado = v.estado;
    dibujar(v, pausado);
  }

  function dibujar(v, pausado) {
    if (v.origen_lat != null && !pinOrigen) pinOrigen = L.marker([v.origen_lat, v.origen_lon], { icon: LimaGo.iconoPin("origen") }).bindTooltip("Recojo").addTo(capa);
    if (v.destino_lat != null && !pinDestino) pinDestino = L.marker([v.destino_lat, v.destino_lon], { icon: LimaGo.iconoPin("destino") }).bindTooltip("Destino").addTo(capa);
    const conConductor = CON_CONDUCTOR.has(v.estado) && v.conductor;
    const ruta = conConductor && v.ruta_restante && v.ruta_restante.length > 1 ? v.ruta_restante : [];
    if (linea) capa.removeLayer(linea);
    linea = ruta.length ? L.polyline(ruta, { color: v.estado === "en_viaje" ? "#f26b3a" : "#0f766e", weight: 6, opacity: 0.85 }).addTo(capa) : null;
    const ahora = performance.now();
    const duracion = Math.max(300, Math.min(2500, ultimaActualizacion ? ahora - ultimaActualizacion : 1000));
    ultimaActualizacion = ahora;
    if (conConductor) {
      if (!vehiculo) vehiculo = new LimaGo.VehiculoAnimado(mapa, { codigo: v.conductor.codigo });
      vehiculo.actualizar(v.conductor, ruta, { pausado, duracionMs: duracion });
      if (seguir && centrado && vehiculo.posicion() && !mapa.getBounds().pad(-0.15).contains(vehiculo.posicion())) mapa.panTo(vehiculo.posicion());
    } else if (vehiculo) { vehiculo.quitar(); vehiculo = null; }
    if (!centrado) {
      const puntos = [];
      if (pinOrigen) puntos.push(pinOrigen.getLatLng());
      if (pinDestino) puntos.push(pinDestino.getLatLng());
      if (vehiculo && vehiculo.posicion()) puntos.push(vehiculo.posicion());
      if (linea) puntos.push(...linea.getLatLngs());
      if (puntos.length) { mapa.fitBounds(L.latLngBounds(puntos), { padding: [50, 50], maxZoom: 17 }); centrado = true; }
    }
  }

  async function refrescar() {
    try {
      const v = await LimaGo.api(`/viajes/${idViaje}`);
      pintar(v);
      if (!ACTIVOS.has(v.estado) && temporizador) { clearInterval(temporizador); temporizador = null; }
    } catch (error) {
      if (error.estado === 404) {
        LimaGo.borrar("limago.viaje");
        idViaje = null;
        Plantilla.notificar("No encontramos esa solicitud.", "error");
        mostrarBuscador();
        if (temporizador) { clearInterval(temporizador); temporizador = null; }
      }
    }
  }

  $("#cancelar").addEventListener("click", async () => {
    if (!confirm("¿Seguro que quieres cancelar el viaje?")) return;
    const boton = $("#cancelar");
    boton.setAttribute("aria-busy", "true");
    try { pintar(await LimaGo.api(`/viajes/${idViaje}/cancelar`, { method: "POST" })); }
    catch (error) { Plantilla.notificar(error.message, "error"); }
    finally { boton.removeAttribute("aria-busy"); }
  });

  $("#alerta").addEventListener("click", () => {
    const modal = Plantilla.abrirModal("Alerta de seguridad", `
      <p>Se notificará al <strong>centro de operaciones de LimaGo</strong> con la ubicación de tu viaje y se asignará la unidad de apoyo más cercana.</p>
      <div class="aviso advertencia">Esta es una función de demostración dentro de una simulación: <strong>no</strong> contacta a la Policía Nacional, al SAMU, al serenazgo ni a ningún servicio real. En una emergencia real llama directamente a los servicios de emergencia.</div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
        <button class="boton secundario" type="button" data-cancelar>Cancelar</button>
        <button class="boton alerta" type="button" data-enviar>Enviar alerta</button>
      </div>`);
    modal.elemento.querySelector("[data-cancelar]").addEventListener("click", modal.cerrar);
    modal.elemento.querySelector("[data-enviar]").addEventListener("click", async () => {
      try {
        const r = await LimaGo.api(`/viajes/${idViaje}/alerta`, { method: "POST" });
        modal.cerrar();
        Plantilla.notificar(r.duplicada ? "Ya registramos tu alerta; el centro de operaciones la está atendiendo."
          : `Alerta registrada. Unidad de apoyo simulada ${r.unidad || ""} a ${LimaGo.distancia(r.distancia_unidad_m)}.`, r.duplicada ? "info" : "exito", 8000);
      } catch (e) { Plantilla.notificar(e.message, "error"); }
    });
  });

  if (!idViaje) { mostrarBuscador(); return; }
  await refrescar();
  if (idViaje) temporizador = setInterval(refrescar, 1000);
})();
