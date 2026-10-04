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
from flask_babel import lazy_gettext as _l
from flask_babel.speaklater import LazyString

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
    ("constancia", _l("Constancia"), "🔥"),
    ("fuerza", _l("Fuerza"), "🏋️"),
    ("estandares", _l("Estándares de fuerza"), "🎖️"),
    ("volumen", _l("Volumen"), "📦"),
    ("records", _l("Récords"), "🏅"),
    ("habitos", _l("Horarios y hábitos"), "⏰"),
    ("exploracion", _l("Exploración"), "🧭"),
    ("divertidos", _l("Divertidos"), "🎉"),
    ("extremos", _l("Extremos"), "💀"),
    ("secretos", _l("Secretos"), "🤫"),
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


def _lower(text):
    """Minúsculas de un texto traducible, sin traducirlo todavía."""
    return LazyString(lambda: str(text).lower())


_LEVEL_EMOJI = {"principiante": "🌱", "novato": "🥉", "intermedio": "🥈", "avanzado": "🥇", "elite": "👑"}
ACHIEVEMENTS = [
    # ---------------------------------------------------------------- Constancia
    *_tiers("workouts", "constancia", "workouts", _l("entrenos"), [
        (1, "👟", _l("Primer paso"), _l("Completa tu primer entreno.")),
        (5, "🖐️", _l("Cogiendo el ritmo"), _l("Completa 5 entrenos.")),
        (10, "🔟", _l("Ya no es casualidad"), _l("Completa 10 entrenos.")),
        (25, "🧱", _l("Hábito en construcción"), _l("Completa 25 entrenos.")),
        (50, "🥈", _l("Medio centenar"), _l("Completa 50 entrenos.")),
        (100, "💯", _l("El club de los 100"), _l("Completa 100 entrenos.")),
        (250, "🏛️", _l("Veterano"), _l("Completa 250 entrenos.")),
        (500, "🗿", _l("Parte del mobiliario"), _l("Completa 500 entrenos.")),
    ]),
    *_tiers("streak", "constancia", "streak_days", _l("días"), [
        (7, "🔥", _l("Racha encendida"), _l("Llega a una racha de 7 días entrenados.")),
        (14, "🔥", _l("Racha de dos semanas"), _l("Llega a una racha de 14 días entrenados.")),
        (30, "🌋", _l("Imparable"), _l("Llega a una racha de 30 días entrenados.")),
        (60, "☄️", _l("Fuerza de la naturaleza"), _l("Llega a una racha de 60 días entrenados.")),
        (100, "🌞", _l("Racha centenaria"), _l("Llega a una racha de 100 días entrenados.")),
    ]),
    *_tiers("weekdays", "constancia", "max_week_days", _l("días"), [
        (3, "📅", _l("Tres por semana"), _l("Entrena 3 días distintos en una misma semana.")),
        (4, "📆", _l("Cuatro por semana"), _l("Entrena 4 días distintos en una misma semana.")),
        (5, "🗓️", _l("Laborable completo"), _l("Entrena 5 días distintos en una misma semana.")),
    ]),
    *_tiers("months", "constancia", "months_active", _l("meses"), [
        (2, "🌱", _l("Segundo mes"), _l("Entrena en 2 meses distintos.")),
        (3, "🌿", _l("Un trimestre"), _l("Entrena en 3 meses distintos.")),
        (6, "🌳", _l("Medio año"), _l("Entrena en 6 meses distintos.")),
        (12, "🎂", _l("Un año de hierro"), _l("Entrena en 12 meses distintos.")),
    ]),
    A("comeback", "constancia", "🦅", _l("El regreso"), _l("Vuelve a entrenar tras 30 días o más sin hacerlo."),
      check=lambda s: s["comeback"]),
    *_tiers("hours", "constancia", "hours_trained", "h", [
        (10, "⏳", _l("10 horas de hierro"), _l("Acumula 10 horas entrenando.")),
        (50, "⌛", _l("50 horas"), _l("Acumula 50 horas entrenando.")),
        (100, "🕰️", _l("Centenario de horas"), _l("Acumula 100 horas entrenando.")),
    ]),

    # ---------------------------------------------------------------- Fuerza
    *_tiers("heavy", "fuerza", "max_weight", "kg", [
        (50, "🏋️", _l("Medio quintal"), _l("Haz una serie con 50 kg o más.")),
        (100, "💪", _l("Tres cifras"), _l("Haz una serie con 100 kg o más.")),
        (150, "🦍", _l("Gorila"), _l("Haz una serie con 150 kg o más.")),
        (200, "🐻", _l("Oso"), _l("Haz una serie con 200 kg o más.")),
    ]),
    A("bench_bw", "fuerza", "🛋️", _l("Tu propio peso en banca"),
      _l("Llega a un 1RM estimado en press de banca igual a tu peso corporal."),
      metric="bench_bw", target=1.0, unit=_l("× tu peso")),
    A("bench_15bw", "fuerza", "🚀", _l("Banca avanzada"),
      _l("Llega a un 1RM estimado en press de banca de 1,5 veces tu peso corporal."),
      metric="bench_bw", target=1.5, unit=_l("× tu peso")),
    A("squat_15bw", "fuerza", "🦵", _l("Piernas de acero"),
      _l("Llega a un 1RM estimado en sentadilla de 1,5 veces tu peso corporal."),
      metric="squat_bw", target=1.5, unit=_l("× tu peso")),
    A("squat_2bw", "fuerza", "🏔️", _l("Doble en sentadilla"),
      _l("Llega a un 1RM estimado en sentadilla del doble de tu peso corporal."),
      metric="squat_bw", target=2.0, unit=_l("× tu peso")),
    A("deadlift_2bw", "fuerza", "🏗️", _l("Grúa humana"),
      _l("Llega a un 1RM estimado en peso muerto del doble de tu peso corporal."),
      metric="deadlift_bw", target=2.0, unit=_l("× tu peso")),
    A("deadlift_25bw", "fuerza", "🌍", _l("Levantas el planeta"),
      _l("Llega a un 1RM estimado en peso muerto de 2,5 veces tu peso corporal."),
      metric="deadlift_bw", target=2.5, unit=_l("× tu peso")),
    *_tiers("e1rm", "fuerza", "best_e1rm", "kg", [
        (100, "📈", _l("1RM de tres cifras"), _l("Llega a un 1RM estimado de 100 kg en cualquier ejercicio.")),
        (150, "📊", _l("1RM de 150"), _l("Llega a un 1RM estimado de 150 kg en cualquier ejercicio.")),
    ]),

    # ---------------------------------------------------------------- Estándares
    # Niveles de Kilgore (ExRx), ver app/strength_standards.py. Nivel
    # "alcanzado": cada sesión con el peso corporal de ese momento.
    *[
        A(f"std_{lift}_{level}", "estandares", _LEVEL_EMOJI[level],
          _l("%(lift)s: %(level)s", lift=standards.LIFT_LABELS[lift], level=standards.LEVEL_LABELS[level]),
          _l("Alcanza el nivel %(level)s en %(lift)s según los estándares de %(source)s "
             "(1RM estimado con series de hasta 10 reps, según tu sexo y tu peso corporal).",
             level=standards.LEVEL_LABELS[level], lift=_lower(standards.LIFT_LABELS[lift]),
             source="StrengthLevel" if lift in standards.SL_LIFTS else "Lon Kilgore"),
          check=(lambda s, lift=lift, i=i: s[f"std_{lift}"] is not None and s[f"std_{lift}"] >= i))
        for lift in standards.LIFTS
        for i, level in enumerate(standards.LEVELS)
    ],
    A("std_big3_intermedio", "estandares", "🥈", _l("Intermedio en los tres grandes"),
      _l("Nivel Intermedio o más en press de banca, sentadilla y peso muerto a la vez."),
      check=lambda s: s["std_big3"] is not None and s["std_big3"] >= 2),
    A("std_big3_avanzado", "estandares", "🥇", _l("Avanzado en los tres grandes"),
      _l("Nivel Avanzado o más en press de banca, sentadilla y peso muerto a la vez."),
      check=lambda s: s["std_big3"] is not None and s["std_big3"] >= 3),
    A("std_big3_elite", "estandares", "👑", _l("Élite en los tres grandes"),
      _l("Nivel Élite en press de banca, sentadilla y peso muerto: nivel de competición."),
      check=lambda s: s["std_big3"] is not None and s["std_big3"] >= 4),
    # Hitos de discos: barra de 20 kg + discos de 20 kg por lado.
    *_tiers("plates_bench", "estandares", "max_bench_kg", "kg", [
        (60, "🔵", _l("Banca: un disco por lado"), _l("Haz press de banca con 60 kg (barra + un disco de 20 por lado).")),
        (100, "🔵", _l("Banca: dos discos"), _l("Haz press de banca con 100 kg (dos discos de 20 por lado).")),
        (140, "🔵", _l("Banca: tres discos"), _l("Haz press de banca con 140 kg (tres discos de 20 por lado).")),
    ]),
    *_tiers("plates_squat", "estandares", "max_squat_kg", "kg", [
        (100, "🟣", _l("Sentadilla: dos discos"), _l("Haz sentadilla con 100 kg (dos discos de 20 por lado).")),
        (140, "🟣", _l("Sentadilla: tres discos"), _l("Haz sentadilla con 140 kg (tres discos de 20 por lado).")),
        (180, "🟣", _l("Sentadilla: cuatro discos"), _l("Haz sentadilla con 180 kg (cuatro discos de 20 por lado).")),
    ]),
    *_tiers("plates_deadlift", "estandares", "max_deadlift_kg", "kg", [
        (140, "🟠", _l("Peso muerto: tres discos"), _l("Haz peso muerto con 140 kg (tres discos de 20 por lado).")),
        (180, "🟠", _l("Peso muerto: cuatro discos"), _l("Haz peso muerto con 180 kg (cuatro discos de 20 por lado).")),
        (220, "🟠", _l("Peso muerto: cinco discos"), _l("Haz peso muerto con 220 kg (cinco discos de 20 por lado).")),
    ]),
    *_tiers("dots", "estandares", "dots", _l("puntos"), [
        (200, "📐", _l("DOTS 200"), _l("Llega a 200 puntos DOTS con tus 1RM estimados de banca, sentadilla y peso muerto.")),
        (300, "📐", _l("DOTS 300"), _l("Llega a 300 puntos DOTS: un total sólido para tu peso.")),
        (400, "📐", _l("DOTS 400"), _l("Llega a 400 puntos DOTS: nivel de powerlifter competitivo.")),
        (500, "📐", _l("DOTS 500"), _l("Llega a 500 puntos DOTS: nivel de competición nacional o más.")),
    ]),

    # ---------------------------------------------------------------- Volumen
    *_tiers("volume", "volumen", "volume_t", "t", [
        (1, "🚗", _l("Un coche"), _l("Mueve 1 tonelada en total (peso × reps).")),
        (6, "🐘", _l("Un elefante"), _l("Mueve 6 toneladas en total: un elefante africano.")),
        (25, "🦖", _l("Un T-Rex... y pico"), _l("Mueve 25 toneladas en total.")),
        (60, "🪖", _l("Un tanque"), _l("Mueve 60 toneladas en total: un carro de combate.")),
        (150, "🐋", _l("Una ballena azul"), _l("Mueve 150 toneladas en total: el animal más grande del planeta.")),
        (400, "✈️", _l("Un jumbo"), _l("Mueve 400 toneladas en total: un Boeing 747 cargado.")),
    ]),
    *_tiers("sets", "volumen", "sets", _l("series"), [
        (10, "✔️", _l("Primeras diez"), _l("Completa 10 series.")),
        (100, "✅", _l("Cien series"), _l("Completa 100 series.")),
        (500, "📋", _l("Quinientas"), _l("Completa 500 series.")),
        (1000, "🧾", _l("Mil series"), _l("Completa 1.000 series.")),
        (2500, "📚", _l("Archivo de series"), _l("Completa 2.500 series.")),
    ]),
    *_tiers("reps", "volumen", "reps", _l("reps"), [
        (100, "🔁", _l("Cien repeticiones"), _l("Acumula 100 repeticiones.")),
        (1000, "🔄", _l("Mil repeticiones"), _l("Acumula 1.000 repeticiones.")),
        (10000, "🌀", _l("Diez mil"), _l("Acumula 10.000 repeticiones.")),
        (25000, "🌪️", _l("Huracán de reps"), _l("Acumula 25.000 repeticiones.")),
    ]),
    *_tiers("session_volume", "volumen", "max_session_volume_t", "t", [
        (5, "🧳", _l("Sesión cargada"), _l("Mueve 5 toneladas en un solo entreno.")),
        (10, "🚚", _l("Camión de mudanzas"), _l("Mueve 10 toneladas en un solo entreno.")),
    ]),
    *_tiers("session_sets", "volumen", "max_session_sets", _l("series"), [
        (20, "📈", _l("Sesión larga"), _l("Haz 20 series en un solo entreno.")),
        (30, "🧨", _l("Volumen monstruoso"), _l("Haz 30 series en un solo entreno.")),
    ]),

    # ---------------------------------------------------------------- Récords
    *_tiers("prs", "records", "prs", _l("récords"), [
        (1, "🏅", _l("Primer récord"), _l("Bate tu primer récord personal.")),
        (10, "🥉", _l("Coleccionista de récords"), _l("Bate 10 récords personales.")),
        (25, "🥈", _l("Rompe-marcas"), _l("Bate 25 récords personales.")),
        (50, "🥇", _l("Máquina de récords"), _l("Bate 50 récords personales.")),
        (100, "👑", _l("Leyenda de los récords"), _l("Bate 100 récords personales.")),
    ]),
    *_tiers("session_prs", "records", "max_session_prs", _l("récords"), [
        (3, "🎯", _l("Triplete"), _l("Bate 3 récords en un mismo entreno.")),
        (5, "🎆", _l("Día histórico"), _l("Bate 5 récords en un mismo entreno.")),
    ]),
    *_tiers("pr_exercises", "records", "pr_exercises", _l("ejercicios"), [
        (5, "🗂️", _l("Récords variados"), _l("Ten récords en 5 ejercicios distintos.")),
        (15, "🧰", _l("Fuerte en todo"), _l("Ten récords en 15 ejercicios distintos.")),
    ]),

    # ---------------------------------------------------------------- Hábitos
    *_tiers("early", "habitos", "early", _l("entrenos"), [
        (1, "🌅", _l("Madrugador"), _l("Empieza un entreno antes de las 7:00.")),
        (10, "🐓", _l("Gallo del gimnasio"), _l("Empieza 10 entrenos antes de las 7:00.")),
    ]),
    *_tiers("late", "habitos", "late", _l("entrenos"), [
        (1, "🦉", _l("Búho"), _l("Empieza un entreno a partir de las 22:00.")),
        (10, "🌙", _l("Criatura de la noche"), _l("Empieza 10 entrenos a partir de las 22:00.")),
    ]),
    *_tiers("weekend", "habitos", "weekend", _l("entrenos"), [
        (1, "🛹", _l("Ni el finde me para"), _l("Entrena un sábado o domingo.")),
        (10, "🏖️", _l("Guerrero de fin de semana"), _l("Entrena 10 veces en fin de semana.")),
    ]),
    *_tiers("lunch", "habitos", "lunch", _l("entrenos"), [
        (5, "🥪", _l("Pausa para comer"), _l("Empieza 5 entrenos entre las 13:00 y las 16:00.")),
    ]),
    *_tiers("rated", "habitos", "rated", _l("valoraciones"), [
        (10, "📝", _l("Autocrítico"), _l("Valora 10 entrenos al terminarlos.")),
    ]),
    *_tiers("comments", "habitos", "comments", _l("comentarios"), [
        (5, "💬", _l("Diario de entreno"), _l("Escribe un comentario en 5 entrenos.")),
        (25, "📖", _l("Escritor de gimnasio"), _l("Escribe un comentario en 25 entrenos.")),
    ]),
    *_tiers("weighins", "habitos", "weighins", _l("registros"), [
        (1, "⚖️", _l("Subirse a la báscula"), _l("Registra tu peso corporal.")),
        (10, "📉", _l("Control de peso"), _l("Registra tu peso corporal 10 veces.")),
        (30, "🔬", _l("Científico de ti mismo"), _l("Registra tu peso corporal 30 veces.")),
    ]),

    # ---------------------------------------------------------------- Exploración
    *_tiers("exercises", "exploracion", "exercises", _l("ejercicios"), [
        (5, "🧭", _l("Explorador"), _l("Entrena 5 ejercicios distintos.")),
        (15, "🗺️", _l("Cartógrafo"), _l("Entrena 15 ejercicios distintos.")),
        (30, "🌐", _l("Enciclopedia"), _l("Entrena 30 ejercicios distintos.")),
        (50, "🛰️", _l("Lo has probado todo"), _l("Entrena 50 ejercicios distintos.")),
    ]),
    *_tiers("routines", "exploracion", "routines", _l("rutinas"), [
        (1, "📐", _l("Con plan"), _l("Crea tu primera rutina.")),
        (4, "🧩", _l("Programador"), _l("Ten 4 rutinas.")),
        (10, "🏗️", _l("Arquitecto de rutinas"), _l("Ten 10 rutinas.")),
    ]),
    *_tiers("ai", "exploracion", "ai_analyses", _l("análisis"), [
        (1, "🤖", _l("Pregúntale a la IA"), _l("Genera tu primer análisis de IA.")),
        (5, "🧠", _l("Entrenador digital"), _l("Genera 5 análisis de IA.")),
    ]),
    *_tiers("notes", "exploracion", "exercise_notes", _l("notas"), [
        (3, "🗒️", _l("Apuntes técnicos"), _l("Escribe notas técnicas en 3 ejercicios.")),
    ]),
    *_tiers("favorites", "exploracion", "favorites", _l("favoritos"), [
        (5, "⭐", _l("Tengo mis favoritos"), _l("Marca 5 ejercicios como favoritos.")),
    ]),
    *_tiers("set_types", "exploracion", "set_types_used", _l("tipos"), [
        (4, "🎨", _l("Paleta completa"), _l("Usa los 4 tipos de serie: normal, calentamiento, fallo y dropset.")),
    ]),

    # ---------------------------------------------------------------- Divertidos
    A("monday_bench", "divertidos", "🌍", _l("Lunes internacional de pecho"),
      _l("Haz press de banca un lunes. Como manda la tradición."), check=lambda s: s["monday_bench"]),
    A("skip_legs_never", "divertidos", "🍗", _l("Nunca te saltas pierna"),
      _l("Entrena pierna (sentadilla, prensa...) en 10 entrenos distintos."), metric="leg_days", target=10, unit=_l("entrenos")),
    *_tiers("failure", "divertidos", "failure_sets", _l("series"), [
        (10, "😵", _l("Hasta el fallo"), _l("Haz 10 series al fallo.")),
        (50, "🫠", _l("Vives en el fallo"), _l("Haz 50 series al fallo.")),
    ]),
    *_tiers("dropsets", "divertidos", "dropsets", _l("dropsets"), [
        (10, "🪂", _l("Bajando peso"), _l("Haz 10 dropsets.")),
        (50, "🎢", _l("Montaña rusa"), _l("Haz 50 dropsets.")),
    ]),
    A("warmup_pro", "divertidos", "🧘", _l("Calentar es de sabios"),
      _l("Marca 25 series de calentamiento."), metric="warmup_sets", target=25, unit=_l("series")),
    A("perfect_day", "divertidos", "🌈", _l("Día perfecto"), _l("Valora un entreno con un 10."),
      check=lambda s: s["rating10"] > 0),
    A("bad_day", "divertidos", "🌧️", _l("Mal día, pero fuiste"),
      _l("Valora un entreno con un 1 o un 2. Lo importante es que fuiste."), check=lambda s: s["rating_low"] > 0),
    A("express", "divertidos", "⚡", _l("Entreno exprés"), _l("Termina un entreno de 25 minutos o menos (con series hechas)."),
      check=lambda s: s["express"]),
    A("marathon", "divertidos", "🐢", _l("¿Vives aquí?"), _l("Haz un entreno de más de 2 horas."),
      check=lambda s: s["longest_min"] >= 120),
    A("monotema", "divertidos", "🔂", _l("Monotemático"), _l("Entrena el mismo ejercicio en 30 sesiones."),
      metric="max_exercise_sessions", target=30, unit=_l("sesiones")),
    A("high_reps", "divertidos", "🫁", _l("Pulmones de acero"), _l("Haz una serie de 25 repeticiones o más."),
      check=lambda s: s["max_reps"] >= 25),
    A("single", "divertidos", "1️⃣", _l("Uno y basta"), _l("Haz una serie de 1 repetición al fallo (RIR 0 / RPE 10)."),
      check=lambda s: s["true_single"]),
    A("variety_day", "divertidos", "🍱", _l("Bufé libre"), _l("Haz 8 ejercicios distintos en un mismo entreno."),
      check=lambda s: s["max_session_exercises"] >= 8),

    # ---------------------------------------------------------------- Extremos
    A("workouts_1000", "extremos", "🌌", _l("Mil entrenos"), _l("Completa 1.000 entrenos."), metric="workouts", target=1000, unit=_l("entrenos")),
    A("streak_365", "extremos", "♾️", _l("Un año sin fallar"), _l("Llega a una racha de 365 días entrenados."),
      metric="streak_days", target=365, unit=_l("días")),
    A("week_7", "extremos", "🤖", _l("Sin días libres"), _l("Entrena los 7 días de una misma semana."),
      metric="max_week_days", target=7, unit=_l("días")),
    A("volume_1000", "extremos", "🚢", _l("Un transatlántico"), _l("Mueve 1.000 toneladas en total."),
      metric="volume_t", target=1000, unit="t"),
    A("volume_7300", "extremos", "🗼", _l("La Torre Eiffel"), _l("Mueve 7.300 toneladas en total: lo que pesa la Torre Eiffel."),
      metric="volume_t", target=7300, unit="t"),
    A("reps_100k", "extremos", "🧬", _l("Cien mil repeticiones"), _l("Acumula 100.000 repeticiones."),
      metric="reps", target=100000, unit=_l("reps")),
    A("heavy_250", "extremos", "🐉", _l("Dragón"), _l("Haz una serie con 250 kg o más."), metric="max_weight", target=250, unit="kg"),
    A("deadlift_3bw", "extremos", "⚡", _l("Triple peso muerto"), _l("Llega a un 1RM estimado en peso muerto del triple de tu peso."),
      metric="deadlift_bw", target=3.0, unit=_l("× tu peso")),
    A("hours_500", "extremos", "🧙", _l("500 horas"), _l("Acumula 500 horas entrenando."), metric="hours_trained", target=500, unit="h"),

    # ---------------------------------------------------------------- Secretos
    A("new_year", "secretos", "🎆", _l("Propósito cumplido"), _l("Entrena un 1 de enero."), check=lambda s: s["new_year"], secret=True),
    A("christmas", "secretos", "🎄", _l("Turrón quemado"), _l("Entrena un 25 de diciembre."), check=lambda s: s["christmas"], secret=True),
    A("friday13", "secretos", "🐈‍⬛", _l("Supersticioso no"), _l("Entrena un viernes 13."), check=lambda s: s["friday13"], secret=True),
    A("midnight", "secretos", "🕛", _l("Medianoche de hierro"), _l("Empieza un entreno entre las 0:00 y las 4:00."),
      check=lambda s: s["midnight"], secret=True),
    A("leap_day", "secretos", "🐸", _l("Día bisiesto"), _l("Entrena un 29 de febrero."), check=lambda s: s["leap_day"], secret=True),
    A("anniversary", "secretos", "🎉", _l("Aniversario"), _l("Sigue entrenando un año después de tu primer entreno."),
      check=lambda s: s["anniversary"], secret=True),
    A("palindrome", "secretos", "🔢", _l("Capicúa"), _l("Mueve un volumen total capicúa en un entreno (p. ej. 12.321 kg)."),
      check=lambda s: s["palindrome_session"], secret=True),
    A("exact_100", "secretos", "🎯", _l("Redondo"), _l("Haz una serie de exactamente 100 kg × 10 repeticiones."),
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
    from app.routes import compute_smart_streak, estimated_1rm, is_real_set, latest_bodyweight, to_local

    bodyweight = latest_bodyweight(user.id)  # dominadas: carga = peso + lastre

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
            best_e1rm["any"] = max(best_e1rm["any"], estimated_1rm(s, bodyweight))

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

    decimals = 2 if a.metric and a.metric.endswith("_bw") else 1
    shown = value or 0
    if not unlocked:
        factor = 10 ** decimals
        shown = math.floor(shown * factor) / factor
    return f"{fmt_num(shown, decimals)} / {fmt_num(a.target, decimals)} {a.unit}".strip()


def evaluate(user, _retry=True):
    """Calcula todos los logros, guarda los recién conseguidos y devuelve
    (lista de dicts para mostrar, lista de logros nuevos en esta llamada)."""
    from sqlalchemy.exc import IntegrityError

    stats = compute_stats(user)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
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
            # Fecha explícita: sin ella el logro recién creado no la tiene hasta
            # guardarse, y ordenar "Recientes" por fecha rompía /logros (500
            # justo la primera visita en que se desbloqueaba algo).
            ua = UserAchievement(user_id=user.id, code=a.code, unlocked_at=now)
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
        try:
            db.session.commit()
        except IntegrityError:
            # Otra petición (p. ej. la precarga del navegador) acaba de guardar
            # los mismos logros: se recalcula una vez con lo que ya hay.
            db.session.rollback()
            if _retry:
                return evaluate(user, _retry=False)
            raise
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
