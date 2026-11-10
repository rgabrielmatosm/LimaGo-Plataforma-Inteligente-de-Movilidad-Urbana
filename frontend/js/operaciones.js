/* LimaGo V3 — centro de operaciones. Todas las llamadas usan el código de operador (Authorization: Bearer). */
"use strict";

(() => {
  const $ = (s) => document.querySelector(s);
  document.querySelectorAll("[data-icono]").forEach((n) => { n.innerHTML = Plantilla.icono(n.dataset.icono); });
  const CLAVE = "limago.operador";
  const leerCodigo = () => { try { return sessionStorage.getItem(CLAVE); } catch (e) { return null; } };
  const guardarCodigo = (v) => { try { v ? sessionStorage.setItem(CLAVE, v) : sessionStorage.removeItem(CLAVE); } catch (e) { /* sin almacenamiento */ } };
  let codigo = leerCodigo();
  let mapa = null, flota = null, capaPasajeros = null, capaApoyo = null, temporizador = null, configurado = false;
  let alertasVistas = null;

  const api = (ruta, opciones = {}) => LimaGo.api(ruta, { ...opciones, headers: { Authorization: `Bearer ${codigo}` } });

  function mostrarAcceso(mensaje = "") {
    if (temporizador) { clearInterval(temporizador); temporizador = null; }
    $("#panel").classList.add("oculto");
    $("#acceso").classList.remove("oculto");
    $("#acceso-mensaje").textContent = mensaje;
    $("#acceso-mensaje").className = `ayuda ${mensaje ? "error" : ""}`;
    $("#codigo").focus();
  }

  async function entrar() {
    try {
      await api("/operaciones/sesion");
    } catch (error) {
      guardarCodigo(null);
      codigo = null;
      mostrarAcceso(error.estado === 401 ? "Código incorrecto." : error.message);
      return;
    }
    $("#acceso").classList.add("oculto");
    $("#panel").classList.remove("oculto");
    $("#enlace-monitoreo").href = `${location.protocol}//${location.hostname}:3000/`;
    if (!mapa) {
      mapa = LimaGo.crearMapa("mapa");
      flota = new LimaGo.CapaFlota(mapa, { radio: 4 });
      capaPasajeros = L.layerGroup().addTo(mapa);
      capaApoyo = L.layerGroup().addTo(mapa);
      $("#ver-flota").addEventListener("change", (e) => {
        if (e.target.checked) flota.capa.addTo(mapa); else mapa.removeLayer(flota.capa);
      });
      LimaGo.dibujarCobertura(mapa).catch(() => {});
    }
    await refrescar();
    temporizador = setInterval(refrescar, 2000);
  }

  async function refrescar() {
    try {
      const [r, f, a] = await Promise.all([api("/operaciones/resumen"), LimaGo.api("/flota"), api("/operaciones/alertas")]);
      if ($("#ver-flota").checked) flota.actualizar(f.conductores);
      for (const k of ["disponible", "en_camino", "en_viaje", "desconectado"]) $(`#k-${k}`).textContent = (r.conteo[k] || 0).toLocaleString("es-PE");
      $("#k-ofertas").textContent = r.ofertas_vigentes ?? "—";
      $("#k-alertas").textContent = r.alertas_abiertas ?? "—";
      pintarAlertas(a);
      pintarAceptacion(r.aceptacion);
      $("#k-activas").textContent = r.total_activas;
      $("#k-turno").textContent = `${r.turno} · ${LimaGo.hora(r.hora_simulada)}`;
      const tasa = r.estadisticas.tasa_asignacion;
      $("#k-tasa").textContent = tasa == null ? "—" : `${Math.round(tasa * 100)} %`;
      const estado = $("#estado-servicio");
      estado.className = `etiqueta ${!r.worker_activo ? "estado-rechazada" : r.en_pausa ? "estado-asignada" : "estado-completada"}`;
      estado.textContent = !r.worker_activo ? "Sin respuesta" : r.en_pausa ? `En pausa · semilla ${r.semilla}` : `En marcha · semilla ${r.semilla}`;
      if (!configurado && r.configuracion) {
        $("#congestion").checked = r.configuracion.congestion_activa;
        $("#k").value = r.configuracion.k_candidatos;
        $("#demanda").value = r.configuracion.tasa_solicitudes_por_turno;
        $("#hora-escenario").value = r.configuracion.reloj === "lima" ? "" : LimaGo.hora(r.hora_simulada);
        $("#reloj-modo").textContent = r.configuracion.reloj === "lima"
          ? "Reloj: hora actual de Lima. Fijar una hora (p. ej. 08:00 o 15:00) reproduce los escenarios de prueba."
          : "Reloj: hora fijada por el operador; avanza con cada turno.";
        configurado = true;
      }
      capaPasajeros.clearLayers();
      for (const s of r.activas) {
        if (["buscando", "asignada", "esperando_recogida"].includes(s.estado) && s.origen_lat != null) {
          L.circleMarker([s.origen_lat, s.origen_lon], { radius: 5, color: "#ffffff", weight: 1.5, fillColor: "#0f1f1c", fillOpacity: 1 })
            .bindTooltip(`Solicitud #${s.id}`).addTo(capaPasajeros);
          if (s.conductor) L.polyline([[s.conductor.lat, s.conductor.lon], [s.origen_lat, s.origen_lon]], { color: "#d97706", weight: 1.5, dashArray: "4 4" }).addTo(capaPasajeros);
        }
      }
      const canales = { app: "App", simulacion: "Escenario", operaciones: "Lote" };
      $("#activas").innerHTML = r.activas.length ? r.activas.slice(0, 40).map((s) => `<tr>
          <td class="num">#${s.id}</td><td>${LimaGo.escapar(LimaGo.corto(s.origen_texto, 2)) || "—"}</td><td>${canales[s.canal] || s.canal}</td>
          <td class="num">${LimaGo.codigoConductor(s.conductor_id)}</td><td class="num">${LimaGo.minutos(s.eta_s)}</td>
          <td><span class="etiqueta estado-${s.estado}">${LimaGo.ESTADOS_VIAJE[s.estado] || s.estado}</span></td></tr>`).join("")
        : '<tr><td colspan="6" class="vacio">No hay solicitudes activas.</td></tr>';
    } catch (error) {
      if (error.estado === 401) { guardarCodigo(null); codigo = null; mostrarAcceso("La sesión expiró. Ingresa el código de nuevo."); return; }
      Plantilla.notificar(error.message, "error");
    }
  }

  function pintarAlertas({ alertas, unidades }) {
    const abiertas = alertas.filter((x) => x.estado === "abierta");
    const nuevas = alertasVistas == null ? [] : abiertas.filter((x) => !alertasVistas.has(x.id));
    alertasVistas = new Set(alertas.map((x) => x.id));
    for (const x of nuevas) Plantilla.notificar(`Nueva alerta en el viaje #${x.solicitud_id}${x.unidad ? ` · ${x.unidad} asignada` : ""}`, "error");
    const aviso = $("#aviso-alertas");
    aviso.classList.toggle("oculto", !abiertas.length);
    aviso.textContent = abiertas.length ? `Hay ${abiertas.length} alerta(s) sin atender. Revisa la tabla de alertas.` : "";
    $("#alertas").innerHTML = alertas.length ? alertas.slice(0, 20).map((x) => `<tr>
        <td class="num">#${x.id}</td><td class="num"><a href="seguimiento.html?id=${x.solicitud_id}">#${x.solicitud_id}</a></td>
        <td class="num">${LimaGo.fecha(x.creada_en)}</td>
        <td>${x.unidad ? `${LimaGo.escapar(x.unidad)} · ${LimaGo.distancia(x.distancia_unidad_m)}` : "Sin unidad libre"}</td>
        <td><span class="etiqueta ${x.estado === "abierta" ? "estado-rechazada" : "estado-completada"}">${x.estado === "abierta" ? "Abierta" : "Atendida"}</span></td>
        <td>${x.estado === "abierta" ? `<button class="boton secundario pequeno" type="button" data-atender="${x.id}">Atender</button>` : LimaGo.escapar(x.nota || "")}</td></tr>`).join("")
      : '<tr><td colspan="6" class="vacio">No hay alertas registradas.</td></tr>';
    capaApoyo.clearLayers();
    for (const u of unidades) {
      L.circleMarker([u.lat, u.lon], { radius: 6, color: "#ffffff", weight: 2, fillColor: u.estado === "asignada" ? "#dc2626" : "#2563eb", fillOpacity: 1 })
        .bindTooltip(`${u.codigo} · ${u.estado === "asignada" ? `atendiendo alerta #${u.alerta_id}` : "disponible"} (simulada)`).addTo(capaApoyo);
    }
    for (const x of abiertas) {
      if (x.lat != null) L.circleMarker([x.lat, x.lon], { radius: 9, color: "#dc2626", weight: 3, fillOpacity: 0.2 }).bindTooltip(`Alerta #${x.id}`).addTo(capaApoyo);
    }
  }

  function pintarAceptacion(a) {
    if (!a || !a.solicitudes) { $("#aceptacion").innerHTML = '<p class="ayuda" style="margin:0">Sin datos todavía.</p>'; return; }
    const pct = (n) => `${Math.round((100 * n) / Math.max(1, a.solicitudes))} %`;
    const coincide = a.aceptadas ? Math.round((100 * a.coincide_con_academico) / a.aceptadas) : 0;
    $("#aceptacion").innerHTML = `<div class="datos-viaje">
      <div><span>Solicitudes resueltas</span><strong>${a.solicitudes}</strong></div>
      <div><span>Aceptadas</span><strong>${a.aceptadas} (${pct(a.aceptadas)})</strong></div>
      <div><span>Sin aceptación</span><strong>${a.sin_aceptacion}</strong></div>
      <div><span>Ofertas por solicitud</span><strong>${a.intentos_medios == null ? "—" : a.intentos_medios.toFixed(2).replace(".", ",")}</strong></div>
      <div><span>Igual al óptimo de referencia</span><strong>${coincide} %</strong></div>
      <div><span>Espera extra media</span><strong>${a.eta_extra_medio_s == null ? "—" : `${Math.round(a.eta_extra_medio_s)} s`}</strong></div></div>
      <p class="ayuda" style="margin:8px 0 0">El óptimo de referencia es el conductor de menor llegada entre los candidatos; la asignación operativa es quien aceptó la oferta.</p>`;
  }

  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-atender]");
    if (!b) return;
    const nota = prompt("Nota de atención (opcional):", "Contactado por el centro de operaciones") ?? null;
    if (nota === null) return;
    operar(`/operaciones/alertas/${b.dataset.atender}/atender`, { nota }, () => "Alerta marcada como atendida.");
  });

  async function operar(ruta, cuerpo, mensaje) {
    try {
      const r = await api(ruta, { method: "POST", body: cuerpo || {} });
      Plantilla.notificar(mensaje(r), "exito");
      refrescar();
      return r;
    } catch (error) {
      Plantilla.notificar(error.message, "error");
      return null;
    }
  }

  $("#form-acceso").addEventListener("submit", (e) => {
    e.preventDefault();
    const valor = $("#codigo").value.trim();
    if (!valor) { mostrarAcceso("Ingresa el código."); return; }
    codigo = valor;
    guardarCodigo(valor);
    $("#codigo").value = "";
    entrar();
  });
  $("#salir").addEventListener("click", () => { guardarCodigo(null); codigo = null; mostrarAcceso(); });

  document.querySelectorAll("[data-accion]").forEach((b) => b.addEventListener("click", () => {
    const cuerpo = b.dataset.turnos ? { turnos: +b.dataset.turnos } : null;
    operar(`/operaciones/${b.dataset.accion}`, cuerpo, (r) => `Listo: turno ${r.turno}${r.en_pausa ? " (en pausa)" : ""}.`);
  }));

  $("#form-escenario").addEventListener("submit", (e) => {
    e.preventDefault();
    const [hh, mm] = ($("#hora-escenario").value || "").split(":").map(Number);
    const cuerpo = { congestion_activa: $("#congestion").checked, k_candidatos: +$("#k").value,
      tasa_solicitudes_por_turno: +$("#demanda").value };
    if (!Number.isNaN(hh) && $("#hora-escenario").value) cuerpo.hora = hh + (mm || 0) / 60;
    operar("/operaciones/configurar", cuerpo, (r) => `Escenario actualizado: ${r.configuracion.congestion_activa ? "con" : "sin"} hora punta, ${LimaGo.hora(r.hora_simulada)}.`);
  });

  $("#usar-hora-lima").addEventListener("click", () => {
    configurado = false;
    operar("/operaciones/configurar", { reloj_lima: true }, (r) => `El reloj sigue la hora de Lima (${LimaGo.hora(r.hora_simulada)}).`);
  });

  $("#form-lote").addEventListener("submit", async (e) => {
    e.preventDefault();
    const caja = $("#lote-resultado");
    caja.innerHTML = '<div class="buscando" style="margin-top:10px"><span class="girador"></span>Asignando…</div>';
    const r = await operar("/operaciones/lote", { cantidad: +$("#cantidad").value, estrategia: $("#estrategia").value },
      (x) => `${x.solicitudes.length} solicitudes asignadas.`);
    if (!r) { caja.innerHTML = ""; return; }
    const asignados = r.asignaciones.filter((a) => a.conductor_id != null).length;
    const otro = r.estrategia === "optima" ? "por orden de llegada" : "con menor espera total";
    caja.innerHTML = `<div class="aviso info" style="margin-bottom:0">${asignados} de ${r.asignaciones.length} pasajeros con conductor.<br>
      Espera total: <strong>${LimaGo.minutos(r.espera_total_s)}</strong> · ${otro}: ${LimaGo.minutos(r.espera_total_alternativa_s)}.</div>`;
    if (r.centro) mapa.setView(r.centro, 16);
  });

  $("#form-reinicio").addEventListener("submit", (e) => {
    e.preventDefault();
    if (!confirm("Se reiniciará la flota y los viajes en curso quedarán interrumpidos. ¿Continuar?")) return;
    configurado = false;
    operar("/operaciones/reiniciar", { semilla: +$("#semilla").value, num_conductores: +$("#conductores").value },
      (r) => `Escenario reiniciado con semilla ${r.semilla}.`);
  });

  if (codigo) entrar(); else mostrarAcceso();
})();
