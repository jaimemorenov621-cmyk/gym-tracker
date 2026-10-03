"""Recorta los emblemas de la imagen de referencia de Jaime (1024x559, dos
filas de cuatro) y les quita el fondo: tools/rank_sources/<rango>.png.
Uso: python tools/cut_rank_sources.py <imagen.jpg>"""
import colorsys
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

SRC = sys.argv[1]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rank_sources")
os.makedirs(OUT, exist_ok=True)

im = Image.open(SRC).convert("RGB")
W, H = im.size
CELLS = {
    "hierro": (0, 22, 256, 250), "bronce": (256, 22, 512, 250), "plata": (512, 22, 768, 243), "oro": (768, 22, 1024, 250),
    "platino": (0, 288, 256, 505), "diamante": (256, 288, 512, 512), "esmeralda": (512, 288, 768, 512), "titan": (768, 288, 1024, 512),
}


def fg_mask(crop, lum_t, sat_t):
    w, h = crop.size
    px = crop.load()
    m = Image.new("L", (w, h), 0)
    mp = m.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            hh, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum > lum_t or (s > sat_t and lum > 40):
                mp[x, y] = 255
    return m


OPEN = 9
CLOSE = 9
# (centro x, centro y, radio x, radio y) en fracción de la celda
ELLIPSE = {"hierro": (0.54, 0.52, 0.33, 0.52), "esmeralda": (0.5, 0.5, 0.40, 0.56), "bronce": (0.5, 0.5, 0.44, 0.56),
           "plata": (0.5, 0.5, 0.42, 0.56), "platino": (0.5, 0.5, 0.42, 0.56), "oro": (0.5, 0.5, 0.45, 0.56),
           "diamante": (0.5, 0.5, 0.45, 0.56), "titan": (0.5, 0.5, 0.46, 0.56)}


def cutout(name, box, lum_t=62, sat_t=0.35):
    crop = im.crop(box)
    w, h = crop.size
    raw = fg_mask(crop, lum_t, sat_t)
    m = raw.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))   # cerrar huecos pequeños
    # apertura grande: elimina barras finas y bordes de la pared pegados
    opened = m.filter(ImageFilter.MinFilter(OPEN)).filter(ImageFilter.MaxFilter(OPEN))
    grown = opened.filter(ImageFilter.MaxFilter(5))
    from PIL import ImageChops
    m = ImageChops.multiply(m, grown)
    # cierre grande: tapa los huecos del borde para que el fondo no "entre"
    # al interior oscuro del escudo (el interior es parte del emblema)
    m = m.filter(ImageFilter.MaxFilter(CLOSE)).filter(ImageFilter.MinFilter(CLOSE))
    # fondo = lo oscuro conectado con el borde
    for x in range(0, w, 3):
        for y in (0, h - 1):
            if m.getpixel((x, y)) == 0:
                ImageDraw.floodfill(m, (x, y), 100)
    for y in range(0, h, 3):
        for x in (0, w - 1):
            if m.getpixel((x, y)) == 0:
                ImageDraw.floodfill(m, (x, y), 100)
    # huecos interiores -> emblema
    m = m.point(lambda v: 0 if v == 100 else 255)
    # quedarse con la pieza central (semilla: el píxel de emblema más cercano al centro)
    seed = min(((x, y) for y in range(h // 3, 2 * h // 3, 2) for x in range(w // 3, 2 * w // 3, 2)
                if m.getpixel((x, y)) == 255), key=lambda q: (q[0] - w // 2) ** 2 + (q[1] - h // 2) ** 2)
    ImageDraw.floodfill(m, seed, 200)
    m = m.point(lambda v: 255 if v == 200 else 0)
    # Interior del escudo: relleno fila a fila del "cuerpo" (máscara muy
    # abierta), encogido para no tapar los huecos entre laurel y escudo.
    body = m.filter(ImageFilter.MinFilter(15)).filter(ImageFilter.MaxFilter(15))
    interior = Image.new("L", (w, h), 0)
    bp, ip = body.load(), interior.load()
    for y in range(h):
        xs = [x for x in range(w) if bp[x, y]]
        if xs:
            for x in range(xs[0], xs[-1] + 1):
                ip[x, y] = 255
    interior = interior.filter(ImageFilter.MinFilter(9))
    m = ImageChops.lighter(m, interior)
    # Recorte elíptico por emblema: quita barras y luces que sobresalen.
    ex = ELLIPSE.get(name)
    if ex:
        cx, cy, rx, ry = ex
        ell = Image.new("L", (w, h), 0)
        ImageDraw.Draw(ell).ellipse([w * (cx - rx), h * (cy - ry), w * (cx + rx), h * (cy + ry)], fill=255)
        m = ImageChops.multiply(m, ell)
    alpha = m.filter(ImageFilter.GaussianBlur(1.2))
    rgba = crop.convert("RGBA")
    rgba.putalpha(alpha)
    bbox = m.getbbox()
    rgba = rgba.crop(bbox)
    # lienzo cuadrado con margen
    side = max(rgba.size) + 12
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(rgba, ((side - rgba.size[0]) // 2, (side - rgba.size[1]) // 2), rgba)
    canvas.save(os.path.join(OUT, f"{name}.png"))
    return canvas


tiles = []
PARAMS = {"hierro": (44, 0.30), "bronce": (70, 0.28), "plata": (76, 0.35), "oro": (85, 0.30),
          "platino": (72, 0.35), "diamante": (105, 0.35), "esmeralda": (60, 0.30), "titan": (52, 0.30)}
for name, box in CELLS.items():
    tiles.append((name, cutout(name, box, *PARAMS[name])))

print("ok", [t.size for _, t in tiles])
