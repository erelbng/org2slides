#!/usr/bin/env python3
"""Convert a reveal.js org deck into a Beamer-friendly org file.

This is a *generic* tool: pass any reveal org deck and it derives the Beamer
header from that deck's own `#+title:/#+author:/#+subtitle:/#+date:/#+language:`
keywords. The source deck is never modified -- the normal `C-c C-e R R` reveal
export keeps working -- and a derived `<deck>_beamer.org` is produced for the
Org LaTeX/Beamer exporter to turn into a PDF.

Guiding principle: the deck only ever describes layout/styling in HTML+CSS
(`#+REVEAL_HTML: <div style="display: grid|flex ...">`, `#+ATTR_HTML: :style
object-fit:cover; border:...; border-radius:...`, hand-written `<ul>/<a>/<h4>`,
font-size wrappers, font-awesome `<i>`). We read *that* and synthesise the
equivalent Beamer output, so the deck never needs LaTeX-only hints
(`#+ATTR_LATEX:`) to look right in the PDF.

What the converter does:

  1. Replace the deck's keyword block with a Beamer header derived from it.
  2. Drop `#+BEGIN_NOTES` speaker-note blocks.
  3. Demote level-3+ headlines to level-2 (each reveal vertical slide -> a frame),
     then drop the now-empty parent frames.
  4. Turn `{{{video(...)}}}` macros into a poster-frame thumbnail image.
  5. Drop figure-generating babel blocks (keep `:exports code|both` listings)
     + empty `[[file:]]` placeholder links + links to missing image files.
  6. Convert `.svg` links to vector `.pdf` (pdflatex cannot embed SVG).
  7. Translate inline HTML (lists, links, headings, font-awesome icons) to org.
  8. Lay out reveal grid/flex containers as Beamer columns (mixed text+media) or
     centred image galleries (media only), honouring CSS column widths,
     `object-fit:cover` crops, `border:` and `border-radius:` (rounded/circular)
     rules. Unclosed `<div>`s auto-close at the slide boundary.
  9. Centre remaining standalone images; scope reveal `font-size:` reductions.

Run via `org2slides deck.org` (which also does the reveal HTML export and
the tex -> pdf compile), or directly:

    python3 convert_to_beamer.py [deck.org] [-o out.org]
                                 [--theme dark|light|<custom>]
                                 [--keep-empty-frames]

Relative asset paths (images, videos, generated thumbnails/crops) resolve
against the current working directory, so run it from the deck's directory.
"""
import re
import os
import subprocess

# ---- Output configuration (applies to every deck) -------------------------
# Built-in themes (both neutral, no branding): "dark" matches the reveal.js
# "black" background; "light" is its clean counterpart. Any other name is
# looked up as a CUSTOM theme: a directory `themes/<name>/` next to the deck (or under
# $ORG2SLIDES_THEMES) containing a `header.org` with the org keyword lines to
# inject (`{{lang}}` is replaced by the deck language) plus any support files
# (.sty, .tex, images) -- resolved through TEXINPUTS.
THEME = "dark"
BUILTIN_THEMES = ("dark", "light")
# Drop frames that end up empty (a headline with no body) -- these are the
# parents of reveal vertical-slide stacks. Set False to keep them as dividers.
DROP_EMPTY_FRAMES = True
CLASS_OPTIONS = "[aspectratio=169, 15pt, c]"   # `c` vertically centres frame content
COVER_RATIO = 16 / 9            # default tile aspect for object-fit:cover images
# Reveal rounds every image/video; match that. Set to "0pt" for square corners.
DEFAULT_RADIUS = "6pt"


def parse_meta(content):
    """Read the deck's own document keywords so the Beamer header can reuse them."""
    meta = {}
    for key in ("title", "author", "subtitle", "date", "language"):
        m = re.search(rf"^\s*#\+{key}:\s*(.+?)\s*$", content, re.MULTILINE | re.IGNORECASE)
        if m:
            meta[key] = m.group(1).strip()
    return meta


def _find_custom_theme(name):
    """Directory of a custom theme: `themes/<name>/` next to the deck (cwd),
    else `$ORG2SLIDES_THEMES/<name>/`. Must contain a header.org."""
    cands = [os.path.join("themes", name)]
    env = os.environ.get("ORG2SLIDES_THEMES")
    if env:
        cands.append(os.path.join(env, name))
    for c in cands:
        if os.path.isfile(os.path.join(c, "header.org")):
            return c
    return None


def _theme_header_lines(theme, lang):
    """Org keyword lines that select the Beamer theme."""
    if theme in ("dark", "light"):
        return ["#+BEAMER_THEME: default",
                f"#+BEAMER_HEADER: \\input{{neutral_{theme}.tex}}"]
    d = _find_custom_theme(theme)
    if not d:
        raise SystemExit(
            f"theme '{theme}' not found: not a built-in {BUILTIN_THEMES} and no "
            f"themes/{theme}/header.org next to the deck or in $ORG2SLIDES_THEMES")
    print(f"  custom theme: {d}")
    text = open(os.path.join(d, "header.org")).read().replace("{{lang}}", lang)
    return [l for l in text.splitlines() if l.strip()]


def build_header(meta):
    """Build the Beamer document header from the deck's title/author/date/etc.,
    so no per-deck editing of this script is needed."""
    lang = (meta.get("language") or "en").strip()
    h = [f"#+title: {meta.get('title', '')}"]
    if meta.get("author"):
        h.append(f"#+author: {meta['author']}")
    if meta.get("subtitle"):
        h.append(f"#+subtitle: {meta['subtitle']}")
    h += [
        "#+startup: beamer",
        "#+LaTeX_CLASS: beamer",
        f"#+LaTeX_CLASS_OPTIONS: {CLASS_OPTIONS}",
    ]
    h += _theme_header_lines(THEME, lang)
    h += [
        "#+BEAMER_HEADER: \\setbeameroption{hide notes}",
        # Fit every image inside its frame (above the footline); keepaspectratio
        # avoids distortion.
        "#+BEAMER_HEADER: \\setkeys{Gin}{keepaspectratio,width=\\linewidth,height=0.72\\textheight}",
        "#+BEAMER_HEADER: \\usepackage{tikz}",           # rounded/circular image clips
        "#+BEAMER_HEADER: \\usepackage{fontawesome5}",   # inline icons from <i class=fa-...>
        # <hr> rules etc. use o2srule; themes define it, this is the fallback.
        "#+BEAMER_HEADER: \\providecolor{o2srule}{gray}{0.55}",
    ]
    h.append("#+options: toc:nil ':{} num:nil H:2")
    h.append(f"#+language: {lang}")
    if meta.get("date"):
        h.append(f"#+date: {meta['date']}")
    h += ["#+MACRO: blur @@latex:\\alert{$1}@@",
          "#+MACRO: video @@latex:\\textit{[Video]}@@", ""]
    return "\n".join(h) + "\n"


def replace_header(content, header):
    """Swap the deck's leading keyword/property block for the Beamer header.
    Robust to both the `:PROPERTIES:`/`:END:` drawer form and a flat run of
    `#+keyword:` lines; stops before the first headline or `#+BEGIN_` block so
    comment blocks and content are preserved. Deck-defined `#+MACRO:`s are
    carried over (they'd expand to undefined-macro errors otherwise), except
    `video`/`blur`, which the Beamer header redefines with LaTeX-safe bodies."""
    lines = content.split("\n")
    macros, i = [], 0
    while i < len(lines):
        s = lines[i].strip()
        if re.match(r"^\*+\s", lines[i]) or s.upper().startswith("#+BEGIN"):
            break
        if s == "" or s.startswith("#+") or s.startswith(":"):
            m = re.match(r"#\+MACRO:\s*(\w+)", s, re.IGNORECASE)
            if m and m.group(1).lower() not in ("video", "blur"):
                macros.append(lines[i])
            i += 1
            continue
        break
    if macros:
        header += "\n".join(macros) + "\n"
    return header + "\n".join(lines[i:])

# ---------------------------------------------------------------------------
# Shared regexes
# ---------------------------------------------------------------------------
IMG_RE       = re.compile(r"^\s*\[\[(?:file:)?([^\]]+)\]\]\s*$")
# Decks write raw HTML as either `#+REVEAL_HTML:` or plain `#+HTML:` lines;
# treat both the same everywhere.
REVEAL_RE    = re.compile(r"^\s*#\+(?:REVEAL_)?HTML:", re.IGNORECASE)
HEADLINE_RE  = re.compile(r"^\*{1,2} ")
ATTR_RE      = re.compile(r"^\s*#\+(ATTR_\w+|CAPTION|NAME):", re.IGNORECASE)
NAME_RE      = re.compile(r"^\s*#\+(NAME|CAPTION):", re.IGNORECASE)
LATEX_ATTR_RE = re.compile(r"^\s*#\+ATTR_LATEX:", re.IGNORECASE)
CONTAINER_OPEN_RE = re.compile(
    r"#\+(?:REVEAL_)?HTML:\s*<div[^>]*display:\s*(grid|flex)", re.IGNORECASE)
TEMPLATE_COLS_RE = re.compile(r"grid-template-columns:\s*([^;\"]+)", re.IGNORECASE)
FONT_SIZE_RE = re.compile(r"#\+(?:REVEAL_)?HTML:\s*<div[^>]*font-size:\s*([0-9.]+)\s*(%|r?em)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Asset helpers (svg->pdf, video thumbnails, cover-crop)
# ---------------------------------------------------------------------------
def svg2pdf(svg_path):
    """Convert an SVG to a vector PDF next to it (once). Returns True on success."""
    if not os.path.exists(svg_path):
        print(f"  svg not found, skipping: {svg_path}")
        return False
    pdf_path = svg_path[:-4] + ".pdf"
    if not os.path.exists(pdf_path) or os.path.getmtime(pdf_path) < os.path.getmtime(svg_path):
        try:
            import cairosvg
            cairosvg.svg2pdf(url=svg_path, write_to=pdf_path)
            print(f"  svg -> pdf: {pdf_path}")
        except Exception as e:
            print(f"  failed to convert {svg_path}: {e}")
            return False
    return True


THUMB_MAX_W = 1920   # cap thumbnail width: a 4K poster frame on a ~6" slide is wasteful


def get_thumbnail(video_path):
    """Return a poster-frame PNG for a video, generating it with ffmpeg once and
    capping its width at THUMB_MAX_W. The cap is part of the cache filename, so
    changing it invalidates stale thumbnails automatically."""
    video_path = video_path.lstrip("./")
    if not os.path.exists(video_path):
        return None

    thumb_dir = "assets/thumbnails"
    os.makedirs(thumb_dir, exist_ok=True)
    stem = os.path.basename(video_path).rsplit(".", 1)[0]
    thumb_path = os.path.join(thumb_dir, f"{stem}_{THUMB_MAX_W}.png")

    if os.path.exists(thumb_path):
        return thumb_path
    print(f"  generating thumbnail for {video_path} ...")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-update", "1",
             "-vf", f"scale='min({THUMB_MAX_W},iw)':-2", thumb_path],
            check=True, capture_output=True,
        )
    except Exception as e:  # ffmpeg missing or video unreadable -> fall back to a label
        print(f"  failed to generate thumbnail for {video_path}: {e}")
        return None
    return thumb_path


def cover_crop(path, ratio=COVER_RATIO, width_px=1280):
    """Crop a raster image to a fixed aspect, filling the box (CSS object-fit:cover).

    Returns (path_to_use, was_cropped). Non-raster inputs (e.g. vector PDFs) are
    returned unchanged so the caller falls back to aspect-preserving placement.
    width_px is part of the cache filename, so raising it invalidates old crops.
    """
    if path.rsplit(".", 1)[-1].lower() not in ("jpg", "jpeg", "png"):
        return path, False
    src = path.lstrip("./")
    if not os.path.exists(src):
        return path, False
    h_px = max(1, round(width_px / ratio))
    out_dir = "assets/cropped"
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    out = f"{out_dir}/{stem}_{ratio:.3f}_{width_px}.png"
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(src):
        try:
            # `^` resizes to fill, then -extent crops the overflow about the centre.
            subprocess.run(
                ["convert", src, "-resize", f"{width_px}x{h_px}^",
                 "-gravity", "center", "-extent", f"{width_px}x{h_px}", out],
                check=True, capture_output=True)
        except Exception as e:
            print(f"  cover-crop failed for {src}: {e}")
            return path, False
    return out, True


def video_replacer(match):
    """Turn a {{{video(args, width, path)}}} macro into a bare thumbnail image
    link (no width attribute, so it flows through the normal layout engine)."""
    args = [a.strip() for a in match.group(1).split(",")]
    if len(args) < 3:
        return match.group(0)
    path = args[2]
    thumb = get_thumbnail(path)
    if thumb:
        return f"[[file:{thumb}]]"
    return f"\\textit{{[Video: {_tex_escape(os.path.basename(path))}]}}"


# ---------------------------------------------------------------------------
# CSS / attribute parsing  (so the deck never needs #+ATTR_LATEX)
# ---------------------------------------------------------------------------
def _hex6(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return h.upper()


def _parse_img_style(attr_lines):
    """Pull image styling out of the `#+ATTR_HTML`/`#+ATTR_LATEX` lines that
    precede an image. Returns a dict with any of:

      cover (bool)        -- object-fit: cover  -> crop to fill
      ratio (float)       -- aspect-ratio W/H   -> crop aspect
      border (hex, "Npt") -- border: Npx solid #hex
      flex_w (float)      -- flex: 0 0 W%       -> relative tile width
      width_frac (float)  -- :width N% / :width X\\textwidth
      height_frac (float) -- :height N%
    """
    s = {}
    css = ""
    for a in attr_lines:
        ms = re.search(r":style\s+(.*)$", a)
        if ms:
            css += ";" + ms.group(1)
        mw = re.search(r":width\s+([0-9.]+)\s*%", a)
        if mw:
            s["width_frac"] = float(mw.group(1)) / 100.0
        mw2 = re.search(r":width\s+([0-9.]+)\\(?:textwidth|linewidth)", a)
        if mw2:
            s["width_frac"] = float(mw2.group(1))
        mh = re.search(r":height\s+([0-9.]+)\s*%", a)
        if mh:
            s["height_frac"] = float(mh.group(1)) / 100.0
    mhpx = re.search(r"(?::height\s+|height:\s*)([0-9.]+)\s*px", " ".join(attr_lines) + ";" + css)
    if mhpx:
        s["height_px"] = float(mhpx.group(1))
    if re.search(r"object-fit:\s*cover", css, re.IGNORECASE):
        s["cover"] = True
    if re.search(r"object-fit:\s*contain", css, re.IGNORECASE):
        s["cover"] = False
    ma = re.search(r"aspect-ratio:\s*([0-9.]+)\s*/\s*([0-9.]+)", css)
    if ma:
        s["ratio"] = float(ma.group(1)) / float(ma.group(2))
    mb = re.search(r"border:\s*([0-9.]+)px\s+solid\s+(#?[0-9a-fA-F]{3,6})", css)
    if mb:
        s["border"] = (_hex6(mb.group(2)), f"{max(0.4, float(mb.group(1)) * 0.7):.1f}pt")
    mr = re.search(r"border-radius:\s*([0-9.]+)\s*(px|%)", css)
    if mr:
        v, u = float(mr.group(1)), mr.group(2)
        if u == "%" and v >= 50:
            s["round"] = "circle"                        # e.g. a round avatar
        else:
            s["radius"] = f"{min(v * (0.75 if u == 'px' else 0.12), 14):.1f}pt"
    mf = re.search(r"flex:\s*[0-9.]+\s+[0-9.]+\s+([0-9.]+)\s*%", css)
    if mf:
        s["flex_w"] = float(mf.group(1)) / 100.0
    return s


def _parse_col_widths(spec):
    """Turn a CSS grid-template-columns value into beamer column fractions
    (scaled to leave a small gap between columns)."""
    fracs = []
    for tok in spec.replace(";", "").split():
        tok = tok.strip()
        if tok.endswith("%"):
            try:
                fracs.append(float(tok[:-1]) / 100.0)
            except ValueError:
                fracs.append(None)
        else:                       # 1fr, auto, ... -> equal share
            fracs.append(None)
    known = sum(f for f in fracs if f)
    blanks = sum(1 for f in fracs if f is None)
    if blanks:
        share = max(0.0, 1.0 - known) / blanks
        fracs = [f if f else share for f in fracs]
    total = sum(fracs) or 1.0
    return [f / total * 0.94 for f in fracs]


def _weighted_widths(styles, total=0.95):
    """Relative widths for a row of tiles, from their CSS flex hints (equal share
    for tiles without an explicit flex width)."""
    raw = [s.get("flex_w") for s in styles]
    known = sum(w for w in raw if w)
    blanks = sum(1 for w in raw if not w)
    if blanks:
        share = max(0.0, 1.0 - known) / blanks
        raw = [w if w else share for w in raw]
    tot = sum(raw) or 1.0
    return [w / tot * total for w in raw]


def _width_factor(width_str):
    """Leading fraction of a `N\\linewidth` / `N\\textwidth` width (1.0 if bare)."""
    m = re.match(r"\s*([0-9.]+)\\(?:line|text)width", width_str)
    return float(m.group(1)) if m else 1.0


def _is_logo(path, style):
    """A logo / small inline icon -- kept square, matching the HTML (these have no
    border-radius). Detected by name or a small explicit pixel height."""
    if "logo" in os.path.basename(path).lower():
        return True
    hp = style.get("height_px")
    return bool(hp and hp <= 45)


def _img_tex(path, style, width_str, height_str):
    """One image cell, honouring the CSS styling: cover-crop (object-fit:cover),
    coloured border, and rounded / circular corners. Every image gets rounded
    corners by default (DEFAULT_RADIUS) to match the reveal deck. Always bounded
    by width x height with keepaspectratio, so it is never distorted."""
    src = path
    if style.get("cover"):
        cp, ok = cover_crop(path, style.get("ratio", COVER_RATIO))
        if ok:
            src = cp
    opts = f"width={width_str},height={height_str},keepaspectratio"
    inc = f"\\includegraphics[{opts}]{{{src}}}"

    # Logos / icons stay square (they carry no border-radius in the deck).
    if _is_logo(path, style):
        return inc
    border = style.get("border")

    # border-radius: 50% -> circle. A plain `circle` node circumscribes the image
    # (clips nothing), so clip to a circle *inscribed* in the (square) image.
    if style.get("round") == "circle":
        r = f"{_width_factor(width_str) / 2:.4f}\\linewidth"
        img = f"\\includegraphics[width={width_str}]{{{src}}}"
        return ("\\begin{tikzpicture}\\clip (0,0) circle (" + r + ");"
                "\\node[inner sep=0pt] at (0,0){" + img + "};\\end{tikzpicture}")

    # Otherwise clip to a rounded rectangle (the deck's radius, else the default).
    rc = f"rounded corners={style.get('radius', DEFAULT_RADIUS)}"
    if border:
        col, th = border
        return ("{\\definecolor{imgborder}{HTML}{" + col + "}\\tikz{"
                "\\node[inner sep=0pt," + rc + ",clip](im){" + inc + "};"
                "\\draw[" + rc + ",imgborder,line width=" + th + "]"
                " (im.south west) rectangle (im.north east);}}")
    return "\\tikz\\node[inner sep=0pt," + rc + ",clip]{" + inc + "};"


# ---------------------------------------------------------------------------
# Inline raw-HTML -> org  (reveal decks hand-write <ul>/<li>/<a>/<h4>/<p>; the
# beamer backend would otherwise drop them, blanking those columns)
# ---------------------------------------------------------------------------
def _strip_tags(s):
    return re.sub(r"<[^>]+>", "", s)


def _tex_escape(s):
    """Escape LaTeX specials in literal text (e.g. filenames with underscores)."""
    return re.sub(r"([_#%&{}$])", r"\\\1", s)


# Font Awesome v5 (fontawesome5.sty) names verified to compile in this TeX tree.
# `\faIcon` hard-errors on unknown names, so we only emit names in this set and
# translate the common v6 aliases the decks use; anything else degrades to "".
FA_KNOWN = {
    "arrow-right", "arrow-left", "arrow-up", "arrow-down", "arrow-circle-right",
    "angle-right", "chevron-right", "caret-right", "long-arrow-alt-right", "check",
    "check-circle", "check-double", "times", "times-circle", "ban", "exclamation",
    "exclamation-triangle", "exclamation-circle", "info", "info-circle", "question",
    "question-circle", "lightbulb", "star", "star-half-alt", "heart", "cog", "cogs",
    "wrench", "tools", "robot", "brain", "rocket", "bolt", "fire", "flask", "vial",
    "cube", "cubes", "box", "boxes", "database", "server", "network-wired",
    "project-diagram", "sitemap", "code", "terminal", "laptop-code", "play",
    "play-circle", "pause", "stop", "forward", "backward", "search", "eye",
    "chart-line", "chart-bar", "chart-pie", "clock", "hourglass-half", "calendar",
    "file", "file-alt", "folder", "book", "book-open", "graduation-cap", "university",
    "building", "envelope", "link", "home", "user", "users", "map-marker-alt",
    "globe", "wifi", "microchip", "hand-point-right", "plus", "minus", "circle",
    "dot-circle", "thumbs-up", "industry", "handshake", "clipboard", "list",
}
FA_ALIAS = {                       # Font Awesome 6 name -> equivalent v5 name
    "triangle-exclamation": "exclamation-triangle", "circle-exclamation": "exclamation-circle",
    "circle-info": "info-circle", "circle-check": "check-circle", "circle-xmark": "times-circle",
    "circle-question": "question-circle", "xmark": "times", "magnifying-glass": "search",
    "gear": "cog", "gears": "cogs", "house": "home", "location-dot": "map-marker-alt",
    "diagram-project": "project-diagram", "screwdriver-wrench": "tools",
    "user-group": "users", "list-check": "list", "lightbulb-on": "lightbulb",
}
FA_SKIP = {"solid", "regular", "light", "thin", "duotone", "brands", "fw", "li", "border",
           "spin", "pulse", "beat", "fade", "bounce", "shake", "inverse", "stack",
           "stack-1x", "stack-2x", "pull-left", "pull-right", "lg", "sm", "xs",
           "2x", "3x", "4x", "5x", "6x", "7x", "8x", "9x", "10x"}


def _fa_from_class(attrs):
    """Map a Font Awesome `<i class="...">` to `\\faIcon{name}` (or "" if unknown)."""
    for tok in re.findall(r"fa-([a-z0-9-]+)", attrs, re.IGNORECASE):
        tok = tok.lower()
        if tok in FA_SKIP:
            continue
        name = FA_ALIAS.get(tok, tok)
        return f"\\faIcon{{{name}}}~" if name in FA_KNOWN else ""
    return ""


def _html_inline_to_org(s):
    """Translate the inline HTML the deck uses into org markup."""
    def link(m):
        url, txt = m.group(1), _strip_tags(m.group(2)).strip()
        return f"[[{url}][{txt}]]" if txt else f"[[{url}]]"
    s = re.sub(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', link, s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<(strong|b)\b[^>]*>(.*?)</\1>", r"*\2*", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<(em)\b[^>]*>(.*?)</\1>", r"/\2/", s, flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r"<i\b([^>]*)>.*?</i>",
               lambda m: _fa_from_class(m.group(1)), s, flags=re.IGNORECASE | re.DOTALL)
    return s


def convert_inline_html(content):
    """Turn content-bearing `#+REVEAL_HTML:` lines (lists, links, headings,
    paragraphs) into org so the beamer exporter keeps them. Structural `<div>`
    lines are left for the layout engine; `<iframe>` becomes a placeholder note;
    `<svg>`/`<ul>`/icon-only lines are dropped.
    """
    out = []
    for line in content.split("\n"):
        if not REVEAL_RE.match(line):
            out.append(line)
            continue
        html = re.sub(r"^\s*#\+(?:REVEAL_)?HTML:\s?", "", line)
        if "<div" in html or "</div>" in html:          # structural -> keep
            out.append(line)
            continue
        mif = re.search(r'<iframe\b[^>]*src="([^"]+)"', html, re.IGNORECASE)
        if mif:
            out += ["#+BEGIN_EXPORT latex",
                    "\\begin{center}\\textit{[Interactive: "
                    + _tex_escape(os.path.basename(mif.group(1))) + "]}\\end{center}",
                    "#+END_EXPORT"]
            continue
        if re.search(r"<hr\b", html, re.IGNORECASE) and not _strip_tags(html).strip():
            out.append("#+LATEX: \\vspace{3pt}{\\color{o2srule}\\hrule}\\vspace{5pt}")
            continue
        is_li = bool(re.search(r"<li\b", html, re.IGNORECASE))
        is_h = bool(re.search(r"<h[1-6]\b", html, re.IGNORECASE))
        if is_li:                       # one bullet per <li>, even on one line
            for item in re.split(r"<li\b[^>]*>", html, flags=re.IGNORECASE)[1:]:
                t = re.sub(r"\s+", " ", _strip_tags(_html_inline_to_org(item)).strip())
                if t:
                    out.append("- " + t)
            continue
        text = re.sub(r"\s+", " ", _strip_tags(_html_inline_to_org(html)).strip())
        if not text:                                     # <ul>, <svg>, lone icon -> drop
            continue
        if is_h:
            out += ["*" + text + "*", ""]
        else:
            out += [text, ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Layout engine: reveal grid/flex containers -> beamer columns / galleries
# ---------------------------------------------------------------------------
def _size_block_images(lines, height="0.55\\textheight"):
    """Give bare image links inside column / stacked content an explicit
    cover-crop + height cap. Org would otherwise size them at .9\\linewidth with
    no vertical bound, so an image next to a caption overflows the column.
    Named figures and images already in an export block are left alone.
    """
    out, i, n, in_export = [], 0, len(lines), False
    while i < n:
        l = lines[i]
        if re.match(r"^\s*#\+BEGIN_EXPORT", l, re.IGNORECASE):
            in_export = True
        elif re.match(r"^\s*#\+END_EXPORT", l, re.IGNORECASE):
            in_export = False
            out.append(l); i += 1; continue
        m = IMG_RE.match(l)
        if m and not in_export:
            attrs, b = [], len(out) - 1
            while b >= 0 and (ATTR_RE.match(out[b]) or not out[b].strip()):
                if ATTR_RE.match(out[b]):
                    attrs.insert(0, out[b])
                b -= 1
            if any(NAME_RE.match(a) or LATEX_ATTR_RE.match(a) for a in attrs):
                out.append(l); i += 1; continue
            s = _parse_img_style(attrs)
            w = f"{s.get('width_frac', 1.0):.3f}\\linewidth"
            out += ["#+BEGIN_EXPORT latex",
                    "\\begin{center}" + _img_tex(m.group(1), s, w, height) + "\\end{center}",
                    "#+END_EXPORT"]
            i += 1
            continue
        out.append(l)
        i += 1
    return out


def _net_div(line):
    return line.count("<div") - line.count("</div>") if REVEAL_RE.match(line) else 0


def collect_container(lines, start):
    """Collect the inner lines of the grid/flex container opened at lines[start].

    Robust to reveal's unclosed `<div>`s: a container ends at its matching
    `</div>`, OR at the next headline (slide boundary), OR when a *sibling*
    grid/flex container opens at the same level. Returns (inner_lines, next_idx).
    """
    inner, depth, j, n = [], 1, start + 1, len(lines)
    while j < n:
        l = lines[j]
        if HEADLINE_RE.match(l):
            break
        cm = CONTAINER_OPEN_RE.search(l)
        # A sibling *grid* opening at our level starts a new band (stack it
        # vertically). A nested flex (e.g. a small inline arrow/icon wrapper) is
        # just one item of this container, so it is NOT a band -- keep collecting.
        if depth == 1 and cm and cm.group(1).lower() == "grid":
            break
        d = _net_div(l)
        if depth + d <= 0:                               # matching close -> consume
            j += 1
            break
        depth += d
        inner.append(l)
        j += 1
    return inner, j


def split_cells(inner):
    """Split a container's inner lines into cells (each a list of org lines).

    A cell is: an explicit wrapper `<div>...</div>` (reveal "Pattern A"), a bare
    image (its own tile, with any preceding ATTR lines), a nested grid/flex
    container, or a run of text/list lines. reveal decoration lines are kept --
    they are inert for the beamer exporter -- and ignored when classifying cells.
    """
    cells, cur, depth = [], [], 0
    i, n = 0, len(inner)

    def push():
        if cur:
            cells.append(cur[:])
            cur.clear()

    while i < n:
        l = inner[i]
        if depth == 0:
            if CONTAINER_OPEN_RE.search(l):              # nested container -> one cell
                push()
                sub, j = collect_container(inner, i)
                cells.append([l] + sub)
                i = j
                continue
            if REVEAL_RE.match(l) and _net_div(l) > 0:   # wrapper-div cell opens
                push()
                cur.append(l)
                depth += _net_div(l)
                i += 1
                continue
            if IMG_RE.match(l):                          # bare image tile
                if cur and all(ATTR_RE.match(x) or not x.strip() for x in cur):
                    cells.append(cur[:] + [l]); cur.clear()
                else:
                    push(); cells.append([l])
                i += 1
                continue
            if REVEAL_RE.match(l) or re.match(r"^\s*#(?!\+)", l):  # decoration / org comment
                i += 1
                continue
            if not l.strip():                            # blank separates text cells
                push()
                i += 1
                continue
            cur.append(l)                                # text / list / math / attr
            i += 1
        else:                                            # inside a wrapper div
            cur.append(l)
            depth += _net_div(l)
            if depth <= 0:
                depth = 0
                push()
            i += 1
    push()
    return cells


def cell_kind(body):
    imgs = [l for l in body if IMG_RE.match(l)]
    txt = [l for l in body if l.strip() and not IMG_RE.match(l)
           and not ATTR_RE.match(l) and not REVEAL_RE.match(l)
           and not re.match(r"^\s*#(?!\+)", l)]
    if not imgs and not txt:                              # decoration / comment only
        return "empty"
    if any(CONTAINER_OPEN_RE.search(l) for l in body) or len(imgs) > 1 or (imgs and txt):
        return "mixed"
    if len(imgs) == 1:
        return "media"
    return "mixed"


def _media_item(body):
    img = next(l for l in body if IMG_RE.match(l))
    attrs = [l for l in body if ATTR_RE.match(l)]
    return IMG_RE.match(img).group(1), _parse_img_style(attrs)


def _gallery(cells, disp, spec):
    """Media-only container -> centred grid of images, sized to fit the slide."""
    items = [_media_item(c) for c in cells]
    grid_w = _parse_col_widths(spec) if (disp == "grid" and spec) else None
    ncol = len(grid_w) if grid_w else len(items)
    ncol = max(1, ncol)
    nrows = -(-len(items) // ncol)
    hcap = 0.62 if nrows == 1 else min(0.40, 0.66 / nrows)
    rows_tex = []
    for r in range(nrows):
        row = items[r * ncol:(r + 1) * ncol]
        if nrows == 1 and grid_w:
            widths = grid_w[:len(row)]
        elif nrows == 1:
            widths = _weighted_widths([s for _, s in row])
        else:
            widths = [0.95 / ncol] * len(row)
        cells_tex = [_img_tex(p, s, f"{w:.3f}\\linewidth", f"{hcap:.3f}\\textheight")
                     for (p, s), w in zip(row, widths)]
        rows_tex.append("\\hfill\n".join(cells_tex))
    body = "\\par\\medskip\n".join(rows_tex)
    return ["", "#+BEGIN_EXPORT latex", "\\begin{center}", body,
            "\\end{center}", "#+END_EXPORT", ""]


def _columns(cells, disp, spec, valign="t"):
    """Mixed container -> beamer columns (text processed by org, media centred).
    `valign` is "c" for CSS align-items:center, else "t" (top-aligned)."""
    if disp == "grid" and spec:
        cw = _parse_col_widths(spec)
        if len(cw) < len(cells):
            cw = [0.94 / len(cells)] * len(cells)
    else:
        cw = [0.94 / len(cells)] * len(cells)
    out = ["", f"#+LATEX: \\begin{{columns}}[{valign}]"]
    for cell, w in zip(cells, cw[:len(cells)]):
        out.append(f"#+LATEX: \\begin{{column}}{{{w:.3f}\\textwidth}}")
        out.append("")
        if cell_kind(cell) == "media":
            p, s = _media_item(cell)
            tex = _img_tex(p, s, "\\linewidth", "0.72\\textheight")
            out += ["#+BEGIN_EXPORT latex", "\\begin{center}" + tex + "\\end{center}",
                    "#+END_EXPORT"]
        else:
            out += _size_block_images(layout_lines(cell))   # recurse; size loose images
        out += ["", "#+LATEX: \\end{column}"]
    out += ["#+LATEX: \\end{columns}", ""]
    return out


def render_container(open_line, inner):
    disp = CONTAINER_OPEN_RE.search(open_line).group(1).lower()
    # A column-direction flex stacks its children vertically -> not side by side.
    if disp == "flex" and re.search(r"flex-direction:\s*column", open_line, re.IGNORECASE):
        stacked = _size_block_images(layout_lines(inner))
        mfs = re.search(r"font-size:\s*([0-9.]+)\s*(%|r?em)", open_line, re.IGNORECASE)
        cmd = _size_cmd(float(mfs.group(1)) * (1 if mfs.group(2) == "%" else 100)) if mfs else None
        if cmd:                                          # carry the wrapper's font-size
            return ["", "#+LATEX: \\begingroup" + cmd] + stacked + ["#+LATEX: \\endgroup", ""]
        return [""] + stacked + [""]
    tm = TEMPLATE_COLS_RE.search(open_line)
    spec = tm.group(1) if tm else None
    cells = [c for c in split_cells(inner) if cell_kind(c) != "empty"]
    if not cells:
        return []
    if len(cells) == 1:                          # nothing to lay side by side
        c = cells[0]
        if cell_kind(c) == "media":
            p, s = _media_item(c)
            tex = _img_tex(p, s, "\\linewidth", "0.74\\textheight")
            return ["", "#+BEGIN_EXPORT latex", "\\begin{center}" + tex + "\\end{center}",
                    "#+END_EXPORT", ""]
        return layout_lines(c)
    if all(cell_kind(c) == "media" for c in cells):
        return _gallery(cells, disp, spec)
    valign = "c" if re.search(r"align-items:\s*center", open_line, re.IGNORECASE) else "t"
    return _columns(cells, disp, spec, valign)


def layout_lines(lines):
    """Process org lines, replacing every top-level grid/flex container with its
    Beamer layout. Recurses into the cells of mixed containers."""
    out, i, n = [], 0, len(lines)
    while i < n:
        l = lines[i]
        if CONTAINER_OPEN_RE.search(l):
            inner, j = collect_container(lines, i)
            out += render_container(l, inner)
            i = j
            continue
        out.append(l)
        i += 1
    return out


def _size_cmd(pct):
    """Map a reveal CSS font-size percentage to a Beamer size command (None ~ normal)."""
    if pct <= 55:
        return "\\scriptsize"
    if pct <= 70:
        return "\\footnotesize"
    if pct <= 88:
        return "\\small"
    return None


def apply_font_sizes(content):
    """Honour reveal `font-size: N%` wrapper divs (lost on the LaTeX backend) by
    scoping their content in a Beamer size group. Without this, deck text that is
    deliberately shrunk in reveal (RQ lists, reward-function details, the project
    work-package list) renders full-size in the PDF and overflows the slide.

    Groups are balanced defensively: a size group closes at its matching `</div>`,
    and any still-open group is closed at the next headline (slide boundary).
    """
    lines = content.split("\n")
    out, stack, depth = [], [], 0   # stack: (div_depth_at_open, emitted_group?)

    def close_to(newdepth):
        while stack and stack[-1][0] > newdepth:
            _, emitted = stack.pop()
            if emitted:
                out.append("#+LATEX: \\endgroup")

    for l in lines:
        if HEADLINE_RE.match(l):
            close_to(0)
            depth = 0
            out.append(l)
            continue
        delta = _net_div(l)
        m = FONT_SIZE_RE.search(l)
        if m:
            out.append(l)
            depth += delta
            pct = float(m.group(1)) * (1 if m.group(2) == "%" else 100)  # 1em ~ 100%
            cmd = _size_cmd(pct)
            if cmd:
                # \begingroup (not a bare `{`) so a size group at the very start of
                # a frame body is not mistaken for the frame's {subtitle} argument.
                out.append("#+LATEX: \\begingroup" + cmd)
            stack.append((depth, bool(cmd)))
            continue
        if REVEAL_RE.match(l) and delta < 0:
            newdepth = depth + delta
            out.append(l)
            close_to(newdepth)
            depth = newdepth
            continue
        out.append(l)
        depth += delta
    close_to(0)
    return "\n".join(out)


def center_standalone_media(content):
    """Centre standalone images that org would otherwise left-align (chiefly lone
    video thumbnails). Named figures (`#+name:`/`#+caption:`), images carrying an
    explicit `#+ATTR_LATEX:`, and images already inside a column or export block
    are left untouched."""
    lines = content.split("\n")
    out, i, n = [], 0, len(lines)
    in_cols, in_export = 0, False
    while i < n:
        l = lines[i]
        if "\\begin{columns}" in l:
            in_cols += 1
        if "\\end{columns}" in l:
            in_cols = max(0, in_cols - 1)
        if re.match(r"^\s*#\+BEGIN_EXPORT", l, re.IGNORECASE):
            in_export = True
        elif re.match(r"^\s*#\+END_EXPORT", l, re.IGNORECASE):
            in_export = False
            out.append(l); i += 1; continue
        m = IMG_RE.match(l)
        if m and not in_cols and not in_export:
            attrs, b = [], len(out) - 1
            while b >= 0 and (ATTR_RE.match(out[b]) or not out[b].strip()):
                if ATTR_RE.match(out[b]):
                    attrs.insert(0, out[b])
                b -= 1
            if any(NAME_RE.match(a) or LATEX_ATTR_RE.match(a) for a in attrs):
                out.append(l); i += 1; continue
            s = _parse_img_style(attrs)
            w = f"{s.get('width_frac', 1.0):.3f}\\linewidth"
            h = f"{s.get('height_frac', 0.74):.3f}\\textheight" if s.get("height_frac") else "0.74\\textheight"
            tex = _img_tex(m.group(1), s, w, h)
            out += ["#+BEGIN_EXPORT latex", "\\begin{center}" + tex + "\\end{center}",
                    "#+END_EXPORT"]
            i += 1
            continue
        out.append(l)
        i += 1
    return "\n".join(out)


SRC_OPEN_RE  = re.compile(r"^\s*#\+BEGIN_SRC\b(.*)$", re.IGNORECASE)
SRC_CLOSE_RE = re.compile(r"^\s*#\+END_SRC\s*$", re.IGNORECASE)
HEADER_KW_RE = re.compile(r"^\s*#\+header:", re.IGNORECASE)


def _emit_src(lines, i, extra_headers, out):
    """Emit or drop the src block starting at lines[i]; return the next index.

    Kept when the code itself is slide content: `:exports code|both`, or no
    `:exports` at all AND no file-producing `:results`/`:file` header (those
    are babel figure generators whose output image is linked separately)."""
    block, j, n = [lines[i]], i + 1, len(lines)
    while j < n and not SRC_CLOSE_RE.match(lines[j]):
        block.append(lines[j]); j += 1
    if j < n:
        block.append(lines[j]); j += 1
    hdr = lines[i] + " " + extra_headers
    me = re.search(r":exports\s+(\S+)", hdr, re.IGNORECASE)
    exports = me.group(1).lower() if me else None
    makes_file = bool(re.search(r":(?:file\b|results\s+[^:]*file)", hdr, re.IGNORECASE))
    if exports in ("code", "both") or (exports is None and not makes_file):
        out.extend(block)
    return j


def handle_src_blocks(content):
    """Drop figure-generating babel blocks; keep blocks whose code IS the
    content (teaching decks). `#+header:` and `#+RESULTS:` keyword lines are
    dropped either way -- the emacs export runs with `org-export-use-babel
    nil`, so nothing is ever executed and kept blocks render as listings.
    The image link under a `#+RESULTS:` keyword survives (only the keyword
    line goes), so `:exports both` decks show code and figure."""
    lines = content.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        if HEADER_KW_RE.match(lines[i]):
            hdrs = []
            while i < n and HEADER_KW_RE.match(lines[i]):
                hdrs.append(lines[i]); i += 1
            if i < n and SRC_OPEN_RE.match(lines[i]):
                i = _emit_src(lines, i, " ".join(hdrs), out)
            continue
        if SRC_OPEN_RE.match(lines[i]):
            i = _emit_src(lines, i, "", out)
            continue
        if re.match(r"^\s*#\+RESULTS:", lines[i], re.IGNORECASE):
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _density_safe(path):
    """pdflatex aborts with 'Dimension too large' when an image's density
    metadata (PNG pHYs) yields a natural size beyond TeX's ~227 inch limit
    (e.g. a 4000 px diagram stamped at 12 dpi by a drawing tool). Re-stamp
    such images at 96 dpi in a cached copy and return that path."""
    src = path.lstrip("./")
    if not os.path.exists(src):
        return path
    try:
        out = subprocess.run(
            ["identify", "-format", "%w %h %x %U", src + "[0]"],
            check=True, capture_output=True, text=True).stdout.split()
        w, h, xres = float(out[0]), float(out[1]), float(out[2])
        units = out[3] if len(out) > 3 else "Undefined"
    except Exception:
        return path
    if xres <= 0 or units == "Undefined":     # latex assumes 72 dpi -> fine
        return path
    dpi = xres * 2.54 if units.startswith("PixelsPerCentimeter") else xres
    if max(w, h) / dpi <= 200:                # natural size under ~200in: fine
        return path
    out_dir = "assets/sanitized"
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, os.path.basename(src))
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        try:
            subprocess.run(["convert", src, "-units", "PixelsPerInch",
                            "-density", "96", dst],
                           check=True, capture_output=True)
            print(f"  re-stamped absurd density ({dpi:.1f} dpi): {src}")
        except Exception:
            return path
    return dst


def sanitize_image_density(content):
    """Rewrite links to raster images whose density metadata would crash
    pdflatex (see _density_safe)."""
    return re.sub(
        r"\[\[(?:file:)?([^\]]+\.(?:png|jpe?g))\]\]",
        lambda m: m.group(0).replace(m.group(1), _density_safe(m.group(1))),
        content, flags=re.IGNORECASE)


# Box-drawing (U+2500-257F) and block-element (U+2580-259F) characters, as
# pasted from terminal output into decks, are not typesettable by pdflatex
# (inputenc has no mapping). Transliterate to ASCII lookalikes.
_BOX_TRANS = {}
for _cp in range(0x2500, 0x25A0):
    _ch = chr(_cp)
    if _ch in "\u2500\u2501\u2504\u2505\u2508\u2509\u254c\u254d\u2550":
        _BOX_TRANS[_cp] = "-"
    elif _ch in "\u2502\u2503\u2506\u2507\u250a\u250b\u254e\u254f\u2551":
        _BOX_TRANS[_cp] = "|"
    elif _cp >= 0x2580:
        _BOX_TRANS[_cp] = "#"
    else:
        _BOX_TRANS[_cp] = "+"


def ascii_boxes(content):
    return content.translate(_BOX_TRANS)


def drop_missing_images(content):
    """Drop standalone image links whose file does not exist (e.g. a babel
    figure that was never generated, or an asset the deck no longer ships).
    A missing file would otherwise become an \\includegraphics that aborts
    pdflatex; a warning is printed instead."""
    def repl(m):
        path = m.group(1)
        if re.match(r"https?:", path) or os.path.exists(path.lstrip("./")):
            return m.group(0)
        print(f"  missing image, link dropped: {path}")
        return ""
    return re.sub(
        r"^[ \t]*\[\[(?:file:)?([^\]]+\.(?:png|jpe?g|pdf|gif|bmp|webp))\]\][ \t]*\n?",
        repl, content, flags=re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------------------
# Frame-structure fixes
# ---------------------------------------------------------------------------
def wrap_level1_content(content):
    """Wrap direct content of a level-1 headline in its own frame.

    With H:2 the Beamer exporter turns level-1 headlines into *sections* (no
    frame), so content sitting directly under a `* Heading` (before its `**`
    children) would leak out as stray bare pages. We insert a `** Heading` frame
    to hold it, leaving pure section-divider headlines (immediately followed by
    `**`) untouched.
    """
    lines = content.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        out.append(line)
        m = re.match(r"^\* (.+?)\s*$", line)
        if m:
            title = m.group(1)
            k = i + 1
            while k < n and lines[k].strip() == "":          # leading blank lines
                out.append(lines[k]); k += 1
            if k < n and lines[k].strip().upper() == ":PROPERTIES:":  # a drawer
                while k < n and lines[k].strip().upper() != ":END:":
                    out.append(lines[k]); k += 1
                if k < n:
                    out.append(lines[k]); k += 1
                while k < n and lines[k].strip() == "":
                    out.append(lines[k]); k += 1
            # If real content (not a sub-headline) follows, wrap it in a frame.
            if k < n and not re.match(r"^\*{1,2} ", lines[k]):
                out.append("** " + title)
            i = k
            continue
        i += 1
    return "\n".join(out)


def drop_empty_frames(content):
    """Drop level-2 headlines whose body is empty (the parent slides of reveal
    vertical-slide stacks, which would otherwise be blank pages)."""
    lines = content.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        if re.match(r"^\*\* .+", lines[i]):
            k = i + 1
            while k < n and lines[k].strip() == "":
                k += 1
            if k < n and lines[k].strip().upper() == ":PROPERTIES:":
                while k < n and lines[k].strip().upper() != ":END:":
                    k += 1
                if k < n:
                    k += 1
                while k < n and lines[k].strip() == "":
                    k += 1
            if k >= n or re.match(r"^\*{1,2} ", lines[k]):   # nothing before next headline
                i = k
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def convert(src, dst=None):
    if dst is None:
        base = os.path.basename(src)
        dst = (base[:-4] if base.endswith(".org") else base) + "_beamer.org"
    content = open(src).read()

    # 1. Swap the deck's keyword block for a Beamer header derived from it.
    content = replace_header(content, build_header(parse_meta(content)))

    # 2. Drop reveal speaker-note blocks.
    content = re.sub(r"#\+BEGIN_NOTES.*?#\+END_NOTES\n?", "", content,
                     flags=re.DOTALL | re.IGNORECASE)

    # 3. Reveal makes every headline a slide; with H:2 a level-3 headline would
    #    become a `block` crammed into its parent frame. Demote level-3+ to
    #    level-2 so each becomes its own frame (a vertical slide in reveal).
    content = re.sub(r"^\*{3,} ", "** ", content, flags=re.MULTILINE)

    # 4. Replace video macros with thumbnails (before stripping src blocks).
    content = re.sub(r"{{{video\((.*?)\)}}}", video_replacer, content)

    # 5. Handle babel source blocks: drop figure generators (their output
    #    images are referenced separately), keep code that IS the content
    #    (`:exports code|both`); drop `#+header:`/`#+RESULTS:` keyword lines.
    content = handle_src_blocks(content)

    # 5b. Drop empty placeholder image links ([[file:]] / [[]]) left by babel
    #     blocks whose figure was never generated -- they would become an
    #     \includegraphics{} that aborts pdflatex.
    content = re.sub(r"^[ \t]*\[\[(?:file:)?\]\][ \t]*\n?", "", content, flags=re.MULTILINE)

    # 6. Frame structure: wrap loose level-1 content, then drop empty frames.
    content = wrap_level1_content(content)
    if DROP_EMPTY_FRAMES:
        content = drop_empty_frames(content)

    # 7. pdflatex cannot embed SVG. Convert each referenced SVG to a *vector*
    #    PDF (crisp at any size) and point the link at the PDF.
    for svg in sorted(set(re.findall(r"file:([^\]\s]+\.svg)", content))):
        svg_clean = svg.lstrip("./")
        pdf = svg[:-4] + ".pdf"
        if svg2pdf(svg_clean):
            content = content.replace(svg, pdf)
        else:  # conversion failed -> fall back to the PNG sibling
            content = content.replace(svg, svg[:-4] + ".png")

    # 7b. Drop links to images that don't exist on disk, and defuse images
    #     whose density metadata would abort pdflatex.
    content = drop_missing_images(content)
    content = sanitize_image_density(content)

    # 8. Translate hand-written inline HTML (lists, links, headings) to org so
    #    those columns are not blank, then lay out reveal grid/flex containers
    #    (columns / galleries) and centre any remaining standalone images.
    content = convert_inline_html(content)
    content = "\n".join(layout_lines(content.split("\n")))
    content = center_standalone_media(content)

    # 9. Honour reveal `font-size: N%` reductions so dense text fits the slide.
    content = apply_font_sizes(content)

    # Terminal box-drawing characters would abort pdflatex.
    content = ascii_boxes(content)

    open(dst, "w").write(content)
    print(f"wrote {dst}")
    return dst


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Convert a reveal.js org deck into a Beamer-friendly org file.")
    p.add_argument("src", help="reveal org deck")
    p.add_argument("-o", "--output",
                   help="output file (default: <deck>_beamer.org next to cwd)")
    p.add_argument("--theme", default=None,
                   help="built-in: dark (default) | light; any other name is "
                        "looked up in themes/<name>/ next to the deck or in "
                        "$ORG2SLIDES_THEMES")
    p.add_argument("--light", action="store_true",
                   help="shorthand for --theme light")
    p.add_argument("--keep-empty-frames", action="store_true",
                   help="keep empty parent frames as section dividers")
    a = p.parse_args()
    THEME = a.theme or ("light" if a.light else "dark")
    DROP_EMPTY_FRAMES = not a.keep_empty_frames
    convert(a.src, a.output)
