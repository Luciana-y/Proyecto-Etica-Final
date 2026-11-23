// Navegación por vistas: una sección visible a la vez, sincronizada con el hash de la URL.
(function () {
  const vistas = Array.from(document.querySelectorAll(".vista"));
  const ids = vistas.map((v) => v.dataset.vista);
  const enlacesLaterales = Array.from(document.querySelectorAll(".lateral a"));
  const anterior = document.querySelector(".paso.anterior");
  const siguiente = document.querySelector(".paso.siguiente");
  const contador = document.querySelector(".contador");
  const barra = document.querySelector(".progreso-barra");
  const botonMenu = document.querySelector(".boton-menu");
  const velo = document.querySelector(".velo");
  let actual = -1;
  let observador = null;

  function tituloDe(i) {
    const enlace = document.querySelector(`.lateral .nivel-2 > a[data-vista="${ids[i]}"]`);
    return enlace ? enlace.dataset.titulo : "";
  }

  function vistaDeAncla(ancla) {
    if (!ancla) return 0;
    const i = ids.indexOf(ancla);
    if (i >= 0) return i;
    const el = document.getElementById(ancla);
    const contenedor = el && el.closest(".vista");
    return contenedor ? vistas.indexOf(contenedor) : 0;
  }

  function configurarPaso(boton, i) {
    if (i < 0 || i >= vistas.length) {
      boton.hidden = true;
      return;
    }
    boton.hidden = false;
    boton.href = "#" + ids[i];
    boton.querySelector(".paso-titulo").textContent = tituloDe(i);
  }

  function observarSubsecciones(vista) {
    if (observador) observador.disconnect();
    const subenlaces = new Map(
      Array.from(document.querySelectorAll(`.lateral .nivel-3 a[data-vista="${ids[actual]}"]`))
        .map((a) => [a.getAttribute("href").slice(1), a])
    );
    if (!subenlaces.size || !("IntersectionObserver" in window)) return;
    observador = new IntersectionObserver((entradas) => {
      entradas.forEach((e) => {
        if (!e.isIntersecting) return;
        subenlaces.forEach((a) => a.classList.remove("visible"));
        const a = subenlaces.get(e.target.id);
        if (a) a.classList.add("visible");
      });
    }, { rootMargin: "0px 0px -70% 0px" });
    vista.querySelectorAll("h3[id]").forEach((h) => observador.observe(h));
  }

  function mostrar(i, ancla) {
    const cambio = i !== actual;
    if (cambio) {
      vistas.forEach((v, j) => { v.hidden = j !== i; });
      actual = i;
      document.querySelectorAll(".lateral .nivel-2").forEach((li) => {
        const a = li.querySelector(":scope > a");
        li.classList.toggle("activo", a.dataset.vista === ids[i]);
      });
      configurarPaso(anterior, i - 1);
      configurarPaso(siguiente, i + 1);
      contador.textContent = i === 0 ? "Portada" : `Sección ${i} de ${vistas.length - 1}`;
      barra.style.width = `${(i / (vistas.length - 1)) * 100}%`;
      document.title = (i === 0 ? "" : tituloDe(i) + " · ") + document.querySelector(".lateral-titulo").textContent;
      observarSubsecciones(vistas[i]);
    }
    // Se difiere para anular el salto nativo del navegador al h2 con el mismo id.
    const destino = ancla && ancla !== ids[i] ? document.getElementById(ancla) : null;
    requestAnimationFrame(() => {
      if (destino) destino.scrollIntoView();
      else window.scrollTo(0, 0);
    });
  }

  function desdeHash() {
    const ancla = decodeURIComponent(location.hash.slice(1));
    mostrar(vistaDeAncla(ancla), ancla);
  }

  function cerrarMenu() {
    document.body.classList.remove("menu-abierto");
    botonMenu.setAttribute("aria-expanded", "false");
    velo.hidden = true;
  }

  botonMenu.addEventListener("click", () => {
    const abierto = document.body.classList.toggle("menu-abierto");
    botonMenu.setAttribute("aria-expanded", String(abierto));
    velo.hidden = !abierto;
  });
  velo.addEventListener("click", cerrarMenu);
  enlacesLaterales.forEach((a) => a.addEventListener("click", cerrarMenu));

  document.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey || /input|textarea|select/i.test(e.target.tagName)) return;
    if (e.key === "ArrowRight" && actual < vistas.length - 1) location.hash = ids[actual + 1];
    if (e.key === "ArrowLeft" && actual > 0) location.hash = ids[actual - 1];
  });

  window.addEventListener("hashchange", desdeHash);
  desdeHash();

  // Fórmulas: el HTML conserva \( \) y \[ \] generados por arithmatex.
  window.addEventListener("load", () => {
    if (typeof renderMathInElement !== "function") return;
    renderMathInElement(document.body, {
      delimiters: [
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
      ],
      throwOnError: false,
    });
  });
})();
