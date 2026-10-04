"""Prerenderiza los emblemas SVG de app/static/ranks/ a WebP (512, 256 y 128
px) para la app: pintar una veintena de SVG con filtros en cada cambio de
pestaña costaba en el móvil; un WebP pequeño se decodifica en nada.

Usa Edge o Chrome sin interfaz (ya instalados en el equipo; no descarga nada)
para que el resultado sea idéntico a como el navegador pinta el SVG.

Uso: python tools/rasterize_rank_emblems.py   (después de make_rank_emblems.py)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RANKS = ROOT / "app" / "static" / "ranks"
SIZES = (512, 256, 128)
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


def browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    sys.exit("No encuentro Edge ni Chrome para prerenderizar los emblemas.")


def render(exe, workdir, svg, out_png, size=512):
    page = workdir / f"{svg.stem}.html"
    page.write_text(
        f'<!doctype html><html><body style="margin:0;background:transparent">'
        f'<img src="{svg.as_uri()}" width="{size}" height="{size}" style="display:block"></body></html>',
        encoding="utf-8")
    subprocess.run([
        exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
        "--default-background-color=00000000", f"--window-size={size},{size}",
        f"--user-data-dir={workdir / 'profile'}", f"--screenshot={out_png}", page.as_uri(),
    ], check=True, capture_output=True, timeout=60)
    # En Windows el lanzador de Edge vuelve antes de que el proceso real
    # escriba la captura: se espera a que el archivo exista y no crezca.
    last = -1
    for _ in range(150):
        if out_png.exists() and out_png.stat().st_size == last and last > 0:
            return
        last = out_png.stat().st_size if out_png.exists() else -1
        time.sleep(0.1)
    sys.exit(f"{svg.name}: el navegador no generó la captura")


def main():
    exe = browser()
    svgs = sorted(RANKS.glob("*.svg"))
    if len(sys.argv) > 1:
        svgs = [s for s in svgs if s.stem in sys.argv[1:]]
    total = 0
    workdir = Path(tempfile.mkdtemp(prefix="gyre-emblems-"))
    try:
        for svg in svgs:
            png = workdir / f"{svg.stem}.png"
            render(exe, workdir, svg, png)
            im = Image.open(png).convert("RGBA")
            if im.getchannel("A").getextrema()[0] == 255:
                sys.exit(f"{svg.name}: el navegador no devolvió fondo transparente")
            for size in SIZES:
                img = im if size == 512 else im.resize((size, size), Image.LANCZOS)
                out = RANKS / f"{svg.stem}-{size}.webp"
                img.save(out, "WEBP", quality=86, method=6, alpha_quality=90)
                total += out.stat().st_size
            print(svg.stem, "ok")
    finally:
        time.sleep(1)  # que Edge suelte su perfil antes de borrarlo
        shutil.rmtree(workdir, ignore_errors=True)
    print(f"{len(svgs)} emblemas, {round(total / 1024)} KB en WebP")


if __name__ == "__main__":
    main()
