"""Ritmo de cambio de peso frente a la fase elegida (volumen, definición o
recomposición). Pesarse varía de un día a otro (agua, comida, sal), así que
el ritmo sale de una recta ajustada a los pesos de las últimas 4 semanas,
no de comparar dos pesos sueltos.

Rangos de referencia, en % del peso corporal por semana:
  Volumen        +0,25 a +0,5   Iraki, Fitschen, Espinar y Helms (2019),
                                Sports 7(7):154 (culturismo natural fuera de
                                temporada; los principiantes toleran la
                                parte alta, los avanzados la baja).
  Definición     -0,5 a -1      Helms, Aragon y Fitschen (2014), JISSN 11:20
                                (más rápido aumenta el riesgo de perder
                                músculo).
  Recomposición  -0,25 a +0,25  peso estable; el margen es criterio de la app.

Por nivel (se usa el rango de fuerza como indicador de experiencia): Iraki y
cols. recomiendan la parte alta del volumen para principiantes y la baja
para avanzados, y en definición ir más despacio cuanto más avanzado y magro
(Helms 2014; Garthe y cols. 2011, IJSNEM 21(2): 0,7 %/sem conservó más masa
magra que 1,4 %). Los extremos salen de esos trabajos; los cortes del nivel
intermedio son criterio de la app.
"""
from datetime import timedelta

from flask_babel import gettext, lazy_gettext as _l

PHASES = {
    "volumen": {"label": _l("Volumen"), "lo": 0.25, "hi": 0.5,
                "range": _l("subir un 0,25-0,5 % de tu peso por semana")},
    "definicion": {"label": _l("Definición"), "lo": -1.0, "hi": -0.5,
                   "range": _l("bajar un 0,5-1 % de tu peso por semana")},
    "recomposicion": {"label": _l("Recomposición"), "lo": -0.25, "hi": 0.25,
                      "range": _l("mantener el peso (±0,25 % por semana)")},
}
# (volumen lo-hi, definición lo-hi) por nivel; recomposición igual para todos.
LEVELS = {
    "principiante": {"label": _l("principiante o novato"), "volumen": (0.25, 0.5), "definicion": (-1.0, -0.5)},
    "intermedio": {"label": _l("intermedio"), "volumen": (0.2, 0.35), "definicion": (-0.9, -0.5)},
    "avanzado": {"label": _l("avanzado"), "volumen": (0.1, 0.25), "definicion": (-0.75, -0.5)},
}


def level_for_tier(tier):
    """Nivel de experiencia a partir del rango global (None = sin rango)."""
    if tier is None or tier <= 3:      # Hierro..Oro: hasta Novato alto
        return "principiante"
    return "intermedio" if tier <= 5 else "avanzado"   # Platino/Diamante; Esmeralda+


def phase_range(phase, level):
    """(lo, hi) en % por semana para la fase y el nivel."""
    if phase == "recomposicion":
        return PHASES[phase]["lo"], PHASES[phase]["hi"]
    return LEVELS[level][phase]


WINDOW_DAYS = 28
MIN_ENTRIES = 4
MIN_SPAN_DAYS = 14


def weekly_rate(entries, now):
    """{kg_week, pct_week, entries, days} con los pesos de las últimas 4
    semanas, o None si no hay al menos 4 repartidos en 2 semanas.
    entries: [(timestamp, kg)] (cualquier orden)."""
    recent = sorted((ts, kg) for ts, kg in entries if now - ts <= timedelta(days=WINDOW_DAYS))
    if len(recent) < MIN_ENTRIES:
        return None
    span = (recent[-1][0] - recent[0][0]).total_seconds() / 86400
    if span < MIN_SPAN_DAYS:
        return None
    t0 = recent[0][0]
    xs = [(ts - t0).total_seconds() / 86400 for ts, _ in recent]
    ys = [kg for _, kg in recent]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    kg_week = slope * 7
    return {"kg_week": kg_week, "pct_week": 100 * kg_week / my, "entries": len(recent), "days": round(span)}


def assessment(rate, phase, level="principiante"):
    """Cómo va el ritmo para la fase y el nivel: status ok | fast | slow |
    wrong | none y un mensaje corto."""
    if rate is None:
        return {"status": "none", "text": gettext("Registra al menos %(n)s pesos en %(days)s días para ver tu ritmo.", n=MIN_ENTRIES, days=MIN_SPAN_DAYS)}
    info = PHASES.get(phase)
    if info is None:
        return {"status": "none", "text": gettext("Elige tu fase para saber si vas al ritmo adecuado.")}
    pct = rate["pct_week"]
    lo, hi = phase_range(phase, level)
    info = dict(info, lo=lo, hi=hi)
    if phase == "volumen":
        if pct <= 0:
            return {"status": "wrong", "text": gettext("No estás subiendo de peso: para ganar músculo en volumen hace falta algo de superávit.")}
        if pct < info["lo"]:
            return {"status": "slow", "text": gettext("Subes más despacio de lo recomendado: puedes comer algo más.")}
        if pct > info["hi"]:
            return {"status": "fast", "text": gettext("Subes demasiado rápido: probablemente estés ganando más grasa de la necesaria.")}
    elif phase == "definicion":
        if pct >= 0:
            return {"status": "wrong", "text": gettext("No estás bajando de peso: en definición hace falta un déficit.")}
        if pct > info["hi"]:
            return {"status": "slow", "text": gettext("Bajas más despacio de lo recomendado: puedes ajustar un poco el déficit.")}
        if pct < info["lo"]:
            return {"status": "fast", "text": gettext("Bajas demasiado rápido: aumenta el riesgo de perder músculo.")}
    else:  # recomposición
        if pct > info["hi"]:
            return {"status": "fast", "text": gettext("Estás subiendo de peso: eso ya se parece más a un volumen.")}
        if pct < info["lo"]:
            return {"status": "fast", "text": gettext("Estás bajando de peso: eso ya se parece más a una definición.")}
    return {"status": "ok", "text": gettext("Vas al ritmo recomendado para tu fase.")}


def _pct(x):
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def summary(entries, phase, now, tier=None):
    """Todo lo que pintan Inicio y la página de peso. `tier`: rango global
    de fuerza (indicador del nivel); sin rango se usa el de principiante."""
    rate = weekly_rate(entries, now)
    level = level_for_tier(tier)
    out = {"rate": rate, "phase": phase, "phase_info": PHASES.get(phase), "level": level,
           "level_label": LEVELS[level]["label"], "has_tier": tier is not None, **assessment(rate, phase, level)}
    if phase in PHASES:
        lo, hi = phase_range(phase, level)
        a, b = _pct(min(abs(lo), abs(hi))), _pct(max(abs(lo), abs(hi)))
        if phase == "volumen":
            out["target"] = gettext("subir un %(a)s-%(b)s %% de tu peso por semana", a=a, b=b)
        elif phase == "definicion":
            out["target"] = gettext("bajar un %(a)s-%(b)s %% de tu peso por semana", a=a, b=b)
        else:
            out["target"] = gettext("mantener el peso (±0,25 % por semana)")
    return out
