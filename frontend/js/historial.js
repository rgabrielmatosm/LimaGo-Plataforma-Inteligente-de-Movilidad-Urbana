/* LimaGo V3 — historial: filtros, tarjetas/tabla, paginación y detalle de cada solicitud (datos de la base de datos). */
"use strict";

(() => {
  const $ = (s) => document.querySelector(s);
  const POR_PAGINA = 30;
  const CANALES = { app: "Solicitud desde la app", simulacion: "Demanda del escenario", operaciones: "Lote de operaciones" };
  let canal = "app", vista = "tarjetas", filas = [], hayMas = false;

  const lugar = (texto, lat) => LimaGo.escapar(LimaGo.corto(texto, 2)) || (lat != null ? "Punto marcado" : "—");

  function filtrarTexto(lista) {
    const q = $("#filtro-texto").value.trim().toLowerCase();
    if (!q) return lista;
    return lista.filter((s) => String(s.id) === q.replace("#", "") ||
      `${s.origen_texto || ""} ${s.destino_texto || ""}`.toLowerCase().includes(q));
  }

  function pintar() {
    const visibles = filtrarTexto(filas);
    $("#resumen").textContent = filas.length ? `${visibles.length} de ${filas.length} solicitudes cargadas` : "";
    const vacio = !visibles.length;
    $("#estado-vacio").classList.toggle("oculto", !vacio);
    $("#estado-vacio").innerHTML = vacio ? `<div class="vacio tarjeta plana">${Plantilla.icono("vacio")}
        <p>${filas.length ? "Ninguna solicitud coincide con la búsqueda." : "Aún no hay viajes con este filtro."}</p>
        <a class="boton" href="viaje.html">Pedir un viaje</a></div>` : "";
    $("#tarjetas").classList.toggle("oculto", vista !== "tarjetas" || vacio);
    $("#tabla").classList.toggle("oculto", vista !== "tabla" || vacio);
    $("#tarjetas").innerHTML = visibles.map((s) => `
      <article class="tarjeta plana tarjeta-viaje">
        <div class="fila"><strong>#${s.id}</strong><span class="etiqueta estado-${s.estado}">${LimaGo.ESTADOS_VIAJE[s.estado] || s.estado}</span></div>
        <div class="lugares">
          <span><span class="punto" style="background:#0f1f1c"></span>${lugar(s.origen_texto, s.origen_lat)}</span>
          <span><span class="punto" style="background:#f26b3a;border-radius:2px"></span>${lugar(s.destino_texto, s.destino_lat)}</span>
        </div>
        <div class="fila ayuda"><span>${LimaGo.fecha(s.creada_en)}</span><span>${LimaGo.codigoConductor(s.conductor_id)}</span></div>
        <div class="fila"><span class="ayuda">Llegada ${LimaGo.minutos(s.eta_s)} · ${LimaGo.soles(s.tarifa_estimada)}</span>
          <button class="boton fantasma pequeno" type="button" data-detalle="${s.id}">Ver detalle</button></div>
      </article>`).join("");
    $("#filas").innerHTML = visibles.map((s) => `
      <tr><td class="num">#${s.id}</td><td class="num">${LimaGo.fecha(s.creada_en)}</td><td>${lugar(s.origen_texto, s.origen_lat)}</td>
        <td>${lugar(s.destino_texto, s.destino_lat)}</td><td class="num">${LimaGo.codigoConductor(s.conductor_id)}</td>
        <td class="num">${LimaGo.minutos(s.eta_s)}</td><td class="num">${LimaGo.soles(s.tarifa_estimada)}</td>
        <td><span class="etiqueta estado-${s.estado}">${LimaGo.ESTADOS_VIAJE[s.estado] || s.estado}</span></td>
        <td><button class="boton fantasma pequeno" type="button" data-detalle="${s.id}">Detalle</button></td></tr>`).join("");
    $("#mas").classList.toggle("oculto", !hayMas);
  }

  async function cargar(reiniciar = true) {
    const estado = $("#filtro-estado").value;
    const antes = !reiniciar && filas.length ? `&antes_de=${filas[filas.length - 1].id}` : "";
    if (reiniciar) {
      filas = [];
      $("#tarjetas").innerHTML = '<div class="esqueleto" style="height:150px"></div>'.repeat(3);
      $("#tarjetas").classList.remove("oculto");
      $("#estado-vacio").classList.add("oculto");
    }
    $("#mas").setAttribute("aria-busy", "true");
    try {
      const { solicitudes } = await LimaGo.api(`/viajes?canal=${canal}&limite=${POR_PAGINA}${estado ? `&estado=${estado}` : ""}${antes}`);
      filas = filas.concat(solicitudes);
      hayMas = solicitudes.length === POR_PAGINA;
      pintar();
    } catch (e) {
      $("#tarjetas").innerHTML = `<div class="aviso error">${LimaGo.escapar(e.message)}</div>`;
    } finally {
      $("#mas").removeAttribute("aria-busy");
    }
  }

  const RESULTADOS = { acepta: "Aceptó", rechaza: "No aceptó", vencida: "No respondió a tiempo", no_disponible: "Ya no estaba disponible", cancelada: "Cancelada" };

  function desglose(t) {
    const x = t && t.desglose;
    if (!x) return "";
    return `<ul class="desglose">
      <li><span>Tarifa base</span><span>${LimaGo.soles(x.base)}</span></li>
      <li><span>Recorrido</span><span>${LimaGo.soles(x.recorrido)}</span></li>
      <li><span>Tiempo</span><span>${LimaGo.soles(x.tiempo)}</span></li>
      <li><span>Recogida</span><span>${LimaGo.soles(x.recogida)}</span></li>
      ${x.ajuste_minimo > 0 ? `<li><span>Ajuste a tarifa mínima</span><span>${LimaGo.soles(x.ajuste_minimo)}</span></li>` : ""}
      <li class="total"><span>Total confirmado</span><span>${LimaGo.soles(t.total)}</span></li></ul>`;
  }

  function intentos(lista) {
    if (!lista || !lista.length) return "";
    return `<h3 style="font-size:1rem;margin:14px 0 6px">Ofertas a conductores</h3><ol class="ayuda" style="margin:0 0 8px;padding-left:20px">
      ${lista.map((i) => `<li>${LimaGo.codigoConductor(i.conductor_id)}${i.eta_s != null ? ` · llegada ${LimaGo.minutos(i.eta_s)}` : ""} · ${RESULTADOS[i.resultado] || LimaGo.escapar(i.resultado || "pendiente")}</li>`).join("")}</ol>`;
  }

  async function detalle(id) {
    const modal = Plantilla.abrirModal(`Solicitud #${id}`, '<div class="esqueleto" style="height:220px"></div>');
    try {
      const s = await LimaGo.api(`/viajes/${id}`);
      const candidatos = [...(s.candidatos || [])].sort((a, b) => a.distancia_recta_m - b.distancia_recta_m);
      modal.elemento.innerHTML = `
        <p><span class="etiqueta estado-${s.estado}">${LimaGo.ESTADOS_VIAJE[s.estado] || s.estado}</span> <span class="ayuda">${CANALES[s.canal] || ""}</span></p>
        <div class="datos-viaje">
          <div><span>Conductor</span><strong>${LimaGo.codigoConductor(s.conductor_id)}</strong></div>
          <div><span>Llegada estimada</span><strong>${LimaGo.minutos(s.eta_s)}</strong></div>
          <div><span>Tarifa estimada</span><strong>${LimaGo.soles(s.tarifa_estimada)}</strong></div>
          <div><span>Distancia del conductor</span><strong>${LimaGo.distancia(s.distancia_calles_m)}</strong></div>
          <div><span>Distancia del viaje</span><strong>${LimaGo.distancia(s.distancia_viaje_m)}</strong></div>
          <div><span>Solicitado</span><strong>${LimaGo.fecha(s.creada_en)}</strong></div>
          ${s.distrito_origen || s.distrito_destino ? `<div><span>Distritos</span><strong>${LimaGo.escapar([s.distrito_origen, s.distrito_destino].filter(Boolean).join(" → "))}</strong></div>` : ""}
          ${s.intentos && s.intentos.length ? `<div><span>Ofertas enviadas</span><strong>${s.intentos.length}</strong></div>` : ""}
        </div>
        ${desglose(s.tarifa_desglose)}
        ${intentos(s.intentos)}
        <p class="ayuda">Recojo: ${lugar(s.origen_texto, s.origen_lat)} · Destino: ${lugar(s.destino_texto, s.destino_lat)}<br>
          Recogida: ${LimaGo.fecha(s.recogida_en)} · Fin: ${LimaGo.fecha(s.finalizada_en)}${s.mensaje ? ` · ${LimaGo.escapar(s.mensaje)}` : ""}</p>
        <div class="mini-mapa" id="mapa-detalle"></div>
        ${candidatos.length ? `<h3 style="font-size:1rem;margin:14px 0 6px">Conductores evaluados</h3>
        <div class="tabla-envoltura"><table><thead><tr><th>Conductor</th><th>Línea recta</th><th>Por calles</th><th>Llegada</th></tr></thead><tbody>
        ${candidatos.map((c) => `<tr${c.conductor_id === s.conductor_id ? ' style="background:var(--marca-suave)"' : ""}><td>${c.codigo}${c.conductor_id === s.conductor_id ? " · elegido" : ""}</td>
          <td class="num">${LimaGo.distancia(c.distancia_recta_m)}</td><td class="num">${c.alcanzable ? LimaGo.distancia(c.distancia_calles_m) : "sin ruta"}</td>
          <td class="num">${c.alcanzable ? LimaGo.minutos(c.eta_s) : "—"}</td></tr>`).join("")}</tbody></table></div>` : ""}
        ${["buscando", "asignada", "esperando_recogida", "en_viaje"].includes(s.estado) ? `<a class="boton bloque" style="margin-top:14px" href="seguimiento.html?id=${s.id}">Seguir este viaje</a>` : ""}`;
      const mapa = LimaGo.crearMapa("mapa-detalle", { scrollWheelZoom: false });
      const capas = [];
      if (s.ruta_recogida && s.ruta_recogida.length > 1) capas.push(L.polyline(s.ruta_recogida, { color: "#0f766e", weight: 5 }));
      if (s.ruta_viaje && s.ruta_viaje.length > 1) capas.push(L.polyline(s.ruta_viaje, { color: "#f26b3a", weight: 5 }));
      if (s.origen_lat != null) capas.push(L.marker([s.origen_lat, s.origen_lon], { icon: LimaGo.iconoPin("origen") }));
      if (s.destino_lat != null) capas.push(L.marker([s.destino_lat, s.destino_lon], { icon: LimaGo.iconoPin("destino") }));
      const grupo = L.featureGroup(capas).addTo(mapa);
      if (capas.length) mapa.fitBounds(grupo.getBounds(), { padding: [30, 30], maxZoom: 16 });
      else LimaGo.dibujarCobertura(mapa).catch(() => {});
    } catch (e) {
      modal.elemento.innerHTML = `<div class="aviso error">${LimaGo.escapar(e.message)}</div>`;
    }
  }

  document.addEventListener("click", (e) => {
    const boton = e.target.closest("[data-detalle]");
    if (boton) detalle(+boton.dataset.detalle);
  });
  document.querySelectorAll("[data-canal]").forEach((b) => b.addEventListener("click", () => {
    canal = b.dataset.canal;
    document.querySelectorAll("[data-canal]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    cargar();
  }));
  document.querySelectorAll("[data-vista]").forEach((b) => b.addEventListener("click", () => {
    vista = b.dataset.vista;
    document.querySelectorAll("[data-vista]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    try { localStorage.setItem("limago.vista-historial", vista); } catch (err) { /* sin almacenamiento */ }
    pintar();
  }));
  $("#filtro-estado").addEventListener("change", () => cargar());
  $("#filtro-texto").addEventListener("input", pintar);
  $("#mas").addEventListener("click", () => cargar(false));
  try {
    const guardada = localStorage.getItem("limago.vista-historial");
    if (guardada) document.querySelector(`[data-vista="${guardada}"]`)?.click();
  } catch (err) { /* sin almacenamiento */ }
  cargar();
})();
