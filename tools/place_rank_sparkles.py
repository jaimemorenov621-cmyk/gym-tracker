"""Coloca los destellos (sparkles) de los emblemas SOLO en huecos vacíos.

Para cada rango:
  1. Renderiza el emblema a 512 px sin destellos, sin halo y sin rayos (todas
     sus divisiones, y se unen: la posición vale para las tres). Píxel con
     alpha > 0 = ocupado.
  2. Envolvente convexa de la silueta; "hueco" = píxel vacío dentro de ella.
  3. Mapa de distancias (transformada euclídea exacta) de cada hueco al
     píxel ocupado más cercano.
  4. Un destello de radio r solo se centra donde la holgura es >= r + 4 px y
     su caja (2r x 2r) no toca ningún píxel ocupado. Si no cabe, no se pone:
     nunca se encoge por debajo del mínimo ni tapa nada.
  5. Selección determinista: candidatos por cercanía a la esquina superior
     izquierda del emblema, hasta MAX_PER_RANK, separados al menos un 12 %
     del ancho del emblema.
  6. Tamaño: el dominante, 7 % del ancho del emblema (6 % si no cabe); los
     demás, la mitad del dominante. Mínimo 3 %; por debajo se descarta.
  7. Guarda las posiciones (relativas al lienzo) en tools/rank_sparkles.json
     y la máscara en tools/rank_masks/<rango>.png (para el test).
 10. Overlays de depuración en debug/<rango>.png: silueta en gris, huecos en
     verde, destellos en dorado.

Uso: python tools/place_rank_sparkles.py      (usa Edge/Chrome sin interfaz)
Una vez aprobadas, las posiciones no se recalculan: make_rank_emblems.py
solo lee el JSON.
"""
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_rank_emblems as mre  # noqa: E402
from rasterize_rank_emblems import browser, render  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "tools" / "rank_sparkles.json"
MASKS = ROOT / "tools" / "rank_masks"
DEBUG = ROOT / "debug"
SIZE = 512
MARGIN = 4                   # px de holgura extra alrededor del destello
MAX_PER_RANK = {"hierro": 0, "bronce": 0, "plata": 1, "oro": 1, "platino": 1, "diamante": 2,
                "esmeralda": 2, "campeon": 2, "titan": 3}
DOMINANT = (0.07, 0.06)      # fracción del ancho del emblema, en orden de preferencia
SECONDARY = 0.5              # del dominante
MIN_SIZE = 0.03
SEPARATION = 0.12
ALPHA = 0                    # píxel ocupado si alpha > ALPHA (el criterio pedido: 0)


# ------------------------------------------------------------ geometría
def convex_hull(points):
    """Cadena monótona de Andrew. points: [(x, y)]."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def hull_mask(hull):
    img = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(img).polygon([(x + 0.5, y + 0.5) for x, y in hull], fill=1, outline=1)
    return img.load()


def _edt_1d(f):
    """Transformada de distancia 1D al cuadrado (Felzenszwalb y Huttenlocher).
    f: coste por posición (0 ocupado, número enorme si no)."""
    n = len(f)
    d, v, z = [0.0] * n, [0] * n, [0.0] * (n + 1)
    k = 0
    z[0], z[1] = -math.inf, math.inf
    for q in range(1, n):
        s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
        while s <= z[k]:
            k -= 1
            s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
        k += 1
        v[k], z[k], z[k + 1] = q, s, math.inf
    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        d[q] = (q - v[k]) ** 2 + f[v[k]]
    return d


def distance_map(occupied):
    """Distancia euclídea de cada píxel al ocupado más cercano (0 si ocupado)."""
    inf = 1e12
    grid = [[0.0 if occupied[y][x] else inf for x in range(SIZE)] for y in range(SIZE)]
    for x in range(SIZE):  # columnas
        col = _edt_1d([grid[y][x] for y in range(SIZE)])
        for y in range(SIZE):
            grid[y][x] = col[y]
    return [[math.sqrt(v) for v in _edt_1d(row)] for row in grid]


# ------------------------------------------------------------ máscara
def silhouette(exe, workdir, key):
    """Unión de las siluetas de todas las divisiones, sin efectos."""
    divs = (3,) if key == "titan" else (1, 2, 3)
    occ = [[False] * SIZE for _ in range(SIZE)]
    for div in divs:
        svg = workdir / f"{key}-{div}.svg"
        svg.write_text(mre.build(key, div, sparkle=False, glow=False, sunburst=False), encoding="utf-8")
        png = workdir / f"{key}-{div}.png"
        render(exe, workdir, svg, png, SIZE)
        alpha = Image.open(png).convert("RGBA").getchannel("A").load()
        for y in range(SIZE):
            row = occ[y]
            for x in range(SIZE):
                if alpha[x, y] > ALPHA:
                    row[x] = True
    return occ


def box_clear(occ, cx, cy, r):
    x0, x1 = math.floor(cx - r), math.ceil(cx + r)
    y0, y1 = math.floor(cy - r), math.ceil(cy + r)
    if x0 < 0 or y0 < 0 or x1 >= SIZE or y1 >= SIZE:
        return False
    return not any(occ[y][x] for y in range(y0, y1 + 1) for x in range(x0, x1 + 1))


def place(key, occ):
    pts = [(x, y) for y in range(SIZE) for x in range(SIZE) if occ[y][x]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    left, top, width = min(xs), min(ys), max(xs) - min(xs) + 1
    # Para la envolvente bastan los extremos de cada fila.
    edge = []
    for y in range(SIZE):
        row = [x for x in range(SIZE) if occ[y][x]]
        if row:
            edge += [(row[0], y), (row[-1], y)]
    hull = convex_hull(edge)
    inside = hull_mask(hull)
    dist = distance_map(occ)
    holes = [(x, y) for y in range(SIZE) for x in range(SIZE) if inside[x, y] and not occ[y][x]]
    order = sorted(holes, key=lambda p: ((p[0] - left) ** 2 + (p[1] - top) ** 2, p[1], p[0]))

    chosen = []
    limit = MAX_PER_RANK[key]

    def first_fit(r, taken):
        for x, y in order:
            if dist[y][x] < r + MARGIN:
                continue
            if any(math.hypot(x - cx, y - cy) < SEPARATION * width for cx, cy, _ in taken):
                continue
            if box_clear(occ, x, y, r):
                return x, y
        return None

    if limit:
        dominant = None
        for frac in DOMINANT:
            r = frac * width / 2
            spot = first_fit(r, chosen)
            if spot:
                dominant = frac
                chosen.append((*spot, r))
                break
        if dominant:
            r2 = dominant * SECONDARY * width / 2
            if dominant * SECONDARY >= MIN_SIZE:
                while len(chosen) < limit:
                    spot = first_fit(r2, chosen)
                    if not spot:
                        break
                    chosen.append((*spot, r2))
    return {"hull": hull, "inside": inside, "holes": holes, "chosen": chosen, "width": width}


def overlay(key, occ, info):
    img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
    px = img.load()
    for x, y in info["holes"]:
        px[x, y] = (120, 210, 120)
    for y in range(SIZE):
        for x in range(SIZE):
            if occ[y][x]:
                px[x, y] = (150, 150, 150)
    d = ImageDraw.Draw(img)
    d.line([*info["hull"], info["hull"][0]], fill=(60, 140, 60), width=1)
    for i, (x, y, r) in enumerate(info["chosen"]):
        d.rectangle([x - r, y - r, x + r, y + r], outline=(160, 110, 0))
        k = r * 0.14
        star = [(x, y - r), (x + k, y - k), (x + r, y), (x + k, y + k), (x, y + r), (x - k, y + k), (x - r, y), (x - k, y - k)]
        d.polygon(star, fill=(232, 178, 20))
    d.text((6, 4), f"{key}: {len(info['chosen'])}/{MAX_PER_RANK[key]} destellos", fill=(0, 0, 0))
    DEBUG.mkdir(parents=True, exist_ok=True)
    img.save(DEBUG / f"{key}.png")


def main():
    """--alpha N --tag nombre: variante de comparación (umbral de opacidad
    distinto) que escribe en debug/<nombre>/ y tools/rank_sparkles.<nombre>.json,
    sin tocar la configuración ni las máscaras aprobadas."""
    global ALPHA, CONFIG, DEBUG, MASKS
    args = sys.argv[1:]
    if "--alpha" in args:
        i = args.index("--alpha")
        ALPHA = int(args[i + 1])
        del args[i:i + 2]
    if "--tag" in args:
        i = args.index("--tag")
        tag = args[i + 1]
        del args[i:i + 2]
        CONFIG = ROOT / "tools" / f"rank_sparkles.{tag}.json"
        DEBUG = ROOT / "debug" / tag
        MASKS = DEBUG / "masks"
    exe = browser()
    keys = args or list(MAX_PER_RANK)
    config = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    MASKS.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="gyre-sparkles-"))
    try:
        for key in keys:
            occ = silhouette(exe, workdir, key)
            info = place(key, occ)
            mask = Image.new("1", (SIZE, SIZE), 0)
            mp = mask.load()
            for y in range(SIZE):
                for x in range(SIZE):
                    if occ[y][x]:
                        mp[x, y] = 1
            mask.save(MASKS / f"{key}.png", optimize=True)
            # Relativo al lienzo: centro (0-1) y radio (fracción del lado).
            config[key] = [[round(x / SIZE, 4), round(y / SIZE, 4), round(r / SIZE, 4)] for x, y, r in info["chosen"]]
            overlay(key, occ, info)
            print(f"{key}: {len(info['chosen'])}/{MAX_PER_RANK[key]}  ancho emblema {info['width']} px")
    finally:
        time.sleep(1)
        shutil.rmtree(workdir, ignore_errors=True)
    CONFIG.write_text(json.dumps(config, indent=1) + "\n", encoding="utf-8")
    print("posiciones en", CONFIG, "· overlays en", DEBUG)


if __name__ == "__main__":
    main()
