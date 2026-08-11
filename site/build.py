#!/usr/bin/env python3
"""Genera il sito vetrina di TreasureIQ.

Fonte di verità: i markdown in `docs/` (gli stessi che vivono nel repo) più la
vetrina in `site/vetrina.html`. Qui NON si duplica il contenuto: si rende. Ogni
doc diventa una pagina con la stessa impaginazione, la vetrina è la home.

Uso:
    python3 site/build.py [--out DIR] [--base PREFISSO]

    --out DIR    dove scrivere il sito (default: site/_site)
    --base PREF  prefisso dei link assoluti, per GitHub Pages di progetto
                 (es. /TreasureIQ). Default vuoto: link relativi alla radice.

Dipendenza unica: `markdown` (pip install markdown). Se manca, lo dice e si
ferma senza tracce a metà.
"""
from __future__ import annotations

import argparse
import html as _html
import re
import shutil
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
DOCS = RADICE / "docs"
SITE = RADICE / "site"

#: L'ordine della navigazione. (file in docs/, titolo in nav, slug della pagina).
#: L'ordine è quello in cui si legge il progetto, non alfabetico.
NAV: list[tuple[str, str, str]] = [
    ("architettura.md", "Architettura", "architettura"),
    ("connettori.md", "Connettori", "connettori"),
    ("api.md", "API", "api"),
    ("evoluzione.md", "Evoluzione", "evoluzione"),
    ("roadmap.md", "Roadmap", "roadmap"),
    ("sicurezza.md", "Sicurezza", "sicurezza"),
]

MARCHIO = (
    '<a class="marchio" href="{home}">'
    '<img src="{base}/assets/marchio.svg" width="36" height="36" alt=""/>'
    '<span class="marchio__nome">Treasure<span class="marchio__iq">IQ</span></span></a>'
)


def _masthead(base: str, home: str) -> str:
    return (
        '<header class="masthead">'
        + MARCHIO.format(base=base, home=home)
        + '<nav>'
        f'<a href="{home}#come-funziona">Come funziona</a>'
        f'<a href="{base}/architettura.html">Architettura</a>'
        f'<a href="{base}/api.html">API</a>'
        '<a class="repo" href="https://github.com/stanzinofree/TreasureIQ">GitHub</a>'
        '</nav></header>'
    )


def _footer(base: str, home: str) -> str:
    voci = "".join(
        f'<li><a href="{base}/{slug}.html">{titolo}</a></li>' for _, titolo, slug in NAV
    )
    return (
        '<footer class="site-footer"><div class="dentro">'
        '<div>'
        '<div class="hanko">TIQ<br/>済</div>'
        '<p style="margin-top:16px">TreasureIQ non inventa un nuovo standard: '
        'legge quello che i Comuni pubblicano davvero e dice al cittadino cosa gli '
        'spetta, senza mentire su cosa non sa.</p>'
        '</div>'
        '<div class="colonne">'
        f'<div><h4>Documentazione</h4><ul>{voci}</ul></div>'
        '<div><h4>Progetto</h4><ul>'
        '<li><a href="https://github.com/stanzinofree/TreasureIQ">Codice sorgente</a></li>'
        f'<li><a href="{home}#numeri">I numeri veri</a></li>'
        '</ul></div>'
        '</div>'
        '</div></footer>'
    )


def _guscio(titolo: str, corpo: str, base: str, home: str, classe: str = "") -> str:
    """L'HTML completo di una pagina: testa, masthead, corpo, footer.

    Lo script Mermaid entra solo se la pagina ha davvero un diagramma: nessun
    fetch al CDN sulle pagine che non lo usano."""
    mermaid = _MERMAID_SCRIPT if 'class="mermaid"' in corpo else ""
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{titolo}</title>
<link rel="icon" type="image/svg+xml" href="{base}/assets/marchio.svg"/>
<link rel="stylesheet" href="{base}/assets/theme.css"/>
</head>
<body class="{classe}">
{_masthead(base, home)}
{corpo}
{_footer(base, home)}
{mermaid}
</body>
</html>
"""


def _riscrivi_link(html: str, base: str) -> str:
    """Da link fra documenti a link del sito.

    I docs si linkano fra loro come `architettura.md` o `./api.md#foo`, e a
    volte come `docs/api.md`. Sul sito le pagine sono `<slug>.html` alla radice.
    """
    def sostituisci(m: re.Match) -> str:
        pre, percorso, frammento = m.group(1), m.group(2), m.group(3) or ""
        nome = percorso.split("/")[-1]  # scarta ./ o docs/
        slug = nome[:-3]  # toglie .md
        return f'{pre}"{base}/{slug}.html{frammento}"'

    # href="...qualcosa.md" oppure href="...qualcosa.md#ancora"
    return re.sub(r'(href=)"((?:\./|docs/)?[\w\-]+)\.md(#[\w\-]+)?"', sostituisci, html)


def _rendi_markdown(testo: str):
    try:
        import markdown
    except ImportError:
        sys.exit(
            "Manca la dipendenza `markdown`. Installa con:\n"
            "    pip install markdown\n"
        )
    md = markdown.Markdown(
        extensions=["extra", "toc", "sane_lists", "smarty", "admonition"],
        output_format="html5",
    )
    return md.convert(testo)


#: I blocchi ```mermaid` che l'estensione `fenced_code` rende come
#: `<pre><code class="language-mermaid">…</code></pre>`, con `<>&` già entità
#: HTML. Mermaid.js si aggancia a `<pre class="mermaid">` e vuole il testo
#: grezzo: qui si riscrive il guscio e si de-entizza il diagramma.
_RE_MERMAID = re.compile(
    r'<pre><code class="language-mermaid">(.*?)</code></pre>',
    re.DOTALL,
)


def _rendi_mermaid(html: str) -> str:
    def sostituisci(m: re.Match) -> str:
        sorgente = _html.unescape(m.group(1))
        return f'<pre class="mermaid">{sorgente}</pre>'

    return _RE_MERMAID.sub(sostituisci, html)


#: Init di Mermaid, iniettato solo nelle pagine che contengono un diagramma.
#: ESM dal CDN (GitHub Pages, non l'artifact: la rete esterna è concessa).
#: Tema `base` ricalibrato sui token civici del sito — mai i blu di default.
_MERMAID_SCRIPT = """<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
mermaid.initialize({
  startOnLoad: true,
  theme: 'base',
  fontFamily: '"Zen Kaku Gothic New", system-ui, sans-serif',
  themeVariables: {
    background: '#f2f4f7',
    primaryColor: '#ffffff',
    primaryTextColor: '#0b1d3a',
    primaryBorderColor: '#0057b8',
    secondaryColor: '#e6eaf0',
    tertiaryColor: '#e6eaf0',
    lineColor: '#3b4a63',
    textColor: '#0b1d3a',
    fontSize: '15px',
  },
});
</script>"""


def _nav_laterale(base: str, slug_attivo: str) -> str:
    voci = "".join(
        f'<li><a href="{base}/{slug}.html"'
        + (' aria-current="page"' if slug == slug_attivo else "")
        + f">{titolo}</a></li>"
        for _, titolo, slug in NAV
    )
    return (
        '<aside class="doc__nav">'
        '<p class="gruppo">Documentazione</p>'
        f'<ul>{voci}</ul>'
        '</aside>'
    )


def costruisci(out: Path, base: str) -> None:
    home = f"{base}/index.html" if base else "index.html"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # assets
    shutil.copytree(SITE / "assets", out / "assets")
    # la gif della demo, se c'è
    gif = RADICE / "treasureiq-caso1-ciampino.gif"
    if gif.exists():
        (out / "assets").mkdir(exist_ok=True)
        shutil.copy(gif, out / "assets" / "demo.gif")

    # vetrina (home)
    vetrina = (SITE / "vetrina.html").read_text("utf-8")
    vetrina = vetrina.replace("{{base}}", base).replace("{{home}}", home)
    (out / "index.html").write_text(
        _guscio("TreasureIQ — le informazioni del tuo Comune, senza caccia al tesoro", vetrina, base, home, "vetrina"),
        "utf-8",
    )

    # una pagina per doc
    resi = []
    for file, titolo, slug in NAV:
        sorgente = DOCS / file
        if not sorgente.exists():
            print(f"  · salto {file} (non trovato)")
            continue
        html = _rendi_markdown(sorgente.read_text("utf-8"))
        html = _rendi_mermaid(html)
        html = _riscrivi_link(html, base)
        corpo = (
            '<main class="doc">'
            + _nav_laterale(base, slug)
            + f'<article class="prosa">{html}</article>'
            + '</main>'
        )
        (out / f"{slug}.html").write_text(
            _guscio(f"{titolo} — TreasureIQ", corpo, base, home, "documento"), "utf-8"
        )
        resi.append(slug)

    # .nojekyll: serviamo file statici già pronti, GitHub non deve processarli
    (out / ".nojekyll").write_text("", "utf-8")
    print(f"Fatto: {out}  (vetrina + {len(resi)} pagine: {', '.join(resi)})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera il sito vetrina di TreasureIQ.")
    ap.add_argument("--out", default=str(SITE / "_site"), help="cartella di uscita")
    ap.add_argument("--base", default="", help="prefisso link (es. /TreasureIQ)")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    costruisci(Path(args.out), base)


if __name__ == "__main__":
    main()
