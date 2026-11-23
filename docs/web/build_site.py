"""Genera el sitio estático del informe (_site/) a partir de docs/informe_final.md.

Uso, desde la raíz del repositorio:  python docs/web/build_site.py
- Parser CommonMark + tablas (markdown-it-py): renderiza igual que GitHub.
- Cada sección de nivel 2 (##) se publica como una vista con navegación anterior/siguiente.
- Las fórmulas $...$ se conservan como \\( \\) y \\[ \\] para KaTeX en el navegador.
"""
import html
import re
import shutil
from pathlib import Path

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin

RAIZ = Path(__file__).resolve().parents[2]
DOCS = RAIZ / "docs"
WEB = DOCS / "web"
SALIDA = RAIZ / "_site"
INFORME = DOCS / "informe_final.md"


def render_math(contenido: str, config: dict) -> str:
    texto = html.escape(contenido)
    if config.get("display_mode"):
        return f'<div class="math">\\[{texto}\\]</div>\n'
    return f'<span class="math">\\({texto}\\)</span>'


MD = (MarkdownIt("commonmark", {"html": True})
      .enable("table")
      .use(dollarmath_plugin, double_inline=True, renderer=render_math)
      .use(anchors_plugin, min_level=2, max_level=3))


def separar_portada(texto: str) -> tuple[str, str, str]:
    """Devuelve (titulo, portada_md, cuerpo_md). El índice manual se reemplaza por el lateral."""
    inicio = re.search(r"^## 1\. ", texto, flags=re.M).start()
    portada, cuerpo = texto[:inicio], texto[inicio:]
    titulo = re.search(r"^# (.+)$", portada, flags=re.M).group(1).strip()
    portada = re.sub(r"^# .+$", "", portada, count=1, flags=re.M)
    portada = re.sub(r"^## Índice\n.*?(?=^### Índice de figuras)", "", portada, flags=re.M | re.S)
    portada = re.sub(r"^## (.+)$", r'<p class="subtitulo">\1</p>', portada, count=1, flags=re.M)
    portada = re.sub(r"^---\s*$", "", portada, flags=re.M)
    return titulo, portada, cuerpo


def embellecer(fragmento: str) -> str:
    """Ajustes de presentación sobre el HTML generado."""
    fragmento = re.sub(r'<p><img src="([^"]+)" alt="([^"]*)" ?/?></p>',
                       r'<figure><a href="\1" target="_blank" rel="noopener">'
                       r'<img src="\1" alt="\2" loading="lazy"></a></figure>', fragmento)
    fragmento = fragmento.replace("<p><em>Figura", '<p class="pie"><em>Figura')
    fragmento = fragmento.replace("<p><strong>Lectura.</strong></p>", '<p class="lectura">Lectura</p>')
    fragmento = fragmento.replace("<table>", '<div class="tabla"><table>').replace("</table>", "</table></div>")
    return fragmento


def dividir_secciones(cuerpo_html: str) -> list[tuple[str, str]]:
    """Corta el HTML en bloques que empiezan en cada <h2 id=...>."""
    partes = re.split(r'(?=<h2 id=")', cuerpo_html)
    return [(re.match(r'<h2 id="([^"]+)"', p).group(1), p) for p in partes if p.startswith("<h2 id=")]


LATEX_PLANO = {r"\epsilon": "ε", r"\Delta": "Δ"}


def texto_plano(fragmento: str) -> str:
    """Título sin etiquetas ni LaTeX, para botones de paginación y <title>."""
    def plano(m: re.Match) -> str:
        expr = html.unescape(m.group(1))
        for latex, simbolo in LATEX_PLANO.items():
            expr = expr.replace(latex, simbolo)
        return expr
    fragmento = re.sub(r'<span class="math">\\\((.*?)\\\)</span>', plano, fragmento)
    return html.escape(html.unescape(re.sub(r"<[^>]+>", "", fragmento)).strip(), quote=True)


def indice_lateral(secciones: list[tuple[str, str]]) -> str:
    items = ['<li class="nivel-2"><a href="#portada" data-vista="portada" data-titulo="Portada">Portada</a></li>']
    for vid, contenido in secciones:
        titulo = re.search(r"<h2[^>]*>(.*?)</h2>", contenido, flags=re.S).group(1)
        hijos = "".join(f'<li class="nivel-3"><a href="#{hid}" data-vista="{vid}">{nombre}</a></li>'
                        for hid, nombre in re.findall(r'<h3 id="([^"]+)">(.*?)</h3>', contenido, flags=re.S))
        sub = f'<ul class="sub">{hijos}</ul>' if hijos else ""
        items.append(f'<li class="nivel-2"><a href="#{vid}" data-vista="{vid}" data-titulo="{texto_plano(titulo)}">'
                     f'{titulo}</a>{sub}</li>')
    return "<ul>" + "".join(items) + "</ul>"


def construir() -> None:
    texto = INFORME.read_text(encoding="utf-8")
    titulo, portada_md, cuerpo_md = separar_portada(texto)

    secciones = [(vid, embellecer(s)) for vid, s in dividir_secciones(MD.render(cuerpo_md))]
    vistas = [("portada", f"<h1>{html.escape(titulo)}</h1>{embellecer(MD.render(portada_md))}")] + secciones
    secciones_html = "\n".join(
        f'<section class="vista" id="v-{vid}" data-vista="{vid}" hidden>{contenido}</section>'
        for vid, contenido in vistas
    )

    plantilla = (WEB / "plantilla.html").read_text(encoding="utf-8")
    pagina = (plantilla
              .replace("{{titulo}}", html.escape(titulo))
              .replace("{{indice}}", indice_lateral(secciones))
              .replace("{{secciones}}", secciones_html))

    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    SALIDA.mkdir(parents=True)
    (SALIDA / "index.html").write_text(pagina, encoding="utf-8")
    shutil.copy(WEB / "estilo.css", SALIDA / "estilo.css")
    shutil.copy(WEB / "app.js", SALIDA / "app.js")
    shutil.copytree(DOCS / "figuras", SALIDA / "figuras")
    (SALIDA / ".nojekyll").touch()
    print(f"Sitio generado en {SALIDA} | vistas: {len(vistas)}")


if __name__ == "__main__":
    construir()
