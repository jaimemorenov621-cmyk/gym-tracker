"""Crea tools/rank_sources/campeon.png a partir del emblema de Diamante
(la imagen de referencia no trae Campeón): recoloreado carmesí y oro y con
"CAMPEÓN" en la placa del nombre. Si algún día hay un Campeón dibujado en el
mismo estilo, basta con dejarlo como tools/rank_sources/campeon.png."""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "rank_sources", "diamante.png")
OUT = os.path.join(HERE, "rank_sources", "campeon.png")
FONT = r"C:\Windows\Fonts\impact.ttf"

# Mapa de degradado por luminosidad: sombras carmesí, medios rojo, luces oro.
STOPS = [(0.0, (18, 0, 8)), (0.35, (88, 4, 34)), (0.62, (168, 16, 56)), (0.82, (222, 70, 96)), (0.93, (246, 196, 96)), (1.0, (255, 246, 210))]


def gradient_map(v):
    for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
        if v <= b:
            t = (v - a) / (b - a)
            return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))
    return STOPS[-1][1]


LUT = [gradient_map(i / 255) for i in range(256)]

src = Image.open(SRC).convert("RGBA")
S = 2
img = src.resize((src.width * S, src.height * S), Image.LANCZOS)
lum = img.convert("L")
r = lum.point([c[0] for c in LUT])
g = lum.point([c[1] for c in LUT])
b = lum.point([c[2] for c in LUT])
out = Image.merge("RGBA", (r, g, b, img.getchannel("A")))

# Placa del nombre (en coordenadas del emblema de 227 px).
x0, y0, x1, y1 = 46 * S, 44 * S, 182 * S, 77 * S
plate = Image.new("RGBA", out.size, (0, 0, 0, 0))
d = ImageDraw.Draw(plate)
d.rounded_rectangle([x0, y0, x1, y1], radius=8 * S, fill=(70, 4, 26, 255), outline=(240, 190, 80, 255), width=2 * S)
out.alpha_composite(plate)
shine = Image.new("RGBA", out.size, (0, 0, 0, 0))  # brillo suave arriba, en su propia capa
sd = ImageDraw.Draw(shine)
for i in range(22):
    sd.line([(x0 + 5 * S, y0 + 3 * S + i), (x1 - 5 * S, y0 + 3 * S + i)], fill=(255, 130, 160, max(0, 70 - i * 3)))
out.alpha_composite(shine)

font = ImageFont.truetype(FONT, 25 * S)
text = "CAMPEÓN"
txt = Image.new("RGBA", out.size, (0, 0, 0, 0))
td = ImageDraw.Draw(txt)
tw = td.textlength(text, font=font)
tx, ty = (x0 + x1) / 2 - tw / 2, y0 + 1 * S
td.text((tx, ty + 2 * S), text, font=font, fill=(0, 0, 0, 160))          # sombra
td.text((tx, ty), text, font=font, fill=(255, 226, 140, 255), stroke_width=1 * S, stroke_fill=(110, 50, 0, 255))
out.alpha_composite(txt.filter(ImageFilter.GaussianBlur(0.3)))

out = out.resize(src.size, Image.LANCZOS)
out.save(OUT)
print("ok", OUT)
