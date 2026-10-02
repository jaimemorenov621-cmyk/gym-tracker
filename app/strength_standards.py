"""Estándares de fuerza: en qué nivel está cada levantamiento.

FUENTE (citada también en la app):
  Lon Kilgore, PhD, "Weightlifting Performance Standards", ExRx.net
  https://exrx.net/Testing/WeightLifting/StrengthStandards
  Tablas de adultos de 18 a 39 años, en libras (las originales; consultadas
  el 02/10/2026): .../BenchStandards, .../SquatStandards,
  .../DeadliftStandards, .../PressStandards

Qué son y qué no: estándares de rendimiento (1RM, sin equipo de ayuda salvo
cinturón) basados en ~70 años de clasificaciones de halterofilia y
powerlifting. La propia fuente avisa de que no son normas de población ni
están derivados por regresión. Niveles de la fuente:
  Untrained    -> Principiante: no ha entrenado el ejercicio, pero lo hace bien.
  Novice       -> Novato: entrena con regularidad desde hace unos meses.
  Intermediate -> Intermedio: entrena con regularidad hasta un par de años.
  Advanced     -> Avanzado: lleva varios años entrenando.
  Elite        -> Élite: compite en deportes de fuerza.

Cómo se aplican aquí (decisiones nuestras, documentadas en /progress):
  - Las tablas van por categoría de peso corporal (límite superior de cada
    categoría). Entre dos categorías se interpola linealmente. Por debajo de
    la primera se usa la primera; por encima de la última categoría con
    límite se usa la fila "+" (más de 319 lb ≈ 145 kg en hombres, de 198 lb
    ≈ 90 kg en mujeres). Nunca se extrapola.
  - Se compara con el 1RM ESTIMADO (estimated_1rm) de series reales de 10
    repeticiones efectivas o menos: más allá, la estimación pierde fiabilidad.
  - Edad: solo tenemos la tabla de 18-39 años (la app no guarda la edad).
  - "Nivel alcanzado" = el mejor nivel de cualquier sesión, cada una con el
    peso corporal registrado más cercano ANTERIOR a esa sesión (o el primero,
    si es como mucho 30 días posterior). Así pesarse hoy no cambia lo que ya
    alcanzaste, y no contradice logros ya desbloqueados.

DOTS (puntuación de powerlifting que corrige por peso corporal): fórmula de
Tim Konertz (BVDK, 2019). Coeficientes verificados en el código de
OpenPowerlifting (crates/coefficients/src/dots.rs).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import BodyWeightEntry, SetEntry, Workout

SOURCE_NAME = "Lon Kilgore, «Weightlifting Performance Standards» (ExRx.net), adultos de 18 a 39 años"
SOURCE_URL = "https://exrx.net/Testing/WeightLifting/StrengthStandards"

LEVELS = ["principiante", "novato", "intermedio", "avanzado", "elite"]
LEVEL_LABELS = {
    "principiante": "Principiante",
    "novato": "Novato",
    "intermedio": "Intermedio",
    "avanzado": "Avanzado",
    "elite": "Élite",
}
LEVEL_DESCRIPTIONS = {
    "principiante": "No ha entrenado el ejercicio, pero lo ejecuta bien.",
    "novato": "Entrena con regularidad desde hace unos meses.",
    "intermedio": "Entrena con regularidad desde hace hasta un par de años.",
    "avanzado": "Lleva varios años entrenando.",
    "elite": "Compite en deportes de fuerza.",
}

LIFTS = ["bench", "squat", "deadlift", "press"]
BIG_THREE = ["bench", "squat", "deadlift"]
LIFT_LABELS = {
    "bench": "Press de banca",
    "squat": "Sentadilla",
    "deadlift": "Peso muerto",
    "press": "Press militar",
}
LIFT_RULES = {  # condición de la fuente para que el estándar aplique
    "bench": "La barra toca el pecho con una pausa breve y se extienden los codos del todo.",
    "squat": "Los muslos bajan por debajo de la paralela.",
    "deadlift": "Rodillas, cadera y espalda alta se extienden del todo.",
    "press": "De pie, piernas rectas, sin echar el tronco atrás y extendiendo los codos.",
}

# Tablas ORIGINALES en libras, tal cual la fuente (ExRx publica también una
# versión en kg, pero no es una conversión exacta: difiere hasta 4,4 kg y
# tiene alguna incoherencia, p. ej. peso muerto femenino de 44 kg). Se pasan
# a kg abajo sin redondear. Fila: (límite de la categoría en lb | None = la
# fila "+", umbrales de Principiante, Novato, Intermedio, Avanzado, Élite).
LB_PER_KG = 1 / 0.45359237
_MEN_LB = [114, 123, 132, 148, 165, 181, 198, 220, 242, 275, 319, None]
_WOMEN_LB = [97, 105, 114, 123, 132, 148, 165, 181, 198, None]
TABLES_LB = {
    ("hombre", "bench"): [
        (85, 110, 130, 180, 220), (90, 115, 140, 195, 240), (100, 125, 155, 210, 260),
        (110, 140, 170, 235, 290), (120, 150, 185, 255, 320), (130, 165, 200, 275, 345),
        (135, 175, 215, 290, 360), (140, 185, 225, 305, 380), (145, 190, 230, 315, 395),
        (150, 195, 240, 325, 405), (155, 200, 245, 335, 415), (160, 205, 250, 340, 425)],
    ("mujer", "bench"): [
        (50, 65, 75, 95, 115), (55, 70, 80, 100, 125), (60, 75, 85, 110, 135), (65, 80, 90, 115, 140),
        (70, 85, 95, 125, 150), (75, 90, 105, 135, 165), (80, 95, 115, 145, 185), (85, 110, 120, 160, 195),
        (90, 115, 130, 165, 205), (95, 120, 140, 175, 220)],
    ("hombre", "squat"): [
        (80, 145, 175, 240, 320), (85, 155, 190, 260, 345), (90, 170, 205, 280, 370),
        (100, 190, 230, 315, 410), (110, 205, 250, 340, 445), (120, 220, 270, 370, 480),
        (125, 230, 285, 390, 505), (130, 245, 300, 410, 530), (135, 255, 310, 425, 550),
        (140, 260, 320, 435, 570), (145, 270, 325, 445, 580), (150, 275, 330, 455, 595)],
    ("mujer", "squat"): [
        (40, 85, 100, 130, 165), (50, 90, 105, 140, 175), (55, 100, 115, 150, 190), (55, 105, 120, 160, 200),
        (60, 110, 130, 170, 210), (65, 120, 140, 185, 230), (70, 130, 150, 200, 255), (75, 140, 165, 215, 270),
        (80, 150, 175, 230, 290), (85, 160, 185, 240, 305)],
    ("hombre", "deadlift"): [
        (95, 180, 205, 300, 385), (105, 195, 220, 320, 415), (115, 210, 240, 340, 440),
        (125, 235, 270, 380, 480), (135, 255, 295, 410, 520), (150, 275, 315, 440, 550),
        (155, 290, 335, 460, 565), (165, 305, 350, 480, 585), (170, 320, 365, 490, 595),
        (175, 325, 375, 500, 600), (180, 335, 380, 505, 610), (185, 340, 390, 510, 615)],
    ("mujer", "deadlift"): [
        (55, 105, 120, 175, 230), (60, 115, 130, 190, 240), (65, 120, 140, 200, 255), (70, 130, 150, 210, 265),
        (75, 135, 160, 220, 275), (80, 150, 175, 240, 295), (90, 160, 190, 260, 320), (95, 175, 205, 275, 330),
        (100, 185, 215, 285, 350), (110, 195, 230, 300, 365)],
    ("hombre", "press"): [
        (55, 75, 90, 110, 130), (60, 80, 100, 115, 140), (65, 85, 105, 125, 150),
        (70, 95, 120, 140, 170), (75, 100, 130, 155, 190), (80, 110, 140, 165, 220),
        (85, 115, 145, 175, 235), (90, 120, 155, 185, 255), (95, 125, 160, 190, 265),
        (95, 130, 165, 195, 275), (100, 135, 170, 200, 280), (100, 140, 175, 205, 285)],
    ("mujer", "press"): [
        (30, 40, 50, 65, 85), (35, 45, 55, 70, 90), (35, 50, 60, 75, 100), (40, 50, 60, 80, 105),
        (40, 55, 65, 85, 110), (45, 60, 70, 95, 120), (50, 65, 75, 105, 135), (50, 70, 80, 110, 140),
        (55, 75, 85, 115, 150), (60, 80, 95, 125, 160)],
}


def _to_kg(lb):
    return None if lb is None else lb / LB_PER_KG


# Las mismas tablas en kg: (límite de la categoría | None, 5 umbrales).
TABLES = {
    (sex, lift): [
        (_to_kg(limit), *(_to_kg(v) for v in row))
        for limit, row in zip(_MEN_LB if sex == "hombre" else _WOMEN_LB, rows)
    ]
    for (sex, lift), rows in TABLES_LB.items()
}
assert all(len(rows) == len(_MEN_LB if sex == "hombre" else _WOMEN_LB) for (sex, _), rows in TABLES_LB.items())

MAX_EFFECTIVE_REPS = 10
BW_AFTER_MAX_DAYS = 30
CURRENT_WINDOW_DAYS = 365


# ------------------------------------------------------------ detección
# Solo el levantamiento de la tabla, no sus variantes (otra carga, otro
# estándar). Es preferible no reconocer un nombre raro que contar mal.
_LIFT_WORDS = {
    "bench": ("press de banca", "press banca", "press en banca", "bench press", "banca plana"),
    "squat": ("sentadilla", "squat"),
    "deadlift": ("peso muerto", "deadlift"),
    "press": ("press militar", "military press", "overhead press", "press por encima de la cabeza"),
}
_COMMON_EXCLUDE = (
    "mancuerna", "dumbbell", "kettlebell", "pesa rusa", "smith", "multipower", "maquina", "machine",
    "banda", "band", "cadena", "chain", "landmine", "unilateral", "una pierna", "un brazo",
    "single", "one arm", "one-arm", "one leg",
)
_LIFT_EXCLUDE = {
    "bench": ("inclinad", "incline", "declinad", "decline", "agarre cerrado", "agarre estrecho", "close",
              "suelo", "floor", "tabla", "board", "pin", "spoto", "guillotina", "guillotine"),
    "squat": ("bulgara", "bulgarian", "hack", "goblet", "frontal", "front", "zercher", "overhead",
              "por encima", "split", "zancada", "lunge", "pistol", "sissy", "caja", "box", "banco",
              "bench", "salto", "jump", "peso corporal", "bodyweight", "sin peso", "prensa", "press",
              "sumo", "cinturon", "belt"),
    "deadlift": ("rumano", "romanian", "rigida", "stiff", "piernas rectas", "straight", "deficit",
                 "rack", "bloque", "block", "trap", "hexagonal", "parcial", "partial", "snatch",
                 "arranque"),
    "press": ("sentado", "seated", "arnold", "push press", "tras nuca", "behind", "nuca"),
}


def _strip(s):
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def lift_of(exercise_name):
    """"bench"/"squat"/"deadlift"/"press" si el nombre es ESE levantamiento
    (con barra, sin variantes); None si no. "banca" a secas cuenta como
    banca, pero no como parte de otro nombre ("fondos en banca")."""
    name = _strip(exercise_name or "").strip()
    if name == "banca":
        return "bench"
    for lift in LIFTS:
        if any(w in name for w in _LIFT_WORDS[lift]):
            if any(w in name for w in _COMMON_EXCLUDE + _LIFT_EXCLUDE[lift]):
                return None
            return lift
    return None


# ------------------------------------------------------------ umbrales
def thresholds(sex, lift, body_weight):
    """Umbrales en kg (Principiante..Élite) para ese sexo, levantamiento y
    peso corporal. None si el sexo no es "hombre"/"mujer"."""
    table = TABLES.get((sex, lift))
    if table is None or not body_weight:
        return None
    limited = [r for r in table if r[0] is not None]
    if body_weight > limited[-1][0]:
        return list(table[-1][1:])  # fila "+"
    if body_weight <= limited[0][0]:
        return list(limited[0][1:])
    for lo, hi in zip(limited, limited[1:]):
        if lo[0] <= body_weight <= hi[0]:
            t = (body_weight - lo[0]) / (hi[0] - lo[0])
            return [a + (b - a) * t for a, b in zip(lo[1:], hi[1:])]
    raise AssertionError("inalcanzable")  # pragma: no cover


def level_index(e1rm, ths):
    """-1 = por debajo de Principiante; 0..4 = Principiante..Élite."""
    idx = -1
    for i, threshold in enumerate(ths):
        if e1rm >= threshold:
            idx = i
    return idx


def level_label(idx):
    if idx is None:
        return None
    return "Por debajo de Principiante" if idx < 0 else LEVEL_LABELS[LEVELS[idx]]


# ------------------------------------------------------------ DOTS
_DOTS = {
    "hombre": ((-0.0000010930, 0.0007391293, -0.1918759221, 24.0900756, -307.75076), (40.0, 210.0)),
    "mujer": ((-0.0000010706, 0.0005158568, -0.1126655495, 13.6175032, -57.96288), (40.0, 150.0)),
}


def dots(total, body_weight, sex):
    if sex not in _DOTS or not body_weight or not total:
        return None
    (a, b, c, d, e), (lo, hi) = _DOTS[sex]
    x = min(max(body_weight, lo), hi)
    denominator = a * x ** 4 + b * x ** 3 + c * x ** 2 + d * x + e
    return total * 500.0 / denominator


# ------------------------------------------------------------ perfil
def _valid_e1rm(entry):
    """1RM estimado de la serie, o None si no vale para el estándar."""
    from app.routes import effective_reps, estimated_1rm, is_real_set

    if not is_real_set(entry) or (entry.set_type or "normal") == "calentamiento":
        return None
    if effective_reps(entry) > MAX_EFFECTIVE_REPS:
        return None
    return estimated_1rm(entry)


def _body_weight_at(points, when):
    """Peso registrado más cercano anterior a `when`; si no hay, el primero
    siempre que sea como mucho BW_AFTER_MAX_DAYS días posterior.
    points: [(fecha UTC naive, kg)] ordenados por fecha."""
    before = None
    for ts, kg in points:
        if ts <= when:
            before = kg
        else:
            break
    if before is not None:
        return before
    if points and points[0][0] - when <= timedelta(days=BW_AFTER_MAX_DAYS):
        return points[0][1]
    return None


def _naive_utc(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def strength_profile(user, rows=None, weights=None, now=None):
    """Nivel por levantamiento, nivel global y DOTS.

    rows: [(Workout, SetEntry)] ya cargadas (compute_stats las reutiliza);
    si no, se consultan. weights: BodyWeightEntry del usuario.
    """
    sex = user.sex if user.sex in ("hombre", "mujer") else None
    if rows is None:
        rows = db.session.execute(
            sa.select(Workout, SetEntry)
            .join(SetEntry, SetEntry.workout_id == Workout.id)
            .where(Workout.user_id == user.id)
            .order_by(Workout.timestamp.asc())
        ).all()
    if weights is None:
        weights = db.session.scalars(
            sa.select(BodyWeightEntry)
            .where(BodyWeightEntry.user_id == user.id)
            .order_by(BodyWeightEntry.timestamp.asc())
        ).all()
    # Siempre en UTC naive, como Workout.timestamp.
    bw_points = sorted((_naive_utc(e.timestamp), e.weight) for e in weights)
    latest_bw = bw_points[-1][1] if bw_points else None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    # Mejor e1RM válido por sesión (entreno) y levantamiento; y mejor carga
    # real levantada (para los hitos de discos, cualquier nº de reps).
    sessions = defaultdict(dict)  # lift -> {workout_id: (timestamp, e1rm, entry)}
    max_weight = defaultdict(float)
    from app.routes import is_real_set

    lift_cache = {}
    for w, s in rows:
        if s.exercise not in lift_cache:
            lift_cache[s.exercise] = lift_of(s.exercise)
        lift = lift_cache[s.exercise]
        if lift is None:
            continue
        if is_real_set(s) and (s.set_type or "normal") != "calentamiento":
            max_weight[lift] = max(max_weight[lift], s.weight)
        e1rm = _valid_e1rm(s)
        if e1rm is None:
            continue
        prev = sessions[lift].get(w.id)
        if prev is None or e1rm > prev[1]:
            sessions[lift][w.id] = (w.timestamp, e1rm)

    lifts = {}
    for lift in LIFTS:
        info = {
            "lift": lift,
            "label": LIFT_LABELS[lift],
            "rule": LIFT_RULES[lift],
            "has_data": bool(sessions[lift]),
            "max_weight": max_weight[lift] or None,
            "reached": None,         # índice -1..4 (mejor de todas las sesiones)
            "reached_label": None,
            "reached_at": None,
            "reached_e1rm": None,
            "best_e1rm_all": max((e for ts, e in sessions[lift].values()), default=None),
            "best_e1rm": None,       # mejor e1RM válido de los últimos 12 meses
            "ratio": None,           # best_e1rm / último peso
            "next_label": None,
            "next_kg": None,         # umbral del siguiente nivel con tu peso actual
            "missing_kg": None,
            "meets_next_now": False,
            "bar_pct": None,
        }
        recent = [e for ts, e in sessions[lift].values() if now - ts <= timedelta(days=CURRENT_WINDOW_DAYS)]
        info["best_e1rm"] = max(recent) if recent else None
        if sex and bw_points:
            for ts, e1rm in sorted(sessions[lift].values()):
                bw = _body_weight_at(bw_points, ts)
                ths = thresholds(sex, lift, bw)
                if ths is None:
                    continue
                idx = level_index(e1rm, ths)
                if info["reached"] is None or idx > info["reached"]:
                    info.update(reached=idx, reached_at=ts, reached_e1rm=e1rm)
            if info["reached"] is not None:
                info["reached_label"] = level_label(info["reached"])
                if info["reached"] < len(LEVELS) - 1:
                    nxt = info["reached"] + 1
                    ths_now = thresholds(sex, lift, latest_bw)
                    info["next_label"] = LEVEL_LABELS[LEVELS[nxt]]
                    info["next_kg"] = ths_now[nxt]
                    if info["best_e1rm"] is not None:
                        info["missing_kg"] = max(0.0, ths_now[nxt] - info["best_e1rm"])
                        info["meets_next_now"] = info["best_e1rm"] >= ths_now[nxt]
                        # Barra: del umbral del nivel actual (0 si aún no hay
                        # nivel) al del siguiente, con tu peso actual.
                        floor = ths_now[nxt - 1] if nxt > 0 else 0.0
                        span = ths_now[nxt] - floor
                        info["bar_pct"] = round(100 * min(1.0, max(0.0, (info["best_e1rm"] - floor) / span))) if span > 0 else 100
        if info["best_e1rm"] is not None and latest_bw:
            info["ratio"] = info["best_e1rm"] / latest_bw
        lifts[lift] = info

    # Qué falta para poder dar niveles.
    missing = []
    if not sex:
        missing.append("sexo")
    if not bw_points:
        missing.append("peso corporal")
    missing_lifts = [LIFT_LABELS[l] for l in BIG_THREE if not lifts[l]["has_data"]]

    global_level = None
    if not missing and not missing_lifts and all(lifts[l]["reached"] is not None for l in BIG_THREE):
        global_level = min(lifts[l]["reached"] for l in BIG_THREE)

    dots_score = None
    if sex and latest_bw and all(lifts[l]["best_e1rm"] for l in BIG_THREE):
        total = sum(lifts[l]["best_e1rm"] for l in BIG_THREE)
        dots_score = dots(total, latest_bw, sex)

    return {
        "sex": sex,
        "latest_bw": latest_bw,
        "lifts": lifts,
        "missing": missing,
        "missing_lifts": missing_lifts,
        "global": global_level,
        "global_label": level_label(global_level),
        "dots": dots_score,
    }
