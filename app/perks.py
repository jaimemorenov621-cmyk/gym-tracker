"""Ventajas por nivel (XP).

Regla de diseño: las ventajas son COSMÉTICAS o de comodidad. Ningún dato,
gráfico ni análisis profesional depende del nivel (un principiante necesita
el mismo feedback que cualquiera). La única ventaja con coste real es el
análisis de IA extra, por eso llega tarde (nivel 20).

El nivel se lee de la caché User.xp_total (sin recalcular): para decidir un
color o un diseño no hace falta exactitud al XP, y así no se añade trabajo a
cada página.
"""
from app import progression

# Colores de acento: la clave va en <html data-accent>; los valores, en
# style.css (:root[data-accent="..."]).
ACCENTS = [
    {"key": "morado", "name": "Morado", "level": 1},
    {"key": "azul", "name": "Azul", "level": 10},
    {"key": "verde", "name": "Verde", "level": 15},
    {"key": "naranja", "name": "Naranja", "level": 25},
]

# Diseños de la tarjeta de récord (los dibuja app/static/share_card.js).
SHARE_DESIGNS = [
    {"key": "clasico", "name": "Clásico", "level": 1,
     "bg": ["#120c2c", "#251663"], "glows": ["rgba(124, 77, 255, 0.55)", "rgba(34, 201, 140, 0.25)"],
     "kicker": "#c9b8ff", "metric": ["#b69cff", "#7fd8ff", "#5cf0b4"], "link": "#b69cff"},
    {"key": "medianoche", "name": "Medianoche", "level": 5,
     "bg": ["#06132b", "#0f2f63"], "glows": ["rgba(56, 132, 255, 0.55)", "rgba(125, 211, 252, 0.22)"],
     "kicker": "#a9c8ff", "metric": ["#93c5fd", "#7fe3ff", "#c4f1ff"], "link": "#93c5fd"},
    {"key": "fuego", "name": "Fuego", "level": 15,
     "bg": ["#2a0a05", "#5c1a0b"], "glows": ["rgba(255, 106, 0, 0.55)", "rgba(255, 196, 0, 0.22)"],
     "kicker": "#ffc9a3", "metric": ["#ffb36b", "#ff8a3d", "#ffd166"], "link": "#ffb36b"},
    {"key": "oro", "name": "Oro", "level": 25,
     "bg": ["#0d0b07", "#2b2412"], "glows": ["rgba(212, 175, 55, 0.45)", "rgba(255, 236, 179, 0.16)"],
     "kicker": "#f3dc95", "metric": ["#f9e7a6", "#e6c35c", "#c9a227"], "link": "#e6c35c"},
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
        rows.append({"level": d["level"], "text": f"Diseño «{d['name']}» para la tarjeta de récord"})
    for a in ACCENTS[1:]:
        rows.append({"level": a["level"], "text": f"Color de acento {a['name'].lower()} para la app"})
    rows.append({"level": BADGE_LEVEL, "text": "Tu nivel y tu rango en la tarjeta de récord que compartes"})
    rows.append({"level": AI_EXTRA_LEVEL, "text": "Un análisis de IA más por semana (2 en vez de 1)"})
    rows.sort(key=lambda r: (r["level"], r["text"]))
    for r in rows:
        r["unlocked"] = level >= r["level"]
    return rows
