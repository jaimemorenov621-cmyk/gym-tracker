"""Cuentas de demostración (vídeos, capturas, probar las ventajas de nivel).

    flask seed-demo NOMBRE [--weeks 52] [--strength 1.0] [--lang es|en] [--friend OTRO]

Crea un usuario con un historial realista: 4 entrenos por semana con
progresión y descargas, series de calentamiento/fallo/dropset, peso
corporal, check-in, rutinas, notas y básicos personales. El nivel, los
logros y el rango salen de esos datos con las reglas normales de la app
(nada se fija a mano). La contraseña se genera al azar y solo se imprime en
la terminal de quien ejecuta el comando.

Marcadas como demo: signup_method="demo" (no cuentan como altas reales en
/landing/stats) y fecha de alta al inicio del historial.
"""
import random
import secrets
from datetime import datetime, time, timedelta, timezone

import click
import sqlalchemy as sa

from app import app, db
from app.models import (
    AthleteCard, BodyWeightEntry, DailyCheckin, ExerciseNote, Friendship, PersonalBasic, Routine,
    RoutineExercise, SetEntry, User, UserAchievement, WeeklyGoalHistory, Workout,
)

# (clave, nombre es, nombre en, 1RM al final del año con fuerza 1.0 y ~80 kg, series, reps, compuesto)
EXERCISES = {
    "bench": ("press de banca", "bench press", 115, 4, 5, True),
    "row": ("remo con barra", "barbell row", 100, 4, 6, True),
    "ohp": ("press militar", "overhead press", 72, 3, 8, True),
    "pullup": ("dominadas", "pull-ups", 30, 3, 6, True),          # lastre (0 = solo el peso)
    "curl": ("curl de bíceps con barra", "barbell curl", 55, 3, 10, False),
    "lateral": ("elevaciones laterales", "lateral raise", 22, 3, 14, False),
    "squat": ("sentadilla", "squat", 150, 4, 5, True),
    "rdl": ("peso muerto rumano", "romanian deadlift", 140, 3, 8, True),
    "legpress": ("prensa", "leg press", 260, 3, 10, False),
    "legcurl": ("curl femoral", "leg curl", 75, 3, 12, False),
    "incline": ("press inclinado con mancuernas", "incline dumbbell press", 38, 3, 10, False),
    "pulldown": ("jalón al pecho", "lat pulldown", 90, 3, 10, False),
    "deadlift": ("peso muerto", "deadlift", 190, 3, 4, True),
    "hipthrust": ("hip thrust", "hip thrust", 170, 3, 8, False),
    "lunge": ("zancadas", "lunges", 60, 3, 10, False),
    "pushdown": ("extensión de tríceps en polea", "tricep pushdown", 45, 3, 12, False),
}
ROUTINES = [
    ("Torso A", "Upper A", ["bench", "row", "ohp", "pullup", "curl", "lateral"]),
    ("Pierna A", "Lower A", ["squat", "rdl", "legpress", "legcurl"]),
    ("Torso B", "Upper B", ["incline", "pulldown", "ohp", "row", "pushdown", "lateral"]),
    ("Pierna B", "Lower B", ["deadlift", "hipthrust", "lunge", "legcurl"]),
]
TRAINING_DAYS = (0, 1, 3, 4)          # lunes, martes, jueves, viernes
COMMENTS_ES = ["Buena sesión, todo fluyó", "Me costó el último set", "Dormí poco, pero cumplí",
               "Récord en el básico 💪", "Técnica muy sólida hoy", "Descarga: ligero y limpio"]
COMMENTS_EN = ["Great session, everything flowed", "Last set was tough", "Slept little, but got it done",
               "New PR on the main lift 💪", "Technique felt solid today", "Deload: light and clean"]


def _round(kg, step=2.5):
    return max(0.0, round(kg / step) * step)


def _weight_for(e1rm, reps, rir):
    """Peso que da ese 1RM estimado con reps + RIR (Epley, como la app)."""
    return e1rm / (1 + (reps + rir) / 30)


def seed_demo(username, weeks=52, strength=1.0, lang="es", friend=None, seed=7):
    rnd = random.Random(seed)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()
    start_day = today - timedelta(weeks=weeks)
    start_day -= timedelta(days=start_day.weekday())  # lunes
    name = (lambda k: EXERCISES[k][0]) if lang == "es" else (lambda k: EXERCISES[k][1])

    password = secrets.token_urlsafe(9)
    user = User(username=username, email=f"{username.lower()}@demo.gyre.invalid", sex="hombre", height_cm=178,
                training_goal="hipertrofia", training_days="".join(map(str, TRAINING_DAYS)), body_phase="volumen",
                effort_scale="rir", signup_method="demo", signup_source="demo",
                created_at=datetime.combine(start_day, time(9, 0)))
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    db.session.add(WeeklyGoalHistory(user_id=user.id, goal=3, effective_from=datetime.combine(start_day, time(0, 0))))

    routines = []
    for i, (name_es, name_en, keys) in enumerate(ROUTINES):
        r = Routine(name=name_es if lang == "es" else name_en, order_index=i, user_id=user.id)
        db.session.add(r)
        db.session.flush()
        for j, k in enumerate(keys):
            _, _, _, sets, reps, compound = EXERCISES[k]
            db.session.add(RoutineExercise(routine_id=r.id, exercise=name(k), target_sets=sets,
                                           target_reps=f"{reps}-{reps + 2}" if not compound else str(reps),
                                           rir="1-2" if compound else "1", order_index=j))
        routines.append((r, keys))

    # Peso corporal: de ~76 a ~80 kg en el año, con ruido diario.
    total_days = (today - start_day).days
    for d in range(0, total_days, 3):
        day = start_day + timedelta(days=d)
        kg = 76 + 4 * d / max(total_days, 1) + rnd.uniform(-0.6, 0.6)
        db.session.add(BodyWeightEntry(user_id=user.id, weight=round(kg, 1),
                                       timestamp=datetime.combine(day, time(7, 30))))

    comments = COMMENTS_ES if lang == "es" else COMMENTS_EN
    session_no = 0
    week = 0
    day = start_day
    while day < today:
        week_index = (day - start_day).days // 7
        deload = week_index % 6 == 5
        if day.weekday() in TRAINING_DAYS and rnd.random() > 0.06:   # alguna semana se falla un día
            routine, keys = routines[session_no % len(routines)]
            session_no += 1
            progress = 0.72 + 0.28 * min(1.0, week_index / max(weeks - 1, 1))   # del 72 % al 100 % del 1RM final
            start = datetime.combine(day, time(17, rnd.choice((0, 10, 20, 30, 40))))
            w = Workout(user_id=user.id, timestamp=start, note=routine.name, routine_id=routine.id,
                        performance_rating=rnd.choice((6, 7, 7, 8, 8, 9, 10)) if not deload else 6,
                        performance_comment=rnd.choice(comments) if rnd.random() < 0.25 else None,
                        ended_at=start + timedelta(minutes=rnd.randint(58, 82)))
            db.session.add(w)
            db.session.flush()
            minute = 0
            for k in keys:
                _, _, final, sets, reps, compound = EXERCISES[k]
                e1rm = final * strength * progress * rnd.uniform(0.97, 1.02) * (0.85 if deload else 1)
                rir = 4 if deload else rnd.choice((1, 2, 2, 3))
                step = 1.0 if final < 40 else 2.5
                if k == "pullup":
                    # Dominadas: lastre sobre el peso corporal (~78 kg).
                    work = _round(_weight_for(e1rm + 78, reps, rir) - 78, 1.25)
                else:
                    work = _round(_weight_for(e1rm, reps, rir), step)
                if compound and k != "pullup":
                    minute += 3
                    db.session.add(SetEntry(workout_id=w.id, exercise=name(k), weight=_round(work * 0.55, step),
                                            reps=reps + 3, rir=5, completed=True, set_type="calentamiento",
                                            completed_at=start + timedelta(minutes=minute)))
                for s in range(sets):
                    minute += 3
                    set_type, s_rir, s_reps, s_weight = "normal", rir, reps, work
                    if s == sets - 1 and not compound and not deload and rnd.random() < 0.3:
                        set_type, s_rir = "fallo", 0
                    elif s == sets - 1 and not compound and not deload and rnd.random() < 0.15:
                        set_type, s_weight, s_reps = "dropset", _round(work * 0.75, step), reps + 4
                    db.session.add(SetEntry(workout_id=w.id, exercise=name(k), weight=max(s_weight, 0.0), reps=s_reps,
                                            rir=s_rir, completed=True, set_type=set_type,
                                            completed_at=start + timedelta(minutes=minute)))
        elif rnd.random() < 0.6:
            db.session.add(DailyCheckin(user_id=user.id, day=day, sleep=rnd.randint(3, 5),
                                        energy=rnd.randint(2, 5), soreness=rnd.randint(0, 2)))
        day += timedelta(days=1)
    week += 1

    db.session.add(ExerciseNote(user_id=user.id, exercise=name("bench"), default_rest_seconds=180,
                                notes="Escápulas atrás y abajo\nPies firmes\nPausa breve en el pecho" if lang == "es"
                                else "Shoulder blades back and down\nFeet planted\nBrief pause on the chest"))
    db.session.add(ExerciseNote(user_id=user.id, exercise=name("squat"), default_rest_seconds=180,
                                notes="Bracing antes de bajar\nRodillas hacia fuera" if lang == "es"
                                else "Brace before descending\nKnees out"))
    for i, k in enumerate(("hipthrust", "legpress", "incline")):
        db.session.add(PersonalBasic(user_id=user.id, exercise=name(k), position=i))
    db.session.commit()

    # Medallas de récord (mismo código que al completar una serie en la app).
    from app.routes import apply_pr_flags_for_session, get_exercise_sessions
    for k in EXERCISES:
        for session in get_exercise_sessions(name(k), user_id=user.id)[0]:
            apply_pr_flags_for_session(session)
    db.session.commit()

    from app import achievements, progression
    achievements.evaluate(user)
    for ua in db.session.scalars(sa.select(UserAchievement).where(UserAchievement.user_id == user.id)):
        ua.seen = True  # que no salgan 100 avisos de golpe al entrar
    progression.refresh_xp(user.id)
    unlocked = list(db.session.scalars(
        sa.select(UserAchievement.code).where(UserAchievement.user_id == user.id).order_by(UserAchievement.unlocked_at.desc())))
    showcase = [c for c in ("std_big3_avanzado", "std_big3_intermedio", "workouts_100", "prs_50", "volume_150", "streak_30")
                if c in unlocked][:4]
    import json
    db.session.add(AthleteCard(user_id=user.id, in_rankings=True, show_rank=True, show_level=True, show_streak=True,
                               show_consistency=True, show_kg=True, show_bodyweight=False,
                               featured_lifts=json.dumps([name("bench"), name("squat"), name("deadlift")], ensure_ascii=False),
                               featured_achievements=json.dumps(showcase)))
    if friend:
        other = db.session.scalar(sa.select(User).where(User.username == friend))
        if other is None:
            raise click.ClickException(f"No existe el usuario {friend!r} para hacerlo amigo.")
        db.session.add(Friendship(requester_id=other.id, addressee_id=user.id, status="accepted", accepted_at=now))
    db.session.commit()
    return user, password


@app.cli.command("seed-demo")
@click.argument("username")
@click.option("--weeks", default=52, show_default=True, help="Semanas de historial.")
@click.option("--strength", default=1.0, show_default=True, help="Multiplicador de fuerza (1.0 ≈ Avanzado con 80 kg).")
@click.option("--lang", type=click.Choice(["es", "en"]), default="es", show_default=True, help="Idioma de ejercicios y rutinas.")
@click.option("--friend", default=None, help="Usuario existente con el que queda como amigo (para los rankings).")
def seed_demo_command(username, weeks, strength, lang, friend):
    """Crea una cuenta de demostración con un historial realista."""
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # consola de Windows
    if db.session.scalar(sa.select(User).where(User.username == username)) is not None:
        raise click.ClickException(f"Ya existe el usuario {username!r}: elige otro nombre.")
    user, password = seed_demo(username, weeks=weeks, strength=strength, lang=lang, friend=friend)
    from app import progression, strength_standards
    level = progression.level_for(progression.current_xp(user.id))["level"]
    rank = strength_standards.strength_profile(user)["global_rank"]
    sets = db.session.scalar(sa.select(sa.func.count()).select_from(SetEntry).join(Workout).where(Workout.user_id == user.id))
    click.echo(f"Creado {username!r}: nivel {level}, rango {rank['label'] if rank else 'sin rango'}, {sets} series.")
    click.echo(f"Contraseña (solo se muestra ahora): {password}")
