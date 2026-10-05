"""Volumen semanal por grupo muscular frente a la evidencia (Fase 3).

Qué mide: series DURAS por grupo muscular en los últimos 7 días (y la media
semanal de las últimas 4 semanas, más estable). No estima "recuperación" ni
"fatiga": solo cuenta series, que es lo que la investigación relaciona con
la hipertrofia.

Evidencia (citada en /progress):
  - Schoenfeld, Ogborn y Krieger (2017), J Sports Sci 35(11):1073-1082:
    metaanálisis dosis-respuesta; más series semanales por músculo, más
    hipertrofia, con 10 o más claramente por encima de menos de 5.
  - Pelland y col. (2024), SportRxiv, metarregresiones con 67 estudios:
    la curva sigue subiendo con el volumen pero con rendimientos
    decrecientes (forma de raíz cuadrada), y cuentan las series indirectas
    como media serie ("fractional"). Para la fuerza, el volumen extra rinde
    menos que para la hipertrofia.
  10-20 series por músculo y semana es el rango práctico más citado; por
  encima no es "malo", pero cada serie extra aporta menos.

Cómo contamos (decisiones nuestras, explicadas en la app):
  - Serie dura: hecha, con peso y repeticiones, no de calentamiento, y con
    RIR 4 o menos (RPE 6 o más). Sin esfuerzo anotado, cuenta (no podemos
    saberlo).
  - Músculos del catálogo: primario = 1 serie, secundario = 0,5 (como
    Pelland). Ejercicios fuera del catálogo no cuentan y se avisa.
  - Días en hora de Madrid. "Últimos 7 días" incluye hoy.
"""
from collections import defaultdict
from datetime import datetime, timedelta

import sqlalchemy as sa
from flask_babel import gettext

from app import db
from app.models import SetEntry, Workout

LOW, HIGH = 10, 20
MAX_HARD_RIR = 4
SECONDARY_WEIGHT = 0.5
WEEKS = 4
# Grupos que se muestran siempre; el resto (cuello, antebrazos, aductores)
# solo si se han entrenado.
MAIN_GROUPS = (
    "pecho", "dorsales", "trapecios", "hombros", "biceps", "triceps", "abdomen",
    "espalda_baja", "cuadriceps", "isquiotibiales", "gluteos", "pantorrillas",
)


def is_hard_set(entry):
    from app.routes import is_real_set

    if not is_real_set(entry) or (entry.set_type or "normal") == "calentamiento":
        return False
    if entry.rir is not None:
        return entry.rir <= MAX_HARD_RIR
    if entry.rpe is not None:
        return entry.rpe >= 10 - MAX_HARD_RIR
    return True


def status_for(sets, low=LOW, high=HIGH):
    if sets <= 0:
        return "none"
    if sets < low:
        return "low"
    if high is None or sets <= high:
        return "ok"
    return "high"


# ------------------------------------------------------------ rango personal
# Cada persona responde distinto al volumen. Con tus datos, para cada grupo:
# cada vez que repites un ejercicio cuyo músculo PRINCIPAL es ese grupo, se
# mide el cambio de tu 1RM estimado frente a la sesión anterior (hasta 21
# días antes) y se anota el volumen (series duras) que hiciste de ese grupo
# en los 7 días previos. Se agrupan esas mediciones por tramos de volumen y
# tu "punto dulce" es el tramo en que más progresaste. Requisitos: 12
# mediciones y al menos 2 tramos con 4 o más. Es una CORRELACIÓN (influyen
# sueño, dieta, descargas...) y el 1RM mide fuerza, no tamaño: la app lo
# presenta como estimación, con su confianza. Es SOLO informativa: el mapa
# y los colores del volumen usan siempre el rango de la evidencia (10-20).
#
# Sesgo corregido: tras una descarga, unas vacaciones o una semana floja la
# fuerza suele subir porque se va la fatiga, no porque poco volumen sea
# mejor; contar esas mediciones empujaba el "punto dulce" a 0-6 series. Por
# eso se descartan las mediciones cuyo volumen de esos 7 días está muy por
# debajo de tu media de las 3 semanas anteriores (descarga) o llegan tras
# semanas sin entrenar ese grupo (vuelta de un parón), y las que comparan
# sesiones separadas más de 14 días.
PERSONAL_WEEKS = 26
MIN_PAIRS = 12
MIN_PER_BIN = 4
MAX_GAP_DAYS = 14
DELOAD_RATIO = 0.6   # semana con menos del 60 % de tu media reciente = descarga
BINS = [(0, 6), (6, 10), (10, 14), (14, 18), (18, 22), (22, None)]
_CHANGE_CAP = 0.2
_WORSE_BY = 0.005  # medio punto por sesión menos que el mejor tramo


def _bin_of(sets):
    for lo, hi in BINS:
        if hi is None or sets < hi:
            return (lo, hi)
    return BINS[-1]


def _rir_of(entry):
    if entry.rir is not None:
        return entry.rir
    if entry.rpe is not None:
        return 10 - entry.rpe
    return None


def personal_ranges(user_id, today=None):
    """{grupo: estimación} para los grupos con datos suficientes."""
    import math

    from app.routes import estimated_1rm, is_real_set, latest_bodyweight, prefetch_catalog_exercises, to_local
    from app.usage import local_today

    today = today or local_today()
    first_day = today - timedelta(weeks=PERSONAL_WEEKS)
    since = datetime.combine(first_day - timedelta(days=1), datetime.min.time())
    rows = db.session.execute(
        sa.select(
            Workout.timestamp, SetEntry.exercise, SetEntry.weight, SetEntry.reps,
            SetEntry.rir, SetEntry.rpe, SetEntry.set_type, SetEntry.completed,
        )
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(Workout.user_id == user_id, Workout.timestamp >= since)
    ).all()
    if not rows:
        return {}
    prefetch_catalog_exercises({r.exercise for r in rows})
    bw = latest_bodyweight(user_id)

    daily_sets = defaultdict(lambda: defaultdict(float))   # grupo -> día -> series
    daily_rir = defaultdict(lambda: defaultdict(list))     # grupo -> día -> [rir]
    best = defaultdict(dict)                               # ejercicio -> día -> mejor 1RM
    primary = {}
    cache = {}
    for r in rows:
        d = to_local(r.timestamp).date()
        if d < first_day:
            continue
        if r.exercise not in cache:
            cache[r.exercise] = _groups_for(r.exercise)
            primary[r.exercise] = [g for g, w in cache[r.exercise] if w == 1.0]
        groups = cache[r.exercise]
        if not groups:
            continue
        if is_hard_set(r):
            rir = _rir_of(r)
            for g, w in groups:
                daily_sets[g][d] += w
                if rir is not None and w == 1.0:
                    daily_rir[g][d].append(rir)
        if is_real_set(r) and (r.set_type or "normal") != "calentamiento":
            e = estimated_1rm(r, bw)
            if e > best[r.exercise].get(d, 0):
                best[r.exercise][d] = e

    pairs = defaultdict(list)  # grupo -> [(series 7 días antes, cambio, rir medio)]
    for exercise, by_day in best.items():
        days = sorted(by_day)
        for d0, d1 in zip(days, days[1:]):
            if (d1 - d0).days > MAX_GAP_DAYS or by_day[d0] <= 0:
                continue
            change = max(-_CHANGE_CAP, min(_CHANGE_CAP, math.log(by_day[d1] / by_day[d0])))
            window = [d1 - timedelta(days=i) for i in range(1, 8)]
            before = [d1 - timedelta(days=i) for i in range(8, 29)]   # las 3 semanas anteriores
            for g in primary.get(exercise, []):
                vol = sum(daily_sets[g].get(d, 0.0) for d in window)
                baseline = sum(daily_sets[g].get(d, 0.0) for d in before) / 3
                if baseline <= 0 or vol < DELOAD_RATIO * baseline:
                    continue  # vuelta de un parón o descarga: sesgaría hacia poco volumen
                rirs = [x for d in window for x in daily_rir[g].get(d, [])]
                pairs[g].append((vol, change, sum(rirs) / len(rirs) if rirs else None))

    out = {}
    for g, items in pairs.items():
        if len(items) < MIN_PAIRS:
            continue
        bins = defaultdict(list)
        for vol, change, rir in items:
            bins[_bin_of(vol)].append((change, rir))
        stats = {
            b: {
                "n": len(v),
                "mean": sum(c for c, _ in v) / len(v),
                "rir": (lambda xs: sum(xs) / len(xs) if xs else None)([x for _, x in v if x is not None]),
            }
            for b, v in bins.items()
        }
        usable = {b: st for b, st in stats.items() if st["n"] >= MIN_PER_BIN}
        if len(usable) < 2:
            continue
        sweet = max(usable, key=lambda b: usable[b]["mean"])
        worse_above = [b for b in usable if b[0] > sweet[0] and usable[b]["mean"] < usable[sweet]["mean"] - _WORSE_BY]
        n = len(items)
        out[g] = {
            "low": sweet[0],
            "high": sweet[1],               # None = "o más" (aún sin techo visto)
            "n": n,
            "confidence": gettext("alta") if n >= 40 else (gettext("media") if n >= 20 else gettext("baja")),
            "gain_pct": (math.exp(usable[sweet]["mean"]) - 1) * 100,
            "rir": usable[sweet]["rir"],
            "over_from": min((b[0] for b in worse_above), default=None),
            "bins": {f"{b[0]}-{b[1] if b[1] is not None else '+'}": st for b, st in sorted(usable.items())},
        }
    return out


def _groups_for(exercise_name):
    """[(grupo, peso)]: primarios 1, secundarios 0,5; vacío si no está en
    el catálogo."""
    from app.routes import MUSCLE_GROUP_MAP, find_catalog_exercise

    catalog = find_catalog_exercise(exercise_name)
    if not catalog or not catalog.primary_muscles:
        return []
    weights = {}
    for muscle in catalog.primary_muscles.split(", "):
        group = MUSCLE_GROUP_MAP.get(muscle)
        if group:
            weights[group] = 1.0
    for muscle in (catalog.secondary_muscles or "").split(", "):
        group = MUSCLE_GROUP_MAP.get(muscle)
        if group and group not in weights:
            weights[group] = SECONDARY_WEIGHT
    return list(weights.items())


def weekly_volume(user_id, today=None, personal=None):
    from app.progression import MUSCLE_GROUP_LABELS
    from app.routes import MUSCLE_GROUPS, prefetch_catalog_exercises, to_local
    from app.usage import local_today

    today = today or local_today()
    first_day = today - timedelta(days=7 * WEEKS - 1)
    since = datetime.combine(first_day - timedelta(days=1), datetime.min.time())
    rows = db.session.execute(
        sa.select(
            Workout.timestamp, SetEntry.exercise, SetEntry.weight, SetEntry.reps,
            SetEntry.rir, SetEntry.rpe, SetEntry.set_type, SetEntry.completed,
        )
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(Workout.user_id == user_id, Workout.timestamp >= since)
    ).all()
    prefetch_catalog_exercises({r.exercise for r in rows})

    last7 = defaultdict(float)
    total = defaultdict(float)
    unmapped = no_effort = hard_sets = 0
    cache = {}
    for r in rows:
        d = to_local(r.timestamp).date()
        if not (first_day <= d <= today) or not is_hard_set(r):
            continue
        hard_sets += 1
        if r.rir is None and r.rpe is None:
            no_effort += 1
        if r.exercise not in cache:
            cache[r.exercise] = _groups_for(r.exercise)
        groups = cache[r.exercise]
        if not groups:
            unmapped += 1
            continue
        recent = (today - d).days < 7
        for group, weight in groups:
            total[group] += weight
            if recent:
                last7[group] += weight

    if personal is None:
        personal = personal_ranges(user_id, today=today)
    items = []
    for group in MUSCLE_GROUPS:
        if group not in MAIN_GROUPS and not total.get(group):
            continue
        sets7 = last7.get(group, 0.0)
        own = personal.get(group)  # estimación tuya, solo informativa
        low, high = LOW, HIGH
        items.append({
            "group": group,
            "label": MUSCLE_GROUP_LABELS.get(group, group),
            "last7": sets7,
            "avg4": total.get(group, 0.0) / WEEKS,
            "low": low,
            "high": high,
            "personal": own,
            "status": status_for(sets7, low, high),
            # Barra de 0 a 25 series, con la banda del rango (personal o 10-20).
            "bar_pct": round(min(sets7, 25) / 25 * 100),
            "band_left": round(min(low, 25) / 25 * 100),
            "band_width": round((min(high if high is not None else 25, 25) - min(low, 25)) / 25 * 100),
        })
    return {
        "items": items,
        # Estado de TODOS los grupos (para colorear el mapa; los no listados, sin series).
        "status": {g: next((i["status"] for i in items if i["group"] == g), "none") for g in MUSCLE_GROUPS},
        "unmapped": unmapped,
        "no_effort": no_effort,
        "hard_sets": hard_sets,
        "counts": {s: sum(1 for g in items if g["status"] == s) for s in ("none", "low", "ok", "high")},
    }


# Colores del mapa (inicio y Progreso). Por debajo del rango, el ámbar se
# intensifica según lo cerca que estés del mínimo.
MAP_COLORS = {"none": "#d9d5ef", "ok": "#22c98c", "high": "#e5484d"}


def _mix(a, b, t):
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def map_colors(volume):
    """{grupo: color} para TODOS los grupos del mapa."""
    from app.routes import MUSCLE_GROUPS

    by_group = {i["group"]: i for i in volume["items"]}
    colors = {}
    for g in MUSCLE_GROUPS:
        item = by_group.get(g)
        status = item["status"] if item else "none"
        if status == "low":
            t = min(1.0, item["last7"] / item["low"]) if item["low"] else 1.0
            colors[g] = _mix("#f9e3b0", "#f0a020", t)
        else:
            colors[g] = MAP_COLORS[status]
    return colors
