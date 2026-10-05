"""Ventajas por nivel (XP).

Regla de diseño: las ventajas son COSMÉTICAS o de comodidad. Ningún dato,
gráfico ni análisis profesional depende del nivel (un principiante necesita
el mismo feedback que cualquiera). La única ventaja con coste real es el
análisis de IA extra, por eso llega tarde (nivel 20).

El nivel se lee de la caché User.xp_total (sin recalcular): para decidir un
color o un diseño no hace falta exactitud al XP, y así no se añade trabajo a
cada página.
"""
from flask_babel import gettext, lazy_gettext as _l

from app import progression

# Colores de acento: la clave va en <html data-accent>; los valores, en
# style.css (:root[data-accent="..."]).
ACCENTS = [
    {"key": "morado", "name": _l("Morado"), "level": 1},
    {"key": "azul", "name": _l("Azul"), "level": 10},
    {"key": "verde", "name": _l("Verde"), "level": 15},
    {"key": "naranja", "name": _l("Naranja"), "level": 25},
    {"key": "rojo", "name": _l("Rojo"), "level": 30},
    {"key": "turquesa", "name": _l("Turquesa"), "level": 40},
    {"key": "dorado", "name": _l("Dorado"), "level": 50},
]

# Diseños de la tarjeta de récord (los dibuja app/static/share_card.js).
SHARE_DESIGNS = [
    {"key": "clasico", "name": _l("Clásico"), "level": 1,
     "bg": ["#120c2c", "#251663"], "glows": ["rgba(124, 77, 255, 0.55)", "rgba(34, 201, 140, 0.25)"],
     "kicker": "#c9b8ff", "metric": ["#b69cff", "#7fd8ff", "#5cf0b4"], "link": "#b69cff"},
    {"key": "medianoche", "name": _l("Medianoche"), "level": 5,
     "bg": ["#06132b", "#0f2f63"], "glows": ["rgba(56, 132, 255, 0.55)", "rgba(125, 211, 252, 0.22)"],
     "kicker": "#a9c8ff", "metric": ["#93c5fd", "#7fe3ff", "#c4f1ff"], "link": "#93c5fd"},
    {"key": "fuego", "name": _l("Fuego"), "level": 15,
     "bg": ["#2a0a05", "#5c1a0b"], "glows": ["rgba(255, 106, 0, 0.55)", "rgba(255, 196, 0, 0.22)"],
     "kicker": "#ffc9a3", "metric": ["#ffb36b", "#ff8a3d", "#ffd166"], "link": "#ffb36b"},
    {"key": "oro", "name": _l("Oro"), "level": 25,
     "bg": ["#0d0b07", "#2b2412"], "glows": ["rgba(212, 175, 55, 0.45)", "rgba(255, 236, 179, 0.16)"],
     "kicker": "#f3dc95", "metric": ["#f9e7a6", "#e6c35c", "#c9a227"], "link": "#e6c35c"},
    {"key": "aurora", "name": _l("Aurora"), "level": 35,
     "bg": ["#04201c", "#1b1046"], "glows": ["rgba(45, 212, 191, 0.5)", "rgba(168, 85, 247, 0.35)"],
     "kicker": "#a7f3d0", "metric": ["#99f6e4", "#c4b5fd", "#f0abfc"], "link": "#5eead4"},
    {"key": "obsidiana", "name": _l("Obsidiana"), "level": 45,
     "bg": ["#050505", "#1c1c22"], "glows": ["rgba(226, 232, 240, 0.28)", "rgba(148, 163, 184, 0.18)"],
     "kicker": "#e2e8f0", "metric": ["#f8fafc", "#cbd5e1", "#94a3b8"], "link": "#e2e8f0"},
    {"key": "leyenda", "name": _l("Leyenda"), "level": 50,
     "bg": ["#14051f", "#3b0a2a"], "glows": ["rgba(250, 204, 21, 0.45)", "rgba(244, 63, 94, 0.3)"],
     "kicker": "#fde68a", "metric": ["#fde68a", "#fbbf24", "#f472b6"], "link": "#fbbf24"},
]

BADGE_LEVEL = 10        # nivel (y rango) en la tarjeta compartida
AI_EXTRA_LEVEL = 20     # un análisis de IA más por semana
AI_PER_WEEK = 1
AI_PER_WEEK_EXTRA = 2


def level_of(user):
    return progression.level_for(user.xp_total or 0)["level"]


def unlocked(items, level):
    return [i for i in items if level >= i["level"]]


def ai_per_week(level):
    return AI_PER_WEEK_EXTRA if level >= AI_EXTRA_LEVEL else AI_PER_WEEK


def perk_list(level):
    """Todas las ventajas en orden de nivel, para /nivel."""
    rows = []
    for d in SHARE_DESIGNS[1:]:
        rows.append({"level": d["level"], "text": gettext("Diseño «%(name)s» para la tarjeta de récord", name=d["name"])})
    for a in ACCENTS[1:]:
        rows.append({"level": a["level"], "text": gettext("Color de acento %(name)s para la app", name=str(a["name"]).lower())})
    rows.append({"level": BADGE_LEVEL, "text": gettext("Tu nivel y tu rango en la tarjeta de récord que compartes")})
    rows.append({"level": AI_EXTRA_LEVEL, "text": gettext("Un análisis de IA más por semana (2 en vez de 1)")})
    rows.sort(key=lambda r: (r["level"], r["text"]))
    for r in rows:
        r["unlocked"] = level >= r["level"]
    return rows
