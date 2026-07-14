#!/usr/bin/env python3
"""Collect an exported reveal.js HTML deck into a self-contained dist folder,
shrinking media on the way -- so a CI pipeline can publish a minimal artifact
(GitLab Pages `public/`, artifact size limits).

    python3 webdist.py --dist public deck.html [deck2.html ...]

For every local file the HTML references (src/href/poster/data-src/
data-background-*) the file is copied into the dist folder under the same
relative path -- no rewriting needed. On the way:

  * raster images wider/taller than --max-img are downscaled (quality 85)
  * videos wider than --max-video are re-encoded (h264, --crf, aac 96k)
  * iframe'd local HTML (e.g. an interactive viewer) is scanned one level
    deep and its references are collected too
  * when the deck uses a local reveal.js (`revealjs/dist/...`), the theme
    fonts directory is copied as well (referenced from CSS, invisible to
    the HTML scan)

Files are only regenerated when the source is newer (safe to re-run; wire a
CI cache at the dist folder to skip re-encoding videos every pipeline).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
VIDEO_EXT = {"mp4", "webm", "mov", "m4v"}
# Attribute values may be quoted or bare (org's video macro emits
# `src= ./assets/x.mp4` -- unquoted, even with a space after the `=`).
REF_RE = re.compile(
    r"""(?:src|href|poster|data-src|data-background-image|data-background-video|data-background-iframe)
        \s*=\s*(?:["']([^"']+)["']|([^\s"'<>]+))""", re.IGNORECASE | re.VERBOSE)


def probe_width(path):
    """Pixel width of an image or video (None if it cannot be measured)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width", "-of", "csv=p=0", path],
            check=True, capture_output=True, text=True).stdout.strip()
        return int(out.splitlines()[0])
    except Exception:
        return None


def probe_kbps(path):
    """Overall bitrate of a video in kbit/s (None if it cannot be measured)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate",
             "-of", "csv=p=0", path],
            check=True, capture_output=True, text=True).stdout.strip()
        return int(out.splitlines()[0]) // 1000
    except Exception:
        return None


REUSE = False   # --reuse: trust existing dist files (CI cache; git checkouts
                # have fresh mtimes, so the mtime comparison never skips there)


def newer(src, dst):
    if REUSE and os.path.exists(dst):
        return False
    return not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src)


def put_image(src, dst, max_px):
    if not newer(src, dst):
        return
    w = probe_width(src)
    if w and w > max_px:
        subprocess.run(
            ["convert", src, "-resize", f"{max_px}x{max_px}>",
             "-strip", "-quality", "85", dst], check=True, capture_output=True)
        print(f"  img   {src}  ({w}px -> <= {max_px}px)")
    else:
        shutil.copy2(src, dst)


def put_video(src, dst, max_px, crf, max_kbps):
    """Re-encode when the video is wider than max_px OR fatter than max_kbps
    (an already-small-resolution but barely-compressed screen recording can
    be hundreds of MB); plain copy otherwise."""
    if not newer(src, dst):
        return
    w, kbps = probe_width(src), probe_kbps(src)
    if (w and w > max_px) or (kbps and kbps > max_kbps):
        print(f"  video {src}  ({w}px, {kbps or '?'} kbps -> <={max_px}px, crf {crf}) ...")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", src,
             "-vf", f"scale='min({max_px},iw)':-2",
             "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             "-c:a", "aac", "-b:a", "96k", dst], check=True)
    else:
        shutil.copy2(src, dst)


def collect(html_path, dist, args, seen):
    """Copy html_path and everything it references into dist."""
    base = os.path.dirname(os.path.abspath(html_path)) or "."
    rel_html = os.path.basename(html_path)
    os.makedirs(dist, exist_ok=True)
    shutil.copy2(html_path, os.path.join(dist, rel_html))
    content = open(html_path, encoding="utf-8", errors="replace").read()

    for quoted, bare in REF_RE.findall(content):
        ref = (quoted or bare).split("#")[0].split("?")[0].strip()
        if not ref or re.match(r"^(https?:)?//|^(data|mailto|javascript):", ref):
            continue
        rel = os.path.normpath(ref)
        if rel.startswith(".."):          # outside the deck directory -> leave alone
            continue
        src = os.path.join(base, rel)
        if not os.path.isfile(src) or rel in seen:
            continue
        seen.add(rel)
        dst = os.path.join(dist, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        if ext in IMG_EXT:
            put_image(src, dst, args.max_img)
        elif ext in VIDEO_EXT:
            put_video(src, dst, args.max_video, args.crf, args.max_kbps)
        elif ext in ("html", "htm"):      # iframe'd viewer: scan one level deep
            collect(src, dist, args, seen)
        else:                             # css / js / fonts / models ...
            shutil.copy2(src, dst)
        # CSS-referenced reveal theme fonts are invisible to the HTML scan.
        m = re.match(r"(.*?/dist)/theme/", rel.replace(os.sep, "/"))
        if m:
            fonts = os.path.join(base, m.group(1), "theme", "fonts")
            if os.path.isdir(fonts) and ("fonts:" + m.group(1)) not in seen:
                seen.add("fonts:" + m.group(1))
                shutil.copytree(fonts, os.path.join(dist, m.group(1), "theme", "fonts"),
                                dirs_exist_ok=True)


def dir_size(d):
    return sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(d) for f in fs)


def main():
    ap = argparse.ArgumentParser(
        description="Bundle exported reveal HTML + shrunken media into a dist folder.")
    ap.add_argument("html", nargs="+", help="exported deck HTML file(s)")
    ap.add_argument("--dist", required=True, help="output folder (e.g. public)")
    ap.add_argument("--max-img", type=int, default=1920,
                    help="max image width/height in px (default: %(default)s)")
    ap.add_argument("--max-video", type=int, default=1280,
                    help="max video width in px (default: %(default)s)")
    ap.add_argument("--crf", type=int, default=28,
                    help="h264 quality for re-encoded videos (default: %(default)s)")
    ap.add_argument("--max-kbps", type=int, default=2500,
                    help="re-encode videos above this bitrate even when the "
                         "resolution is fine (default: %(default)s)")
    ap.add_argument("--reuse", action="store_true",
                    help="keep existing files in the dist folder instead of "
                         "comparing mtimes (use with a CI cache; delete the "
                         "folder or bump the cache key after media changes)")
    args = ap.parse_args()
    global REUSE
    REUSE = args.reuse

    seen = set()
    for html in args.html:
        if not os.path.isfile(html):
            sys.exit(f"not found: {html}")
        print(f"collecting {html} -> {args.dist}/")
        collect(html, args.dist, args, seen)
    print(f"dist size: {dir_size(args.dist) / 1e6:.1f} MB ({args.dist}/)")


if __name__ == "__main__":
    main()
