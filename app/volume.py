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


def status_for(sets):
    if sets <= 0:
        return "none"
    if sets < LOW:
        return "low"
    if sets <= HIGH:
        return "ok"
    return "high"


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


def weekly_volume(user_id, today=None):
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

    items = []
    for group in MUSCLE_GROUPS:
        if group not in MAIN_GROUPS and not total.get(group):
            continue
        sets7 = last7.get(group, 0.0)
        items.append({
            "group": group,
            "label": MUSCLE_GROUP_LABELS.get(group, group),
            "last7": sets7,
            "avg4": total.get(group, 0.0) / WEEKS,
            "status": status_for(sets7),
            # Barra de 0 a 25 series: 10 y 20 caen en el 40 % y el 80 %.
            "bar_pct": round(min(sets7, 25) / 25 * 100),
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
