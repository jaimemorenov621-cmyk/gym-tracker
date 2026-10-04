"""Recetas de material de los emblemas de rango. Todos los colores de los
emblemas salen de aquí (tools/make_rank_emblems.py): nada de colores sueltos.

Cada receta:
  metal     gradiente metálico de 7 stops con bandas claro-oscuro-claro
  bevel     (luz, sombra) del bisel
  shadow    sombra (relieves, sombras propias)
  specular  brillo especular
  field     campo del escudo (centro, medio, borde)
  cloth     cinta (claro, oscuro, pliegue)
  ink       (opcional) color del numeral si el metal no contrasta con la cinta
  gem       gema (brillo, cuerpo, profundo)
  leaf      hojas/plumas (luz, medio, sombra)
  glow      (opcional) halo / rayos de los rangos altos
"""


def _metal(c0, c1, c2, c3, c4, c5, c6):
    return [(0, c0), (0.16, c1), (0.34, c2), (0.5, c3), (0.66, c4), (0.82, c5), (1, c6)]


GOLD_LEAF = ("#fff0b0", "#e0a92e", "#7a4e08")

MATERIALS = {
    "hierro": {
        "metal": _metal("#c9ced4", "#7d848c", "#33373c", "#8e959d", "#d5dadf", "#555b62", "#1e2124"),
        "bevel": ("#e8ecef", "#121416"), "shadow": "#08090a", "specular": "#ffffff",
        "field": ("#6a7078", "#41464d", "#1d2023"),
        "cloth": ("#8a2f22", "#5a1a12", "#2e0b07"),
        "gem": ("#ffd0c0", "#c0392b", "#5a0d06"),
        "leaf": ("#c9ced4", "#7d848c", "#33373c"),
    },
    "bronce": {
        "metal": _metal("#ffe0b8", "#d98e4e", "#7a3f14", "#e09a5a", "#ffd3a0", "#9c5420", "#4a2208"),
        "bevel": ("#ffe8cc", "#3a1a06"), "shadow": "#1e0c02", "specular": "#fff6ea",
        "field": ("#d49660", "#8a4f1e", "#4a240a"),
        "cloth": ("#24457a", "#142a50", "#08152a"),
        "gem": ("#cfe4ff", "#2f6fd0", "#0c2a5a"),
        "leaf": ("#ffd3a0", "#c07a3e", "#6a3410"),
    },
    "plata": {
        "metal": _metal("#ffffff", "#cfd5dc", "#6e7681", "#d9dee4", "#ffffff", "#8c949e", "#4a5058"),
        "bevel": ("#ffffff", "#2a2f36"), "shadow": "#11141a", "specular": "#ffffff",
        "field": ("#e4e8ec", "#a9b0b8", "#5d646d"),
        "cloth": ("#8e2030", "#5c111c", "#30070c"),
        "gem": ("#ffd6dc", "#d02040", "#5a0614"),
        "leaf": ("#ffffff", "#b8c0c8", "#6e7681"),
    },
    "oro": {
        "metal": _metal("#fff7d1", "#f4ca55", "#a86f0c", "#f8d66e", "#fff2bd", "#c58b19", "#6a4004"),
        "bevel": ("#fff9e0", "#4e2f03"), "shadow": "#2a1702", "specular": "#ffffff",
        "field": ("#f1c75c", "#c08a20", "#6e470a"),
        "cloth": ("#3557c0", "#1b3380", "#0c1a48"),
        "gem": ("#ffd0d0", "#d8202c", "#6a0610"),
        "leaf": ("#fff0b0", "#e0a92e", "#7a4e08"),
    },
    "platino": {  # blanco azulado: se distingue de plata por color además de por silueta
        "metal": _metal("#ffffff", "#d8e8f2", "#7f9cb2", "#e2eef6", "#ffffff", "#93acc0", "#4f6678"),
        "bevel": ("#ffffff", "#22384a"), "shadow": "#0c1822", "specular": "#ffffff",
        "field": ("#eaf4fa", "#b2c8d8", "#6a8396"),
        "cloth": ("#2b5aa8", "#173670", "#0b1d40"),
        "gem": ("#e8fbff", "#5ad0ff", "#0a5a8a"),
        "leaf": ("#ffffff", "#c4d8e6", "#7f9cb2"),
    },
    "diamante": {
        "metal": _metal("#f2fbff", "#a8d4f2", "#2e5e94", "#b8e0fa", "#ffffff", "#4f86bf", "#173a66"),
        "bevel": ("#ffffff", "#0d2340"), "shadow": "#06111f", "specular": "#ffffff",
        "field": ("#7fb8ea", "#2f66a8", "#102e58"),
        "cloth": ("#e9f4ff", "#9cbde0", "#5a7aa0"), "ink": "#173a66",
        "gem": ("#ffffff", "#bfe6ff", "#3a7ad0"),
        "leaf": ("#f2fbff", "#a8d4f2", "#2e5e94"),
        "glow": "#8fc8ff",
    },
    "esmeralda": {
        "metal": _metal("#e0ffef", "#5fd99a", "#0b6b3c", "#6fe0a8", "#d6ffe9", "#1f9a5e", "#053a20"),
        "bevel": ("#eafff4", "#032414"), "shadow": "#01120a", "specular": "#ffffff",
        "field": ("#3fd08a", "#0f7a45", "#053a20"),
        "cloth": ("#b0182a", "#6a0a16", "#3a040a"),
        "gem": ("#e6fff2", "#2fe08a", "#055a2c"),
        "leaf": GOLD_LEAF,
        "glow": "#4fe39a",
    },
    "campeon": {  # rubí: canto de oro y campo carmesí
        "metal": _metal("#fff4c8", "#f0b840", "#9a5a08", "#f6cc5a", "#fff0b8", "#c07a12", "#5e3004"),
        "bevel": ("#fff6d8", "#4a1a02"), "shadow": "#24070a", "specular": "#ffffff",
        "field": ("#ff5a72", "#b0122c", "#4a0612"),
        "cloth": ("#fff0b0", "#d9a030", "#8a5a0c"), "ink": "#8a0f22",
        "gem": ("#ffd0d8", "#e01438", "#5a0414"),
        "leaf": GOLD_LEAF,
        "glow": "#ff5a7a",
    },
    "titan": {  # maestro: obsidiana y oro fundido
        "metal": _metal("#ffd98a", "#c87a1e", "#4a2006", "#e0962e", "#ffe2a0", "#8a4a14", "#2a1204"),
        "bevel": ("#ffe6b0", "#1a0800"), "shadow": "#0a0300", "specular": "#fff4dc",
        "field": ("#3a1d5c", "#160b26", "#05030a"),
        "cloth": ("#3a1a06", "#1c0c02", "#0a0400"),
        "gem": ("#fff0c0", "#ff8a1e", "#8a2a00"),
        "leaf": GOLD_LEAF,
        "glow": "#ff8a2a",
    },
}
