# org2slides

<div align="center">
[![CI](https://github.com/erelbng/org2slides/actions/workflows/ci.yml/badge.svg)](https://github.com/erelbng/org2slides/actions/workflows/ci.yml)
</div>

[Live examples](https://erelbng.github.io/org2slides/) (built by the CI from `examples/`)

Forge a **reveal.js HTML presentation** and a **Beamer PDF** from a single org-mode deck — one command, no per-deck LaTeX hints.

```
./org2slides talk.org          # -> talk.html + talk_beamer.pdf
```

The org deck stays the single source of truth: write it for reveal.js (`#+REVEAL_HTML:` layouts, CSS styling, videos, babel figures) and org2slides derives a matching Beamer PDF from the very same HTML/CSS hints — grid/flex containers become columns or image galleries, `object-fit: cover` becomes a crop, `border-radius` becomes rounded/circular clips, `font-size: N%` becomes a Beamer size group, videos become poster-frame thumbnails, font-awesome icons become `\faIcon`, SVGs become vector PDFs.

Decks may live in **any directory** — outputs land next to the deck, the built-in PDF themes ship in this repository (resolved via `TEXINPUTS`), and ox-reveal/htmlize are vendored, so a bare `emacs-nox` is enough. That makes the repo cloneable straight into a CI pipeline (see below). Private or institutional themes stay in YOUR deck repository (see "Themes").

## Try it

Two self-contained example decks live in `examples/`:

```
./org2slides examples/minimal.org examples/showcase.org
```

produces `examples/minimal.html` + `examples/minimal_beamer.pdf` (and the same for `showcase`) — reveal.js is downloaded into `examples/revealjs/` on the first run. `minimal.org` shows the basic workflow (grid layout, SVG, speaker notes); `showcase.org` exercises the whole converter (video poster frames, `object-fit: cover` galleries, circular avatars, font-awesome icons, code listings, font-size groups). Add `--theme light` to restyle both outputs; the [live demo](https://erelbng.github.io/org2slides/) shows every built-in theme, rebuilt from these two files on each push.

## Command line

```
org2slides [options] deck.org [deck2.org ...]

  --html         export only the reveal.js HTML
  --pdf          export only the Beamer PDF          (default: both)
  --dist DIR     additionally bundle a self-contained, size-optimised
                 website into DIR (see "Minimal footprint" below)
  --debug        keep intermediates (<deck>_beamer.org/.tex, aux files),
                 full pdflatex output
  --theme T      theme: dark (default) | light, or a custom theme shipped
                 with your decks (see "Themes")
  --light        shorthand for --theme light
```

Environment knobs: `PDF_COMPRESS=0` (skip Ghostscript), `PDF_DPI` (default 300), `PDF_JPEGQ` (default 95), `REVEAL_VERSION` (default 5.2.1).

Two things make exports reproducible on any machine:

* **Babel never executes** (`:eval never-export`): decks export with their
  committed `#+RESULTS:` figures. Blocks with `:exports code|both` still
  show their code.
* **reveal.js auto-download**: when the deck's `#+REVEAL_ROOT:` points to a
  local directory that does not exist (fresh CI checkout — `revealjs/` is
  usually gitignored), org2slides fetches that reveal.js version there.

## Minimal footprint 

Some providers have artifact/Pages size limits, and decks tend to reference 4K screen recordings. `--dist DIR` walks the exported HTML and copies **only the files it actually references** into `DIR`, shrinking media on the way:

* images larger than 1920 px are downscaled (quality 85),
* videos wider than 1280 px **or fatter than 2500 kbit/s** are re-encoded
  (h264 crf 28, aac 96k, faststart),
* iframe'd local HTML (interactive viewers) is followed one level deep,
* reveal's theme fonts are included (referenced from CSS, invisible to the
  HTML scan).

Relative paths are preserved, so nothing in the HTML is rewritten; the folder is a complete website. For different budgets call webdist directly:

```
python3 webdist.py --dist public --max-img 1600 --max-video 960 \
                   --crf 30 --max-kbps 1500 talk.html
```

## Themes

| name             | look                                                           |
|------------------|----------------------------------------------------------------|
| `dark` (default) | matches reveal's black background (#191919), blue/teal accents |
| `light`          | its clean light counterpart                                    |

**Custom themes live with your decks, not here.** `--theme mytheme` looks for `themes/mytheme/` next to the deck (or under `$ORG2SLIDES_THEMES`) containing:

```
themes/mytheme/
  header.org            org keyword lines injected into the derived deck
  mybeamertheme.sty     + any .sty/.tex/image files the header needs
```

`header.org` example (`{{lang}}` is replaced by the deck's `#+language:`):

```org
#+BEAMER_THEME: [color=navy, lang={{lang}}]MyCorp
#+BEAMER_HEADER: \input{mycorp_dark_overrides.tex}
#+BEAMER_HEADER: \colorlet{o2srule}{white!45}
```

**The HTML follows the theme too.** With `--theme`, a matching stylesheet is copied next to the deck (`org2slides-theme.css`) and injected as an extra reveal stylesheet — colours AND typography mirror the PDF: both themes use Source Sans Pro on both sides (the PDF loads the `sourcesanspro` TeX package, reveal ships the webfont), and reveal's default UPPERCASE headings are turned off to match the frame titles. Built-ins ship theirs in `theme/reveal_<name>.css`; a custom theme provides an optional `themes/<name>/reveal.css`. The source deck is never modified, and its own `#+REVEAL_EXTRA_CSS` files keep working. Without `--theme`, the HTML export is untouched.

## Emacs integration

Add to `init.el`:

```elisp
(load "~/path/to/org2slides/org2slides.el")
(with-eval-after-load 'org
  (define-key org-mode-map (kbd "C-c b") #'org2slides-export))
```

or with `use-package`:

```elisp
(use-package org2slides
  :load-path "~/path/to/org2slides"
  :commands (org2slides-export org2slides-export-pdf org2slides-export-html)
  :init (with-eval-after-load 'org
          (define-key org-mode-map (kbd "C-c b") #'org2slides-export)))
```

Then, in a deck buffer:

| Command                               | Effect                               |
|---------------------------------------|--------------------------------------|
| `M-x org2slides-export` (`C-c b`)     | HTML + PDF, opens the PDF when done  |
| `C-u M-x org2slides-export`           | same, keep intermediates (`--debug`) |
| `M-x org2slides-export-pdf` / `-html` | one backend only                     |

Everything is also in the org export dispatcher, `C-c C-e s`:
`s` HTML + PDF · `h` HTML · `p` PDF · `d` PDF debug · `l` PDF light theme ·
`t` PDF with chosen theme (built-in or custom).

Builds run asynchronously in a `*org2slides*` compilation buffer — Emacs stays usable, errors are jumpable. Customize `org2slides-extra-args` (e.g. `("--theme" "mytheme")`) and `org2slides-open-output`.

Your interactive `C-c C-e R R` (ox-reveal) export keeps working as before — org2slides does not touch org configuration.

## CI integration

### GitLab

This repository ships `ci/org2slides.gitlab-ci.yml` with ready-made hidden jobs. A presentation repository's `.gitlab-ci.yml` becomes:

```yaml
include:
  - project: 'you/org2slides'           # adjust: where org2slides lives
    file: 'ci/org2slides.gitlab-ci.yml'

pages:                                  # publish all decks via GitLab Pages
  extends: .org2slides-pages

export:                                 # and/or downloadable HTML+PDF artifacts
  extends: .org2slides-export
```

That's the whole pipeline — repeat those five lines in every presentation repository. Override per project:

```yaml
pages:
  extends: .org2slides-pages
  variables:
    DECKS: "talk.org lecture.org"       # default: *.org in the repo root
    ORG2SLIDES_REPO: "https://gitlab.example.com/you/org2slides.git"
```

`.org2slides-pages` builds into `public/` via `--dist` (minimal, self-contained) and caches re-encoded videos between pipelines (`webdist.py --reuse`); bump the cache key after replacing a video under the same name. `.org2slides-export` uploads the plain HTML + PDF next to the sources.

Without the include, any job boils down to:

```yaml
pages:
  image: debian:trixie-slim
  before_script:
    - apt-get update && apt-get install -y --no-install-recommends
      git ca-certificates curl emacs-nox python3 python3-cairosvg
      texlive-latex-extra texlive-fonts-extra texlive-pictures
      texlive-plain-generic texlive-bibtex-extra texlive-lang-german
      ffmpeg imagemagick ghostscript poppler-utils
    - git clone --depth 1 https://gitlab.example.com/you/org2slides.git /opt/org2slides
  script:
    - /opt/org2slides/org2slides --dist public *.org
  artifacts:
    paths: [public]
```
### GitHub Actions

```yaml
jobs:
  decks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get update && sudo apt-get install -y
          emacs-nox python3-cairosvg texlive-latex-extra texlive-fonts-extra
          texlive-pictures texlive-plain-generic texlive-bibtex-extra texlive-lang-german
          ffmpeg imagemagick
          ghostscript poppler-utils curl
      - run: git clone --depth 1 https://github.com/you/org2slides /opt/org2slides
      - run: /opt/org2slides/org2slides --dist public *.org
      - uses: actions/upload-pages-artifact@v3
        with: { path: public }
```

## Requirements

- `emacs-nox` (org ships with it; ox-reveal + htmlize are vendored in
  `vendor/`)
- `texlive-latex-extra texlive-fonts-extra texlive-pictures
  texlive-plain-generic texlive-bibtex-extra texlive-lang-german`
  (beamer, tikz, fontawesome5; babel-ngerman for
  `#+language: de` decks; ulem for org's default preamble;
  bibtex-extra only matters for custom themes that load biblatex)
- `python3` — plus `cairosvg` for vector SVG→PDF conversion
  (`python3-cairosvg`, or a `.venv/` in this repo or next to the deck;
  falls back to the deck's `.png` siblings without it)
- `ffmpeg` (poster frames, video re-encoding, media probing),
  `imagemagick` (crops, downscaling), `ghostscript` + `poppler-utils`
  (PDF compression), `curl` (reveal.js auto-download)

## Known limitations

- `<iframe>` embeds → `[Interactive: …]` placeholder.
- Videos → static poster-frame thumbnail.
- Inline colours (`<span style="color:…">`) → colour dropped.
- Layouts driven by CSS *classes* + `<style>` blocks (only inline
  `display:grid|flex` styles become columns; class-based layouts stack
  vertically).
