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
"""
from datetime import timedelta

PHASES = {
    "volumen": {"label": "Volumen", "lo": 0.25, "hi": 0.5,
                "range": "subir un 0,25-0,5 % de tu peso por semana"},
    "definicion": {"label": "Definición", "lo": -1.0, "hi": -0.5,
                   "range": "bajar un 0,5-1 % de tu peso por semana"},
    "recomposicion": {"label": "Recomposición", "lo": -0.25, "hi": 0.25,
                      "range": "mantener el peso (±0,25 % por semana)"},
}
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


def assessment(rate, phase):
    """Cómo va el ritmo para la fase: status ok | fast | slow | wrong | none
    y un mensaje corto."""
    if rate is None:
        return {"status": "none", "text": f"Registra al menos {MIN_ENTRIES} pesos en {MIN_SPAN_DAYS} días para ver tu ritmo."}
    info = PHASES.get(phase)
    if info is None:
        return {"status": "none", "text": "Elige tu fase para saber si vas al ritmo adecuado."}
    pct = rate["pct_week"]
    if phase == "volumen":
        if pct <= 0:
            return {"status": "wrong", "text": "No estás subiendo de peso: para ganar músculo en volumen hace falta algo de superávit."}
        if pct < info["lo"]:
            return {"status": "slow", "text": "Subes más despacio de lo recomendado: puedes comer algo más."}
        if pct > info["hi"]:
            return {"status": "fast", "text": "Subes demasiado rápido: probablemente estés ganando más grasa de la necesaria."}
    elif phase == "definicion":
        if pct >= 0:
            return {"status": "wrong", "text": "No estás bajando de peso: en definición hace falta un déficit."}
        if pct > info["hi"]:
            return {"status": "slow", "text": "Bajas más despacio de lo recomendado: puedes ajustar un poco el déficit."}
        if pct < info["lo"]:
            return {"status": "fast", "text": "Bajas demasiado rápido: aumenta el riesgo de perder músculo."}
    else:  # recomposición
        if pct > info["hi"]:
            return {"status": "fast", "text": "Estás subiendo de peso: eso ya se parece más a un volumen."}
        if pct < info["lo"]:
            return {"status": "fast", "text": "Estás bajando de peso: eso ya se parece más a una definición."}
    return {"status": "ok", "text": "Vas al ritmo recomendado para tu fase."}


def summary(entries, phase, now):
    """Todo lo que pintan Inicio y la página de peso."""
    rate = weekly_rate(entries, now)
    return {"rate": rate, "phase": phase, "phase_info": PHASES.get(phase), **assessment(rate, phase)}
