"""Emblemas de rango v3: app/static/ranks/<rango>-<división>.svg (y titan.svg).

Estilo de insignia de gimnasio: escudo metálico con biselado, placa con el
nombre, motivo de fuerza en el centro y adornos que crecen con el rango.
Cada división mejora el emblema del mismo rango:
  I   base
  II  + adornos laterales (laurel/gemas/remaches dorados) + 2 estrellas
  III + aura, destellos animados, brillo que recorre el escudo + 3 estrellas
"""
import math
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "static", "ranks")
os.makedirs(OUT, exist_ok=True)

SHIELD = ("M50 40 Q100 28 150 40 L162 48 L160 104 C158 144 132 166 100 180 "
          "C68 166 42 144 40 104 L38 48 Z")
INNER = ("M56 50 Q100 40 144 50 L151 56 L150 104 C148 137 127 155 100 167 "
         "C73 155 52 137 50 104 L49 56 Z")

# metal: (claro, medio, oscuro, borde, texto placa, color motivo, aura)
METALS = {
    "hierro":    ("#c9cdd3", "#6d737c", "#33373e", "#1e2126", "#e7e9ec", "#d9dce1", "#8a9099"),
    "bronce":    ("#ffd0a1", "#c4743a", "#6e3812", "#45210a", "#ffe2c4", "#ffd9b3", "#ff9a4d"),
    "plata":     ("#ffffff", "#c3cad6", "#727d8f", "#3e4554", "#f7f9fc", "#ffffff", "#b9d4ff"),
    "oro":       ("#fff4c2", "#e6b52c", "#8f6406", "#5c3f00", "#fff6d6", "#fff3c4", "#ffcc33"),
    "platino":   ("#f4fbff", "#b8c9d9", "#5c7287", "#2c3b4a", "#ffffff", "#eef6ff", "#7fd0ff"),
    "diamante":  ("#ffffff", "#cfe6ff", "#6f93c9", "#2a4472", "#ffffff", "#ffffff", "#8ec5ff"),
    "esmeralda": ("#c9ffe0", "#1fae64", "#0a5a31", "#063b20", "#eafff3", "#d9ffe9", "#33e08a"),
    "campeon":   ("#ffd6e8", "#c2185b", "#6a0a32", "#3d051c", "#fff0f6", "#ffe3ef", "#ff4f9a"),
    "titan":     ("#c9c4d6", "#4b4458", "#1c1823", "#0b090f", "#ffe1b0", "#ffd28a", "#ff7a1a"),
}
NAMES = {"hierro": "HIERRO", "bronce": "BRONCE", "plata": "PLATA", "oro": "ORO", "platino": "PLATINO",
         "diamante": "DIAMANTE", "esmeralda": "ESMERALDA", "campeon": "CAMPEÓN", "titan": "TITÁN"}
GOLD = ("#fff3c4", "#e6b52c", "#8f6406", "#5c3f00")


def grad(gid, stops, vertical=True):
    x2, y2 = ("0", "1") if vertical else ("1", "0")
    s = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
    return f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">{s}</linearGradient>'


def star(cx, cy, r, fill, stroke="none", inner=0.45, n=5):
    pts = []
    for i in range(n * 2):
        rr = r if i % 2 == 0 else r * inner
        a = -math.pi / 2 + math.pi * i / n
        pts.append(f"{cx + rr * math.cos(a):.1f},{cy + rr * math.sin(a):.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'


def sparkle(cx, cy, r, delay):
    d = (f"M{cx} {cy - r} Q{cx} {cy} {cx + r} {cy} Q{cx} {cy} {cx} {cy + r} "
         f"Q{cx} {cy} {cx - r} {cy} Q{cx} {cy} {cx} {cy - r} Z")
    return f'<path class="tw" style="animation-delay:{delay}s" d="{d}" fill="#fff"/>'


def laurel(fill, edge, n=9, spread=1.0):
    out = []
    for side in (-1, 1):
        out.append(f'<path d="M{100 + side * 22} 184 Q{100 + side * 66 * spread} 160 {100 + side * 64 * spread} 96" '
                   f'fill="none" stroke="{edge}" stroke-width="2.5"/>')
        for i in range(n):
            t = i / (n - 1)
            x = 100 + side * (24 + 42 * spread * math.sin(t * math.pi / 2))
            y = 182 - 86 * t
            ang = (-28 - 52 * t) * side
            out.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="6" ry="12.5" fill="{fill}" stroke="{edge}" '
                       f'stroke-width="1.4" transform="rotate({ang:.0f} {x:.1f} {y:.1f})"/>')
    return "".join(out)


def gem(cx, cy, r, color, dark):
    pts = f"{cx},{cy - r} {cx + r * .85},{cy - r * .2} {cx + r * .55},{cy + r} {cx - r * .55},{cy + r} {cx - r * .85},{cy - r * .2}"
    return (f'<polygon points="{pts}" fill="{color}" stroke="{dark}" stroke-width="1.6"/>'
            f'<path d="M{cx - r * .85} {cy - r * .2} H{cx + r * .85} M{cx} {cy - r} L{cx - r * .3} {cy - r * .2} L{cx} {cy + r} L{cx + r * .3} {cy - r * .2} Z" '
            f'fill="none" stroke="#fff" stroke-width="1" opacity=".7"/>'
            f'<circle cx="{cx - r * .35}" cy="{cy - r * .45}" r="{r * .18:.1f}" fill="#fff" opacity=".9"/>')


def wings(fill, edge):
    out = []
    for side in (-1, 1):
        for k in range(3):
            base_y = 66 + k * 18
            tip_x = 100 + side * (90 - k * 6)
            mid_x = 100 + side * (70 - k * 4)
            d = (f"M{100 + side * 46} {base_y} C{mid_x} {base_y - 26} {tip_x} {base_y - 30 + k * 6} {tip_x + side * 4} {base_y - 14 + k * 8} "
                 f"C{tip_x - side * 6} {base_y - 2 + k * 4} {mid_x} {base_y + 14} {100 + side * 46} {base_y + 20} Z")
            out.append(f'<path d="{d}" fill="{fill}" stroke="{edge}" stroke-width="2" stroke-linejoin="round" opacity="{1 - k * .1:.2f}"/>')
            out.append(f'<path d="M{100 + side * 48} {base_y + 8} Q{mid_x} {base_y - 6} {tip_x} {base_y - 16 + k * 7}" stroke="#fff" stroke-width="1.4" fill="none" opacity=".5"/>')
    return "".join(out)


# ---------------------------------------------------------------- motivos
def plates(x, y, side, fill, edge, n=2):
    out = []
    for i in range(n):
        h = 30 - i * 7
        px = x + side * i * 7
        out.append(f'<rect x="{px - 3.5:.1f}" y="{y - h / 2:.1f}" width="7" height="{h}" rx="2" fill="{fill}" stroke="{edge}" stroke-width="1.5"/>')
    return "".join(out)


def dumbbell(fill, edge):
    return (f'<rect x="70" y="112" width="60" height="7" rx="3" fill="{fill}" stroke="{edge}" stroke-width="1.5"/>'
            + plates(72, 115.5, -1, fill, edge, 3) + plates(128, 115.5, 1, fill, edge, 3))


def barbell(y, fill, edge, n=3, x1=58, x2=142):
    return (f'<rect x="{x1}" y="{y - 3}" width="{x2 - x1}" height="6" rx="3" fill="{fill}" stroke="{edge}" stroke-width="1.3"/>'
            + plates(x1 + 10, y, -1, fill, edge, n) + plates(x2 - 10, y, 1, fill, edge, n))


def kettlebell(fill, edge):
    return (f'<circle cx="100" cy="122" r="22" fill="none" stroke="{edge}" stroke-width="5" stroke-dasharray="5 4" opacity=".75"/>'
            f'<path d="M88 112 Q88 96 100 96 Q112 96 112 112" fill="none" stroke="{fill}" stroke-width="6" stroke-linecap="round"/>'
            f'<circle cx="100" cy="126" r="15" fill="{fill}" stroke="{edge}" stroke-width="2"/>'
            f'<ellipse cx="94" cy="120" rx="4" ry="6" fill="#fff" opacity=".35"/>')


def figure(fill, edge, pose):
    """Silueta de atleta. pose: 'flex' (doble bíceps), 'press' (barra arriba), 'atlas' (sujeta el mundo)."""
    cx, top = 100, 92
    parts = [f'<circle cx="{cx}" cy="{top}" r="7.5" fill="{fill}" stroke="{edge}" stroke-width="1.5"/>']
    torso = (f"M{cx - 11} {top + 9} L{cx + 11} {top + 9} L{cx + 17} {top + 13} L{cx + 12} {top + 34} "
             f"L{cx + 8} {top + 46} L{cx - 8} {top + 46} L{cx - 12} {top + 34} L{cx - 17} {top + 13} Z")
    parts.append(f'<path d="{torso}" fill="{fill}" stroke="{edge}" stroke-width="1.5" stroke-linejoin="round"/>')
    parts.append(f'<path d="M{cx} {top + 16} V{top + 42} M{cx - 7} {top + 24} H{cx + 7} M{cx - 6} {top + 31} H{cx + 6} '
                 f'M{cx - 12} {top + 16} Q{cx - 6} {top + 21} {cx} {top + 17} Q{cx + 6} {top + 21} {cx + 12} {top + 16}" '
                 f'fill="none" stroke="{edge}" stroke-width="1.3" opacity=".6"/>')
    leg = lambda s: (f'<path d="M{cx + s * 5} {top + 45} L{cx + s * 9} {top + 70} L{cx + s * 7} {top + 82}" fill="none" '
                     f'stroke="{fill}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>')
    leg_edge = lambda s: (f'<path d="M{cx + s * 5} {top + 45} L{cx + s * 9} {top + 70} L{cx + s * 7} {top + 82}" fill="none" '
                          f'stroke="{edge}" stroke-width="11.5" stroke-linecap="round" stroke-linejoin="round"/>')
    if pose == "atlas":
        leg = lambda s: (f'<path d="M{cx + s * 5} {top + 45} L{cx + s * 14} {top + 62} L{cx + s * (4 if s < 0 else 12)} {top + 80}" fill="none" '
                         f'stroke="{fill}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>')
        leg_edge = lambda s: (f'<path d="M{cx + s * 5} {top + 45} L{cx + s * 14} {top + 62} L{cx + s * (4 if s < 0 else 12)} {top + 80}" fill="none" '
                              f'stroke="{edge}" stroke-width="11.5" stroke-linecap="round" stroke-linejoin="round"/>')
    arms = []
    for s in (-1, 1):
        if pose == "flex":
            d = f"M{cx + s * 15} {top + 13} L{cx + s * 30} {top + 13} L{cx + s * 31} {top - 6}"
            bic = f'<ellipse cx="{cx + s * 24}" cy="{top + 9}" rx="7" ry="5.5" fill="{fill}" stroke="{edge}" stroke-width="1.3"/>'
            fist = f'<circle cx="{cx + s * 31}" cy="{top - 9}" r="5" fill="{fill}" stroke="{edge}" stroke-width="1.3"/>'
        elif pose == "press":
            d = f"M{cx + s * 15} {top + 13} L{cx + s * 24} {top - 2} L{cx + s * 26} {top - 22}"
            bic = ""
            fist = f'<circle cx="{cx + s * 26}" cy="{top - 24}" r="4.5" fill="{fill}" stroke="{edge}" stroke-width="1.3"/>'
        else:  # atlas
            d = f"M{cx + s * 15} {top + 13} L{cx + s * 24} {top - 4} L{cx + s * 18} {top - 18}"
            bic = ""
            fist = ""
        arms.append(f'<path d="{d}" fill="none" stroke="{edge}" stroke-width="10.5" stroke-linecap="round" stroke-linejoin="round"/>'
                    f'<path d="{d}" fill="none" stroke="{fill}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>{bic}{fist}')
    out = leg_edge(-1) + leg_edge(1) + leg(-1) + leg(1) + "".join(arms) + "".join(parts)
    if pose == "press":
        out = barbell(top - 24, fill, edge, n=3, x1=56, x2=144) + out
    if pose == "atlas":
        g = (f'<circle cx="{cx}" cy="{top - 32}" r="22" fill="#2b5fa8" stroke="{edge}" stroke-width="2"/>'
             f'<path d="M{cx - 14} {top - 44} q8 6 4 14 q-6 6 2 12 M{cx + 6} {top - 50} q6 8 0 14 q-4 6 6 10" fill="none" stroke="#7fd36b" stroke-width="5" stroke-linecap="round"/>'
             f'<ellipse cx="{cx}" cy="{top - 32}" rx="22" ry="8" fill="none" stroke="#bcd8ff" stroke-width="1" opacity=".6"/>'
             f'<ellipse cx="{cx}" cy="{top - 32}" rx="9" ry="22" fill="none" stroke="#bcd8ff" stroke-width="1" opacity=".6"/>'
             f'<circle cx="{cx - 8}" cy="{top - 42}" r="5" fill="#fff" opacity=".3"/>')
        out = g + out
    t = {"atlas": "translate(100 127) scale(.66) translate(-100 -112)",
         "press": "translate(100 121) scale(.72) translate(-100 -112)"}.get(pose, "translate(100 112) scale(.82) translate(-100 -112)")
    return f'<g transform="{t}">{out}</g>'


# ---------------------------------------------------------------- emblema
def emblem(key, div):
    light, mid, dark, edge, plate_txt, motif, aura = METALS[key]
    gid = lambda n: f"{key}{div}_{n}"
    rich = key in ("oro", "platino", "diamante", "esmeralda", "campeon", "titan")
    defs = [
        grad(gid("rim"), [(0, light), (0.35, mid), (0.55, light), (1, dark)]),
        grad(gid("field"), [(0, mid), (0.5, dark), (1, edge)]),
        grad(gid("plate"), [(0, dark), (0.5, edge), (1, dark)]),
        grad(gid("motif"), [(0, "#ffffff"), (0.4, motif), (1, mid)]),
        grad(gid("gold"), [(0, GOLD[0]), (0.45, GOLD[1]), (1, GOLD[2])]),
        f'<clipPath id="{gid("clip")}"><path d="{INNER}"/></clipPath>',
        f'<radialGradient id="{gid("aura")}"><stop offset="0" stop-color="{aura}" stop-opacity=".85"/>'
        f'<stop offset=".55" stop-color="{aura}" stop-opacity=".25"/><stop offset="1" stop-color="{aura}" stop-opacity="0"/></radialGradient>',
        '<linearGradient id="%s" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
        '<stop offset=".5" stop-color="#fff" stop-opacity=".65"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>' % gid("shine"),
        '<linearGradient id="%s" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#ff3d00"/>'
        '<stop offset=".5" stop-color="#ff8f00"/><stop offset="1" stop-color="#ffe082"/></linearGradient>' % gid("fire"),
    ]
    style = ("<style>.tw{animation:tw 2.2s ease-in-out infinite;transform-box:fill-box;transform-origin:center}"
             "@keyframes tw{0%,100%{opacity:.1;transform:scale(.5)}50%{opacity:1;transform:scale(1)}}"
             ".sh{animation:sh 3.4s ease-in-out infinite}@keyframes sh{0%{transform:translateX(-170px)}60%,100%{transform:translateX(170px)}}"
             ".au{animation:au 2.6s ease-in-out infinite;transform-origin:100px 105px}"
             "@keyframes au{0%,100%{opacity:.7;transform:scale(.95)}50%{opacity:1;transform:scale(1.04)}}"
             ".fl{animation:fl .9s ease-in-out infinite alternate;transform-box:fill-box;transform-origin:50% 100%}"
             "@keyframes fl{from{transform:scaleY(.86) skewX(-3deg)}to{transform:scaleY(1.08) skewX(3deg)}}"
             "@media (prefers-reduced-motion:reduce){.tw,.sh,.au,.fl{animation:none}}</style>")
    p = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200" role="img" '
         f'aria-label="Rango {NAMES[key].lower()}{"" if key == "titan" else " " + "I" * div}">', style, "<defs>" + "".join(defs) + "</defs>"]

    # ---- fondo: aura (III, y siempre en Titán) y fuego
    if div == 3 or key == "titan":
        p.append(f'<circle class="au" cx="100" cy="105" r="98" fill="url(#{gid("aura")})"/>')
    if key == "titan":
        for i, (x, h) in enumerate([(46, 70), (60, 92), (140, 92), (154, 70), (100, 40), (76, 60), (124, 60)]):
            p.append(f'<path class="fl" style="animation-delay:{i * 0.13:.2f}s" d="M{x - 11} 184 C{x - 20} {184 - h * .45} {x - 4} {184 - h * .6} {x} {184 - h} '
                     f'C{x + 5} {184 - h * .62} {x + 20} {184 - h * .45} {x + 11} 184 C{x + 5} 190 {x - 5} 190 {x - 11} 184 Z" fill="url(#{gid("fire")})" opacity=".92"/>')
    # ---- alas (división III, desde Plata; Titán siempre)
    if (div == 3 and key not in ("hierro", "bronce")) or key == "titan":
        p.append(wings(f"url(#{gid('rim')})", edge))
    # ---- laurel (desde Bronce; más grande en II/III)
    if key not in ("hierro",):
        if key in ("oro", "campeon", "titan", "esmeralda"):
            p.append(laurel(f"url(#{gid('gold')})", GOLD[3], 9 if div > 1 else 7, 1.05 if div > 1 else .95))
        elif div >= 2 or key in ("plata", "platino", "diamante"):
            p.append(laurel(light, edge, 8 if div > 1 else 6, 1.0 if div > 1 else .92))
    # ---- corona (Campeón y Titán)
    if key in ("campeon", "titan"):
        p.append(f'<path d="M70 38 L75 12 L88 26 L100 4 L112 26 L125 12 L130 38 Z" fill="url(#{gid("gold")})" stroke="{GOLD[3]}" stroke-width="2" stroke-linejoin="round"/>'
                 + gem(75, 14, 4.5, "#ff3d6e", "#7a0022") + gem(100, 7, 5.5, "#40c4ff", "#01579b") + gem(125, 14, 4.5, "#3ddc84", "#0b5a31"))
    # ---- escudo
    p.append(f'<path d="{SHIELD}" transform="translate(0 5)" fill="#000" opacity=".35"/>')
    p.append(f'<path d="{SHIELD}" fill="url(#{gid("rim")})" stroke="{edge}" stroke-width="3" stroke-linejoin="round"/>')
    p.append(f'<path d="{INNER}" fill="url(#{gid("field")})" stroke="{dark}" stroke-width="2"/>')
    p.append(f'<g clip-path="url(#{gid("clip")})">')
    p.append('<path d="M40 40 L160 40 L160 82 C130 70 70 70 40 88 Z" fill="#fff" opacity=".12"/>')
    if key == "hierro":  # óxido
        for x, y, r in [(70, 140, 9), (128, 120, 7), (84, 72, 6), (118, 150, 8), (62, 104, 5)]:
            p.append(f'<ellipse cx="{x}" cy="{y}" rx="{r}" ry="{r * .7:.1f}" fill="#8a4b1f" opacity=".45"/>')
    if key == "diamante":  # facetas
        p.append('<path d="M50 60 L100 110 L150 60 M50 150 L100 110 L150 150 M100 40 V170" stroke="#fff" stroke-width="1.2" opacity=".25" fill="none"/>')
    if div == 3 or key == "titan":
        p.append(f'<rect class="sh" x="40" y="20" width="46" height="180" fill="url(#{gid("shine")})" transform="skewX(-18)"/>')
    p.append("</g>")
    # remaches / tachuelas en el borde
    if key in ("hierro", "bronce") or (div >= 2 and key in ("plata",)):
        stud = "#e6b52c" if div >= 2 else light
        for x, y in [(52, 46), (148, 46), (44, 78), (156, 78), (46, 112), (154, 112), (60, 146), (140, 146)]:
            p.append(f'<circle cx="{x}" cy="{y}" r="3.2" fill="{stud}" stroke="{edge}" stroke-width="1.2"/>')
    if key == "diamante":
        for i in range(18):
            t = i / 17
            # tachuelas de diamante a lo largo del borde
            ang = math.pi * (1.05 + 0.9 * t)
            x = 100 + 58 * math.cos(ang) * (1 if t < .5 else 1)
        for x, y in [(52, 48), (68, 42), (84, 38), (100, 36), (116, 38), (132, 42), (148, 48), (44, 70), (156, 70),
                     (44, 94), (156, 94), (48, 118), (152, 118), (58, 140), (142, 140), (74, 158), (126, 158), (100, 172)]:
            p.append(f'<circle cx="{x}" cy="{y}" r="2.6" fill="#fff" stroke="#9cc3ff" stroke-width=".8"/>')
    # ---- motivo central
    m_fill, m_edge = f"url(#{gid('motif')})", edge
    if key == "hierro":
        p.append('<g transform="translate(0 4)">' + dumbbell(m_fill, m_edge) + "</g>")
    elif key == "bronce":
        p.append(kettlebell(m_fill, m_edge))
    elif key == "plata":
        p.append(figure(m_fill, m_edge, "press"))
    elif key == "oro":
        p.append(barbell(124, m_fill, m_edge, n=3, x1=56, x2=144) + star(100, 102, 14, f"url(#{gid('gold')})", GOLD[3]))
    elif key in ("platino", "esmeralda", "campeon"):
        p.append(figure(m_fill, m_edge, "flex"))
    elif key == "diamante":
        p.append(figure(m_fill, m_edge, "press"))
    elif key == "titan":
        p.append(figure(m_fill, m_edge, "atlas"))
    # ---- placa con el nombre
    p.append(f'<path d="M46 60 H154 L162 69 L154 78 H46 L38 69 Z" fill="url(#{gid("plate")})" stroke="{light}" stroke-width="1.6"/>')
    size = 15 if len(NAMES[key]) <= 6 else (13 if len(NAMES[key]) <= 8 else 11.5)
    p.append(f'<text x="100" y="{69 + size * .36:.1f}" text-anchor="middle" font-family="Impact, \'Arial Black\', \'Segoe UI Black\', sans-serif" '
             f'font-weight="900" font-size="{size}" letter-spacing="1.5" fill="{plate_txt}" stroke="{edge}" stroke-width=".6" '
             f'paint-order="stroke">{NAMES[key]}</text>')
    # ---- gemas del rango
    if key == "platino":
        p.append(gem(100, 46, 6 if div > 1 else 5, "#7fd0ff", "#01579b") + (gem(100, 162, 5, "#7fd0ff", "#01579b") if div > 1 else ""))
    if key == "esmeralda":
        p.append(gem(100, 46, 7, "#3ddc84", "#0b5a31") + (gem(66, 150, 4.5, "#3ddc84", "#0b5a31") + gem(134, 150, 4.5, "#3ddc84", "#0b5a31") if div > 1 else ""))
    if key == "diamante":
        p.append(gem(100, 166, 8 if div > 1 else 6.5, "#e3f2ff", "#2a4472"))
    if key == "campeon" and div > 1:
        p.append(gem(100, 162, 6, "#ff3d6e", "#7a0022"))
    # ---- gemas laterales en el borde (división II y III)
    if div >= 2 and key != "titan":
        side_gem = {"hierro": "#c9cdd3", "bronce": "#ffb27a", "plata": "#bfe3ff", "oro": "#ffe082", "platino": "#7fd0ff",
                    "diamante": "#e3f2ff", "esmeralda": "#3ddc84", "campeon": "#ff3d6e"}[key]
        p.append(gem(41, 92, 5, side_gem, edge) + gem(159, 92, 5, side_gem, edge))
    # ---- estrellas de división (I, II, III)
    if key != "titan":
        for i in range(div):
            x = 100 + (i - (div - 1) / 2) * 14
            p.append(star(x, 152 if key not in ("diamante", "platino", "campeon") or div == 1 else 148, 6,
                          f"url(#{gid('gold')})", GOLD[3]))
    # ---- destellos (III y Titán)
    if div == 3 or key == "titan":
        for i, (x, y) in enumerate([(34, 50), (168, 56), (26, 124), (176, 128), (60, 186), (142, 188)][: 4 if not rich else 6]):
            p.append(sparkle(x, y, 8 if i % 2 == 0 else 6, round(i * 0.35, 2)))
    p.append("</svg>")
    return "".join(p)


# limpiar versiones anteriores sin división
for f in os.listdir(OUT):
    if f.endswith(".svg"):
        os.remove(os.path.join(OUT, f))
for key in METALS:
    if key == "titan":
        with open(os.path.join(OUT, "titan.svg"), "w", encoding="utf-8") as fh:
            fh.write(emblem(key, 3))
        continue
    for div in (1, 2, 3):
        with open(os.path.join(OUT, f"{key}-{div}.svg"), "w", encoding="utf-8") as fh:
            fh.write(emblem(key, div))
print("ok", len(os.listdir(OUT)))
