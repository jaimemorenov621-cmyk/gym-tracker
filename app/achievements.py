"""Sistema de logros.

El catálogo vive aquí, en código (no en la base de datos): cada logro es una
métrica de las estadísticas del usuario y un objetivo, o una comprobación
propia. Las estadísticas se calculan de golpe (una consulta para todo el
historial de series + unas pocas para el resto) y solo se guarda en
UserAchievement CUÁNDO se desbloqueó cada uno.

Añadir un logro = añadir una línea a ACHIEVEMENTS. El código (`code`) no se
puede cambiar una vez publicado: es lo que se guarda por usuario.
"""
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import sqlalchemy as sa

from app import db
from app import strength_standards as standards
from app.models import (
    AiAnalysis,
    BodyWeightEntry,
    ExerciseFavorite,
    ExerciseNote,
    Routine,
    SetEntry,
    UserAchievement,
    Workout,
)

CATEGORIES = [
    ("constancia", "Constancia", "🔥"),
    ("fuerza", "Fuerza", "🏋️"),
    ("estandares", "Estándares de fuerza", "🎖️"),
    ("volumen", "Volumen", "📦"),
    ("records", "Récords", "🏅"),
    ("habitos", "Horarios y hábitos", "⏰"),
    ("exploracion", "Exploración", "🧭"),
    ("divertidos", "Divertidos", "🎉"),
    ("extremos", "Extremos", "💀"),
    ("secretos", "Secretos", "🤫"),
]


@dataclass(frozen=True)
class Achievement:
    code: str
    category: str
    emoji: str
    title: str
    desc: str
    metric: Optional[str] = None          # clave de stats que se compara con target
    target: Optional[float] = None
    check: Optional[Callable] = None      # alternativa: función stats -> bool
    secret: bool = False                  # oculto ("???") hasta conseguirlo
    unit: str = ""                        # para mostrar el progreso ("kg", "días"...)


def _tiers(prefix, category, metric, unit, rows):
    """Familia escalonada: rows = [(objetivo, emoji, título, descripción), ...]."""
    return [
        Achievement(f"{prefix}_{int(t)}", category, e, title, desc, metric=metric, target=t, unit=unit)
        for t, e, title, desc in rows
    ]


A = Achievement
_LEVEL_EMOJI = {"principiante": "🌱", "novato": "🥉", "intermedio": "🥈", "avanzado": "🥇", "elite": "👑"}
ACHIEVEMENTS = [
    # ---------------------------------------------------------------- Constancia
    *_tiers("workouts", "constancia", "workouts", "entrenos", [
        (1, "👟", "Primer paso", "Completa tu primer entreno."),
        (5, "🖐️", "Cogiendo el ritmo", "Completa 5 entrenos."),
        (10, "🔟", "Ya no es casualidad", "Completa 10 entrenos."),
        (25, "🧱", "Hábito en construcción", "Completa 25 entrenos."),
        (50, "🥈", "Medio centenar", "Completa 50 entrenos."),
        (100, "💯", "El club de los 100", "Completa 100 entrenos."),
        (250, "🏛️", "Veterano", "Completa 250 entrenos."),
        (500, "🗿", "Parte del mobiliario", "Completa 500 entrenos."),
    ]),
    *_tiers("streak", "constancia", "streak_days", "días", [
        (7, "🔥", "Racha encendida", "Llega a una racha de 7 días entrenados."),
        (14, "🔥", "Racha de dos semanas", "Llega a una racha de 14 días entrenados."),
        (30, "🌋", "Imparable", "Llega a una racha de 30 días entrenados."),
        (60, "☄️", "Fuerza de la naturaleza", "Llega a una racha de 60 días entrenados."),
        (100, "🌞", "Racha centenaria", "Llega a una racha de 100 días entrenados."),
    ]),
    *_tiers("weekdays", "constancia", "max_week_days", "días", [
        (3, "📅", "Tres por semana", "Entrena 3 días distintos en una misma semana."),
        (4, "📆", "Cuatro por semana", "Entrena 4 días distintos en una misma semana."),
        (5, "🗓️", "Laborable completo", "Entrena 5 días distintos en una misma semana."),
    ]),
    *_tiers("months", "constancia", "months_active", "meses", [
        (2, "🌱", "Segundo mes", "Entrena en 2 meses distintos."),
        (3, "🌿", "Un trimestre", "Entrena en 3 meses distintos."),
        (6, "🌳", "Medio año", "Entrena en 6 meses distintos."),
        (12, "🎂", "Un año de hierro", "Entrena en 12 meses distintos."),
    ]),
    A("comeback", "constancia", "🦅", "El regreso", "Vuelve a entrenar tras 30 días o más sin hacerlo.",
      check=lambda s: s["comeback"]),
    *_tiers("hours", "constancia", "hours_trained", "h", [
        (10, "⏳", "10 horas de hierro", "Acumula 10 horas entrenando."),
        (50, "⌛", "50 horas", "Acumula 50 horas entrenando."),
        (100, "🕰️", "Centenario de horas", "Acumula 100 horas entrenando."),
    ]),

    # ---------------------------------------------------------------- Fuerza
    *_tiers("heavy", "fuerza", "max_weight", "kg", [
        (50, "🏋️", "Medio quintal", "Haz una serie con 50 kg o más."),
        (100, "💪", "Tres cifras", "Haz una serie con 100 kg o más."),
        (150, "🦍", "Gorila", "Haz una serie con 150 kg o más."),
        (200, "🐻", "Oso", "Haz una serie con 200 kg o más."),
    ]),
    A("bench_bw", "fuerza", "🛋️", "Tu propio peso en banca",
      "Llega a un 1RM estimado en press de banca igual a tu peso corporal.",
      metric="bench_bw", target=1.0, unit="× tu peso"),
    A("bench_15bw", "fuerza", "🚀", "Banca avanzada",
      "Llega a un 1RM estimado en press de banca de 1,5 veces tu peso corporal.",
      metric="bench_bw", target=1.5, unit="× tu peso"),
    A("squat_15bw", "fuerza", "🦵", "Piernas de acero",
      "Llega a un 1RM estimado en sentadilla de 1,5 veces tu peso corporal.",
      metric="squat_bw", target=1.5, unit="× tu peso"),
    A("squat_2bw", "fuerza", "🏔️", "Doble en sentadilla",
      "Llega a un 1RM estimado en sentadilla del doble de tu peso corporal.",
      metric="squat_bw", target=2.0, unit="× tu peso"),
    A("deadlift_2bw", "fuerza", "🏗️", "Grúa humana",
      "Llega a un 1RM estimado en peso muerto del doble de tu peso corporal.",
      metric="deadlift_bw", target=2.0, unit="× tu peso"),
    A("deadlift_25bw", "fuerza", "🌍", "Levantas el planeta",
      "Llega a un 1RM estimado en peso muerto de 2,5 veces tu peso corporal.",
      metric="deadlift_bw", target=2.5, unit="× tu peso"),
    *_tiers("e1rm", "fuerza", "best_e1rm", "kg", [
        (100, "📈", "1RM de tres cifras", "Llega a un 1RM estimado de 100 kg en cualquier ejercicio."),
        (150, "📊", "1RM de 150", "Llega a un 1RM estimado de 150 kg en cualquier ejercicio."),
    ]),

    # ---------------------------------------------------------------- Estándares
    # Niveles de Kilgore (ExRx), ver app/strength_standards.py. Nivel
    # "alcanzado": cada sesión con el peso corporal de ese momento.
    *[
        A(f"std_{lift}_{level}", "estandares", _LEVEL_EMOJI[level],
          f"{standards.LIFT_LABELS[lift]}: {standards.LEVEL_LABELS[level]}",
          f"Alcanza el nivel {standards.LEVEL_LABELS[level]} en {standards.LIFT_LABELS[lift].lower()} "
          f"según los estándares de Lon Kilgore (1RM estimado con series de hasta 10 reps, "
          f"según tu sexo y tu peso corporal).",
          check=(lambda s, lift=lift, i=i: s[f"std_{lift}"] is not None and s[f"std_{lift}"] >= i))
        for lift in standards.LIFTS
        for i, level in enumerate(standards.LEVELS)
    ],
    A("std_big3_intermedio", "estandares", "🥈", "Intermedio en los tres grandes",
      "Nivel Intermedio o más en press de banca, sentadilla y peso muerto a la vez.",
      check=lambda s: s["std_big3"] is not None and s["std_big3"] >= 2),
    A("std_big3_avanzado", "estandares", "🥇", "Avanzado en los tres grandes",
      "Nivel Avanzado o más en press de banca, sentadilla y peso muerto a la vez.",
      check=lambda s: s["std_big3"] is not None and s["std_big3"] >= 3),
    A("std_big3_elite", "estandares", "👑", "Élite en los tres grandes",
      "Nivel Élite en press de banca, sentadilla y peso muerto: nivel de competición.",
      check=lambda s: s["std_big3"] is not None and s["std_big3"] >= 4),
    # Hitos de discos: barra de 20 kg + discos de 20 kg por lado.
    *_tiers("plates_bench", "estandares", "max_bench_kg", "kg", [
        (60, "🔵", "Banca: un disco por lado", "Haz press de banca con 60 kg (barra + un disco de 20 por lado)."),
        (100, "🔵", "Banca: dos discos", "Haz press de banca con 100 kg (dos discos de 20 por lado)."),
        (140, "🔵", "Banca: tres discos", "Haz press de banca con 140 kg (tres discos de 20 por lado)."),
    ]),
    *_tiers("plates_squat", "estandares", "max_squat_kg", "kg", [
        (100, "🟣", "Sentadilla: dos discos", "Haz sentadilla con 100 kg (dos discos de 20 por lado)."),
        (140, "🟣", "Sentadilla: tres discos", "Haz sentadilla con 140 kg (tres discos de 20 por lado)."),
        (180, "🟣", "Sentadilla: cuatro discos", "Haz sentadilla con 180 kg (cuatro discos de 20 por lado)."),
    ]),
    *_tiers("plates_deadlift", "estandares", "max_deadlift_kg", "kg", [
        (140, "🟠", "Peso muerto: tres discos", "Haz peso muerto con 140 kg (tres discos de 20 por lado)."),
        (180, "🟠", "Peso muerto: cuatro discos", "Haz peso muerto con 180 kg (cuatro discos de 20 por lado)."),
        (220, "🟠", "Peso muerto: cinco discos", "Haz peso muerto con 220 kg (cinco discos de 20 por lado)."),
    ]),
    *_tiers("dots", "estandares", "dots", "puntos", [
        (200, "📐", "DOTS 200", "Llega a 200 puntos DOTS con tus 1RM estimados de banca, sentadilla y peso muerto."),
        (300, "📐", "DOTS 300", "Llega a 300 puntos DOTS: un total sólido para tu peso."),
        (400, "📐", "DOTS 400", "Llega a 400 puntos DOTS: nivel de powerlifter competitivo."),
        (500, "📐", "DOTS 500", "Llega a 500 puntos DOTS: nivel de competición nacional o más."),
    ]),

    # ---------------------------------------------------------------- Volumen
    *_tiers("volume", "volumen", "volume_t", "t", [
        (1, "🚗", "Un coche", "Mueve 1 tonelada en total (peso × reps)."),
        (6, "🐘", "Un elefante", "Mueve 6 toneladas en total: un elefante africano."),
        (25, "🦖", "Un T-Rex... y pico", "Mueve 25 toneladas en total."),
        (60, "🪖", "Un tanque", "Mueve 60 toneladas en total: un carro de combate."),
        (150, "🐋", "Una ballena azul", "Mueve 150 toneladas en total: el animal más grande del planeta."),
        (400, "✈️", "Un jumbo", "Mueve 400 toneladas en total: un Boeing 747 cargado."),
    ]),
    *_tiers("sets", "volumen", "sets", "series", [
        (10, "✔️", "Primeras diez", "Completa 10 series."),
        (100, "✅", "Cien series", "Completa 100 series."),
        (500, "📋", "Quinientas", "Completa 500 series."),
        (1000, "🧾", "Mil series", "Completa 1.000 series."),
        (2500, "📚", "Archivo de series", "Completa 2.500 series."),
    ]),
    *_tiers("reps", "volumen", "reps", "reps", [
        (100, "🔁", "Cien repeticiones", "Acumula 100 repeticiones."),
        (1000, "🔄", "Mil repeticiones", "Acumula 1.000 repeticiones."),
        (10000, "🌀", "Diez mil", "Acumula 10.000 repeticiones."),
        (25000, "🌪️", "Huracán de reps", "Acumula 25.000 repeticiones."),
    ]),
    *_tiers("session_volume", "volumen", "max_session_volume_t", "t", [
        (5, "🧳", "Sesión cargada", "Mueve 5 toneladas en un solo entreno."),
        (10, "🚚", "Camión de mudanzas", "Mueve 10 toneladas en un solo entreno."),
    ]),
    *_tiers("session_sets", "volumen", "max_session_sets", "series", [
        (20, "📈", "Sesión larga", "Haz 20 series en un solo entreno."),
        (30, "🧨", "Volumen monstruoso", "Haz 30 series en un solo entreno."),
    ]),

    # ---------------------------------------------------------------- Récords
    *_tiers("prs", "records", "prs", "récords", [
        (1, "🏅", "Primer récord", "Bate tu primer récord personal."),
        (10, "🥉", "Coleccionista de récords", "Bate 10 récords personales."),
        (25, "🥈", "Rompe-marcas", "Bate 25 récords personales."),
        (50, "🥇", "Máquina de récords", "Bate 50 récords personales."),
        (100, "👑", "Leyenda de los récords", "Bate 100 récords personales."),
    ]),
    *_tiers("session_prs", "records", "max_session_prs", "récords", [
        (3, "🎯", "Triplete", "Bate 3 récords en un mismo entreno."),
        (5, "🎆", "Día histórico", "Bate 5 récords en un mismo entreno."),
    ]),
    *_tiers("pr_exercises", "records", "pr_exercises", "ejercicios", [
        (5, "🗂️", "Récords variados", "Ten récords en 5 ejercicios distintos."),
        (15, "🧰", "Fuerte en todo", "Ten récords en 15 ejercicios distintos."),
    ]),

    # ---------------------------------------------------------------- Hábitos
    *_tiers("early", "habitos", "early", "entrenos", [
        (1, "🌅", "Madrugador", "Empieza un entreno antes de las 7:00."),
        (10, "🐓", "Gallo del gimnasio", "Empieza 10 entrenos antes de las 7:00."),
    ]),
    *_tiers("late", "habitos", "late", "entrenos", [
        (1, "🦉", "Búho", "Empieza un entreno a partir de las 22:00."),
        (10, "🌙", "Criatura de la noche", "Empieza 10 entrenos a partir de las 22:00."),
    ]),
    *_tiers("weekend", "habitos", "weekend", "entrenos", [
        (1, "🛹", "Ni el finde me para", "Entrena un sábado o domingo."),
        (10, "🏖️", "Guerrero de fin de semana", "Entrena 10 veces en fin de semana."),
    ]),
    *_tiers("lunch", "habitos", "lunch", "entrenos", [
        (5, "🥪", "Pausa para comer", "Empieza 5 entrenos entre las 13:00 y las 16:00."),
    ]),
    *_tiers("rated", "habitos", "rated", "valoraciones", [
        (10, "📝", "Autocrítico", "Valora 10 entrenos al terminarlos."),
    ]),
    *_tiers("comments", "habitos", "comments", "comentarios", [
        (5, "💬", "Diario de entreno", "Escribe un comentario en 5 entrenos."),
        (25, "📖", "Escritor de gimnasio", "Escribe un comentario en 25 entrenos."),
    ]),
    *_tiers("weighins", "habitos", "weighins", "registros", [
        (1, "⚖️", "Subirse a la báscula", "Registra tu peso corporal."),
        (10, "📉", "Control de peso", "Registra tu peso corporal 10 veces."),
        (30, "🔬", "Científico de ti mismo", "Registra tu peso corporal 30 veces."),
    ]),

    # ---------------------------------------------------------------- Exploración
    *_tiers("exercises", "exploracion", "exercises", "ejercicios", [
        (5, "🧭", "Explorador", "Entrena 5 ejercicios distintos."),
        (15, "🗺️", "Cartógrafo", "Entrena 15 ejercicios distintos."),
        (30, "🌐", "Enciclopedia", "Entrena 30 ejercicios distintos."),
        (50, "🛰️", "Lo has probado todo", "Entrena 50 ejercicios distintos."),
    ]),
    *_tiers("routines", "exploracion", "routines", "rutinas", [
        (1, "📐", "Con plan", "Crea tu primera rutina."),
        (4, "🧩", "Programador", "Ten 4 rutinas."),
        (10, "🏗️", "Arquitecto de rutinas", "Ten 10 rutinas."),
    ]),
    *_tiers("ai", "exploracion", "ai_analyses", "análisis", [
        (1, "🤖", "Pregúntale a la IA", "Genera tu primer análisis de IA."),
        (5, "🧠", "Entrenador digital", "Genera 5 análisis de IA."),
    ]),
    *_tiers("notes", "exploracion", "exercise_notes", "notas", [
        (3, "🗒️", "Apuntes técnicos", "Escribe notas técnicas en 3 ejercicios."),
    ]),
    *_tiers("favorites", "exploracion", "favorites", "favoritos", [
        (5, "⭐", "Tengo mis favoritos", "Marca 5 ejercicios como favoritos."),
    ]),
    *_tiers("set_types", "exploracion", "set_types_used", "tipos", [
        (4, "🎨", "Paleta completa", "Usa los 4 tipos de serie: normal, calentamiento, fallo y dropset."),
    ]),

    # ---------------------------------------------------------------- Divertidos
    A("monday_bench", "divertidos", "🌍", "Lunes internacional de pecho",
      "Haz press de banca un lunes. Como manda la tradición.", check=lambda s: s["monday_bench"]),
    A("skip_legs_never", "divertidos", "🍗", "Nunca te saltas pierna",
      "Entrena pierna (sentadilla, prensa...) en 10 entrenos distintos.", metric="leg_days", target=10, unit="entrenos"),
    *_tiers("failure", "divertidos", "failure_sets", "series", [
        (10, "😵", "Hasta el fallo", "Haz 10 series al fallo."),
        (50, "🫠", "Vives en el fallo", "Haz 50 series al fallo."),
    ]),
    *_tiers("dropsets", "divertidos", "dropsets", "dropsets", [
        (10, "🪂", "Bajando peso", "Haz 10 dropsets."),
        (50, "🎢", "Montaña rusa", "Haz 50 dropsets."),
    ]),
    A("warmup_pro", "divertidos", "🧘", "Calentar es de sabios",
      "Marca 25 series de calentamiento.", metric="warmup_sets", target=25, unit="series"),
    A("perfect_day", "divertidos", "🌈", "Día perfecto", "Valora un entreno con un 10.",
      check=lambda s: s["rating10"] > 0),
    A("bad_day", "divertidos", "🌧️", "Mal día, pero fuiste",
      "Valora un entreno con un 1 o un 2. Lo importante es que fuiste.", check=lambda s: s["rating_low"] > 0),
    A("express", "divertidos", "⚡", "Entreno exprés", "Termina un entreno de 25 minutos o menos (con series hechas).",
      check=lambda s: s["express"]),
    A("marathon", "divertidos", "🐢", "¿Vives aquí?", "Haz un entreno de más de 2 horas.",
      check=lambda s: s["longest_min"] >= 120),
    A("monotema", "divertidos", "🔂", "Monotemático", "Entrena el mismo ejercicio en 30 sesiones.",
      metric="max_exercise_sessions", target=30, unit="sesiones"),
    A("high_reps", "divertidos", "🫁", "Pulmones de acero", "Haz una serie de 25 repeticiones o más.",
      check=lambda s: s["max_reps"] >= 25),
    A("single", "divertidos", "1️⃣", "Uno y basta", "Haz una serie de 1 repetición al fallo (RIR 0 / RPE 10).",
      check=lambda s: s["true_single"]),
    A("variety_day", "divertidos", "🍱", "Bufé libre", "Haz 8 ejercicios distintos en un mismo entreno.",
      check=lambda s: s["max_session_exercises"] >= 8),

    # ---------------------------------------------------------------- Extremos
    A("workouts_1000", "extremos", "🌌", "Mil entrenos", "Completa 1.000 entrenos.", metric="workouts", target=1000, unit="entrenos"),
    A("streak_365", "extremos", "♾️", "Un año sin fallar", "Llega a una racha de 365 días entrenados.",
      metric="streak_days", target=365, unit="días"),
    A("week_7", "extremos", "🤖", "Sin días libres", "Entrena los 7 días de una misma semana.",
      metric="max_week_days", target=7, unit="días"),
    A("volume_1000", "extremos", "🚢", "Un transatlántico", "Mueve 1.000 toneladas en total.",
      metric="volume_t", target=1000, unit="t"),
    A("volume_7300", "extremos", "🗼", "La Torre Eiffel", "Mueve 7.300 toneladas en total: lo que pesa la Torre Eiffel.",
      metric="volume_t", target=7300, unit="t"),
    A("reps_100k", "extremos", "🧬", "Cien mil repeticiones", "Acumula 100.000 repeticiones.",
      metric="reps", target=100000, unit="reps"),
    A("heavy_250", "extremos", "🐉", "Dragón", "Haz una serie con 250 kg o más.", metric="max_weight", target=250, unit="kg"),
    A("deadlift_3bw", "extremos", "⚡", "Triple peso muerto", "Llega a un 1RM estimado en peso muerto del triple de tu peso.",
      metric="deadlift_bw", target=3.0, unit="× tu peso"),
    A("hours_500", "extremos", "🧙", "500 horas", "Acumula 500 horas entrenando.", metric="hours_trained", target=500, unit="h"),

    # ---------------------------------------------------------------- Secretos
    A("new_year", "secretos", "🎆", "Propósito cumplido", "Entrena un 1 de enero.", check=lambda s: s["new_year"], secret=True),
    A("christmas", "secretos", "🎄", "Turrón quemado", "Entrena un 25 de diciembre.", check=lambda s: s["christmas"], secret=True),
    A("friday13", "secretos", "🐈‍⬛", "Supersticioso no", "Entrena un viernes 13.", check=lambda s: s["friday13"], secret=True),
    A("midnight", "secretos", "🕛", "Medianoche de hierro", "Empieza un entreno entre las 0:00 y las 4:00.",
      check=lambda s: s["midnight"], secret=True),
    A("leap_day", "secretos", "🐸", "Día bisiesto", "Entrena un 29 de febrero.", check=lambda s: s["leap_day"], secret=True),
    A("anniversary", "secretos", "🎉", "Aniversario", "Sigue entrenando un año después de tu primer entreno.",
      check=lambda s: s["anniversary"], secret=True),
    A("palindrome", "secretos", "🔢", "Capicúa", "Mueve un volumen total capicúa en un entreno (p. ej. 12.321 kg).",
      check=lambda s: s["palindrome_session"], secret=True),
    A("exact_100", "secretos", "🎯", "Redondo", "Haz una serie de exactamente 100 kg × 10 repeticiones.",
      check=lambda s: s["exact_100x10"], secret=True),
]

BY_CODE = {a.code: a for a in ACHIEVEMENTS}
assert len(BY_CODE) == len(ACHIEVEMENTS), "códigos de logro repetidos"

_BENCH = ("banca", "bench")  # solo para "Lunes internacional de pecho" (laxo a propósito)
_LEGS = ("sentadilla", "squat", "prensa", "leg press", "zancada", "lunge", "hack", "bulgara", "búlgara",
         "femoral", "cuadriceps", "cuádriceps", "extension de pierna", "extensión de pierna", "hip thrust")


def _has(name, words):
    return any(w in name for w in words)


def compute_stats(user):
    """Todas las métricas que usan los logros, para un usuario."""
    from app.routes import compute_smart_streak, estimated_1rm, is_real_set, to_local

    rows = db.session.execute(
        sa.select(Workout, SetEntry)
        .join(SetEntry, SetEntry.workout_id == Workout.id)
        .where(Workout.user_id == user.id)
        .order_by(Workout.timestamp.asc())
    ).all()

    workouts = {}
    sets_by_workout = defaultdict(list)
    for w, s in rows:
        workouts[w.id] = w
        sets_by_workout[w.id].append(s)

    st = defaultdict(float)
    st.update({k: False for k in (
        "comeback", "monday_bench", "express", "true_single", "new_year", "christmas", "friday13",
        "midnight", "leap_day", "anniversary", "palindrome_session", "exact_100x10")})
    exercises, pr_exercises, set_types = set(), set(), set()
    exercise_sessions = defaultdict(int)
    best_e1rm = {"any": 0.0}
    days, months, week_days = set(), set(), defaultdict(set)
    counted = []

    for wid, w in workouts.items():
        real = [s for s in sets_by_workout[wid] if is_real_set(s)]
        if not real:
            continue  # entreno sin series hechas: no cuenta
        counted.append(w)
        local = to_local(w.timestamp)
        d = local.date()
        days.add(d)
        months.add((d.year, d.month))
        week_days[d - timedelta(days=d.weekday())].add(d)
        hour = local.hour
        st["early"] += 4 <= hour < 7
        st["late"] += hour >= 22
        st["lunch"] += 13 <= hour < 16
        st["weekend"] += d.weekday() >= 5
        st["midnight"] |= hour < 4
        st["new_year"] |= (d.month, d.day) == (1, 1)
        st["christmas"] |= (d.month, d.day) == (12, 25)
        st["friday13"] |= d.day == 13 and d.weekday() == 4
        st["leap_day"] |= (d.month, d.day) == (2, 29)
        if w.performance_rating is not None:
            st["rated"] += 1
            st["rating10"] += w.performance_rating == 10
            st["rating_low"] += w.performance_rating <= 2
        if w.performance_comment and w.performance_comment.strip():
            st["comments"] += 1
        if w.ended_at:
            minutes = (w.ended_at - w.timestamp).total_seconds() / 60
            if 0 < minutes < 24 * 60:
                st["minutes"] += minutes
                st["longest_min"] = max(st["longest_min"], minutes)
                st["express"] |= minutes <= 25

        session_volume = sum(s.weight * s.reps for s in real)
        st["max_session_volume_t"] = max(st["max_session_volume_t"], session_volume / 1000)
        st["max_session_sets"] = max(st["max_session_sets"], len(real))
        session_exercises = {s.exercise for s in real}
        st["max_session_exercises"] = max(st["max_session_exercises"], len(session_exercises))
        st["max_session_prs"] = max(st["max_session_prs"], sum(1 for s in real if s.is_pr))
        rounded = str(int(round(session_volume)))
        st["palindrome_session"] |= len(rounded) >= 3 and rounded == rounded[::-1]
        if d.weekday() == 0 and any(_has(e, _BENCH) for e in session_exercises):
            st["monday_bench"] = True
        if any(_has(e, _LEGS) for e in session_exercises):
            st["leg_days"] += 1
        for e in session_exercises:
            exercise_sessions[e] += 1

        for s in real:
            st["sets"] += 1
            st["reps"] += s.reps
            st["volume"] += s.weight * s.reps
            st["max_weight"] = max(st["max_weight"], s.weight)
            st["max_reps"] = max(st["max_reps"], s.reps)
            exercises.add(s.exercise)
            set_types.add(s.set_type or "normal")
            st["failure_sets"] += s.set_type == "fallo"
            st["dropsets"] += s.set_type == "dropset"
            st["warmup_sets"] += s.set_type == "calentamiento"
            if s.is_pr:
                st["prs"] += 1
                pr_exercises.add(s.exercise)
            if s.reps == 1 and (s.rir == 0 or s.rpe == 10):
                st["true_single"] = True
            if s.weight == 100 and s.reps == 10:
                st["exact_100x10"] = True
            best_e1rm["any"] = max(best_e1rm["any"], estimated_1rm(s))

    sorted_days = sorted(days)
    for a, b in zip(sorted_days, sorted_days[1:]):
        if (b - a).days >= 30:
            st["comeback"] = True
            break
    today = to_local(datetime.now(timezone.utc)).date()
    st["anniversary"] = bool(sorted_days) and (today - sorted_days[0]).days >= 365 and (today - sorted_days[-1]).days <= 30

    st["workouts"] = len(counted)
    st["exercises"] = len(exercises)
    st["pr_exercises"] = len(pr_exercises)
    st["set_types_used"] = len(set_types & {"normal", "calentamiento", "fallo", "dropset"})
    st["max_exercise_sessions"] = max(exercise_sessions.values(), default=0)
    st["months_active"] = len(months)
    st["max_week_days"] = max((len(v) for v in week_days.values()), default=0)
    st["volume_t"] = st["volume"] / 1000
    st["hours_trained"] = st["minutes"] / 60
    st["best_e1rm"] = best_e1rm["any"]
    st["streak_days"] = compute_smart_streak(user.id, list(workouts.values()))["days"]

    # Fuerza relativa y estándares: mismo criterio estricto que /progress
    # (solo el levantamiento con barra, sin variantes; 1RM estimado con series
    # de hasta 10 repeticiones efectivas). Ver app/strength_standards.py.
    profile = standards.strength_profile(user, rows=rows)
    latest_bw = profile["latest_bw"]
    for lift in ("bench", "squat", "deadlift"):
        best = profile["lifts"][lift]["best_e1rm_all"]
        st[f"{lift}_bw"] = (best / latest_bw) if (best and latest_bw) else 0.0
    for lift in standards.LIFTS:
        st[f"std_{lift}"] = profile["lifts"][lift]["reached"]
        st[f"max_{lift}_kg"] = profile["lifts"][lift]["max_weight"] or 0.0
    st["std_big3"] = profile["global"]
    st["dots"] = profile["dots"] or 0.0

    def count(model, *where):
        return db.session.scalar(sa.select(sa.func.count()).select_from(model).where(*where)) or 0

    st["weighins"] = count(BodyWeightEntry, BodyWeightEntry.user_id == user.id)
    st["routines"] = count(Routine, Routine.user_id == user.id)
    st["ai_analyses"] = count(AiAnalysis, AiAnalysis.user_id == user.id)
    st["favorites"] = count(ExerciseFavorite, ExerciseFavorite.user_id == user.id)
    st["exercise_notes"] = count(
        ExerciseNote, ExerciseNote.user_id == user.id, ExerciseNote.notes.is_not(None), ExerciseNote.notes != ""
    )
    return st


def _status(a, stats):
    if a.check is not None:
        return bool(a.check(stats)), None, None
    value = stats.get(a.metric, 0) or 0
    return value >= a.target, value, a.target


def progress_text(a, value, unlocked):
    """"1,47 / 1,5 × tu peso". Mientras no esté conseguido, el valor se
    redondea HACIA ABAJO: si no, 1,47 salía como "1,5 / 1,5" sin estar
    desbloqueado. Los cocientes de peso llevan 2 decimales."""
    from app.routes import fmt_num

    decimals = 2 if "peso" in a.unit else 1
    shown = value or 0
    if not unlocked:
        factor = 10 ** decimals
        shown = math.floor(shown * factor) / factor
    return f"{fmt_num(shown, decimals)} / {fmt_num(a.target, decimals)} {a.unit}".strip()


def evaluate(user):
    """Calcula todos los logros, guarda los recién conseguidos y devuelve
    (lista de dicts para mostrar, lista de logros nuevos en esta llamada)."""
    stats = compute_stats(user)
    unlocked = {
        ua.code: ua
        for ua in db.session.scalars(sa.select(UserAchievement).where(UserAchievement.user_id == user.id))
    }
    newly = []
    result = []
    for a in ACHIEVEMENTS:
        done, value, target = _status(a, stats)
        ua = unlocked.get(a.code)
        if done and ua is None:
            ua = UserAchievement(user_id=user.id, code=a.code)
            db.session.add(ua)
            unlocked[a.code] = ua
            newly.append(a)
        result.append({
            "a": a,
            "unlocked": ua is not None,
            "unlocked_at": ua.unlocked_at if ua is not None else None,
            "value": value,
            "target": target,
            # Sin conseguir, la barra nunca llega al 100 % (99,6 % no es 100 %).
            "pct": 100 if ua is not None else (min(99, math.floor(100 * value / target)) if target else 0),
            "progress": progress_text(a, value, ua is not None) if target else None,
        })
    if newly:
        db.session.commit()
    return result, newly


def unseen(user_id):
    """Logros desbloqueados aún no anunciados (y los marca como vistos)."""
    rows = db.session.scalars(
        sa.select(UserAchievement)
        .where(UserAchievement.user_id == user_id, UserAchievement.seen.is_(False))
        .order_by(UserAchievement.unlocked_at)
    ).all()
    if not rows:
        return []
    for r in rows:
        r.seen = True
    db.session.commit()
    return [BY_CODE[r.code] for r in rows if r.code in BY_CODE]
