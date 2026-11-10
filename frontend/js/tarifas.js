/* LimaGo V3 — tarifas orientativas: misma cotización que al pedir (ruta real, tráfico de la hora y recogida). */
"use strict";

(async () => {
  const $ = (s) => document.querySelector(s);
  $("#selector-origen").outerHTML = LimaGo.htmlSelector("origen", "Origen", "Ej.: Óvalo Gutiérrez, Miraflores");
  $("#selector-destino").outerHTML = LimaGo.htmlSelector("destino", "Destino", "Ej.: Aeropuerto Jorge Chávez");
  const mapa = LimaGo.crearMapa("mapa");
  LimaGo.dibujarCobertura(mapa).catch(() => {});
  LimaGo.SelectorLugar.conectarMapa(mapa);
  const capaRuta = L.layerGroup().addTo(mapa);
  const origen = new LimaGo.SelectorLugar($('[data-lugar="origen"]'), { nombre: "Origen", mapa, tipoPin: "origen" });
  const destino = new LimaGo.SelectorLugar($('[data-lugar="destino"]'), { nombre: "Destino", mapa, tipoPin: "destino" });

  try {
    const tr = await LimaGo.api("/trafico");
    $("#trafico-actual").innerHTML = `<span class="chip-trafico ${tr.nivel}">${LimaGo.NIVELES_TRAFICO[tr.nivel] || tr.nivel} · ${LimaGo.hora(tr.hora)}</span>
      <br><span class="etiqueta-simulacion">Estimado con un modelo por horario; no es tráfico en tiempo real.</span>`;
  } catch (e) { $("#trafico-actual").textContent = ""; }

  try {
    const t = await LimaGo.api("/tarifas");
    $("#tabla-tarifas").innerHTML = `
      <tr><td>Tarifa base</td><td class="num">${LimaGo.soles(t.base)}</td></tr>
      <tr><td>Por kilómetro de viaje</td><td class="num">${LimaGo.soles(t.por_km)} / km</td></tr>
      <tr><td>Por minuto estimado de viaje</td><td class="num">${LimaGo.soles(t.por_minuto)} / min</td></tr>
      <tr><td>Recogida (después de ${String(t.recogida_gratis_km).replace(".", ",")} km sin costo)</td><td class="num">${LimaGo.soles(t.por_km_recogida)} / km, máx. ${LimaGo.soles(t.tope_recogida)}</td></tr>
      <tr><td>Tarifa mínima</td><td class="num">${LimaGo.soles(t.minima)}</td></tr>`;
  } catch (e) {
    $("#tabla-tarifas").innerHTML = `<tr><td colspan="2">${LimaGo.escapar(e.message)}</td></tr>`;
  }

  async function resolver(selector, nombre) {
    const d = selector.datos();
    if (!d) throw new Error(`Indica el ${nombre}.`);
    if (d.lat != null) return d;
    const { resultados } = await LimaGo.api(`/geocodificar?q=${encodeURIComponent(d.texto)}`);
    if (!resultados.length) throw new Error(`No encontramos el ${nombre} en la zona de cobertura.`);
    selector.fijar(resultados[0]);
    return selector.valor;
  }

  $("#estimador").addEventListener("submit", async (e) => {
    e.preventDefault();
    const caja = $("#resultado");
    const boton = $("#calcular");
    boton.setAttribute("aria-busy", "true");
    caja.innerHTML = '<div class="buscando" style="margin-top:14px"><span class="girador"></span>Calculando la mejor ruta…</div>';
    try {
      const o = await resolver(origen, "origen"), d = await resolver(destino, "destino");
      const r = await LimaGo.api("/viajes/cotizar", { method: "POST", body: { origen: o, destino: d } });
      const x = r.tarifa.desglose;
      caja.innerHTML = `
        <div class="tarjeta plana" style="margin-top:16px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
            <div><span class="ayuda">Total estimado</span><div class="precio">${LimaGo.soles(r.tarifa.total)}</div></div>
            <span class="chip-trafico ${r.trafico.nivel}">${LimaGo.NIVELES_TRAFICO[r.trafico.nivel] || ""}</span>
          </div>
          <ul class="desglose">
            <li><span>Tarifa base</span><span>${LimaGo.soles(x.base)}</span></li>
            <li><span>Recorrido (${LimaGo.distancia(r.distancia_m)})</span><span>${LimaGo.soles(x.recorrido)}</span></li>
            <li><span>Tiempo (${LimaGo.minutos(r.duracion_s)})</span><span>${LimaGo.soles(x.tiempo)}</span></li>
            <li><span>Recogida${r.recogida.distancia_m ? ` (${LimaGo.distancia(r.recogida.distancia_m)})` : ""}</span><span>${LimaGo.soles(x.recogida)}</span></li>
            ${x.ajuste_minimo > 0 ? `<li><span>Ajuste a tarifa mínima</span><span>${LimaGo.soles(x.ajuste_minimo)}</span></li>` : ""}
            <li class="total"><span>Total estimado</span><span>${LimaGo.soles(r.tarifa.total)}</span></li>
          </ul>
          <p class="etiqueta-simulacion" style="margin:0">${[r.origen.distrito, r.destino.distrito].filter(Boolean).join(" → ")}. Monto orientativo en soles, no es un cobro.</p>
          <a class="boton bloque" style="margin-top:12px" href="viaje.html?origen=${encodeURIComponent(LimaGo.corto(r.origen.direccion, 2))}&destino=${encodeURIComponent(LimaGo.corto(r.destino.direccion, 2))}">Pedir este viaje</a>
        </div>`;
      capaRuta.clearLayers();
      const linea = L.polyline(r.ruta, { color: "#0f766e", weight: 6, opacity: 0.85 }).addTo(capaRuta);
      mapa.fitBounds(linea.getBounds(), { padding: [40, 40], maxZoom: 17 });
    } catch (error) {
      if (error.estado === 409 && error.opciones.length) {
        caja.innerHTML = `<div class="aviso info">${LimaGo.escapar(error.message)}: ${error.opciones.map((x) => LimaGo.escapar(LimaGo.corto(x.direccion, 2))).join(" · ")}. Escribe una dirección más precisa.</div>`;
      } else {
        caja.innerHTML = `<div class="aviso error">${LimaGo.escapar(error.message)}</div>`;
      }
    } finally {
      boton.removeAttribute("aria-busy");
    }
  });
})();
