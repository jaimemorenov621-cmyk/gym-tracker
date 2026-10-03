"""Emblemas de rango: app/static/ranks/<rango>-<división>.svg (y titan.svg).

Una sola familia: el mismo escudo para todos, y cada rango hereda lo del
anterior y suma más, para que se vea de un vistazo cuál es mejor:
  - material: hierro, bronce, plata, oro, platino, diamante, esmeralda,
    campeón (carmesí y oro), titán (obsidiana y oro fundido);
  - el peso que lleva: disco, kettlebell, mancuerna, dos mancuernas, y una
    barra con 1, 2, 3, 4 y 5 discos por lado (la de Titán se dobla);
  - el escudo crece y el canto engorda; cimera, alas cada vez mayores,
    gemas, laurel y corona.
Detallitos históricos: remaches (hierro), dentículos griegos (bronce),
perlado, flor de lis, corona radiada y numerales romanos.
Divisiones: el numeral de la cinta; II + filete interior y halo suave;
III + halo intenso y destellos.

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
    "emerald": ["#d2ffe6", "#2fbf78", "#0a5a32", "#25a866", "#eafff3", "#06401f"],
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


def ribbon(doc, cloth, metal, division, ink=None, y=200):
    top = doc.lin([(0, cloth[0]), (1, cloth[1])], 0, 0, 0, 1)
    fold = cloth[2]
    y = round(y, 1)
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


def halo(doc, color, op=0.55):
    g = doc.rad([(0, color, op), (0.45, color, op * 0.4), (1, color, 0)], 0.5, 0.5, 0.5)
    return f'<circle cx="128" cy="118" r="126" fill="{g}"/>'


# ------------------------------------------------------------ piezas
SHIELD = "M66 46H190V112C190 160 160 188 128 202C96 188 66 160 66 112Z"
SC = (128, 124)  # centro de escala del escudo


def kettlebell(doc, cx, cy, size, metal):
    c = METALS[metal]
    body = doc.rad([(0, c[4]), (0.55, c[1]), (1, c[2])], 0.36, 0.32, 0.8)
    r = size / 2
    by = cy + r * 0.25
    handle = (f"M{n(cx - r * 0.6)} {n(by - r * 0.55)}C{n(cx - r * 0.8)} {n(by - r * 1.75)} "
              f"{n(cx + r * 0.8)} {n(by - r * 1.75)} {n(cx + r * 0.6)} {n(by - r * 0.55)}")
    return (f'<path d="{handle}" fill="none" stroke="#000" stroke-opacity=".5" stroke-width="{n(r * 0.36)}" transform="translate(1 2)"/>'
            f'<path d="{handle}" fill="none" stroke="#1b1208" stroke-width="{n(r * 0.36)}"/>'
            f'<path d="{handle}" fill="none" stroke="{c[1]}" stroke-width="{n(r * 0.26)}"/>'
            f'<path d="{handle}" fill="none" stroke="{c[4]}" stroke-opacity=".7" stroke-width="{n(r * 0.07)}" transform="translate(-.6 -.8)"/>'
            f'<circle cx="{n(cx)}" cy="{n(by + 2)}" r="{n(r)}" fill="#000" opacity=".45"/>'
            f'<circle cx="{n(cx)}" cy="{n(by)}" r="{n(r)}" fill="{body}" stroke="#1b1208" stroke-width="1.2"/>'
            f'<rect x="{n(cx - r * 0.6)}" y="{n(by + r * 0.82)}" width="{n(r * 1.2)}" height="{n(r * 0.22)}" rx="2" fill="{c[2]}"/>'
            f'<path d="M{n(cx - r * 0.62)} {n(by - r * 0.3)}A{n(r * 0.72)} {n(r * 0.72)} 0 0 1 {n(cx + r * 0.1)} {n(by - r * 0.72)}" '
            f'fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="{n(r * 0.1)}" stroke-linecap="round"/>')


def loaded_bar(doc, cx, cy, plates, metal, plate_metal=None, bend=0.0):
    """Barra con `plates` discos por lado (cabe dentro del escudo); `bend`
    la dobla por el peso."""
    c = METALS[metal]
    pc = METALS[plate_metal or metal]
    pf = doc.lin([(0, pc[2]), (0.35, pc[1]), (0.55, pc[4]), (0.8, pc[1]), (1, pc[2])], 0, 0, 1, 0)
    half = 54

    def y(x):
        return cy + bend * (x / half) ** 2

    def ang(x):
        return math.degrees(math.atan(2 * bend * x / (half * half)))

    pts = [(cx + x, y(x)) for x in [half * (i / 10 - 1) for i in range(21)]]
    bar = poly(pts)
    out = [f'<path d="{bar}" fill="none" stroke="#000" stroke-opacity=".45" stroke-width="5" transform="translate(1 2)"/>',
           f'<path d="{bar}" fill="none" stroke="#1d1f23" stroke-width="4.6" stroke-linecap="round"/>',
           f'<path d="{bar}" fill="none" stroke="{c[1]}" stroke-width="3.2" stroke-linecap="round"/>',
           f'<path d="{bar}" fill="none" stroke="{c[4]}" stroke-opacity=".7" stroke-width="1" transform="translate(0 -.8)"/>']

    def piece(x, w, h, fill, rx=1.6):
        return (f'<g transform="translate({n(cx + x)} {n(y(x))}) rotate({n(ang(x))})">'
                f'<rect x="{n(-w / 2 + 1)}" y="{n(-h / 2 + 2)}" width="{n(w)}" height="{n(h)}" rx="{n(rx)}" fill="#000" opacity=".45"/>'
                f'<rect x="{n(-w / 2)}" y="{n(-h / 2)}" width="{n(w)}" height="{n(h)}" rx="{n(rx)}" fill="{fill}" stroke="#000" stroke-opacity=".65" stroke-width=".9"/>'
                f'<rect x="{n(-w / 2 + 0.8)}" y="{n(-h / 2 + 1.5)}" width="1.2" height="{n(h - 3)}" rx=".6" fill="#fff" opacity=".45"/></g>')
    collar = doc.metal(metal, 0, 1)
    for side in (-1, 1):
        out.append(piece(side * 20, 3.4, 11, collar, 1))
        x = side * 22
        w = 8 if plates <= 3 else 6.6
        for k in range(plates):
            h = 48 - k * 3.5
            out.append(piece(x + side * w / 2, w, h, pf))
            x += side * (w + 0.5)
    return "".join(out)


def wings(doc, size, metal, count):
    """Alas a los lados del escudo; más grandes cuanto más alto el rango."""
    back = doc.lin([(0, METALS[metal][1]), (1, METALS[metal][2])], 0, 0, 1, 1)
    front = doc.lin([(0, METALS[metal][4]), (0.6, METALS[metal][1]), (1, METALS[metal][2])], 0, 0, 1, 1)
    side_svg = []
    for row, fill, k in ((0, back, 1.0), (1, front, 0.68)):
        for i in range(count):
            t = i / (count - 1)
            a = 12 - t * 92
            L = size * k * (0.62 + 0.38 * math.sin(math.pi * (0.35 + 0.65 * t)))
            w = L * 0.13
            side_svg.append(f'<g transform="translate(176 {84 + row * 6}) rotate({n(a)})">'
                            f'<path d="M0 {n(-w)}C{n(L * 0.35)} {n(-w * 1.9)} {n(L * 0.85)} {n(-w * 1.2)} {n(L)} 0C{n(L * 0.8)} {n(w)} {n(L * 0.35)} {n(w * 1.3)} 0 {n(w)}Z" '
                            f'fill="{fill}" stroke="#000" stroke-opacity=".55" stroke-width=".8"/>'
                            f'<path d="M2 0L{n(L * 0.8)} {n(-w * 0.2)}" stroke="#fff" stroke-opacity=".3" stroke-width=".7"/></g>')
    one = "".join(side_svg)
    return f'<g filter="url(#ds)">{one}<g transform="translate(256 0) scale(-1 1)">{one}</g></g>'


def fleur(doc, cx, cy, sc, metal):
    m = doc.metal(metal, 0, 1)
    shape = ("M0 -22C6 -14 7 -6 0 2C-7 -6 -6 -14 0 -22Z"
             "M-3 0C-8 -2 -16 -2 -17 -10C-18 -16 -12 -18 -10 -13C-12 -12 -12 -8 -8 -6C-6 -5 -4 -4 -3 -2Z"
             "M3 0C8 -2 16 -2 17 -10C18 -16 12 -18 10 -13C12 -12 12 -8 8 -6C6 -5 4 -4 3 -2Z"
             "M-9 0H9V4H-9Z M-6 4C-6 9 -2 10 0 8C2 10 6 9 6 4Z")
    return (f'<g transform="translate({n(cx)} {n(cy)}) scale({sc})" filter="url(#ds)">'
            f'<path d="{shape}" fill="{m}" stroke="#000" stroke-opacity=".55" stroke-width=".9"/></g>')


def finial(doc, x, y, r, metal):
    m = doc.metal(metal)
    return (f'<rect x="{n(x - 1.6)}" y="{n(y - r * 1.6)}" width="3.2" height="{n(r * 1.6)}" fill="{m}" stroke="#000" stroke-opacity=".5" stroke-width=".6"/>'
            f'<circle cx="{n(x)}" cy="{n(y - r * 1.9)}" r="{n(r)}" fill="{m}" stroke="#000" stroke-opacity=".55" stroke-width=".8"/>')


def gem(doc, x, y, r, colors):
    g = doc.rad([(0, "#fff"), (0.3, colors[0]), (1, colors[1])], 0.35, 0.3, 0.8)
    return (f'<circle cx="{n(x)}" cy="{n(y + 1)}" r="{n(r + 1.4)}" fill="#000" opacity=".4"/>'
            f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r + 1.4)}" fill="{doc.metal("gold")}"/>'
            f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r)}" fill="{g}" stroke="#000" stroke-opacity=".5" stroke-width=".6"/>')


def crystal(doc, cx, cy, h):
    w = h * 0.42
    pts = [(cx, cy - h / 2), (cx + w, cy - h * 0.12), (cx, cy + h / 2), (cx - w, cy - h * 0.12)]
    c = (cx, cy - h * 0.12)
    shades = ["#ffffff", "#a8d4ff", "#5a9be0", "#d8eeff"]
    faces = "".join(f'<path d="{poly([pts[i], pts[(i + 1) % 4], c])}Z" fill="{shades[i]}"/>' for i in range(4))
    return (f'<g filter="url(#ds)" stroke="#1b3766" stroke-width=".8" stroke-linejoin="round">{faces}'
            f'<path d="{poly(pts)}Z" fill="none" stroke-width="1.2"/></g>')


def rays(doc, color, count=18, r=124, op=0.45):
    fade = doc.rad([(0, color, op), (0.6, color, op * 0.5), (1, color, 0)], 0.5, 0.5, 0.5)
    tri = []
    for i in range(count):
        a = i * 360 / count
        p0, p1 = polar(128, 118, r, a - 4), polar(128, 118, r, a + 4)
        tri.append(f"M128 118L{n(p0[0])} {n(p0[1])}L{n(p1[0])} {n(p1[1])}Z")
    return f'<path d="{" ".join(tri)}" fill="{fade}"/>'


def sparkles(points):
    out = []
    for x, y, r in points:
        out.append(f'<path d="M{x} {y - r}Q{x} {y} {x + r} {y}Q{x} {y} {x} {y + r}Q{x} {y} {x - r} {y}Q{x} {y} {x} {y - r}Z" fill="#fff" opacity=".9"/>')
    return "".join(out)


# ------------------------------------------------------------ rangos
#   s: escala del escudo; rim: grosor relativo del canto (inset del campo)
RANKS = {
    "hierro": dict(tier=0, s=0.8, rim="iron", field=("#4a5058", "#2a2e34", "#16181b"), item=("plate", "iron"),
                   cloth=("#7a2e22", "#4a1610", "#2a0a06"), halo="#c9d2dc"),
    "bronce": dict(tier=1, s=0.83, rim="bronze", field=("#7a4218", "#3e1e08", "#1e0e03"), item=("kettlebell", "bronze"),
                   cloth=("#22477a", "#122848", "#081428"), halo="#ffb070"),
    "plata": dict(tier=2, s=0.86, rim="silver", field=("#3f4c5e", "#232b36", "#10141a"), item=("dumbbell", "silver"),
                  cloth=("#8a1f2e", "#561018", "#30070c"), halo="#bfe0ff"),
    "oro": dict(tier=3, s=0.88, rim="gold", field=("#7a4e0c", "#4a2c04", "#221402"), item=("dumbbells", "gold"),
                cloth=("#24439a", "#132a66", "#0a1638"), halo="#ffd25a"),
    "platino": dict(tier=4, s=0.9, rim="platinum", field=("#2f5a6c", "#173240", "#0a1820"), item=("bar", "platinum", 1),
                    cloth=("#2b5aa8", "#173670", "#0b1d40"), halo="#bfe6ff"),
    "diamante": dict(tier=5, s=0.92, rim="steelblue", field=("#2a58a0", "#132f60", "#08152e"), item=("bar", "steelblue", 2),
                     cloth=("#e9f4ff", "#9cbde0", "#5a7aa0"), halo="#8fc8ff", ink="#1b3766", gems=("#bfe2ff", "#3a7ad0")),
    "esmeralda": dict(tier=6, s=0.94, rim="emerald", field=("#13804a", "#0a4a2b", "#031f12"), item=("bar", "gold", 3, "emerald"),
                      cloth=("#b0182a", "#6a0a16", "#3a040a"), halo="#4fe39a", gems=("#7dffb8", "#0a7a40")),
    "campeon": dict(tier=7, s=0.96, rim="gold", field=("#c0142e", "#7a0a1c", "#3a030c"), item=("bar", "gold", 4),
                    cloth=("#fff0b0", "#d9a030", "#8a5a0c"), halo="#ff5a7a", ink="#8a0f22", gems=("#ff7a90", "#9a0a2a")),
    "titan": dict(tier=8, s=1.0, rim="darkbronze", field=("#3a1d5c", "#160b26", "#05030a"), item=("bar", "gold", 5),
                  cloth=("#3a1a06", "#1c0c02", "#0a0400"), halo="#ff8a2a", gems=("#ffd27a", "#d0500a")),
}
WINGS = {"oro": ("gold", 38, 5), "platino": ("platinum", 42, 6), "diamante": ("steelblue", 48, 6),
         "esmeralda": ("emerald", 54, 7), "campeon": ("gold", 58, 7), "titan": ("gold", 64, 8)}


def center_item(doc, item):
    kind, metal = item[0], item[1]
    if kind == "plate":
        return plate(doc, 128, 120, 34, metal)
    if kind == "kettlebell":
        return kettlebell(doc, 128, 122, 52, metal)
    if kind == "dumbbell":
        return dumbbell(doc, 128, 122, 104, -20, metal)
    if kind == "dumbbells":
        return dumbbell(doc, 128, 122, 104, 35, metal) + dumbbell(doc, 128, 122, 104, -35, metal)
    plates = item[2]
    plate_metal = item[3] if len(item) > 3 else None
    return loaded_bar(doc, 128, 122, plates, metal, plate_metal, bend=7 if plates == 5 else 0)


def crest(doc, key, cfg):
    t = cfg["tier"]
    m = cfg["rim"]
    if t == 2:
        return finial(doc, 128, 47, 5.5, m)
    if t == 3:
        return fleur(doc, 128, 44, 1.0, m)
    if t == 4:
        return fleur(doc, 128, 44, 1.15, m) + finial(doc, 70, 48, 4.5, m) + finial(doc, 186, 48, 4.5, m)
    if t == 5:
        return crystal(doc, 128, 30, 34) + finial(doc, 70, 48, 4.5, m) + finial(doc, 186, 48, 4.5, m)
    if t == 6:
        return (fleur(doc, 128, 44, 1.2, "gold") + gem(doc, 128, 28, 6, cfg["gems"])
                + finial(doc, 70, 48, 4.5, "gold") + finial(doc, 186, 48, 4.5, "gold"))
    if t >= 7:
        return coronet(doc, "gold", cfg["gems"], 48)
    return ""


def build(key, division):
    cfg = RANKS[key]
    t = cfg["tier"]
    doc = Doc(key)
    sc = cfg["s"]
    group = f'transform="translate({SC[0]} {SC[1]}) scale({sc}) translate({-SC[0]} {-SC[1]})"'
    back, front = [], []
    if division >= 2:
        back.append(halo(doc, cfg["halo"], 0.3 if division == 2 else 0.6))
    if t == 8:
        back.append(rays(doc, "#ffb347"))
    inner = []  # dentro del grupo escalado
    if t == 8:
        inner.append(radiate_crown(doc, 40))
    if key in WINGS:
        metal, size, count = WINGS[key]
        inner.append(wings(doc, size, metal, count))
    if t >= 6:
        inner.append(laurel(doc, "gold", {6: 0.45, 7: 0.55, 8: 0.6}[t]))
    # escudo: el canto engorda con el rango
    rim_inset = 0.9 - t * 0.006
    f0, f1, f2 = cfg["field"]
    field = doc.rad([(0, f0), (0.6, f1), (1, f2)], 0.42, 0.3, 0.85)
    if t == 8:
        glow = doc.uid("gl")
        doc.defs.append(f'<filter id="{glow}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="4"/></filter>')
        inner.append(f'<path d="{SHIELD}" fill="none" stroke="#ff8a1e" stroke-width="7" opacity=".8" filter="url(#{glow})"/>')
    inner.append(shield_base(doc, SHIELD, doc.metal(cfg["rim"]), field, rim_inset, cy=124))
    c = METALS[cfg["rim"]]
    if t == 0:  # remaches
        inner.append(f'<g {inset(0.95, cy=124)}><path d="{SHIELD}" fill="none" stroke="#000" stroke-opacity=".5" stroke-width="5.4" stroke-linecap="round" stroke-dasharray="0.1 13" transform="translate(.6 .9)"/>'
                     f'<path d="{SHIELD}" fill="none" stroke="#c6cdd4" stroke-width="4.6" stroke-linecap="round" stroke-dasharray="0.1 13"/></g>')
    elif t == 1:  # dentículos griegos
        inner.append(f'<g {inset(0.948, cy=124)}><path d="{SHIELD}" fill="none" stroke="#3a1a06" stroke-width="5" stroke-dasharray="2.4 2.4" opacity=".75"/></g>')
    else:  # perlado
        inner.append(f'<g {inset(0.952 - t * 0.003, cy=124)}><path d="{SHIELD}" fill="none" stroke="#000" stroke-opacity=".45" stroke-width="3.4" stroke-linecap="round" stroke-dasharray="0.1 6.5" transform="translate(.4 .7)"/>'
                     f'<path d="{SHIELD}" fill="none" stroke="{c[4]}" stroke-width="2.8" stroke-linecap="round" stroke-dasharray="0.1 6.5"/></g>')
    if division >= 2:  # filete interior
        inner.append(f'<g {inset(rim_inset - 0.07, cy=124)}><path d="{SHIELD}" fill="none" stroke="{c[4]}" stroke-opacity=".8" stroke-width="1.6"/></g>')
    if t == 8:  # estrellas en la obsidiana
        stars = "".join(f'<circle cx="{n(doc.rng.uniform(76, 180))}" cy="{n(doc.rng.uniform(56, 190))}" r="{n(doc.rng.uniform(.4, 1.1))}" fill="#fff" opacity="{doc.rng.choice([.4, .7])}"/>'
                        for _ in range(36))
        inner.append(f'<g clip-path="{doc.clip(SHIELD)}">{stars}</g>')
    inner.append(center_item(doc, cfg["item"]))
    if "gems" in cfg:
        for x, y in ((80, 58), (176, 58), (72, 116), (184, 116), (128, 192)):
            inner.append(gem(doc, x, y, 3.6 if t < 7 else 4.2, cfg["gems"]))
    inner.append(specular(doc, SHIELD, 100, 70, 70, 58, 0.3))
    inner.append(crest(doc, key, cfg))
    if division == 3:
        inner.append(sparkles([(60, 60, 7), (200, 78, 5), (52, 170, 5), (206, 176, 7)]))
    body = f'<g {group}>{"".join(inner)}</g>'
    ry = SC[1] + (202 - SC[1]) * sc - 8
    ribbon_svg = ribbon(doc, cfg["cloth"], cfg["rim"] if t != 8 else "gold", None if key == "titan" else division, cfg.get("ink"), y=ry)
    return doc.svg("".join(back) + body + ribbon_svg)


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
