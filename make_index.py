#!/usr/bin/env python3
"""Generate a modern landing page for a dist folder full of exported decks.

    python3 make_index.py --dist public [--title "My talks"]
                          [--subtitle "..."] [--source-url URL]

Discovers every `<name>.html` deck in the dist folder (its `<name>_beamer.pdf`
is linked when present), renders the PDF's first page as a card preview via
pdftoppm (poppler-utils), and writes a self-contained responsive `index.html`
(inline CSS, no external requests) into the dist folder.
"""
import argparse
import html
import os
import re
import subprocess

CSS = """
  :root{--bg:#14161a;--card:#1d2126;--edge:#2a2f36;--fg:#e8eaed;--dim:#9aa0a8;
        --acc:#4da3ff;--acc2:#7ee0c3}
  *{box-sizing:border-box;margin:0}
  body{background:radial-gradient(1200px 600px at 20% -10%,#1e2733 0%,var(--bg) 55%);
       color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
       min-height:100vh;padding:48px 24px}
  main{max-width:1080px;margin:0 auto}
  h1{font-size:clamp(1.6rem,4vw,2.4rem);letter-spacing:-.02em}
  p.sub{color:var(--dim);margin:.4rem 0 1.4rem}
  nav.chips{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 2rem}
  nav.chips a{padding:.3rem .95rem;border:1px solid var(--edge);border-radius:999px;
       color:var(--fg);text-decoration:none;font-size:.85rem}
  nav.chips a:hover{border-color:var(--acc)}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:22px}
  .card{background:var(--card);border:1px solid var(--edge);border-radius:16px;
        overflow:hidden;display:flex;flex-direction:column;
        transition:transform .15s ease,border-color .15s ease}
  .card:hover{transform:translateY(-3px);border-color:var(--acc)}
  .card a.preview{display:block;aspect-ratio:16/9;background:#000;overflow:hidden;
        text-decoration:none}
  .card img{width:100%;height:100%;object-fit:cover;display:block}
  .card .noimg{width:100%;height:100%;display:flex;align-items:center;
        justify-content:center;font-size:3.2rem;font-weight:700;
        color:rgba(255,255,255,.85)}
  .body{padding:16px 18px 18px;display:flex;flex-direction:column;gap:12px;flex:1}
  .name{font-weight:600;font-size:1.05rem;overflow-wrap:anywhere}
  .row{display:flex;gap:10px;margin-top:auto}
  .btn{flex:1;text-align:center;text-decoration:none;font-weight:600;font-size:.9rem;
       padding:.5rem .9rem;border-radius:999px}
  .btn.play{background:linear-gradient(135deg,var(--acc),var(--acc2));color:#0b0d10}
  .btn.pdf{border:1px solid var(--edge);color:var(--fg)}
  .btn.pdf:hover{border-color:var(--acc2)}
  footer{margin-top:3rem;color:var(--dim);font-size:.85rem}
  footer a{color:var(--acc)}
  @media (prefers-color-scheme: light){
    :root{--bg:#f4f6f8;--card:#fff;--edge:#dde2e8;--fg:#1b1e22;--dim:#5c646d}
    body{background:radial-gradient(1200px 600px at 20% -10%,#e2ecf6 0%,var(--bg) 55%)}
    .btn.play{color:#fff}
  }
"""


def preview(pdf, dist, name):
    """First PDF page as a small PNG under previews/ (returns rel path or None)."""
    out_dir = os.path.join(dist, "previews")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, name)
    try:
        subprocess.run(["pdftoppm", "-png", "-f", "1", "-l", "1",
                        "-scale-to-x", "640", "-scale-to-y", "-1",
                        "-singlefile", pdf, stem],
                       check=True, capture_output=True)
        return f"previews/{name}.png"
    except Exception:
        return None


def card(dist, page):
    name = page[:-5]
    pdf = f"{name}_beamer.pdf"
    has_pdf = os.path.exists(os.path.join(dist, pdf))
    img = preview(os.path.join(dist, pdf), dist, name) if has_pdf else None
    title = html.escape(re.sub(r"[_-]+", " ", name).strip())
    if img:
        inner = f'<img src="{img}" alt="">'
    else:                      # no PDF -> gradient tile with the deck's initial
        hue = sum(name.encode()) % 360
        inner = (f'<span class="noimg" style="background:linear-gradient(135deg,'
                 f'hsl({hue} 45% 28%),hsl({(hue + 50) % 360} 55% 42%))">'
                 f'{html.escape(title[:1].upper())}</span>')
    pdf_btn = (f'<a class="btn pdf" href="{html.escape(pdf)}">PDF</a>'
               if has_pdf else "")
    return f"""<div class="card">
  <a class="preview" href="{html.escape(page)}">{inner}</a>
  <div class="body"><div class="name">{title}</div>
    <div class="row"><a class="btn play" href="{html.escape(page)}">Present</a>{pdf_btn}</div>
  </div></div>"""


def main():
    ap = argparse.ArgumentParser(description="Modern index page for exported decks.")
    ap.add_argument("--dist", required=True)
    ap.add_argument("--title", default="Presentations")
    ap.add_argument("--subtitle",
                    default="reveal.js in the browser — Beamer PDF for offline.")
    ap.add_argument("--source-url", default=None,
                    help="optional 'source' link shown in the footer")
    ap.add_argument("--nav", action="append", default=[], metavar="LABEL=HREF",
                    help="chip link(s) shown under the subtitle (repeatable)")
    a = ap.parse_args()

    pages = sorted(f for f in os.listdir(a.dist) if f.endswith(".html")
                   and f not in ("index.html", "README.html")
                   and not f.endswith("viewer.html"))
    cards = "\n".join(card(a.dist, p) for p in pages)
    chips = "".join(
        f'<a href="{html.escape(h)}">{html.escape(l)}</a>'
        for l, _, h in (n.partition("=") for n in a.nav) if h)
    nav = f'<nav class="chips">{chips}</nav>\n' if chips else ""
    src = (f' · <a href="{html.escape(a.source_url)}">source</a>'
           if a.source_url else "")
    out = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(a.title)}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎞</text></svg>">
<style>{CSS}</style></head><body><main>
<h1>{html.escape(a.title)}</h1>
<p class="sub">{html.escape(a.subtitle)}</p>
{nav}<div class="grid">
{cards}
</div>
<footer>exported with org2slides{src}</footer>
</main></body></html>
"""
    with open(os.path.join(a.dist, "index.html"), "w", encoding="utf-8") as f:
        f.write(out)
    print(f"index.html with {len(pages)} deck(s) -> {a.dist}/index.html")


if __name__ == "__main__":
    main()
