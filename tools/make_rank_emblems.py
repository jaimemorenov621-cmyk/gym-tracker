"""Emblemas de rango: misma composición (escudo, G de Gyre, barra con
discos, cinta con numeral) con acabado de material más rico. Los colores
salen de tools/rank_materials.py; los ornamentos orgánicos (hojas,
plumas) se construyen paramétricamente desde una forma base.

Salida: app/static/ranks/<rango>-<división>.svg y titan.svg (los nombres que
usa la app). Con --preview escribe en app/static/ranks_preview/ (sin publicar).

Presupuesto de adornos por rango (se acumulan; ver RANK_CFG):
  Hierro / Bronce      remaches + laurel corto
  Plata / Oro          + laurel completo, alas de 1-2 filas, corona pequeña
  Platino / Diamante   + alas de 3 filas, rosetas, gema (diamante: cristal)
  Esmeralda / Campeón  + filigrana floral en el marco (campeón: corona alta)
  Titán                todo + corona radiada, rayos y halo
Divisiones: el numeral; II y III añaden gemas en la cinta; III, en los
rangos altos, halo y destellos.

Ejecutar: python tools/make_rank_emblems.py [--preview]
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rank_materials import MATERIALS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "static", "ranks")
PREVIEW = os.path.join(ROOT, "app", "static", "ranks_preview")
CX, CY = 128, 124          # centro de escala del escudo
SHIELD = "M66 46H190V112C190 160 160 188 128 202C96 188 66 160 66 112Z"
SEGMENTS = [("L", (66, 46), (190, 46)), ("L", (190, 46), (190, 112)),
            ("C", (190, 112), (190, 160), (160, 188), (128, 202)),
            ("C", (128, 202), (96, 188), (66, 160), (66, 112)), ("L", (66, 112), (66, 46))]


def n(x):
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


class Doc:
    def __init__(self, seed):
        self.defs, self.k, self.rng = [], 0, random.Random(seed)

    def uid(self, p):
        self.k += 1
        return f"{p}{self.k}"

    @staticmethod
    def _stops(stops):
        out = []
        for st in stops:
            o, c, a = st[0], st[1], (st[2] if len(st) > 2 else 1)
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

    def clip(self, d, transform=""):
        i = self.uid("c")
        t = f' transform="{transform}"' if transform else ""
        self.defs.append(f'<clipPath id="{i}"><path d="{d}"{t}/></clipPath>')
        return f"url(#{i})"

    def svg(self, body):
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
                '<defs><filter id="ds" x="-20%" y="-20%" width="140%" height="140%">'
                '<feDropShadow dx="0" dy="3" stdDeviation="2.6" flood-color="#000" flood-opacity=".5"/></filter>'
                '<filter id="blur3" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="3"/></filter>'
                + "".join(self.defs) + "</defs>" + body + "</svg>")


# ------------------------------------------------------------ geometría
def _cubic(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def shield_points(count, f=1.0):
    """`count` puntos repartidos por igual a lo largo del contorno del
    escudo, escalado `f` respecto al centro, con su tangente."""
    fine = []
    for seg in SEGMENTS:
        steps = 120
        for i in range(steps):
            t = i / steps
            if seg[0] == "L":
                (x0, y0), (x1, y1) = seg[1], seg[2]
                fine.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            else:
                fine.append(_cubic(*seg[1:], t))
    fine.append(fine[0])
    acc = [0.0]
    for a, b in zip(fine, fine[1:]):
        acc.append(acc[-1] + math.dist(a, b))
    total = acc[-1]
    pts, j = [], 0
    for k in range(count):
        target = total * k / count
        while acc[j + 1] < target:
            j += 1
        a, b = fine[j], fine[j + 1]
        t = (target - acc[j]) / max(1e-9, acc[j + 1] - acc[j])
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        tx, ty = b[0] - a[0], b[1] - a[1]
        L = math.hypot(tx, ty) or 1
        pts.append((CX + (x - CX) * f, CY + (y - CY) * f, tx / L, ty / L))
    return pts


def inset(f):
    return f'translate({CX} {CY}) scale({f}) translate({-CX} {-CY})'


def metal(doc, m, x2=1, y2=1):
    return doc.lin(m["metal"], 0, 0, x2, y2)


# ------------------------------------------------------------ capas
RIM = 0.83      # el campo empieza al 86 % del contorno


def frame(doc, m):
    """Borde exterior con bisel (doble trazo claro/oscuro), canto de metal
    y arista interior hundida."""
    light, dark = m["bevel"]
    return (f'<path d="{SHIELD}" fill="{metal(doc, m)}" filter="url(#ds)"/>'
            f'<path d="{SHIELD}" fill="none" stroke="{dark}" stroke-width="1.8"/>'
            f'<path d="{SHIELD}" fill="none" stroke="{light}" stroke-opacity=".85" stroke-width="1.1" transform="{inset(0.985)}"/>'
            f'<path d="{SHIELD}" fill="none" stroke="{dark}" stroke-opacity=".55" stroke-width="1.1" transform="{inset(0.955)}"/>')


def beads(doc, m, count=38, f=0.93, r=2.5):
    """Perlado del marco: cada perla con su sombra y su brillo."""
    light, dark = m["bevel"]
    g = doc.rad([(0, m["specular"]), (0.35, m["metal"][4][1]), (0.75, m["metal"][1][1]), (1, dark)], 0.35, 0.3, 0.75)
    out = []
    for x, y, _, _ in shield_points(count, f):
        out.append(f'<circle cx="{n(x + 0.6)}" cy="{n(y + 1)}" r="{r}" fill="{m["shadow"]}" opacity=".55"/>'
                   f'<circle cx="{n(x)}" cy="{n(y)}" r="{r}" fill="{g}"/>')
    return "".join(out)


def field(doc, m):
    c0, c1, c2 = m["field"]
    fill = doc.rad([(0, c0), (0.55, c1), (1, c2)], 0.4, 0.28, 0.9)
    vign = doc.rad([(0, "#000", 0), (0.62, "#000", 0), (1, "#000", 0.5)], 0.5, 0.45, 0.62)
    light, dark = m["bevel"]
    edge = doc.lin([(0, dark, 0.85), (0.5, dark, 0.2), (1, light, 0.7)], 0, 0, 0, 1)
    return (f'<g transform="{inset(RIM)}"><path d="{SHIELD}" fill="{fill}"/><path d="{SHIELD}" fill="{vign}"/>'
            f'<path d="{SHIELD}" fill="none" stroke="{edge}" stroke-width="3"/></g>')


def filigree(doc, m, f=RIM - 0.05, waves=24, amp=1.5):
    """Grabado del borde interior: voluta ondulada con puntos, a lo largo
    del contorno (surco oscuro + filo de luz)."""
    light, dark = m["bevel"]
    pts = shield_points(waves * 8, f)
    raised = shield_points(240, RIM - 0.012)
    line = []
    dots = []
    for i, (x, y, tx, ty) in enumerate(pts):
        nx, ny = -ty, tx
        o = amp * math.sin(2 * math.pi * i / 8)
        line.append((x + nx * o, y + ny * o))
        if i % 8 == 2:
            dots.append((x - nx * amp * 1.1, y - ny * amp * 1.1))
    d = "M" + " L".join(f"{n(x)} {n(y)}" for x, y in line) + "Z"
    dot = "".join(f'<circle cx="{n(x)}" cy="{n(y)}" r=".9"/>' for x, y in dots)
    fillet = "M" + " L".join(f"{n(x)} {n(y)}" for x, y, _, _ in raised) + "Z"
    return (f'<path d="{fillet}" fill="none" stroke="{dark}" stroke-opacity=".6" stroke-width="2.2"/>'
            f'<path d="{fillet}" fill="none" stroke="{light}" stroke-opacity=".8" stroke-width="1" transform="translate(-.5 -.6)"/>'
            f'<path d="{d}" fill="none" stroke="{light}" stroke-opacity=".55" stroke-width="1" transform="translate(.5 .7)"/>'
            f'<path d="{d}" fill="none" stroke="{dark}" stroke-opacity=".75" stroke-width="1"/>'
            f'<g fill="{dark}" opacity=".7">{dot}</g>')


def specular(doc, m):
    g = doc.rad([(0, m["specular"], 0.45), (0.6, m["specular"], 0.1), (1, m["specular"], 0)], 0.5, 0.5, 0.5)
    return f'<g clip-path="{doc.clip(SHIELD)}"><ellipse cx="98" cy="70" rx="66" ry="52" fill="{g}"/></g>'


def g_mark(doc, m, cx=128, cy=120, r=31, w=13):
    """La G con relieve: luz arriba-izquierda, sombra abajo-derecha."""
    light, dark = m["bevel"]
    a = math.radians(-42)
    sx, sy = cx + r * math.cos(a), cy + r * math.sin(a)
    d = f"M{n(sx)} {n(sy)}A{r} {r} 0 1 0 {n(cx + r)} {n(cy + 1)}H{n(cx + 3)}"
    k = w * 0.3
    d_hi = f"M{n(sx)} {n(sy)}A{r} {r} 0 1 0 {n(cx + r)} {n(cy + 1)}H{n(cx + 3 + 2 * k)}"
    body = metal(doc, m)
    return (f'<path d="{d}" fill="none" stroke="{m["shadow"]}" stroke-opacity=".6" stroke-width="{w + 3}" transform="translate(1.8 2.8)"/>'
            f'<path d="{d}" fill="none" stroke="{dark}" stroke-width="{w + 2.4}"/>'
            f'<path d="{d}" fill="none" stroke="{m["metal"][2][1]}" stroke-width="{w}" transform="translate(.9 .9)"/>'
            f'<path d="{d}" fill="none" stroke="{body}" stroke-width="{w - 1.6}"/>'
            f'<path d="{d_hi}" fill="none" stroke="{light}" stroke-opacity=".9" stroke-width="1.5" transform="translate({-k} {-k})"/>'
            f'<path d="{d_hi}" fill="none" stroke="{dark}" stroke-opacity=".6" stroke-width="1.3" transform="translate({k} {k})"/>')


def barbell(doc, m, plates, cy=133):
    """Barra con brillo especular y moleteado; discos de canto con surcos
    y el exterior de tres cuartos con anillos concéntricos."""
    light, dark = m["bevel"]
    w, gap, start = (10.5 if plates <= 2 else 9.2), 0.8, 60
    half = start + plates * (w + gap) + 9
    bar_fill = doc.lin([(0, light), (0.3, m["metal"][1][1]), (0.6, m["metal"][2][1]), (1, dark)], 0, 0, 0, 1)
    out = [f'<rect x="{n(CX - half + 1)}" y="{n(cy - 3 + 2.6)}" width="{n(2 * half)}" height="6" rx="3" fill="{m["shadow"]}" opacity=".5"/>',
           f'<rect x="{n(CX - half)}" y="{cy - 3.4}" width="{n(2 * half)}" height="6.8" rx="3.4" fill="{bar_fill}" stroke="{m["shadow"]}" stroke-width="1.4"/>',
           f'<rect x="{n(CX - half + 3)}" y="{cy - 2.2}" width="{n(2 * half - 6)}" height="1.1" rx=".5" fill="{m["specular"]}" opacity=".85"/>']
    for sx in (-1, 1):  # moleteado
        x0 = CX + sx * 40
        out.append(f'<path d="M{n(min(x0, x0 + sx * 14))} {cy + 1.6}h14" stroke="{dark}" stroke-opacity=".45" stroke-width="2.2" stroke-dasharray=".8 1.2"/>')
    pf = doc.lin([(0, dark), (0.25, m["metal"][1][1]), (0.5, m["metal"][4][1]), (0.75, m["metal"][1][1]), (1, dark)], 0, 0, 1, 0)
    face = doc.rad([(0, m["metal"][4][1]), (0.6, m["metal"][1][1]), (1, m["metal"][2][1])], 0.4, 0.35, 0.7)
    for side in (-1, 1):
        x = CX + side * start
        out.append(f'<rect x="{n(x - 2 if side > 0 else x - 2)}" y="{cy - 7}" width="4" height="14" rx="1.2" fill="{metal(doc, m, 0, 1)}" stroke="{dark}" stroke-width=".8"/>')
        x += side * 2
        for k in range(plates):
            h = 64 - k * 5
            x0 = x if side > 0 else x - w
            out.append(f'<rect x="{n(x0 + 1.2)}" y="{n(cy - h / 2 + 2.6)}" width="{n(w)}" height="{n(h)}" rx="3" fill="{m["shadow"]}" opacity=".5"/>'
                       f'<rect x="{n(x0)}" y="{n(cy - h / 2)}" width="{n(w)}" height="{n(h)}" rx="3" fill="{pf}" stroke="{dark}" stroke-width=".9"/>'
                       f'<path d="M{n(x0 + w * 0.3)} {n(cy - h / 2 + 4)}V{n(cy + h / 2 - 4)}M{n(x0 + w * 0.7)} {n(cy - h / 2 + 4)}V{n(cy + h / 2 - 4)}" stroke="{dark}" stroke-opacity=".35" stroke-width=".7"/>')
            x += side * (w + gap)
        # cara del disco exterior en tres cuartos, con anillos concéntricos
        h = 64 - (plates - 1) * 5
        fx = x - side * (gap + w * 0.1)
        rx, ry = w * 0.75, h / 2
        rings = "".join(f'<ellipse cx="{n(fx)}" cy="{cy}" rx="{n(rx * s)}" ry="{n(ry * s)}" fill="none" stroke="{dark}" stroke-opacity=".5" stroke-width=".7"/>'
                        f'<ellipse cx="{n(fx - .5)}" cy="{cy - .7}" rx="{n(rx * s)}" ry="{n(ry * s)}" fill="none" stroke="{light}" stroke-opacity=".5" stroke-width=".5"/>'
                        for s in (0.78, 0.56))
        out.append(f'<ellipse cx="{n(fx)}" cy="{cy}" rx="{n(rx)}" ry="{n(ry)}" fill="{face}" stroke="{dark}" stroke-width=".9"/>{rings}'
                   f'<ellipse cx="{n(fx)}" cy="{cy}" rx="{n(rx * 0.28)}" ry="{n(ry * 0.2)}" fill="{metal(doc, m)}" stroke="{dark}" stroke-width=".6"/>')
        out.append(f'<rect x="{n(x + (0 if side > 0 else -7))}" y="{cy - 3}" width="7" height="6" rx="2" fill="{bar_fill}" stroke="{dark}" stroke-width=".8"/>')
    return "".join(out)


# ------------------------------------------------------------ ornamentos paramétricos
LEAF = "M0 0C{a} {b} {c} {d} {L} 0C{c} {e} {a} {f} 0 0Z"


def leaf_path(L, W):
    return LEAF.format(a=n(L * 0.25), b=n(-W), c=n(L * 0.72), d=n(-W * 0.85), L=n(L), e=n(W * 0.6), f=n(W * 0.75))


def laurel(doc, m, extent=1.0):
    """Hojas individuales a lo largo de una curva, cada una con su
    sombreado (degradado propio, nervio y filo de luz)."""
    lc, mc, sc = m["leaf"]
    shade = doc.lin([(0, lc), (0.45, mc), (1, sc)], 0, 0, 0, 1)
    light, dark = m["bevel"]
    out = []
    rng = doc.rng
    for side in (-1, 1):
        p = [(CX + side * 30, 212), (CX + side * 86, 216), (CX + side * 108, 168), (CX + side * 104, 104)]
        steps = int(15 * extent)
        stem = [_cubic(*p, i / 40) for i in range(int(40 * extent) + 1)]
        out.append(f'<path d="M{" L".join(f"{n(x)} {n(y)}" for x, y in stem)}" fill="none" stroke="{dark}" stroke-width="1.6" stroke-linecap="round"/>')
        for i in range(1, steps + 1):
            t = i / 15
            x, y = _cubic(*p, t)
            x2, y2 = _cubic(*p, min(1, t + 0.01))
            ang = math.degrees(math.atan2(y2 - y, x2 - x))
            L = (21 - 6 * t) * (1 + rng.uniform(-0.06, 0.06))
            for off in (-36, 36):
                a = ang + off * side * -1 + rng.uniform(-3, 3)
                out.append(f'<g transform="translate({n(x)} {n(y)}) rotate({n(a)})">'
                           f'<path d="{leaf_path(L, L * 0.34)}" fill="{shade}" stroke="{dark}" stroke-width=".7"/>'
                           f'<path d="M1.5 0L{n(L * 0.85)} {n(-L * 0.03)}" stroke="{dark}" stroke-opacity=".55" stroke-width=".7"/>'
                           f'<path d="M{n(L * 0.2)} {n(-L * 0.2)}Q{n(L * 0.5)} {n(-L * 0.3)} {n(L * 0.8)} {n(-L * 0.12)}" fill="none" stroke="{light}" stroke-opacity=".75" stroke-width=".6"/></g>')
        x, y = p[3]
        out.append(f'<g transform="translate({n(x)} {n(y)}) rotate({-90 + side * 8})"><path d="{leaf_path(12, 4)}" fill="{shade}" stroke="{dark}" stroke-width=".7"/></g>')
    return f'<g filter="url(#ds)">{"".join(out)}</g>'


# Pluma gorda de punta redondeada (como las de antes), base de todas las alas.
FEATHER = "M0 {a}C{b} {c} {d} {e} {L} {t}Q{L2} {u} {d} {f}C{b} {g} {b0} {h} 0 {h}Z"


def wings(doc, m, rows=2, size=44):
    """Ala heráldica: un brazo curvo desde la esquina del escudo y una pluma
    base repetida a lo largo de él (más larga hacia la punta). Filas: las
    traseras (remeras) más oscuras y largas, las delanteras (coberteras) más
    claras y cortas; variación de ±3° y ±6 %."""
    lc, mc, sc = m["leaf"]
    light, dark = m["bevel"]
    rng = doc.rng
    arm = [(176, 72), (190, 54), (204, 44), (216, 36)]   # hombro -> punta
    rows_cfg = [(1.0, doc.lin([(0, sc), (0.55, mc), (1, mc)], 0, 0, 1, 0), 7, 0.0),
                (0.68, doc.lin([(0, mc), (0.5, lc), (1, lc)], 0, 0, 1, 0), 6, 0.08),
                (0.42, doc.lin([(0, lc), (1, m["specular"])], 0, 0, 1, 0), 5, 0.14)][:rows]
    side = []
    for k, fill, count, lift in rows_cfg:
        for i in range(count):
            t = i / (count - 1)
            x, y = _cubic(*arm, t * (0.92 - lift))
            a = 60 - 52 * t + rng.uniform(-3, 3)              # cuelgan y se abren hacia la punta
            L = size * k * (0.5 + 0.55 * t) * (1 + rng.uniform(-0.06, 0.06))
            W = L * 0.25
            path = FEATHER.format(a=n(-W * 0.45), b=n(L * 0.3), c=n(-W * 1.25), d=n(L * 0.8), e=n(-W * 1.1),
                                  L=n(L), t=n(-W * 0.2), L2=n(L * 1.03), u=n(W * 0.45), f=n(W * 0.75),
                                  g=n(W * 0.95), b0=n(L * 0.1), h=n(W * 0.45))
            barbs = "".join(f'<path d="M{n(L * s_)} {n(-W * 0.1)}l{n(L * 0.07)} {n(-W * 0.55)}" stroke="{dark}" stroke-opacity=".35" stroke-width=".5"/>' for s_ in (0.35, 0.5, 0.65))
            side.append(f'<g transform="translate({n(x)} {n(y)}) rotate({n(a)})">'
                        f'<path d="{path}" fill="{fill}" stroke="{dark}" stroke-width=".7"/>'
                        f'<path d="M1 0L{n(L * 0.92)} 0" stroke="{light}" stroke-opacity=".6" stroke-width=".6"/>{barbs}</g>')
    armd = "M" + " L".join(f"{n(x)} {n(y)}" for x, y in (_cubic(*arm, i / 20) for i in range(19)))
    side.append(f'<path d="{armd}" fill="none" stroke="{dark}" stroke-width="4.4" stroke-linecap="round"/>'
                f'<path d="{armd}" fill="none" stroke="{metal(doc, m, 0, 1)}" stroke-width="3" stroke-linecap="round"/>')
    one = "".join(side)
    return f'<g filter="url(#ds)">{one}<g transform="translate(256 0) scale(-1 1)">{one}</g></g>'


def crown(doc, m, top=46, scale=1.0, points=5):
    """Corona con bisel y gema; `scale` y `points` crecen con el rango."""
    light, dark = m["bevel"]
    body = metal(doc, m, 0, 1)
    g0, g1, g2 = m["gem"]
    gem = doc.rad([(0, g0), (0.4, g1), (1, g2)], 0.35, 0.3, 0.8)
    y0 = top - 1
    half = 18 if points == 5 else 24
    xs = [128 - half + 2 * half * i / (points - 1) for i in range(points)]
    pts = []
    for i, x in enumerate(xs):
        c = abs(i - (points - 1) / 2)
        h = 15 - c * 3.5
        pts.append(f'<path d="M{n(x - 4)} {y0 - 7}L{n(x)} {n(y0 - 7 - h)}L{n(x + 4)} {y0 - 7}Z" fill="{body}" stroke="{dark}" stroke-width=".8"/>'
                   f'<circle cx="{n(x)}" cy="{n(y0 - 7 - h)}" r="{2.6 if c == 0 else 2}" fill="{body}" stroke="{dark}" stroke-width=".7"/>'
                   f'<circle cx="{n(x - .7)}" cy="{n(y0 - 7.7 - h)}" r=".7" fill="{m["specular"]}" opacity=".9"/>')
    band = (f'<rect x="{128 - half - 4}" y="{y0 - 8}" width="{2 * half + 8}" height="8" rx="2" fill="{body}" stroke="{dark}" stroke-width=".9"/>'
            f'<path d="M{128 - half - 2} {y0 - 6.6}H{128 + half + 2}" stroke="{light}" stroke-opacity=".8" stroke-width=".8"/>'
            f'<ellipse cx="128" cy="{y0 - 4}" rx="4" ry="3" fill="{gem}" stroke="{dark}" stroke-width=".6"/>'
            f'<circle cx="127" cy="{y0 - 5}" r=".9" fill="#fff"/>')
    if points > 5:
        band += "".join(f'<circle cx="{n(128 + dx)}" cy="{y0 - 4}" r="1.9" fill="{gem}" stroke="{dark}" stroke-width=".5"/>' for dx in (-14, 14))
    t = f"translate(128 {top}) scale({scale}) translate(-128 {-top})"
    return f'<g filter="url(#ds)" transform="{t}">{"".join(pts)}{band}</g>'


def crystal(doc, m, cx, cy, h):
    """Diamante tallado (cara frontal) sobre la corona."""
    light, dark = m["bevel"]
    g0, g1, g2 = m["gem"]
    w = h * 0.45
    top, mid, bot = (cx, cy - h / 2), cy - h * 0.12, (cx, cy + h / 2)
    left, right = (cx - w, mid), (cx + w, mid)
    tl, tr = (cx - w * 0.45, cy - h / 2 + h * 0.12), (cx + w * 0.45, cy - h / 2 + h * 0.12)
    faces = [([tl, tr, (cx, mid)], g0), ([left, tl, (cx, mid)], g1), ([right, tr, (cx, mid)], g0),
             ([left, (cx, mid), bot], g1), ([right, (cx, mid), bot], g2)]
    out = "".join(f'<path d="M{" L".join(f"{n(x)} {n(y)}" for x, y in pts)}Z" fill="{c}" stroke="{dark}" stroke-width=".5"/>' for pts, c in faces)
    outline = [left, tl, tr, right, bot]
    return (f'<g filter="url(#ds)">{out}<path d="M{" L".join(f"{n(x)} {n(y)}" for x, y in outline)}Z" fill="none" stroke="{dark}" stroke-width="1"/>'
            f'<path d="M{n(tl[0] + 1)} {n(tl[1] + 2)}l3 4" stroke="#fff" stroke-width="1.2" stroke-linecap="round"/></g>')


def rivets(doc, m, count=16, f=0.935, r=3.3):
    """Remaches del marco (hierro y bronce): cabeza abombada con su sombra."""
    light, dark = m["bevel"]
    g = doc.rad([(0, m["specular"]), (0.3, m["metal"][0][1]), (0.7, m["metal"][1][1]), (1, m["metal"][2][1])], 0.35, 0.3, 0.75)
    out = []
    for x, y, _, _ in shield_points(count, f):
        out.append(f'<circle cx="{n(x + 0.8)}" cy="{n(y + 1.3)}" r="{r}" fill="{m["shadow"]}" opacity=".6"/>'
                   f'<circle cx="{n(x)}" cy="{n(y)}" r="{r}" fill="{g}" stroke="{dark}" stroke-width=".6"/>')
    return "".join(out)


def wear(doc, m, count=18):
    """Arañazos y desgaste en el campo (hierro y bronce)."""
    light, dark = m["bevel"]
    rng = doc.rng
    out = []
    for _ in range(count):
        x, y = rng.uniform(80, 176), rng.uniform(56, 186)
        L, a = rng.uniform(4, 11), rng.uniform(-40, 40)
        out.append(f'<path d="M{n(x)} {n(y)}l{n(L * math.cos(math.radians(a)))} {n(L * math.sin(math.radians(a)))}" '
                   f'stroke="{light if rng.random() < .5 else dark}" stroke-opacity=".35" stroke-width=".6" stroke-linecap="round"/>')
    return f'<g clip-path="{doc.clip(SHIELD, inset(RIM))}">{"".join(out)}</g>'


PETAL = "M0 0C{a} {b} {c} {d} {L} 0C{c} {e} {a} {f} 0 0Z"


def rosette(doc, m, x, y, r=9):
    """Roseta: simetría radial de 8 pétalos en dos capas desfasadas 22,5°,
    con anillo central y gema."""
    lc, mc, sc = m["leaf"]
    light, dark = m["bevel"]
    back = doc.lin([(0, sc), (1, mc)], 0, 0, 1, 0)
    front = doc.lin([(0, mc), (1, lc)], 0, 0, 1, 0)
    g0, g1, g2 = m["gem"]
    gem = doc.rad([(0, g0), (0.45, g1), (1, g2)], 0.35, 0.3, 0.8)

    def petals(L, rot, fill):
        p = PETAL.format(a=n(L * 0.3), b=n(-L * 0.32), c=n(L * 0.8), d=n(-L * 0.22), L=n(L), e=n(L * 0.22), f=n(L * 0.32))
        return "".join(f'<path d="{p}" transform="rotate({n(rot + i * 45)})" fill="{fill}" stroke="{dark}" stroke-width=".5"/>' for i in range(8))
    return (f'<g filter="url(#ds)" transform="translate({n(x)} {n(y)})">{petals(r, 0, back)}{petals(r * 0.72, 22.5, front)}'
            f'<circle r="{n(r * 0.36)}" fill="{metal(doc, m)}" stroke="{dark}" stroke-width=".7"/>'
            f'<circle r="{n(r * 0.22)}" fill="{gem}"/><circle cx="-.6" cy="-.7" r=".6" fill="#fff"/></g>')


def floral(doc, m, count=10, f=0.93):
    """Filigrana floral en el marco: florecillas de 5 pétalos sobre el perlado."""
    lc, mc, sc = m["leaf"]
    light, dark = m["bevel"]
    fill = doc.lin([(0, lc), (1, mc)], 0, 0, 1, 0)
    g0, g1, g2 = m["gem"]
    gem = doc.rad([(0, g0), (0.45, g1), (1, g2)], 0.35, 0.3, 0.8)
    out = []
    pts = shield_points(count * 2, f)
    for x, y, _, _ in pts[1::2]:
        p = PETAL.format(a="1.2", b="-1.6", c="3.4", d="-1.2", L="4.2", e="1.2", f="1.6")
        petals = "".join(f'<path d="{p}" transform="rotate({i * 72 - 90})" fill="{fill}" stroke="{dark}" stroke-width=".4"/>' for i in range(5))
        out.append(f'<g transform="translate({n(x)} {n(y)})">{petals}<circle r="1.5" fill="{gem}" stroke="{dark}" stroke-width=".3"/></g>')
    return f'<g filter="url(#ds)">{"".join(out)}</g>'


def rays(doc, m, count=20):
    """Rayos de luz detrás del emblema (Titán)."""
    glow = m.get("glow", m["gem"][1])
    fade = doc.rad([(0, glow, 0.6), (0.55, glow, 0.25), (1, glow, 0)], 0.5, 0.5, 0.5)
    tri = []
    for i in range(count):
        a = math.radians(i * 360 / count)
        a0, a1 = a - 0.07, a + 0.07
        tri.append(f"M128 118L{n(128 + 128 * math.sin(a0))} {n(118 - 128 * math.cos(a0))}L{n(128 + 128 * math.sin(a1))} {n(118 - 128 * math.cos(a1))}Z")
    return f'<path d="{" ".join(tri)}" fill="{fade}"/>'


def halo(doc, m, op=0.5):
    glow = m.get("glow", m["gem"][1])
    g = doc.rad([(0, glow, op), (0.45, glow, op * 0.4), (1, glow, 0)], 0.5, 0.5, 0.5)
    return f'<circle cx="128" cy="118" r="126" fill="{g}"/>'


def sparkles(m, points):
    out = []
    for x, y, r in points:
        out.append(f'<path d="M{x} {y - r}Q{x} {y} {x + r} {y}Q{x} {y} {x} {y + r}Q{x} {y} {x - r} {y}Q{x} {y} {x} {y - r}Z" fill="{m["specular"]}" opacity=".95"/>')
    return "".join(out)


def numeral_glyphs(x, y, h=12):
    w, sw = 3.2, 7.4
    return (f'<rect x="{n(x - w / 2)}" y="{n(y)}" width="{w}" height="{h}"/>'
            f'<rect x="{n(x - sw / 2)}" y="{n(y)}" width="{sw}" height="1.7" rx=".5"/>'
            f'<rect x="{n(x - sw / 2)}" y="{n(y + h - 1.7)}" width="{sw}" height="1.7" rx=".5"/>')


def ribbon(doc, m, division, y=192):
    """Cinta con pliegues, sombra interior y sombra proyectada; numeral
    grabado con relieve (Titán: estrella). En II y III, gemas a los lados."""
    c0, c1, c2 = m["cloth"]
    light, dark = m["bevel"]
    cloth = doc.lin([(0, c0), (0.55, c1), (1, c2)], 0, 0, 0, 1)
    tail = doc.lin([(0, c1), (1, c2)], 0, 0, 0, 1)
    band = f"M54 {y}Q128 {y + 18} 202 {y}L202 {y + 21}Q128 {y + 39} 54 {y + 21}Z"
    tails = (f'<path d="M60 {y + 5}L36 {y + 10}L45 {y + 19}L34 {y + 29}L62 {y + 28}Z" fill="{tail}" stroke="{dark}" stroke-width=".9"/>'
             f'<path d="M196 {y + 5}L220 {y + 10}L211 {y + 19}L222 {y + 29}L194 {y + 28}Z" fill="{tail}" stroke="{dark}" stroke-width=".9"/>'
             f'<path d="M54 {y + 21}L64 {y + 29}L61 {y + 17}Z" fill="{c2}" stroke="{dark}" stroke-width=".6"/>'
             f'<path d="M202 {y + 21}L192 {y + 29}L195 {y + 17}Z" fill="{c2}" stroke="{dark}" stroke-width=".6"/>')
    folds = "".join(f'<path d="M{x} {n(y + 1 + (1 - ((x - 128) / 74) ** 2) * 9)}q{d_} 10 0 21" fill="none" stroke="{c2}" stroke-opacity=".7" stroke-width="1.6"/>'
                    f'<path d="M{x + 2} {n(y + 1 + (1 - ((x - 128) / 74) ** 2) * 9)}q{d_} 10 0 21" fill="none" stroke="#fff" stroke-opacity=".18" stroke-width="1"/>'
                    for x, d_ in ((72, 3), (184, -3)))
    gloss = doc.lin([(0, "#fff", 0), (0.25, "#fff", 0.22), (0.45, "#fff", 0), (1, "#fff", 0)], 0, 0, 0, 1)
    inner = doc.clip(band)
    shade = (f'<g clip-path="{inner}"><path d="M54 {y - 2}Q128 {y + 16} 202 {y - 2}" fill="none" stroke="{m["shadow"]}" stroke-opacity=".55" stroke-width="5"/>'
             f'<path d="M54 {y + 22}Q128 {y + 40} 202 {y + 22}" fill="none" stroke="#000" stroke-opacity=".25" stroke-width="3"/></g>')
    edge = f'<path d="M58 {y + 4}Q128 {y + 21.5} 198 {y + 4}" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width=".9"/>'
    if division:
        xs = [128 + (i - (division - 1) / 2) * 8.6 for i in range(division)]
        glyphs = "".join(numeral_glyphs(x, y + 13) for x in xs)
    else:  # Titán: estrella de ocho puntas
        pts = []
        for i in range(16):
            r = 8 if i % 2 == 0 else 3.2
            a = math.radians(i * 22.5)
            pts.append(f"{n(128 + r * math.sin(a))} {n(y + 19 - r * math.cos(a))}")
        glyphs = f'<path d="M{" L".join(pts)}Z"/>'
    ink = m.get("ink") or metal(doc, m, 0, 1)
    num = (f'<g fill="{m["shadow"]}" opacity=".75" transform="translate(.6 1)">{glyphs}</g>'
           f'<g fill="{light}" opacity=".6" transform="translate(-.5 -.6)">{glyphs}</g>'
           f'<g fill="{ink}">{glyphs}</g>')
    studs = ""
    if division and division >= 2:
        g0, g1, g2 = m["gem"]
        gem = doc.rad([(0, g0), (0.45, g1), (1, g2)], 0.35, 0.3, 0.8)
        for k in range(division - 1):
            for side in (-1, 1):
                x = 128 + side * (34 + k * 12)
                yy = y + 19 + (1 - ((x - 128) / 74) ** 2) * 8 - 8
                studs += (f'<circle cx="{n(x)}" cy="{n(yy + .7)}" r="2.6" fill="{m["shadow"]}" opacity=".5"/>'
                          f'<circle cx="{n(x)}" cy="{n(yy)}" r="2.6" fill="{metal(doc, m)}" stroke="{dark}" stroke-width=".5"/>'
                          f'<circle cx="{n(x)}" cy="{n(yy)}" r="1.6" fill="{gem}"/><circle cx="{n(x - .5)}" cy="{n(yy - .6)}" r=".45" fill="#fff"/>')
    cast = f'<path d="{band}" fill="#000" opacity=".45" transform="translate(0 4)" filter="url(#blur3)"/>'
    return f'{cast}{tails}<path d="{band}" fill="{cloth}" stroke="{dark}" stroke-width="1"/><path d="{band}" fill="{gloss}"/>{folds}{shade}{edge}{studs}{num}'


# ------------------------------------------------------------ rangos
# plates: discos por lado; scale: tamaño del escudo (baja cuando crecen
# las alas, para que quepan); wings: (filas, tamaño); laurel: alcance;
# crown: (escala, puntas) o None.
RANK_CFG = {
    "hierro":    dict(tier=0, plates=1, scale=0.92, wings=None, laurel=0.85, crown=None, frame="rivets"),
    "bronce":    dict(tier=1, plates=1, scale=0.92, wings=None, laurel=1.0, crown=None, frame="rivets"),
    "plata":     dict(tier=2, plates=2, scale=0.9, wings=(1, 36), laurel=1.0, crown=(0.85, 5), frame="beads"),
    "oro":       dict(tier=3, plates=2, scale=0.9, wings=(2, 44), laurel=1.0, crown=(1.0, 5), frame="beads"),
    "platino":   dict(tier=4, plates=3, scale=0.88, wings=(3, 44), laurel=1.0, crown=(1.0, 5), frame="beads", rosettes=True),
    "diamante":  dict(tier=5, plates=3, scale=0.87, wings=(3, 47), laurel=1.0, crown=(1.0, 5), frame="beads", rosettes=True, crystal=True),
    "esmeralda": dict(tier=6, plates=4, scale=0.86, wings=(3, 50), laurel=1.0, crown=(1.05, 5), frame="beads", rosettes=True, floral=True),
    "campeon":   dict(tier=7, plates=4, scale=0.85, wings=(3, 52), laurel=1.0, crown=(1.25, 7), frame="beads", rosettes=True, floral=True),
    "titan":     dict(tier=8, plates=5, scale=0.84, wings=(3, 54), laurel=1.0, crown=(1.25, 7), frame="beads", rosettes=True, floral=True, rays=True),
}


def build(key, division):
    m = MATERIALS[key]
    cfg = RANK_CFG[key]
    doc = Doc(key)
    scale = cfg["scale"]
    back = []
    if cfg.get("rays"):
        back.append(halo(doc, m, 0.55) + rays(doc, m))
    elif division == 3 and cfg["tier"] >= 5:
        back.append(halo(doc, m, 0.45))
    inner = []
    if cfg["wings"]:
        rows, size = cfg["wings"]
        inner.append(wings(doc, m, rows=rows, size=size))
    inner.append(laurel(doc, m, cfg["laurel"]))
    inner += [frame(doc, m), rivets(doc, m) if cfg["frame"] == "rivets" else beads(doc, m), field(doc, m)]
    if cfg["tier"] <= 1:
        inner.append(wear(doc, m))
    inner += [filigree(doc, m), specular(doc, m), barbell(doc, m, cfg["plates"]), g_mark(doc, m)]
    if cfg.get("floral"):
        inner.append(floral(doc, m))
    if cfg.get("rosettes"):
        inner.append(rosette(doc, m, 66, 48) + rosette(doc, m, 190, 48))
    if cfg["crown"]:
        sc, pts = cfg["crown"]
        inner.append(crown(doc, m, 46, sc, pts))
        if cfg.get("crystal"):
            inner.append(crystal(doc, m, 128, 46 - 30 * sc, 16))
    if division == 3 and cfg["tier"] >= 6:
        inner.append(sparkles(m, [(56, 70, 6), (200, 82, 4.5), (50, 170, 4.5), (206, 176, 6)]))
    body = f'<g transform="{inset(scale)}">{"".join(inner)}</g>'
    div = None if key == "titan" else division
    return doc.svg("".join(back) + body + ribbon(doc, m, div, y=CY + (202 - CY) * scale - 8))


if __name__ == "__main__":
    out = PREVIEW if "--preview" in sys.argv else OUT
    os.makedirs(out, exist_ok=True)
    total = 0
    for key in RANK_CFG:
        for div in ((3,) if key == "titan" else (1, 2, 3)):
            name = "titan" if key == "titan" else f"{key}-{div}"
            path = os.path.join(out, f"{name}.svg")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(build(key, div))
            total += os.path.getsize(path)
    print("ok", out, round(total / 1024), "KB")
