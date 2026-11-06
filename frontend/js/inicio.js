/* LimaGo — página de inicio: cifras de cobertura y conductores disponibles. */
"use strict";

(async () => {
  const mapaHeroe = LimaGo.crearMapa("mapa-heroe", { scrollWheelZoom: false });
  const mapaCobertura = LimaGo.crearMapa("mapa-cobertura", { scrollWheelZoom: false });
  const flota = new LimaGo.CapaFlota(mapaHeroe, { soloDisponibles: true, radio: 4 });
  try {
    const { datos } = await LimaGo.dibujarCobertura(mapaHeroe);
    await LimaGo.dibujarCobertura(mapaCobertura);
    document.getElementById("cifra-km").textContent = datos.km_de_vias.toLocaleString("es-PE");
    document.getElementById("cifra-intersecciones").textContent = datos.intersecciones.toLocaleString("es-PE");
  } catch (e) { /* el mapa base sigue visible aunque falle la API */ }

  async function refrescar() {
    try {
      const datos = await LimaGo.api("/flota");
      flota.actualizar(datos.conductores);
      document.getElementById("disponibles-ahora").textContent =
        `${datos.conteo.disponible} conductores disponibles en Miraflores`;
    } catch (e) {
      document.getElementById("disponibles-ahora").textContent = "Conectando con conductores…";
    }
  }

  async function esperaMedia() {
    try {
      const { solicitudes } = await LimaGo.api("/viajes?canal=todos&limite=200");
      const etas = solicitudes.filter((s) => s.eta_s != null).map((s) => s.eta_s);
      if (etas.length) document.getElementById("cifra-espera").textContent =
        LimaGo.minutos(etas.reduce((a, b) => a + b, 0) / etas.length);
    } catch (e) { /* sin datos todavía */ }
  }

  await refrescar();
  esperaMedia();
  setInterval(refrescar, 3000);
  setInterval(esperaMedia, 20000);
})();
