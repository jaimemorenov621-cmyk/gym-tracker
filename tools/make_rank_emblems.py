"""Emblemas de rango: app/static/ranks/<rango>-<división>.svg (y titan.svg).

Cada rango es un escudo histórico del material de su rango, con un elemento
de gimnasio integrado:
  Hierro     escudo celta de la Edad de Hierro; el umbo es un disco
  Bronce     hoplon griego con meandro; halteres (las pesas griegas) en
             estilo de figuras rojas
  Plata      scutum romano con alas y rayos de Júpiter; umbo-disco
  Oro        Egipto: sol alado (un disco) en oro y lapislázuli
  Platino    heráldica medieval: una "barra" que es una barra con discos,
             y roeles (discos) sobre campo adamascado
  Diamante   tarja renacentista; diamante talla brillante sobre mancuernas
  Esmeralda  chimalli azteca: mosaico, greca escalonada, plumas de quetzal
  Campeón    escudo español carmesí; barra dentro de la corona de olivo
             olímpica (kotinos)
  Titán      la bóveda celeste de Atlas: esfera armilar en torno a un disco,
             corona radiada
Divisiones: I escudo + cinta con el numeral; II + ramas de laurel;
III + corona de laurel completa, corona y halo.

Ejecutar: python tools/make_rank_emblems.py
"""
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "app", "static", "ranks")
CX, CY = 128, 120


def n(x):
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


METALS = {
    "iron": ["#a7afb8", "#565d66", "#24282d", "#717983", "#ccd3da", "#2a2e33"],
    "bronze": ["#f6c08a", "#a8622b", "#5a2d0f", "#bd7a3e", "#ffd9ab", "#5a2d0f"],
    "silver": ["#ffffff", "#bcc4cd", "#6c7581", "#d2d9e0", "#ffffff", "#78818c"],
    "gold": ["#fff3bf", "#e4b23a", "#8a5a0c", "#d99d26", "#fff6cc", "#7a4d08"],
    "platinum": ["#ffffff", "#d3e2ec", "#7d95a6", "#dbe8f0", "#ffffff", "#869db0"],
    "steelblue": ["#eef8ff", "#93badb", "#2d4d76", "#a9cbe8", "#ffffff", "#34557e"],
    "darkbronze": ["#ffcf73", "#b0671c", "#3a1a06", "#8a4a14", "#ffc36b", "#2a1204"],
}


class Doc:
    def __init__(self, seed):
        self.defs = []
        self.k = 0
        self.rng = random.Random(seed)

    def uid(self, p):
        self.k += 1
        return f"{p}{self.k}"

    def _stops(self, stops):
        out = []
        for st in stops:
            o, c = st[0], st[1]
            a = st[2] if len(st) > 2 else 1
            out.append(f'<stop offset="{o}" stop-color="{c}"' + (f' stop-opacity="{a}"' if a != 1 else "") + "/>")
        return "".join(out)

    def lin(self, stops, x1=0, y1=0, x2=1, y2=1):
        i = self.uid("l")
        self.defs.append(f'<linearGradient id="{i}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{self._stops(stops)}</linearGradient>')
        return f"url(#{i})"

    def rad(self, stops, cx=0.4, cy=0.35, r=0.75):
        i = self.uid("r")
        self.defs.append(f'<radialGradient id="{i}" cx="{cx}" cy="{cy}" r="{r}">{self._stops(stops)}</radialGradient>')
        return f"url(#{i})"

    def metal(self, name, x2=1, y2=1):
        c = METALS[name]
        return self.lin(list(zip([0, 0.22, 0.45, 0.62, 0.8, 1], c)), 0, 0, x2, y2)

    def soft(self, name, x2=0, y2=1):
        c = METALS[name]
        return self.lin([(0, c[4]), (0.5, c[1]), (1, c[2])], 0, 0, x2, y2)

    def clip(self, d):
        i = self.uid("c")
        self.defs.append(f'<clipPath id="{i}"><path d="{d}"/></clipPath>')
        return f"url(#{i})"

    def svg(self, body):
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
                '<defs><filter id="ds" x="-20%" y="-20%" width="140%" height="140%">'
                '<feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#000" flood-opacity=".45"/></filter>'
                + "".join(self.defs) + "</defs>" + body + "</svg>")


def inset(s, cx=CX, cy=CY):
    return f'transform="translate({cx} {cy}) scale({s}) translate({-cx} {-cy})"'


def emboss(content, fill, d=1.2, light=0.35, dark=0.5):
    """Relieve: sombra abajo-derecha, luz arriba-izquierda y el relleno."""
    return (f'<g transform="translate({d} {d * 1.2})" fill="#000" opacity="{dark}">{content}</g>'
            f'<g transform="translate({-d * 0.6} {-d * 0.7})" fill="#fff" opacity="{light}">{content}</g>'
            f'<g fill="{fill}">{content}</g>')


def engrave(path_d, color, w=1.6, light="#fff", lo=0.35):
    """Línea grabada: surco oscuro con filo de luz debajo."""
    return (f'<path d="{path_d}" fill="none" stroke="{light}" stroke-opacity="{lo}" stroke-width="{w}" '
            f'stroke-linecap="round" stroke-linejoin="round" transform="translate(.6 .8)"/>'
            f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>')


def shadowed(body, dx=1, dy=2, op=0.45):
    """Sombra plana de un grupo de rectángulos (mismas formas en negro)."""
    shadow = body.replace("fill=", "data-f=").replace("<rect ", '<rect fill="#000" ')
    return f'<g transform="translate({dx} {dy})" opacity="{op}">{shadow}</g>{body}'


def shield_base(doc, d, rim, field, s=0.88, cy=CY):
    bevel = doc.lin([(0, "#000", 0.6), (0.5, "#000", 0.1), (1, "#fff", 0.45)], 0, 0, 0, 1)
    return (f'<path d="{d}" fill="{rim}" filter="url(#ds)"/>'
            f'<path d="{d}" fill="none" stroke="#000" stroke-opacity=".55" stroke-width="1.4"/>'
            f'<g {inset(s, cy=cy)}><path d="{d}" fill="{field}"/>'
            f'<path d="{d}" fill="none" stroke="{bevel}" stroke-width="3.2"/></g>')


def specular(doc, d, cx=96, cy=64, rx=90, ry=62, op=0.5):
    g = doc.rad([(0, "#fff", op), (0.6, "#fff", op * 0.25), (1, "#fff", 0)], 0.5, 0.5, 0.5)
    return f'<g clip-path="{doc.clip(d)}"><ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{g}"/></g>'


def polar(cx, cy, r, deg):
    """Ángulo en grados desde arriba, en sentido horario."""
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def circle_d(cx, cy, r):
    return f"M{n(cx - r)} {n(cy)}a{n(r)} {n(r)} 0 1 0 {n(2 * r)} 0a{n(r)} {n(r)} 0 1 0 {n(-2 * r)} 0Z"


def ellipse_d(cx, cy, rx, ry):
    return f"M{n(cx - rx)} {n(cy)}a{n(rx)} {n(ry)} 0 1 0 {n(2 * rx)} 0a{n(rx)} {n(ry)} 0 1 0 {n(-2 * rx)} 0Z"


def poly(pts):
    return "M" + " L".join(f"{n(x)} {n(y)}" for x, y in pts)


def star_path(cx, cy, r_out, r_in, points):
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        pts.append(polar(cx, cy, r, i * 180 / points))
    return poly(pts) + "Z"


# ------------------------------------------------------------ gimnasio
def plate(doc, cx, cy, r, metal="iron", hub=None, face=None):
    """Disco con agarres (tres ventanas), aro, buje y agujero."""
    g = doc.metal(metal)
    c = METALS[metal]
    face = face or doc.rad([(0, c[4]), (0.55, c[1]), (1, c[2])], 0.38, 0.32, 0.8)
    out = [f'<circle cx="{n(cx)}" cy="{n(cy + 1.5)}" r="{n(r)}" fill="#000" opacity=".45"/>',
           f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(r)}" fill="{g}"/>',
           f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(r * 0.88)}" fill="{face}"/>',
           f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(r * 0.88)}" fill="none" stroke="#000" stroke-opacity=".35" stroke-width="{n(max(0.8, r * 0.04))}"/>']
    for k in range(3):
        a0, a1 = 90 + 120 * k - 24, 90 + 120 * k + 24
        r0, r1 = r * 0.5, r * 0.72
        p0, p1 = polar(cx, cy, r1, a0), polar(cx, cy, r1, a1)
        p2, p3 = polar(cx, cy, r0, a1), polar(cx, cy, r0, a0)
        d = (f"M{n(p0[0])} {n(p0[1])}A{n(r1)} {n(r1)} 0 0 1 {n(p1[0])} {n(p1[1])}"
             f"L{n(p2[0])} {n(p2[1])}A{n(r0)} {n(r0)} 0 0 0 {n(p3[0])} {n(p3[1])}Z")
        out.append(f'<path d="{d}" fill="#0b0b0e" opacity=".82" stroke="#000" stroke-opacity=".4" stroke-width="{n(r * 0.05)}" stroke-linejoin="round"/>')
        out.append(f'<path d="{d}" fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="{n(r * 0.03)}" transform="translate(.4 .6)" stroke-linejoin="round"/>')
    out.append(f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(r * 0.33)}" fill="{hub or g}" stroke="#000" stroke-opacity=".45" stroke-width="{n(max(0.6, r * 0.03))}"/>')
    out.append(f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(r * 0.13)}" fill="#0c0c0f"/>')
    out.append(f'<path d="M{n(cx - r * 0.62)} {n(cy - r * 0.42)}A{n(r * 0.75)} {n(r * 0.75)} 0 0 1 {n(cx + r * 0.2)} {n(cy - r * 0.74)}" '
               f'fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="{n(r * 0.06)}" stroke-linecap="round"/>')
    return "".join(out)


def _rect(x0, x1, hh, fill, rx=1.5):
    x0, x1 = sorted((x0, x1))
    return (f'<rect x="{n(x0)}" y="{n(-hh / 2)}" width="{n(x1 - x0)}" height="{n(hh)}" rx="{n(rx)}" '
            f'fill="{fill}" stroke="#000" stroke-opacity=".5" stroke-width=".8"/>')


def dumbbell(doc, cx, cy, L, angle, metal="iron", plate_fill=None):
    m = doc.metal(metal, 0, 1)
    pf = plate_fill or doc.soft(metal)
    parts = [_rect(-L * 0.3, L * 0.3, L * 0.07, m, L * 0.035)]
    for s in (-1, 1):
        parts.append(_rect(s * L * 0.27, s * L * 0.355, L * 0.36, pf, 2))
        parts.append(_rect(s * L * 0.355, s * L * 0.43, L * 0.28, pf, 2))
        parts.append(_rect(s * L * 0.43, s * L * 0.47, L * 0.1, m, 1))
    return f'<g transform="translate({n(cx)} {n(cy)}) rotate({angle})">{shadowed("".join(parts))}</g>'


def barbell(doc, cx, cy, L, angle, metal="iron", plate_fill=None):
    m = doc.metal(metal, 0, 1)
    pf = plate_fill or doc.soft(metal)
    parts = [_rect(-L * 0.5, L * 0.5, L * 0.028, m, 1)]
    for s in (-1, 1):
        parts.append(_rect(s * L * 0.29, s * L * 0.5, L * 0.045, m, 1))
        parts.append(_rect(s * L * 0.285, s * L * 0.305, L * 0.08, m, 1))
        parts.append(_rect(s * L * 0.31, s * L * 0.36, L * 0.38, pf, 2.2))
        parts.append(_rect(s * L * 0.362, s * L * 0.405, L * 0.3, pf, 2))
        parts.append(_rect(s * L * 0.407, s * L * 0.44, L * 0.22, pf, 1.8))
    return f'<g transform="translate({n(cx)} {n(cy)}) rotate({angle})">{shadowed("".join(parts))}</g>'


# ------------------------------------------------------------ adornos
def cubic(p0, p1, p2, p3, t):
    u = 1 - t
    x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
    y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
    dx = 3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0])
    dy = 3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1])
    return x, y, math.degrees(math.atan2(dy, dx))


def leaf(size, fill, rot=0):
    w = size * 0.46
    return (f'<g transform="rotate({n(rot)})"><path d="M0 0C{n(size * 0.25)} {n(-w)} {n(size * 0.75)} {n(-w)} {n(size)} 0C{n(size * 0.75)} {n(w * 0.8)} {n(size * 0.25)} {n(w * 0.8)} 0 0Z" '
            f'fill="{fill}" stroke="#000" stroke-opacity=".5" stroke-width=".7"/>'
            f'<path d="M1 0L{n(size * 0.85)} {n(-w * 0.1)}" stroke="#000" stroke-opacity=".3" stroke-width=".6"/></g>')


def laurel(doc, metal, extent):
    """Dos ramas de laurel que salen de la cinta y suben por los lados."""
    fill = doc.soft(metal, 1, 1)
    out = []
    for side in (-1, 1):
        p = [(CX + side * 40, 222), (CX + side * 98, 224), (CX + side * 116, 150), (CX + side * 92, 58)]
        pts = [cubic(*p, i / 40) for i in range(int(40 * extent) + 1)]
        out.append(f'<path d="{poly((x, y) for x, y, _ in pts)}" fill="none" stroke="{METALS[metal][2]}" stroke-width="2.4" stroke-linecap="round"/>')
        steps = int(18 * extent)
        for i in range(1, steps + 1):
            x, y, ang = cubic(*p, i / 18)
            size = 18 - 6 * i / 18
            out.append(f'<g transform="translate({n(x)} {n(y)})">{leaf(size, fill, ang - 42)}{leaf(size, fill, ang + 42)}</g>')
        x, y, ang = cubic(*p, steps / 18)
        out.append(f'<g transform="translate({n(x)} {n(y)})">{leaf(13, fill, ang)}</g>')
    return "".join(out)


def coronet(doc, metal, gem, top):
    """Corona heráldica sobre el escudo (división III)."""
    m = doc.metal(metal, 0, 1)
    y0 = top - 2
    pts = []
    for i, x in enumerate([102, 115, 128, 141, 154]):
        h = 22 if i == 2 else (15 if i in (1, 3) else 11)
        pts.append(f'<path d="M{x - 5} {n(y0 - 9)}L{x} {n(y0 - 9 - h)}L{x + 5} {n(y0 - 9)}Z" fill="{m}" stroke="#000" stroke-opacity=".5" stroke-width=".9"/>'
                   f'<circle cx="{x}" cy="{n(y0 - 9 - h)}" r="{3.2 if i == 2 else 2.4}" fill="{m}" stroke="#000" stroke-opacity=".5" stroke-width=".8"/>')
    band = f'<path d="M98 {n(y0)}L158 {n(y0)}L156 {n(y0 - 9)}L100 {n(y0 - 9)}Z" fill="{m}" stroke="#000" stroke-opacity=".55" stroke-width="1"/>'
    g = doc.rad([(0, "#fff"), (0.35, gem[0]), (1, gem[1])], 0.35, 0.3, 0.8)
    gems = (f'<ellipse cx="128" cy="{n(y0 - 4.5)}" rx="5" ry="3.6" fill="{g}" stroke="#000" stroke-opacity=".5" stroke-width=".7"/>'
            f'<circle cx="111" cy="{n(y0 - 4.5)}" r="2.2" fill="{g}"/><circle cx="145" cy="{n(y0 - 4.5)}" r="2.2" fill="{g}"/>')
    return f'<g filter="url(#ds)">{"".join(pts)}{band}{gems}</g>'


def radiate_crown(doc, top):
    """Corona radiada (Helios, el Coloso) detrás del escudo de Titán."""
    m = doc.metal("gold", 0, 1)
    rays = []
    cy = top + 44
    for i in range(9):
        a = -60 + i * 15
        x, y = polar(128, cy, 66 if i % 2 == 0 else 58, a)
        b0, b1 = polar(128, cy, 40, a - 5), polar(128, cy, 40, a + 5)
        rays.append(f'<path d="M{n(b0[0])} {n(b0[1])}L{n(x)} {n(y)}L{n(b1[0])} {n(b1[1])}Z" fill="{m}" stroke="#000" stroke-opacity=".5" stroke-width=".8"/>')
    return f'<g filter="url(#ds)">{"".join(rays)}</g>'


def numeral_glyph(x, y, h=13):
    w, sw = 3.4, 8
    return (f'<rect x="{n(x - w / 2)}" y="{n(y)}" width="{n(w)}" height="{n(h)}"/>'
            f'<rect x="{n(x - sw / 2)}" y="{n(y)}" width="{n(sw)}" height="1.8" rx=".6"/>'
            f'<rect x="{n(x - sw / 2)}" y="{n(y + h - 1.8)}" width="{n(sw)}" height="1.8" rx=".6"/>')


def ribbon(doc, cloth, metal, division, ink=None):
    top = doc.lin([(0, cloth[0]), (1, cloth[1])], 0, 0, 0, 1)
    fold = cloth[2]
    y = 200
    band = f"M54 {y}Q128 {y + 18} 202 {y}L202 {y + 20}Q128 {y + 38} 54 {y + 20}Z"
    tails = (f'<path d="M58 {y + 4}L32 {y + 8}L42 {y + 17}L30 {y + 28}L60 {y + 26}Z" fill="{top}" stroke="#000" stroke-opacity=".5" stroke-width="1"/>'
             f'<path d="M198 {y + 4}L224 {y + 8}L214 {y + 17}L226 {y + 28}L196 {y + 26}Z" fill="{top}" stroke="#000" stroke-opacity=".5" stroke-width="1"/>'
             f'<path d="M54 {y + 20}L60 {y + 26}L58 {y + 18}Z" fill="{fold}"/><path d="M202 {y + 20}L196 {y + 26}L198 {y + 18}Z" fill="{fold}"/>')
    edge = f'<path d="M58 {y + 3.5}Q128 {y + 21} 198 {y + 3.5}" fill="none" stroke="#fff" stroke-opacity=".25" stroke-width="1"/>'
    m = ink or doc.metal(metal, 0, 1)
    if division:
        xs = [128 + (i - (division - 1) / 2) * 9 for i in range(division)]
        glyphs = "".join(numeral_glyph(x, y + 11.5) for x in xs)
    else:  # Titán: estrella
        glyphs = f'<path d="{star_path(128, y + 18.5, 8, 3.2, 8)}"/>'
    return (f'<g filter="url(#ds)">{tails}<path d="{band}" fill="{top}" stroke="#000" stroke-opacity=".55" stroke-width="1.1"/>{edge}</g>'
            + emboss(glyphs, m, d=0.8, light=0.25, dark=0.6))


def halo(doc, color):
    g = doc.rad([(0, color, 0.55), (0.45, color, 0.22), (1, color, 0)], 0.5, 0.5, 0.5)
    return f'<circle cx="128" cy="118" r="126" fill="{g}"/>'


# ------------------------------------------------------------ escudos
def hierro(doc):
    d = ellipse_d(128, 120, 58, 84)
    field = doc.rad([(0, "#5d646d"), (0.6, "#3a3f46"), (1, "#1f2226")], 0.38, 0.3, 0.8)
    out = [shield_base(doc, d, doc.metal("iron"), field, 0.87)]
    tex = []
    for _ in range(70):  # martillado
        x, y = doc.rng.uniform(72, 184), doc.rng.uniform(40, 200)
        r = doc.rng.uniform(1.5, 4.5)
        tex.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r)}" fill="{"#fff" if doc.rng.random() < .5 else "#000"}" opacity="{doc.rng.choice([.05, .07, .09])}"/>')
    rust = doc.rad([(0, "#8a4318", 0.5), (1, "#8a4318", 0)], 0.5, 0.5, 0.5)
    for x, y, r in [(92, 70, 16), (168, 160, 20), (100, 178, 12), (160, 64, 10)]:
        tex.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{rust}"/>')
    out.append(f'<g clip-path="{doc.clip(d)}">{"".join(tex)}</g>')
    # espina central con bulbos y trisqueles en los extremos
    out.append(emboss('<rect x="121.5" y="50" width="13" height="140" rx="6.5"/>', doc.metal("iron", 1, 0)))
    for y in (66, 174):
        out.append(f'<circle cx="128" cy="{y + 1.5}" r="14" fill="#000" opacity=".45"/><circle cx="128" cy="{y}" r="14" fill="{doc.metal("iron")}" stroke="#000" stroke-opacity=".5"/>')
        arms = "".join(f'<path d="M0 0C3 -2 7 -6 4 -9.5C1.5 -12 -3 -9.5 -1.2 -6.8" transform="translate(128 {y}) rotate({k * 120})"/>' for k in range(3))
        out.append(f'<g fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="1.8" stroke-linecap="round" transform="translate(.5 .7)">{arms}</g>'
                   f'<g fill="none" stroke="#15171a" stroke-width="1.8" stroke-linecap="round">{arms}</g>')
    out.append(plate(doc, 128, 120, 33, "iron"))
    rv = doc.rad([(0, "#f2f5f8"), (0.4, "#8c949d"), (1, "#26292d")], 0.35, 0.3, 0.7)
    for i in range(18):  # remaches
        a = math.radians(i * 20 + 10)
        x, y = 128 + 54.5 * math.sin(a), 120 - 79 * math.cos(a)
        out.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="2.7" fill="{rv}" stroke="#000" stroke-opacity=".5" stroke-width=".6"/>')
    out.append(specular(doc, d, 104, 70, 70, 60, 0.35))
    return d, "".join(out), 36


def meander(cx, cy, r_in, r_out, units):
    """Greca en anillo: espirales que nacen de la línea base."""
    def P(u, v, k):
        return polar(cx, cy, r_in + (r_out - r_in) * v / 4, (k + u / 4) * 360 / units)
    paths = []
    for k in range(units):
        pts = [(0, 0), (0, 4), (3, 4), (3, 1), (1, 1), (1, 2.6), (2, 2.6)]
        dense = []
        for (u0, v0), (u1, v1) in zip(pts, pts[1:]):
            for j in range(4):
                t = j / 4
                dense.append(P(u0 + (u1 - u0) * t, v0 + (v1 - v0) * t, k))
        dense.append(P(*pts[-1], k))
        paths.append(poly(dense))
    return " ".join(paths), circle_d(cx, cy, r_in)


def bronce(doc):
    d = circle_d(128, 120, 80)
    field = doc.rad([(0, "#ffd9a6"), (0.35, "#d08a4a"), (0.8, "#8a4818"), (1, "#5a2d0f")], 0.38, 0.3, 0.75)
    out = [shield_base(doc, d, doc.metal("bronze"), field, 0.84)]
    mp, base = meander(128, 120, 69.5, 77.5, 26)
    out.append(engrave(mp, "#4a2008", 1.5) + engrave(base, "#4a2008", 1.3))
    # episema en estilo de figuras rojas: disco negro con mancuernas cruzadas
    out.append(f'<circle cx="128" cy="121.5" r="46" fill="#000" opacity=".45"/>'
               f'<circle cx="128" cy="120" r="46" fill="{doc.rad([(0, "#3a261b"), (1, "#0c0705")], 0.4, 0.35, 0.8)}" stroke="#e0a066" stroke-width="2"/>'
               f'<circle cx="128" cy="120" r="41" fill="none" stroke="#d9773c" stroke-width="1" stroke-dasharray="2 3"/>')
    terra = doc.lin([(0, "#f7b27a"), (0.5, "#dc7c40"), (1, "#a8501f")], 0, 0, 0, 1)
    out.append(dumbbell(doc, 128, 120, 70, 38, "bronze", plate_fill=terra) + dumbbell(doc, 128, 120, 70, -38, "bronze", plate_fill=terra))
    olive = "#d9773c"
    for side in (-1, 1):  # ramitas de olivo pintadas
        for i in range(5):
            x, y = polar(128, 120, 34, 180 + side * (40 + i * 22))
            out.append(f'<ellipse cx="{n(x)}" cy="{n(y)}" rx="4.4" ry="1.8" fill="{olive}" transform="rotate({n(side * (40 + i * 22) + 90)} {n(x)} {n(y)})"/>')
    out.append(specular(doc, d, 98, 72, 80, 56, 0.45))
    return d, "".join(out), 40


def plata(doc):
    d = "M88 36H168Q182 36 182 50V190Q182 204 168 204H88Q74 204 74 190V50Q74 36 88 36Z"
    field = doc.lin([(0, "#121821"), (0.2, "#2c3644"), (0.45, "#3d4a5c"), (0.7, "#2a3442"), (1, "#0e131a")], 0, 0, 1, 0)
    out = [shield_base(doc, d, doc.metal("silver"), field, 0.9)]
    silver = doc.metal("silver")
    # rayos de Júpiter en aspa, en plata
    bolt = "M0 -3L18 -6.5L15 -1.2L40 0L19 6.5L22 1.2L0 3Z"
    bolts = "".join(f'<path d="{bolt}" transform="translate({n(polar(128, 120, 27, a)[0])} {n(polar(128, 120, 27, a)[1])}) rotate({a - 90})"/>'
                    for a in (38, 142, 218, 322))
    out.append(emboss(bolts, silver, 1.1, 0.25, 0.6))
    # alas de águila desplegadas desde el umbo
    wing = doc.lin([(0, "#ffffff"), (0.5, "#c3cbd4"), (1, "#7d8793")], 0, 0, 1, 1)
    for side in (-1, 1):
        feathers = []
        for i in range(7):
            ang = -8 - i * 9
            L = 46 - i * 2.2
            rot = ang if side > 0 else 180 - ang
            feathers.append(f'<g transform="translate({128 + side * 16} 124) rotate({rot})">'
                            f'<path d="M0 -3C{n(L * 0.3)} -7 {n(L * 0.8)} -6 {n(L)} 0C{n(L * 0.8)} 3 {n(L * 0.3)} 4 0 3Z" fill="{wing}" stroke="#141a22" stroke-width=".9"/></g>')
        out.append(f'<g clip-path="{doc.clip(d)}">{"".join(reversed(feathers))}</g>')
    out.append(plate(doc, 128, 120, 25, "silver"))
    for y in (48, 192):  # clavos del canto
        for x in (90, 128, 166):
            out.append(f'<circle cx="{x}" cy="{y}" r="2.4" fill="{silver}" stroke="#000" stroke-opacity=".5" stroke-width=".6"/>')
    out.append(specular(doc, d, 104, 66, 60, 70, 0.3))
    return d, "".join(out), 36


def oro(doc):
    d = "M72 204L75 100A53 64 0 0 1 181 100L184 204Z"
    field = doc.rad([(0, "#fff0b0"), (0.45, "#e2ae38"), (1, "#8a5a0c")], 0.4, 0.3, 0.85)
    out = [shield_base(doc, d, doc.metal("gold"), field, 0.88)]
    clip = doc.clip(d)
    lapis = doc.lin([(0, "#3a63c9"), (1, "#16307a")], 0, 0, 0, 1)
    turq = doc.lin([(0, "#7ae8da"), (1, "#1f9a8e")], 0, 0, 0, 1)
    carn = doc.lin([(0, "#ff8a6a"), (1, "#a3241a")], 0, 0, 0, 1)
    gold = doc.metal("gold", 0, 1)
    # collar usej: arcos de cuentas de lapislázuli, turquesa y cornalina
    rows = []
    cx, cy = 128, 118
    for r, fill, w in [(30, lapis, 6), (37, gold, 4), (43, turq, 6), (50, gold, 4), (56, carn, 6), (63, lapis, 7)]:
        a0, a1 = 112, 248
        p0, p1 = polar(cx, cy, r, a0), polar(cx, cy, r, a1)
        rows.append(f'<path d="M{n(p0[0])} {n(p0[1])}A{r} {r} 0 0 1 {n(p1[0])} {n(p1[1])}" fill="none" stroke="#3a2404" stroke-width="{w + 1.4}"/>'
                    f'<path d="M{n(p0[0])} {n(p0[1])}A{r} {r} 0 0 1 {n(p1[0])} {n(p1[1])}" fill="none" stroke="{fill}" stroke-width="{w}"/>')
        if fill is lapis or fill is turq or fill is carn:
            for k in range(a0 + 6, a1 - 4, 9):  # separación entre cuentas
                q0, q1 = polar(cx, cy, r - w / 2, k), polar(cx, cy, r + w / 2, k)
                rows.append(f'<path d="M{n(q0[0])} {n(q0[1])}L{n(q1[0])} {n(q1[1])}" stroke="#3a2404" stroke-width=".8"/>')
    drops = []  # colgantes en gota
    for k in range(118, 246, 8):
        x, y = polar(cx, cy, 70, k)
        drops.append(f'<path d="M0 -4C3 -1 3 4 0 6C-3 4 -3 -1 0 -4Z" fill="{lapis}" stroke="#3a2404" stroke-width=".7" transform="translate({n(x)} {n(y)}) rotate({k - 180})"/>')
    out.append(f'<g clip-path="{clip}">{"".join(rows)}{"".join(drops)}</g>')
    # sol alado: el sol es un disco
    wingclip = doc.clip(d)
    for side in (-1, 1):
        tiers = []
        for fill, L, dy in [(lapis, 13, 6), (turq, 9, 3), (gold, 6, 0)]:
            for i in range(8):
                x = 128 + side * (19 + i * 4.4)
                y = 74 + dy - i * 0.9
                tiers.append(f'<path d="M{n(x)} {n(y)}l{n(side * 4.2)} -.6l0 {n(L - i * 0.5)}q{n(-side * 2.1)} 2.4 {n(-side * 4.2)} .6Z" fill="{fill}" stroke="#3a2404" stroke-width=".7"/>')
        out.append(f'<g clip-path="{wingclip}">{"".join(tiers)}</g>')
        out.append(f'<path d="M{128 + side * 15} 84q{side * 4} 5 {side} 10q{-side * 3} 4 {side * 2} 7" fill="none" stroke="#7a4d08" stroke-width="2.4" stroke-linecap="round"/>')
    out.append(plate(doc, 128, 78, 17, "gold", hub=doc.rad([(0, "#ff9a7a"), (1, "#a3241a")], 0.35, 0.3, 0.8)))
    out.append(plate(doc, 128, 140, 21, "gold", face=lapis))
    out.append(specular(doc, d, 104, 70, 64, 58, 0.45))
    return d, "".join(out), 36


def platino(doc):
    d = "M64 40H192V110C192 158 162 188 128 204C94 188 64 158 64 110Z"
    field = doc.rad([(0, "#ffffff"), (0.5, "#dbe7ef"), (1, "#8fa6b8")], 0.38, 0.28, 0.85)
    out = [shield_base(doc, d, doc.metal("platinum"), field, 0.9)]
    clip = doc.clip(d)
    lat = " ".join(f"M{60 + i * 14} 30L{250 + i * 14} 220M{196 + i * 14} 30L{6 + i * 14} 220" for i in range(-12, 13))
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="1"/>' for x in range(57, 200, 14) for y in range(37, 206, 14))
    out.append(f'<g clip-path="{clip}"><path d="{lat}" stroke="#6f8aa0" stroke-opacity=".22" stroke-width=".9" fill="none"/>'
               f'<g fill="#6f8aa0" opacity=".35">{dots}</g></g>')
    azure = doc.lin([(0, "#5b8fe0"), (0.5, "#1f4fae"), (1, "#0f2c6e")], 0, 0, 0, 1)
    for x, y in ((94, 76), (158, 158)):  # roeles (discos) en azur
        out.append(plate(doc, x, y, 15, "platinum", face=azure))
    out.append(f'<g clip-path="{clip}">{barbell(doc, 128, 117, 150, -45, "platinum", plate_fill=azure)}</g>')
    out.append(specular(doc, d, 100, 66, 70, 56, 0.4))
    return d, "".join(out), 40


def diamante(doc):
    d = ("M70 44Q96 32 128 42Q160 32 186 44Q180 58 192 70V118C192 162 162 190 128 206"
         "C94 190 64 162 64 118V70Q76 58 70 44Z")
    field = doc.rad([(0, "#3b6fb8"), (0.55, "#173a73"), (1, "#0a1a3a")], 0.45, 0.35, 0.8)
    out = [shield_base(doc, d, doc.metal("steelblue"), field, 0.88)]
    rays = []
    for i in range(24):
        p0, p1 = polar(128, 120, 120, i * 15), polar(128, 120, 120, i * 15 + 6)
        rays.append(f"M128 120L{n(p0[0])} {n(p0[1])}L{n(p1[0])} {n(p1[1])}Z")
    out.append(f'<g clip-path="{doc.clip(d)}"><path d="{" ".join(rays)}" fill="#9cc8ff" opacity=".12"/></g>')
    # filete de oro renacentista siguiendo el contorno
    gold = doc.metal("gold", 0, 1)
    out.append(f'<g {inset(0.78)}><path d="{d}" fill="none" stroke="#000" stroke-opacity=".5" stroke-width="3.6"/>'
               f'<path d="{d}" fill="none" stroke="{gold}" stroke-width="2.2"/></g>')
    for x, y in ((92, 62), (164, 62)):
        out.append(f'<path d="{star_path(x, y, 5, 1.8, 4)}" fill="{gold}"/>')
    out.append(dumbbell(doc, 128, 122, 112, 40, "steelblue") + dumbbell(doc, 128, 122, 112, -40, "steelblue"))
    # diamante talla brillante (vista cenital)
    R, r = 31, 15
    outer = [polar(128, 120, R, 22.5 + i * 45) for i in range(8)]
    inner = [polar(128, 120, r, 22.5 + i * 45) for i in range(8)]
    mid = [polar(128, 120, R * 0.92, i * 45) for i in range(8)]
    shades = ["#ffffff", "#d6ecff", "#9fd0ff", "#e9f6ff", "#7fb8f0", "#c7e4ff", "#ffffff", "#a9d6ff"]
    facets = [f'<path d="{poly(outer)}Z" fill="#000" opacity=".5" transform="translate(1 2)"/>']
    for i in range(8):
        a, b = outer[i], outer[(i + 1) % 8]
        ia, ib = inner[i], inner[(i + 1) % 8]
        m = mid[(i + 1) % 8]
        facets.append(f'<path d="{poly([a, m, ia])}Z" fill="{shades[i]}"/>')
        facets.append(f'<path d="{poly([m, b, ib])}Z" fill="{shades[(i + 3) % 8]}"/>')
        facets.append(f'<path d="{poly([ia, m, ib])}Z" fill="{shades[(i + 5) % 8]}"/>')
    table = doc.rad([(0, "#ffffff"), (1, "#bfe2ff")], 0.4, 0.35, 0.8)
    facets.append(f'<path d="{poly(inner)}Z" fill="{table}"/>')
    facets.append(f'<path d="{poly(outer)}Z" fill="none" stroke="#0d2550" stroke-width="1.2"/>')
    out.append(f'<g stroke="#2b5a9a" stroke-width=".5" stroke-linejoin="round">{"".join(facets)}</g>')
    out.append('<path d="M116 108l5 -2l-3 6z" fill="#fff"/>')
    out.append(specular(doc, d, 100, 66, 70, 56, 0.35))
    return d, "".join(out), 38


def esmeralda(doc):
    cy = 110
    d = circle_d(128, cy, 72)
    out = []
    fe = doc.lin([(0, "#1fbf7a"), (0.6, "#0b7a6a"), (1, "#0d3d7a")], 0, 0, 0, 1)
    for i in range(11):  # plumas de quetzal (detrás)
        out.append(f'<g transform="translate(128 {cy + 40}) rotate({-60 + i * 12})">'
                   f'<path d="M0 0C-9 18 -8 46 0 64C8 46 9 18 0 0Z" fill="{fe}" stroke="#032a22" stroke-width=".9"/>'
                   f'<path d="M0 6V60" stroke="#9ff5c8" stroke-opacity=".6" stroke-width=".8"/>'
                   f'<ellipse cx="0" cy="54" rx="3" ry="5" fill="#0d3d7a" opacity=".7"/></g>')
    field = doc.rad([(0, "#5fe0a0"), (0.5, "#0f7a45"), (1, "#053a20")], 0.4, 0.32, 0.8)
    out.append(shield_base(doc, d, doc.metal("gold"), field, 0.9, cy=cy))
    gold = doc.metal("gold", 0, 1)
    steps = []  # greca escalonada (xicalcoliuhqui)
    units = 20
    for k in range(units):
        pts = [polar(128, cy, 50 + v * 3.3, k * 360 / units + u * (360 / units) / 5)
               for u, v in [(0, 0), (0, 1), (1, 1), (1, 2), (2, 2), (2, 3), (3, 3), (3, 2), (4, 2), (4, 1), (5, 1), (5, 0)]]
        steps.append(poly(pts) + "Z")
    out.append(f'<circle cx="128" cy="{cy}" r="61" fill="#06311d"/><circle cx="128" cy="{cy}" r="49" fill="#0a4a2c"/>')
    out.append(f'<path d="{" ".join(steps)}" fill="{gold}" stroke="#3a2404" stroke-width=".6"/>')
    tiles = []  # mosaico de turquesa y jade
    for ring in range(3):
        rr = 36 + ring * 4.2
        cnt = 30 + ring * 4
        for i in range(cnt):
            x, y = polar(128, cy, rr, i * 360 / cnt + ring * 3)
            col = doc.rng.choice(["#3fd6c0", "#22b39b", "#5be3a0", "#1a8f6f", "#7af0d2"])
            tiles.append(f'<rect x="{n(x - 2)}" y="{n(y - 2)}" width="4" height="4" rx=".8" fill="{col}" transform="rotate({n(i * 360 / cnt)} {n(x)} {n(y)})"/>')
    out.append(f'<g stroke="#03261a" stroke-width=".5">{"".join(tiles)}</g>')
    jade = doc.rad([(0, "#b8ffd8"), (0.5, "#1fa866"), (1, "#065a32")], 0.35, 0.3, 0.8)
    out.append(plate(doc, 128, cy, 31, "gold", face=jade))
    out.append(specular(doc, d, 100, 66, 70, 52, 0.4))
    return d, "".join(out), 38


def campeon(doc):
    d = "M66 40H190V134A62 70 0 0 1 66 134Z"
    field = doc.rad([(0, "#ff4a62"), (0.45, "#b0122c"), (1, "#4a0612")], 0.4, 0.3, 0.85)
    out = [shield_base(doc, d, doc.metal("gold"), field, 0.88)]
    fleur = "".join(f'<path d="M{x} {y - 4}l2.6 4l-2.6 4l-2.6 -4z"/>'
                    for y in range(52, 200, 22) for x in range(72 + (y // 22 % 2) * 11, 190, 22))
    out.append(f'<g clip-path="{doc.clip(d)}" fill="#ffb3c0" opacity=".12">{fleur}</g>')
    pearl = doc.rad([(0, "#ffffff"), (0.6, "#efe2cf"), (1, "#a8957a")], 0.35, 0.3, 0.8)
    for x in range(78, 182, 13):  # perlas del canto
        out.append(f'<circle cx="{x}" cy="46" r="2.3" fill="{pearl}"/>')
    # corona de olivo (kotinos), abierta arriba
    olive = doc.lin([(0, "#d9e6a0"), (0.5, "#8fa64a"), (1, "#4e6420")], 0, 0, 1, 1)
    for side in (-1, 1):
        stem = [polar(128, 124, 46, 180 + side * a) for a in range(8, 166, 6)]
        out.append(f'<path d="{poly(stem)}" fill="none" stroke="#5a4210" stroke-width="1.6"/>')
        for i in range(11):
            a = 180 + side * (14 + i * 14.5)
            x, y = polar(128, 124, 46, a)
            heading = a if side > 0 else a + 180  # hacia arriba, siguiendo la rama
            out.append(f'<g transform="translate({n(x)} {n(y)}) rotate({n(heading)})">{leaf(11, olive, -35)}{leaf(11, olive, 35)}</g>')
    out.append(barbell(doc, 128, 124, 112, 0, "gold"))
    out.append(emboss(f'<path d="{star_path(128, 96, 8, 3.4, 5)}"/>', doc.metal("gold"), 0.9))
    out.append(specular(doc, d, 100, 66, 70, 58, 0.35))
    return d, "".join(out), 40


def titan(doc):
    d = "M58 44Q128 30 198 44L192 116C188 162 160 192 128 208C96 192 68 162 64 116Z"
    glow = doc.uid("gl")
    doc.defs.append(f'<filter id="{glow}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="4"/></filter>')
    field = doc.rad([(0, "#3a1d5c"), (0.55, "#160b26"), (1, "#05030a")], 0.5, 0.42, 0.8)
    out = [f'<path d="{d}" fill="none" stroke="#ff8a1e" stroke-width="7" opacity=".75" filter="url(#{glow})"/>',
           shield_base(doc, d, doc.metal("darkbronze"), field, 0.88)]
    stars = []
    for _ in range(46):
        x, y = doc.rng.uniform(66, 190), doc.rng.uniform(44, 200)
        stars.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(doc.rng.uniform(.4, 1.2))}" fill="#fff" opacity="{doc.rng.choice([.4, .6, .9])}"/>')
    const = "M84 70L98 62L112 68L120 56M150 172L162 160L176 166M156 60L170 70L166 84"
    out.append(f'<g clip-path="{doc.clip(d)}">{"".join(stars)}<path d="{const}" fill="none" stroke="#c9b6ff" stroke-opacity=".45" stroke-width=".8"/></g>')
    gold = doc.metal("gold")
    dark = "#3a1a06"
    R = 46
    # esfera armilar de Atlas: eje, meridiano, ecuador, trópicos y eclíptica
    back = doc.clip("M60 30H196V120H60Z")
    front = doc.clip("M60 120H196V210H60Z")

    def ring(rx, ry, rot, w, dash=False, cy=120):
        e = f'<ellipse cx="128" cy="{cy}" rx="{rx}" ry="{ry}" transform="rotate({rot} 128 120)" fill="none" stroke="{gold}" stroke-width="{w}"/>'
        if dash:
            e += f'<ellipse cx="128" cy="{cy}" rx="{rx}" ry="{ry}" transform="rotate({rot} 128 120)" fill="none" stroke="{dark}" stroke-width="1.2" stroke-dasharray="1.2 3.6"/>'
        return e

    axis = (f'<path d="M128 {120 - R - 12}V{120 + R + 12}" stroke="{dark}" stroke-width="4.4" stroke-linecap="round"/>'
            f'<path d="M128 {120 - R - 12}V{120 + R + 12}" stroke="{gold}" stroke-width="2.6" stroke-linecap="round"/>'
            f'<circle cx="128" cy="{120 - R - 13}" r="3.6" fill="{gold}" stroke="{dark}"/><circle cx="128" cy="{120 + R + 13}" r="3.6" fill="{gold}" stroke="{dark}"/>')
    rings = (ring(R, 11, 0, 2.2) + ring(R * 0.8, 8, 0, 1.6, cy=120 - 26) + ring(R * 0.8, 8, 0, 1.6, cy=120 + 26)
             + ring(R + 2, 13, -24, 5, dash=True))
    meridian = f'<circle cx="128" cy="120" r="{R}" fill="none" stroke="{dark}" stroke-width="5.4"/><circle cx="128" cy="120" r="{R}" fill="none" stroke="{gold}" stroke-width="3.6"/>'
    out.append(f'<g clip-path="{back}">{rings}</g>{axis}')
    out.append(plate(doc, 128, 120, 24, "gold", hub=doc.rad([(0, "#ffe2a0"), (1, "#c45a10")], 0.35, 0.3, 0.8)))
    out.append(f'<g clip-path="{front}">{rings}</g>{meridian}')
    out.append(specular(doc, d, 100, 64, 70, 54, 0.3))
    return d, "".join(out), 38


RANKS = {
    # clave: (dibujo, metal de adornos, cinta (claro, oscuro, pliegue), gema, halo)
    "hierro": (hierro, "iron", ("#7a2e22", "#4a1610", "#2a0a06"), ("#ff7a5a", "#7a1a0a"), "#c9d2dc"),
    "bronce": (bronce, "bronze", ("#22477a", "#122848", "#081428"), ("#7ab8ff", "#123a7a"), "#ffb070"),
    "plata": (plata, "silver", ("#8a1f2e", "#561018", "#30070c"), ("#ff8a9a", "#7a0a1a"), "#a9d4ff"),
    "oro": (oro, "gold", ("#24439a", "#132a66", "#0a1638"), ("#ff8a6a", "#8a1a0a"), "#ffd25a"),
    "platino": (platino, "platinum", ("#2b5aa8", "#173670", "#0b1d40"), ("#9fd0ff", "#1a4a9a"), "#bfe6ff"),
    "diamante": (diamante, "steelblue", ("#e9f4ff", "#9cbde0", "#5a7aa0"), ("#ffffff", "#5aa0ff"), "#8fc8ff"),
    "esmeralda": (esmeralda, "gold", ("#b0182a", "#6a0a16", "#3a040a"), ("#b8ffd8", "#0a7a40"), "#4fe39a"),
    "campeon": (campeon, "gold", ("#fff0b0", "#d9a030", "#8a5a0c"), ("#ff8aa0", "#9a0a2a"), "#ff5a7a"),
    "titan": (titan, "gold", ("#3a1a06", "#1c0c02", "#0a0400"), ("#ffd27a", "#c45a10"), "#ff8a2a"),
}


def build(key, division):
    draw, metal, cloth, gem, glow = RANKS[key]
    doc = Doc(key)
    d, body, top = draw(doc)
    parts = []
    if division == 3:
        parts.append(halo(doc, glow))
    if key == "titan":
        parts.append(radiate_crown(doc, top))
    if division >= 2:
        parts.append(laurel(doc, metal, 1.0 if division == 3 else 0.5))
    parts.append(body)
    if division == 3 and key != "titan":
        parts.append(coronet(doc, metal, gem, top))
    ink = {"diamante": "#1b3766", "campeon": "#8a0f22"}.get(key)
    parts.append(ribbon(doc, cloth, metal, None if key == "titan" else division, ink))
    return doc.svg("".join(parts))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith((".svg", ".webp", ".png")):
            os.remove(os.path.join(OUT, f))
    total = 0
    for key in RANKS:
        for div in ((3,) if key == "titan" else (1, 2, 3)):
            name = "titan" if key == "titan" else f"{key}-{div}"
            path = os.path.join(OUT, f"{name}.svg")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(build(key, div))
            total += os.path.getsize(path)
    print("ok", len(os.listdir(OUT)), "emblemas,", round(total / 1024), "KB")
