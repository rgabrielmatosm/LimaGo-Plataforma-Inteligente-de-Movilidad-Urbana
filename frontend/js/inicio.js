/* LimaGo — inicio: mapa en vivo, cifras reales del servicio y acceso rápido a la solicitud. */
"use strict";

(async () => {
  document.querySelectorAll("[data-icono]").forEach((n) => { n.innerHTML = Plantilla.icono(n.dataset.icono); });
  const nota = document.querySelector(".nota-escenario");
  if (nota) {
    nota.insertAdjacentHTML("afterbegin", Plantilla.icono("info"));
    nota.querySelector("svg").style.cssText = "width:16px;height:16px;flex:none";
  }

  const mapaHeroe = LimaGo.crearMapa("mapa-heroe", { scrollWheelZoom: false });
  const mapaCobertura = LimaGo.crearMapa("mapa-cobertura", { scrollWheelZoom: false });
  mapaHeroe.setView([-12.1, -77.03], 13);
  const capaCercanos = L.layerGroup().addTo(mapaHeroe);
  try {
    await LimaGo.dibujarCobertura(mapaHeroe, false);
    const { datos } = await LimaGo.dibujarCobertura(mapaCobertura);
    document.getElementById("cifra-distritos").textContent = datos.distritos.length || "—";
  } catch (e) { /* el mapa base sigue visible aunque falle la API */ }

  // En la vista pública solo se muestran los conductores disponibles más cercanos al centro del mapa.
  async function refrescarFlota() {
    try {
      const centro = mapaHeroe.getCenter();
      const [{ conductores }, flota] = await Promise.all([
        LimaGo.api(`/conductores/cercanos?lat=${centro.lat}&lon=${centro.lng}&n=25`), LimaGo.api("/flota?detalle=false")]);
      capaCercanos.clearLayers();
      for (const c of conductores) L.circleMarker([c.lat, c.lon], { radius: 5, color: "#fff", weight: 1.5, fillColor: "#16a34a", fillOpacity: 1 }).addTo(capaCercanos);
      document.getElementById("disponibles-ahora").textContent = `${flota.conteo.disponible.toLocaleString("es-PE")} conductores disponibles en Lima`;
      document.getElementById("cifra-disponibles").textContent = flota.conteo.disponible.toLocaleString("es-PE");
    } catch (e) {
      document.getElementById("disponibles-ahora").textContent = "Servicio no disponible en este momento";
    }
  }

  async function refrescarCifras() {
    try {
      const { servicio } = await LimaGo.api("/estadisticas");
      document.getElementById("cifra-viajes").textContent = (servicio.por_estado.completada || 0).toLocaleString("es-PE");
      document.getElementById("cifra-espera").textContent = LimaGo.minutos(servicio.eta_media_s);
    } catch (e) { /* se mantiene el guion */ }
  }

  mapaHeroe.on("moveend", refrescarFlota);
  await refrescarFlota();
  refrescarCifras();
  setInterval(refrescarFlota, 4000);
  setInterval(refrescarCifras, 15000);
})();
