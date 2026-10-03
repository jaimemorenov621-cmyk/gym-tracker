"""Emblemas de rango: app/static/ranks/<rango>-<división>.webp (y titan.webp).

Parten de los emblemas de referencia de Jaime, recortados sin fondo en
tools/rank_sources/<rango>.png (cut_rank_sources.py; Campeón: make_campeon_source.py).
Cada división mejora el emblema de su rango:
  I    el emblema con sombra
  II   + resplandor del color del rango + 2 estrellas
  III  + rayos de luz detrás, aura intensa, filo de luz en el contorno,
         destellos + 3 estrellas
Titán (sin divisiones) lleva siempre el tratamiento máximo.

Ejecutar: python tools/make_rank_emblems.py
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "rank_sources")
OUT = os.path.join(os.path.dirname(HERE), "app", "static", "ranks")
SIZE = 320          # lienzo final
EMBLEM = 236        # lado máximo del emblema dentro del lienzo
SS = 3              # supersampling para estrellas y destellos

GLOW = {
    "hierro": (170, 178, 190), "bronce": (235, 150, 90), "plata": (120, 190, 255), "oro": (255, 200, 60),
    "platino": (140, 210, 255), "diamante": (160, 205, 255), "esmeralda": (60, 225, 140),
    "campeon": (255, 70, 120), "titan": (255, 120, 30),
}
RANKS = ["hierro", "bronce", "plata", "oro", "platino", "diamante", "esmeralda", "campeon", "titan"]


def load_emblem(key):
    im = Image.open(os.path.join(SRC, f"{key}.png")).convert("RGBA")
    im = im.crop(im.getbbox())
    scale = EMBLEM / max(im.size)
    return im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)


def place(emblem, dy=-10):
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    layer.alpha_composite(emblem, ((SIZE - emblem.width) // 2, (SIZE - emblem.height) // 2 + dy))
    return layer


def tinted(alpha, color, opacity):
    layer = Image.new("RGBA", (SIZE, SIZE), color + (0,))
    layer.putalpha(alpha.point(lambda v: round(v * opacity)))
    return layer


def rays(color, n=16, opacity=0.38):
    big = Image.new("L", (SIZE * SS, SIZE * SS), 0)
    d = ImageDraw.Draw(big)
    c = SIZE * SS / 2
    r = SIZE * SS * 0.5
    for i in range(n):
        a0 = 2 * math.pi * i / n
        a1 = a0 + math.pi / n * 0.55
        d.polygon([(c, c), (c + r * math.cos(a0), c + r * math.sin(a0)), (c + r * math.cos(a1), c + r * math.sin(a1))], fill=255)
    mask = big.resize((SIZE, SIZE), Image.LANCZOS)
    # se desvanecen hacia fuera
    fade = Image.radial_gradient("L").resize((SIZE, SIZE)).point(lambda v: 255 - v)
    mask = ImageChops.multiply(mask, fade)
    return tinted(mask, color, opacity)


def star_layer(count, y, size=15):
    big = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    gap = size * 2.1
    for k in range(count):
        cx = (SIZE / 2 + (k - (count - 1) / 2) * gap) * SS
        cy = y * SS
        pts = []
        for i in range(10):
            rr = (size if i % 2 == 0 else size * 0.45) * SS
            a = -math.pi / 2 + math.pi * i / 5
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, fill=(255, 205, 70, 255), outline=(120, 70, 0, 255), width=2 * SS)
        d.polygon([(cx, cy - size * SS * 0.8), (cx + size * SS * 0.25, cy - size * SS * 0.1), (cx, cy)], fill=(255, 245, 200, 200))
    return big.resize((SIZE, SIZE), Image.LANCZOS)


def sparkles(points):
    big = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    for x, y, r in points:
        x, y, r = x * SS, y * SS, r * SS
        d.polygon([(x, y - r), (x + r * .18, y - r * .18), (x + r, y), (x + r * .18, y + r * .18), (x, y + r),
                   (x - r * .18, y + r * .18), (x - r, y), (x - r * .18, y - r * .18)], fill=(255, 255, 255, 240))
    return big.resize((SIZE, SIZE), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.4))


def build(key, div):
    emblem = place(load_emblem(key))
    alpha = emblem.getchannel("A")
    color = GLOW[key]
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    top = key == "titan" or div == 3
    if top:
        canvas.alpha_composite(rays(color))
    if div >= 2 or key == "titan":
        glow = tinted(alpha.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(16)), color, 0.95 if top else 0.6)
        canvas.alpha_composite(glow)
    # sombra
    shadow = tinted(alpha.filter(ImageFilter.GaussianBlur(5)), (0, 0, 0), 0.45)
    canvas.alpha_composite(shadow, (0, 4))
    canvas.alpha_composite(emblem)
    if top:  # filo de luz en el contorno
        edge = ImageChops.subtract(alpha, alpha.filter(ImageFilter.MinFilter(5)))
        canvas.alpha_composite(tinted(edge.filter(ImageFilter.GaussianBlur(1)), (255, 255, 255), 0.55))
        canvas.alpha_composite(sparkles([(52, 64, 13), (270, 76, 10), (40, 196, 9), (282, 206, 12), (160, 22, 9)]))
    if key != "titan":
        canvas.alpha_composite(star_layer(div, SIZE - 30))
    return canvas


os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.endswith((".svg", ".webp", ".png")):
        os.remove(os.path.join(OUT, f))
total = 0
for key in RANKS:
    for div in ((3,) if key == "titan" else (1, 2, 3)):
        name = "titan" if key == "titan" else f"{key}-{div}"
        path = os.path.join(OUT, f"{name}.webp")
        build(key, div).save(path, "WEBP", quality=90, method=6)
        total += os.path.getsize(path)
print("ok", len(os.listdir(OUT)), "emblemas,", round(total / 1024), "KB en total")
