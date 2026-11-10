/* LimaGo — cabecera, pie corporativo, tema, notificaciones y modales compartidos por todas las páginas.
   Cada página declara <body data-pagina="..."> y los contenedores <div data-cabecera></div> y <div data-pie></div>. */
"use strict";

const Plantilla = (() => {
  const REPOSITORIO = "https://github.com/rgabrielmatosm/LimaGo-Plataforma-Inteligente-de-Movilidad-Urbana";

  const ICONOS = {
    menu: '<path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>',
    sol: '<circle cx="12" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    luna: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    sistema: '<rect x="3" y="4" width="18" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 20h8M12 16v4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    ubicacion: '<path d="M12 21s-7-6.1-7-11.5A7 7 0 0 1 19 9.5C19 14.9 12 21 12 21z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="9.5" r="2.5" fill="none" stroke="currentColor" stroke-width="2"/>',
    ayuda: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9.5 9.3a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.8M12 17h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>',
    info: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 11v6M12 7.5h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    codigo: '<path fill="currentColor" d="M12 2a10 10 0 0 0-3.2 19.5c.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.3-3.4-1.3-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.6 2.4 1.1 3 .9.1-.7.4-1.1.6-1.4-2.2-.3-4.6-1.1-4.6-5a3.9 3.9 0 0 1 1-2.7 3.6 3.6 0 0 1 .1-2.7s.8-.3 2.8 1a9.6 9.6 0 0 1 5 0c2-1.3 2.8-1 2.8-1 .5 1.4.2 2.4.1 2.7a3.9 3.9 0 0 1 1 2.7c0 3.9-2.4 4.7-4.6 5 .4.3.7.9.7 1.9V21c0 .3.2.6.7.5A10 10 0 0 0 12 2z"/>',
    auto: '<path fill="currentColor" d="M5 11l1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11v6a1 1 0 0 1-1 1h-1a1 1 0 0 1-1-1v-1H8v1a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-6zm2.2-1h9.6l-1-3H8.2l-1 3zM7.5 14a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zm9 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"/>',
    reloj: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v5l3 2" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>',
    ruta: '<circle cx="6" cy="18" r="2.5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="18" cy="6" r="2.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5" fill="none" stroke="currentColor" stroke-width="2"/>',
    moneda: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M15 9.5c-.5-1-1.6-1.5-3-1.5-1.7 0-3 .8-3 2s1.3 1.7 3 2 3 .8 3 2-1.3 2-3 2c-1.4 0-2.5-.5-3-1.5M12 6v2M12 16v2" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>',
    lista: '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    escudo: '<path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
    vacio: '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M20 20l-4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    alerta: '<path d="M12 3l9.5 17h-19L12 3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 10v4M12 17h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    flecha: '<path fill="currentColor" d="M12 2l7 18-7-4-7 4 7-18z"/>',
    gps: '<circle cx="12" cy="12" r="3.5" fill="currentColor"/><circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    persona: '<path fill="currentColor" d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0 2c-4 0-8 2-8 5v1h16v-1c0-3-4-5-8-5z"/>',
  };
  const icono = (nombre, clase = "") => `<svg viewBox="0 0 24 24" aria-hidden="true" class="${clase}">${ICONOS[nombre] || ""}</svg>`;

  const NAVEGACION = [
    ["inicio", "index.html", "Inicio"],
    ["tarifas", "tarifas.html", "Tarifas"],
    ["cobertura", "cobertura.html", "Cobertura"],
    ["ayuda", "ayuda.html", "Ayuda"],
    ["historial", "historial.html", "Mis viajes"],
  ];

  function cabecera(pagina) {
    const enlaces = NAVEGACION.map(([id, href, texto]) =>
      `<a href="${href}"${id === pagina ? ' aria-current="page"' : ""}>${texto}</a>`).join("");
    return `
      <a class="saltar" href="#contenido">Saltar al contenido</a>
      <header class="cabecera">
        <div class="contenedor">
          <a class="logo" href="index.html" aria-label="LimaGo, inicio"><img src="img/logo.svg" alt="" width="32" height="32"><span>Lima<b>Go</b></span></a>
          <nav class="navegacion" id="navegacion" aria-label="Principal">
            ${enlaces}
            <a class="boton pequeno" href="viaje.html"${pagina === "viaje" ? ' aria-current="page"' : ""}>Pedir un viaje</a>
          </nav>
          <div class="acciones-cabecera">
            <button class="boton-icono" type="button" data-tema aria-label="Cambiar tema"></button>
            <button class="boton-icono menu-movil" type="button" aria-controls="navegacion" aria-expanded="false" aria-label="Abrir menú">${icono("menu")}</button>
          </div>
        </div>
      </header>`;
  }

  function pie() {
    const anio = new Date().getFullYear();
    return `
      <footer class="pie">
        <div class="contenedor columnas">
          <section class="marca-pie" aria-label="LimaGo">
            <a class="logo" href="index.html"><img src="img/logo.svg" alt="" width="34" height="34"><span>Lima<b>Go</b></span></a>
            <p>Pide un viaje y te asignamos al conductor que llega primero por las calles, no solo al que está más cerca.</p>
            <div class="dato">${icono("ubicacion")}<span>Cobertura: Lima Metropolitana (provincias de Lima y Callao), Perú.</span></div>
            <div class="dato">${icono("ayuda")}<span>¿Dudas? Visita el <a href="ayuda.html">centro de ayuda</a>.</span></div>
          </section>
          <nav aria-labelledby="pie-sobre">
            <h2 id="pie-sobre">Sobre LimaGo</h2>
            <ul>
              <li><a href="nosotros.html">Quiénes somos</a></li>
              <li><a href="index.html#como-funciona">Cómo funciona</a></li>
              <li><a href="cobertura.html">Cobertura</a></li>
              <li><a href="ayuda.html#preguntas">Preguntas frecuentes</a></li>
            </ul>
          </nav>
          <nav aria-labelledby="pie-viaje">
            <h2 id="pie-viaje">Tu viaje</h2>
            <ul>
              <li><a href="viaje.html">Solicitar viaje</a></li>
              <li><a href="seguimiento.html">Seguimiento</a></li>
              <li><a href="historial.html">Mis viajes</a></li>
              <li><a href="tarifas.html">Tarifas estimadas</a></li>
            </ul>
          </nav>
          <nav aria-labelledby="pie-atencion">
            <h2 id="pie-atencion">Atención e información</h2>
            <ul>
              <li><a href="ayuda.html">Centro de ayuda</a></li>
              <li><a href="legal.html#privacidad">Privacidad</a></li>
              <li><a href="legal.html#terminos">Términos de uso</a></li>
              <li><a href="legal.html#simulacion">Información de la simulación</a></li>
            </ul>
          </nav>
        </div>
        <div class="franja">
          <div class="contenedor">
            <span>© ${anio} LimaGo · Plataforma de simulación de movilidad urbana. Mapas © colaboradores de OpenStreetMap.</span>
            <nav aria-label="Enlaces legales">
              <a href="legal.html#privacidad">Privacidad</a>
              <a href="legal.html#terminos">Términos</a>
              <a href="legal.html#simulacion">Simulación</a>
              <a href="operaciones.html">Acceso operadores</a>
            </nav>
            <div class="social">
              <a href="${REPOSITORIO}" target="_blank" rel="noopener" aria-label="Proyecto LimaGo en GitHub">${icono("codigo")}</a>
            </div>
          </div>
        </div>
      </footer>`;
  }

  // -------------------------------------------------------------- tema
  const TEMAS = ["sistema", "claro", "oscuro"];
  const NOMBRE_TEMA = { sistema: "Tema del sistema", claro: "Tema claro", oscuro: "Tema oscuro" };
  const leerTema = () => { try { return localStorage.getItem("limago.tema") || "sistema"; } catch (e) { return "sistema"; } };
  function aplicarTema(tema) {
    const raiz = document.documentElement;
    if (tema === "claro") raiz.setAttribute("data-theme", "light");
    else if (tema === "oscuro") raiz.setAttribute("data-theme", "dark");
    else raiz.removeAttribute("data-theme");
    try { localStorage.setItem("limago.tema", tema); } catch (e) { /* sin almacenamiento */ }
    document.querySelectorAll("[data-tema]").forEach((b) => {
      b.innerHTML = icono(tema === "claro" ? "sol" : tema === "oscuro" ? "luna" : "sistema");
      b.setAttribute("aria-label", `${NOMBRE_TEMA[tema]}. Pulsa para cambiar`);
      b.title = NOMBRE_TEMA[tema];
    });
  }
  aplicarTema(leerTema()); // antes de pintar para evitar parpadeos

  // ------------------------------------------------------ notificaciones
  function notificar(mensaje, tipo = "info", duracion = 5000) {
    let caja = document.querySelector(".notificaciones");
    if (!caja) {
      caja = document.createElement("div");
      caja.className = "notificaciones";
      caja.setAttribute("aria-live", "polite");
      document.body.appendChild(caja);
    }
    const nota = document.createElement("div");
    nota.className = `notificacion ${tipo}`;
    nota.setAttribute("role", tipo === "error" ? "alert" : "status");
    nota.innerHTML = `<span></span><button type="button" aria-label="Cerrar">×</button>`;
    nota.querySelector("span").textContent = mensaje;
    nota.querySelector("button").addEventListener("click", () => nota.remove());
    caja.appendChild(nota);
    if (duracion) setTimeout(() => nota.remove(), duracion);
  }

  // --------------------------------------------------------------- modal
  function abrirModal(titulo, contenidoHtml) {
    const previo = document.activeElement;
    const fondo = document.createElement("div");
    fondo.className = "modal-fondo";
    fondo.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-titulo">
        <header><h2 id="modal-titulo"></h2><button class="boton-icono" type="button" aria-label="Cerrar">×</button></header>
        <div class="cuerpo">${contenidoHtml}</div></div>`;
    fondo.querySelector("#modal-titulo").textContent = titulo;
    const cerrar = () => { fondo.remove(); document.removeEventListener("keydown", tecla); if (previo) previo.focus(); };
    const tecla = (e) => { if (e.key === "Escape") cerrar(); };
    fondo.addEventListener("click", (e) => { if (e.target === fondo) cerrar(); });
    fondo.querySelector("header button").addEventListener("click", cerrar);
    document.addEventListener("keydown", tecla);
    document.body.appendChild(fondo);
    fondo.querySelector("header button").focus();
    return { elemento: fondo.querySelector(".cuerpo"), cerrar };
  }

  function montar() {
    const pagina = document.body.dataset.pagina || "";
    document.querySelectorAll("[data-cabecera]").forEach((n) => { n.outerHTML = cabecera(pagina); });
    document.querySelectorAll("[data-pie]").forEach((n) => { n.outerHTML = pie(); });
    aplicarTema(leerTema());
    document.querySelectorAll("[data-tema]").forEach((b) => b.addEventListener("click", () => {
      aplicarTema(TEMAS[(TEMAS.indexOf(leerTema()) + 1) % TEMAS.length]);
    }));
    const boton = document.querySelector(".menu-movil");
    const nav = document.getElementById("navegacion");
    if (boton && nav) {
      boton.addEventListener("click", () => {
        const abierta = nav.classList.toggle("abierta");
        boton.setAttribute("aria-expanded", String(abierta));
        boton.setAttribute("aria-label", abierta ? "Cerrar menú" : "Abrir menú");
      });
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && nav.classList.contains("abierta")) { nav.classList.remove("abierta"); boton.setAttribute("aria-expanded", "false"); boton.focus(); }
      });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", montar);
  else montar();

  return { icono, notificar, abrirModal };
})();
