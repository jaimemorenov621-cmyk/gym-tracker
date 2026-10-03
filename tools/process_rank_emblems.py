"""Procesa los emblemas de rango ya generados (no dibuja ni retoca el arte).

Entrada:  assets_src/ranks/<slug>.png  (uno por rango)
Salida:   app/static/ranks/rank-<slug>-512.webp, rank-<slug>.webp (256),
          rank-<slug>-128.webp y rank-<slug>.png (512, reserva)

Pasos:
1. Fondo: si el PNG ya trae transparencia se respeta. Si no, se usa rembg
   si está instalado; si no, se quita un fondo LISO por relleno desde los
   bordes (tolerancia de color), y se avisa si el resultado es dudoso.
2. Bordes: se elimina el contagio de color del fondo en los píxeles
   semitransparentes (sin halo) y se suaviza 1 px el alfa (sin dientes).
3. Recorte al contenido y centrado en lienzo cuadrado con el MISMO margen
   para todos, así escalan igual.
4. Exportación WebP (512/256/128) + PNG de reserva; informe de tamaños.

Uso: python tools/process_rank_emblems.py [--src assets_src/ranks] [--only slug]
"""
import argparse
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUGS = ["hierro", "bronce", "plata", "oro", "platino", "diamante", "esmeralda", "campeon", "titan"]
CANVAS = 512
FILL = 0.9          # el lado mayor del emblema ocupa el 90 % del lienzo
SIZES = {512: "-512", 256: "", 128: "-128"}
TOLERANCE = 38      # distancia de color para el fondo liso (0-441)


def has_real_alpha(im):
    if im.mode != "RGBA":
        return False
    lo, _ = im.getchannel("A").getextrema()
    return lo < 250


def border_color(im):
    """Color medio del borde: el fondo liso."""
    rgb = im.convert("RGB")
    w, h = rgb.size
    px = [rgb.getpixel((x, y)) for x in range(0, w, 4) for y in (0, h - 1)]
    px += [rgb.getpixel((x, y)) for y in range(0, h, 4) for x in (0, w - 1)]
    return tuple(sum(c[i] for c in px) // len(px) for i in range(3))


def remove_flat_background(im):
    """Fondo liso fuera: relleno desde los bordes por similitud de color y,
    en la franja del borde, separación de la mezcla emblema/fondo (alfa y
    color reales), para que no quede halo del color del fondo."""
    rgb = im.convert("RGB")
    bg = border_color(rgb)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg)).convert("L")
    mask = diff.point(lambda v: 0 if v < TOLERANCE else 255)
    w, h = mask.size
    for x in range(0, w, 3):
        for y in (0, h - 1):
            if mask.getpixel((x, y)) == 0:
                ImageDraw.floodfill(mask, (x, y), 128)
    for y in range(0, h, 3):
        for x in (0, w - 1):
            if mask.getpixel((x, y)) == 0:
                ImageDraw.floodfill(mask, (x, y), 128)
    alpha = mask.point(lambda v: 0 if v == 128 else 255)
    # Color "puro" del emblema cerca del borde: media del interior (lejos
    # del fondo) en un radio de unos píxeles.
    interior = alpha.filter(ImageFilter.MinFilter(9))
    blur = 5
    num = Image.composite(rgb, Image.new("RGB", rgb.size), interior).filter(ImageFilter.BoxBlur(blur))
    den = interior.filter(ImageFilter.BoxBlur(blur))
    band = ImageChops.subtract(alpha, interior)
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    op, bp, np_, dp, ap = out.load(), band.load(), num.load(), den.load(), alpha.load()
    for y in range(h):
        for x in range(w):
            if not bp[x, y]:
                continue
            d = dp[x, y]
            r, g, b, _ = op[x, y]
            if d < 8:  # sin interior cerca: se deja como está
                continue
            f = tuple(min(255, c * 255 // d) for c in np_[x, y])
            fb = [f[i] - bg[i] for i in range(3)]
            pb = [(r, g, b)[i] - bg[i] for i in range(3)]
            norm = sum(v * v for v in fb) or 1
            k = max(0.0, min(1.0, sum(pb[i] * fb[i] for i in range(3)) / norm))
            if k < 0.04:
                op[x, y] = (0, 0, 0, 0)
                continue
            col = tuple(max(0, min(255, round(((r, g, b)[i] - bg[i] * (1 - k)) / k))) for i in range(3))
            op[x, y] = col + (round(255 * k),)
    return out, bg


def remove_background(im):
    if has_real_alpha(im):
        return im.convert("RGBA"), None, "transparencia original"
    try:
        from rembg import remove  # opcional
        return remove(im.convert("RGBA")), None, "rembg"
    except ImportError:
        out, bg = remove_flat_background(im)
        return out, bg, f"fondo liso {bg}"


def defringe(im, bg):
    """Borde: fuera el píxel más externo (donde más fondo queda mezclado) y
    un suavizado mínimo del alfa, sin dientes."""
    im = im.convert("RGBA")
    a = im.getchannel("A")
    hard = a.filter(ImageFilter.MinFilter(3))
    soft = ImageChops.darker(a, hard.filter(ImageFilter.GaussianBlur(0.7)))
    im.putalpha(soft)
    return im


def square(im):
    bbox = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    im = im.crop(bbox)
    scale = CANVAS * FILL / max(im.size)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((CANVAS - im.width) // 2, (CANVAS - im.height) // 2))
    return canvas, scale


def process(slug, src_dir, out_dir):
    path = os.path.join(src_dir, f"{slug}.png")
    if not os.path.exists(path):
        return f"{slug}: FALTA {path}"
    im = Image.open(path)
    cut, bg, how = remove_background(im)
    cut = defringe(cut, bg)
    sq, scale = square(cut)
    notes = [how]
    if scale > 1.05:
        notes.append(f"AVISO: origen pequeño, ampliado x{scale:.2f} (se verá blando a 512)")
    sizes = []
    for px, suffix in SIZES.items():
        img = sq if px == CANVAS else sq.resize((px, px), Image.LANCZOS)
        out = os.path.join(out_dir, f"rank-{slug}{suffix}.webp")
        img.save(out, "WEBP", quality=88, method=6, alpha_quality=90)
        kb = os.path.getsize(out) / 1024
        sizes.append(f"{px}px {kb:.0f} KB" + (" (>60 KB)" if px == 256 and kb > 60 else ""))
    sq.save(os.path.join(out_dir, f"rank-{slug}.png"), optimize=True)
    return f"{slug}: {', '.join(sizes)} · {'; '.join(notes)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "assets_src", "ranks"))
    ap.add_argument("--out", default=os.path.join(ROOT, "app", "static", "ranks"))
    ap.add_argument("--only")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for slug in ([args.only] if args.only else SLUGS):
        print(process(slug, args.src, args.out))


if __name__ == "__main__":
    sys.exit(main())
