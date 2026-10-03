"""XP y nivel: calculados SIEMPRE desde los datos reales.

compute_xp() es una función pura sobre los datos ya cargados
(load_xp_inputs: 3 consultas). User.xp_total es solo una caché de su
resultado, válida mientras:
  - xp_cached_seq == xp_seq (no ha cambiado nada desde que se calculó),
  - xp_rules == XP_RULES_VERSION (las reglas no han cambiado),
  - xp_cached_at tiene menos de 24 h (red de seguridad para cualquier vía
    de escritura que no se haya detectado, p. ej. SQL a mano en Neon).

Invalidación (xp_seq sube con un UPDATE atómico en la misma transacción que
el cambio; nunca leer-modificar-escribir):
  1. Operaciones normales del ORM: before_flush recoge los usuarios
     afectados y after_flush sube SU xp_seq.
  2. Cualquier otra escritura (session.execute(update/delete/insert),
     bulk_*_mappings, connection/engine directos, SQL en texto, DELETE de
     un entreno con CASCADE de la base de datos): un listener a nivel de
     cursor la ve y, como no sabe de qué usuario es, sube el xp_seq de
     TODOS. Para una sentencia que no afecta al XP se marca con
     .execution_options(xp_irrelevant=True). En tests
     (XP_STRICT_BULK_DML) una sentencia sin marcar lanza un error, para que
     ninguna escritura masiva nueva pase sin revisar.
  3. Durante las migraciones el listener está apagado (migrations/env.py):
     una migración que toque estas tablas debe llevar el comentario
     "# xp: requiere flask recompute-xp" (lo comprueba un test).

refresh_xp() guarda el total solo si xp_seq no cambió mientras se calculaba
(UPDATE ... WHERE xp_seq = :leido): una escritura concurrente nunca deja un
total viejo marcado como vigente.
"""
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import click
import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import Pool

from app import app, db
from app.models import (
    AiAnalysis,
    BodyWeightEntry,
    DailyActivity,
    DailyCheckin,
    ExerciseFavorite,
    ExerciseNote,
    Routine,
    RoutineBlock,
    RoutineExercise,
    SetEntry,
    User,
    UserAchievement,
    WeeklyGoalHistory,
    Workout,
)

# ------------------------------------------------------------------ reglas
# Cambiar cualquier regla = subir XP_RULES_VERSION (todas las cachés se
# recalculan solas) y actualizar la página /nivel.
XP_RULES_VERSION = 1
XP_WORKOUT = 100            # entreno válido
XP_SET = 5                  # serie de XP
XP_PR = 25                  # récord real
XP_WEEK_PER_MINIMUM = 40    # semana con el mínimo cumplido: 40 × mínimo
XP_CHECKIN = 10             # check-in de recuperación
MAX_SETS_PER_DAY = 25
MAX_PRS_PER_DAY = 3
MAX_WORKOUT_DAYS_PER_WEEK = 6
MIN_SETS_FOR_WORKOUT = 3
MIN_REPS_FOR_WORKOUT = 10
MIN_LOAD_FRACTION = 0.4     # carga mínima frente al mejor 1RM estimado anterior
CACHE_TTL = timedelta(hours=24)
DEFAULT_WEEKLY_MINIMUM = 1  # mismo valor que la racha (app/routes.py)

WATCHED_TABLES = {"workout", "set_entry", "daily_checkin", "weekly_goal_history"}


# ------------------------------------------------------------------ niveles
def xp_to_reach(level):
    """XP acumulado para llegar a `level`. Pasar de L a L+1 cuesta
    500 + 100·(L−1)."""
    n = level - 1
    return 500 * n + 100 * n * (n - 1) // 2


def level_for(total):
    level = 1
    while xp_to_reach(level + 1) <= total:
        level += 1
    start, nxt = xp_to_reach(level), xp_to_reach(level + 1)
    return {
        "level": level,
        "total": total,
        "into": total - start,
        "span": nxt - start,
        "to_next": nxt - total,
        "pct": round(100 * (total - start) / (nxt - start)),
    }


# ------------------------------------------------------------------ datos
@dataclass
class _Workout:
    id: int
    ts: datetime
    finished: bool
    sets: list = field(default_factory=list)


@dataclass
class XpInputs:
    workouts: list
    checkin_days: set
    goals: list  # [(fecha desde la que vale, mínimo | None)], más reciente primero
    bodyweight: float = 0.0  # último peso: en dominadas, carga = peso + lastre


def load_xp_inputs(user_id):
    """Todo lo que necesita compute_xp, en 3 consultas y solo con columnas
    (sin crear objetos del ORM: con 3 años de historial es 3-5 veces más
    rápido)."""
    rows = db.session.execute(
        sa.select(
            Workout.id, Workout.timestamp, Workout.ended_at, Workout.performance_rating,
            SetEntry.exercise, SetEntry.weight, SetEntry.reps, SetEntry.rir, SetEntry.rpe,
            SetEntry.set_type, SetEntry.completed,
        )
        .outerjoin(SetEntry, SetEntry.workout_id == Workout.id)
        .where(Workout.user_id == user_id)
        .order_by(Workout.timestamp, Workout.id, SetEntry.id)
    ).all()
    workouts = {}
    for r in rows:
        w = workouts.get(r.id)
        if w is None:
            w = workouts[r.id] = _Workout(
                r.id, r.timestamp, r.ended_at is not None or r.performance_rating is not None
            )
        if r.exercise is not None:
            w.sets.append(r)
    checkin_days = set(db.session.scalars(sa.select(DailyCheckin.day).where(DailyCheckin.user_id == user_id)))
    goals = [
        (g.effective_from.date(), g.goal)
        for g in db.session.execute(
            sa.select(WeeklyGoalHistory.effective_from, WeeklyGoalHistory.goal)
            .where(WeeklyGoalHistory.user_id == user_id)
            .order_by(WeeklyGoalHistory.effective_from.desc(), WeeklyGoalHistory.id.desc())
        )
    ]
    from app.routes import latest_bodyweight

    return XpInputs(list(workouts.values()), checkin_days, goals, latest_bodyweight(user_id))


# ------------------------------------------------------------------ cálculo
@dataclass
class XpReport:
    total: int
    weeks: dict        # lunes -> desglose de la semana
    by_workout: dict   # id -> desglose del entreno


def _minimum_for(goals, week_start):
    for since, goal in goals:
        if since <= week_start:
            return goal or DEFAULT_WEEKLY_MINIMUM
    return DEFAULT_WEEKLY_MINIMUM


def _new_week():
    return {"workout": 0, "sets": 0, "prs": 0, "bonus": 0, "checkins": 0, "total": 0,
            "days": set(), "workout_days": 0, "minimum": None, "capped": []}


def compute_xp(inputs, include_workout=None, exclude_workout=None):
    """XP total y desglose. Solo cuentan los entrenos terminados (o el
    `include_workout`, para enseñar lo que dará al terminarlo);
    `exclude_workout` sirve para calcular el "antes"."""
    from app.routes import estimated_1rm, is_real_set, to_local

    best = {}  # ejercicio -> mejor 1RM estimado de sesiones ANTERIORES
    days = defaultdict(lambda: {"workout": False, "sets": 0, "prs": 0})
    weeks = defaultdict(_new_week)
    by_workout = {}

    for w in inputs.workouts:
        if w.id == exclude_workout or not (w.finished or w.id == include_workout):
            continue
        d = to_local(w.ts).date()
        week = weeks[d - timedelta(days=d.weekday())]
        day = days[d]
        info = {"workout": 0, "sets_n": 0, "sets": 0, "prs_n": 0, "prs": 0, "total": 0, "notes": []}

        work, session_best = [], {}
        for s in w.sets:
            if not is_real_set(s) or (s.set_type or "normal") == "calentamiento":
                continue
            e1rm = estimated_1rm(s, inputs.bodyweight)
            session_best[s.exercise] = max(session_best.get(s.exercise, 0.0), e1rm)
            prev = best.get(s.exercise)
            if prev is not None and e1rm < MIN_LOAD_FRACTION * prev:
                continue  # serie casi sin carga para ti en ese ejercicio
            work.append(s)
        if session_best:
            week["days"].add(d)

        # Entreno válido: 1 al día y 6 días por semana como mucho.
        if len(work) >= MIN_SETS_FOR_WORKOUT and sum(s.reps for s in work) >= MIN_REPS_FOR_WORKOUT:
            if day["workout"]:
                info["notes"].append("ya contó un entreno ese día")
            elif week["workout_days"] >= MAX_WORKOUT_DAYS_PER_WEEK:
                info["notes"].append("tope de 6 días con entreno por semana")
                week["capped"].append("días")
            else:
                day["workout"] = True
                week["workout_days"] += 1
                info["workout"] = XP_WORKOUT
        else:
            info["notes"].append("menos de 3 series de XP o de 10 repeticiones")

        n = min(len(work), max(0, MAX_SETS_PER_DAY - day["sets"]))
        if n < len(work):
            info["notes"].append("tope de 25 series al día")
            week["capped"].append("series")
        day["sets"] += n
        info["sets_n"], info["sets"] = n, n * XP_SET

        prs = [ex for ex, e in session_best.items() if ex in best and e > best[ex]]
        n = min(len(prs), max(0, MAX_PRS_PER_DAY - day["prs"]))
        if n < len(prs):
            info["notes"].append("tope de 3 récords al día")
            week["capped"].append("récords")
        day["prs"] += n
        info["prs_n"], info["prs"] = n, n * XP_PR
        for ex, e in session_best.items():
            best[ex] = max(best.get(ex, 0.0), e)

        info["total"] = info["workout"] + info["sets"] + info["prs"]
        for key in ("workout", "sets", "prs"):
            week[key] += info[key]
        by_workout[w.id] = info

    for d in inputs.checkin_days:
        weeks[d - timedelta(days=d.weekday())]["checkins"] += XP_CHECKIN

    total = 0
    for week_start, week in weeks.items():
        week["minimum"] = _minimum_for(inputs.goals, week_start)
        if len(week["days"]) >= week["minimum"]:
            week["bonus"] = XP_WEEK_PER_MINIMUM * week["minimum"]
        week["total"] = week["workout"] + week["sets"] + week["prs"] + week["bonus"] + week["checkins"]
        week["capped"] = sorted(set(week["capped"]))
        total += week["total"]
    return XpReport(total, dict(sorted(weeks.items(), reverse=True)), by_workout)


# ------------------------------------------------------------------ caché
def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def refresh_xp(user_id, _after_load=None):
    """Recalcula y guarda la caché SOLO si nada cambió mientras tanto.
    Devuelve (informe, guardado). `_after_load` es un gancho para tests."""
    seq0 = db.session.scalar(sa.select(User.xp_seq).where(User.id == user_id))
    report = compute_xp(load_xp_inputs(user_id))
    if _after_load is not None:
        _after_load()
    result = db.session.execute(
        sa.update(User)
        .where(User.id == user_id, User.xp_seq == seq0)
        .values(xp_total=report.total, xp_cached_seq=seq0, xp_rules=XP_RULES_VERSION, xp_cached_at=_now())
        .execution_options(synchronize_session=False)
    )
    stored = result.rowcount == 1
    db.session.commit()
    return report, stored


def is_cache_fresh(row):
    return (
        row.xp_cached_seq is not None
        and row.xp_cached_seq == row.xp_seq
        and row.xp_rules == XP_RULES_VERSION
        and row.xp_cached_at is not None
        and _now() - row.xp_cached_at < CACHE_TTL
    )


def current_xp(user_id):
    """XP total: de la caché si está al día; si no, recalculado."""
    row = db.session.execute(
        sa.select(User.xp_seq, User.xp_total, User.xp_cached_seq, User.xp_rules, User.xp_cached_at)
        .where(User.id == user_id)
    ).one()
    if is_cache_fresh(row):
        return row.xp_total
    report, _ = refresh_xp(user_id)
    return report.total


def level_up_notice(user_id, total):
    """Nivel nuevo que anunciar, o None. El primer cálculo (todo el
    historial) no avisa; xp_level_seen nunca baja, así que volver a subir a
    un nivel ya anunciado (tras borrar un entreno) no repite el aviso."""
    level = level_for(total)["level"]
    seen = db.session.scalar(sa.select(User.xp_level_seen).where(User.id == user_id))
    notice = None
    if seen is None:
        new_seen = level
    elif level > seen:
        notice, new_seen = level, level
    else:
        return None
    db.session.execute(
        sa.update(User).where(User.id == user_id).values(xp_level_seen=new_seen)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return notice


def workout_xp_preview(user_id, workout_id):
    """Lo que da (o dio) un entreno: "después" con el entreno contado menos
    "antes" sin él. Una sola carga de datos y dos pasadas en memoria; no
    usa la caché (las series guardadas por AJAX la acaban de invalidar)."""
    from app.routes import to_local

    inputs = load_xp_inputs(user_id)
    before = compute_xp(inputs, exclude_workout=workout_id)
    after = compute_xp(inputs, include_workout=workout_id)
    w = next((w for w in inputs.workouts if w.id == workout_id), None)
    info = after.by_workout.get(workout_id)
    if w is None or info is None:
        return None
    d = to_local(w.ts).date()
    week_start = d - timedelta(days=d.weekday())
    week_after = after.weeks[week_start]
    week_before = before.weeks.get(week_start)
    return {
        "gain": after.total - before.total,
        "workout": info,
        "bonus": week_after["bonus"] - (week_before["bonus"] if week_before else 0),
        "week_days": len(week_after["days"]),
        "minimum": week_after["minimum"],
    }


def today_checkin(user_id):
    from app.usage import local_today

    return db.session.scalar(
        sa.select(DailyCheckin).where(DailyCheckin.user_id == user_id, DailyCheckin.day == local_today())
    )


def recent_checkins(user_id, days=14):
    from app.usage import local_today

    return db.session.scalars(
        sa.select(DailyCheckin)
        .where(DailyCheckin.user_id == user_id, DailyCheckin.day > local_today() - timedelta(days=days))
        .order_by(DailyCheckin.day)
    ).all()


MUSCLE_GROUP_LABELS = {
    "trapecios": "Trapecios", "hombros": "Hombros", "pecho": "Pecho", "biceps": "Bíceps",
    "triceps": "Tríceps", "antebrazos": "Antebrazos", "cuello": "Cuello", "abdomen": "Abdomen",
    "dorsales": "Dorsales", "espalda_baja": "Lumbares", "cuadriceps": "Cuádriceps",
    "aductores": "Aductores", "isquiotibiales": "Isquiotibiales", "gluteos": "Glúteos",
    "pantorrillas": "Gemelos",
}
DAYS_SINCE_WINDOW = 60


def _primary_groups(exercise_name):
    """Grupos (solo músculos PRIMARIOS) de un ejercicio según el catálogo;
    lista vacía si el nombre no está en el catálogo (no se adivina)."""
    from app.routes import MUSCLE_GROUP_MAP, find_catalog_exercise

    catalog = find_catalog_exercise(exercise_name)
    if not catalog or not catalog.primary_muscles:
        return []
    groups = []
    for muscle in catalog.primary_muscles.split(", "):
        group = MUSCLE_GROUP_MAP.get(muscle)
        if group and group not in groups:
            groups.append(group)
    return groups


def days_since_by_group(user_id, today=None):
    """{grupo: días desde la última serie real} en los últimos 60 días (fecha
    local) y cuántos ejercicios entrenados no tienen músculo en el catálogo."""
    from app.routes import prefetch_catalog_exercises, to_local
    from app.usage import local_today

    today = today or local_today()
    since = datetime.combine(today - timedelta(days=DAYS_SINCE_WINDOW + 1), datetime.min.time())
    rows = db.session.execute(
        sa.select(SetEntry.exercise, sa.func.max(Workout.timestamp))
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(
            Workout.user_id == user_id, Workout.timestamp >= since,
            SetEntry.completed.is_(True), SetEntry.weight >= 0, SetEntry.reps > 0,
        )
        .group_by(SetEntry.exercise)
    ).all()
    prefetch_catalog_exercises(name for name, _ in rows)
    result, unmapped = {}, 0
    for name, last in rows:
        days = (today - to_local(last).date()).days
        if days > DAYS_SINCE_WINDOW:
            continue
        groups = _primary_groups(name)
        if not groups:
            unmapped += 1
        for g in groups:
            result[g] = min(result.get(g, days), days)
    return result, unmapped


def rest_day_facts(user_id, routine=None):
    """Datos factuales para un día sin entreno: cuántos días hace que
    entrenaste cada grupo (los de la siguiente rutina, si la hay). Nunca
    "recuperado" ni "listo": solo días."""
    from app.routes import prefetch_catalog_exercises

    by_group, unmapped = days_since_by_group(user_id)
    groups = []
    if routine is not None:
        names = list(db.session.scalars(
            sa.select(RoutineExercise.exercise)
            .where(RoutineExercise.routine_id == routine.id)
            .order_by(RoutineExercise.order_index)
        ))
        prefetch_catalog_exercises(names)
        for name in names:
            for g in _primary_groups(name):
                if g not in groups:
                    groups.append(g)
    if not groups:  # sin rutina (o sin músculos en el catálogo): lo entrenado
        groups = sorted(by_group, key=lambda g: by_group[g])[:6]
    return {
        "items": [{"group": g, "label": MUSCLE_GROUP_LABELS.get(g, g), "days": by_group.get(g)} for g in groups],
        "unmapped": unmapped,
        "for_routine": routine is not None and bool(groups),
    }


# ------------------------------------------------------------------ invalidación
def _bump_users(connection, user_ids):
    if user_ids:
        connection.execute(
            sa.update(User.__table__)
            .where(User.__table__.c.id.in_(sorted(user_ids)))
            .values(xp_seq=User.__table__.c.xp_seq + 1)
        )


def _owner_id(obj):
    """user_id de un objeto, aunque aún no esté puesto porque se asignó por
    la relación (Workout(author=current_user) lo rellena el propio flush)."""
    if obj is None:
        return None
    if obj.user_id is not None:
        return obj.user_id
    author = getattr(obj, "author", None)
    return author.id if author is not None else None


@event.listens_for(so.Session, "before_flush")
def _xp_before_flush(session, flush_context, instances):
    users = session.info.setdefault("xp_users", set())
    with session.no_autoflush:
        for obj in list(session.new) + list(session.dirty) + list(session.deleted):
            if obj in session.dirty and not session.is_modified(obj):
                continue
            if isinstance(obj, (Workout, DailyCheckin, WeeklyGoalHistory)):
                users.add(_owner_id(obj))
                users.update(so.attributes.get_history(obj, "user_id").deleted or ())
            elif isinstance(obj, SetEntry):
                workout = obj.workout if obj.workout is not None else (
                    session.get(Workout, obj.workout_id) if obj.workout_id else None
                )
                users.add(_owner_id(workout))
                for old_wid in so.attributes.get_history(obj, "workout_id").deleted or ():
                    users.add(_owner_id(session.get(Workout, old_wid)))
    users.discard(None)
    if users:
        # Las sentencias del propio flush no deben disparar el aumento global.
        session.connection().info["xp_in_flush"] = True


@event.listens_for(so.Session, "after_flush")
def _xp_after_flush(session, flush_context):
    users = session.info.pop("xp_users", set())
    connection = session.connection()
    try:
        _bump_users(connection, users)
    finally:
        connection.info.pop("xp_in_flush", None)


@event.listens_for(so.Session, "after_soft_rollback")
def _xp_after_rollback(session, previous_transaction):
    session.info.pop("xp_users", None)


@event.listens_for(Pool, "checkin")
def _xp_reset_connection(dbapi_connection, connection_record):
    connection_record.info.pop("xp_in_flush", None)


_DML_RE = re.compile(r"\s*(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+[\"`\[]?(\w+)", re.IGNORECASE)


@event.listens_for(Engine, "after_cursor_execute")
def _xp_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    if conn.info.get("xp_in_flush") or conn.info.get("xp_tracking_disabled"):
        return
    m = _DML_RE.match(statement)
    if not m or m.group(1).lower() not in WATCHED_TABLES:
        return
    if context is not None and context.execution_options.get("xp_irrelevant"):
        return
    # No sabemos de qué usuario es: invalida la caché de todos. Cursor
    # aparte para no pisar rowcount/lastrowid de la sentencia original.
    extra = conn.connection.cursor()
    try:
        extra.execute('UPDATE "user" SET xp_seq = xp_seq + 1')
    finally:
        extra.close()
    if app.config.get("XP_STRICT_BULK_DML"):
        raise RuntimeError(
            f"Escritura masiva en {m.group(1)} sin revisar su efecto en el XP: márcala con "
            ".execution_options(xp_irrelevant=True) si no afecta, o déjala invalidando a todos."
        )
    app.logger.warning("XP: escritura masiva en %s, cachés de XP invalidadas para todos", m.group(1))


# ------------------------------------------------------------------ comandos
@app.cli.command("recompute-xp")
@click.option("--user", "user_id", type=int, default=None, help="Solo este usuario (id).")
@click.option("--check", is_flag=True, help="Solo comprobar: no guarda nada.")
def recompute_xp_command(user_id, check):
    """Recalcula la caché de XP desde los datos reales."""
    query = sa.select(User.id, User.username, User.xp_total, User.xp_seq, User.xp_cached_seq,
                      User.xp_rules, User.xp_cached_at)
    if user_id is not None:
        query = query.where(User.id == user_id)
    diffs = 0
    for row in db.session.execute(query).all():
        real = compute_xp(load_xp_inputs(row.id)).total
        fresh = is_cache_fresh(row)
        if fresh and row.xp_total != real:
            diffs += 1
            click.echo(f"DIFERENCIA usuario {row.id}: caché {row.xp_total} != real {real}")
        if not check:
            refresh_xp(row.id)
    click.echo(f"Hecho. Cachés vigentes con diferencias: {diffs}.")


def _user_tables(user_id):
    """(modelo, condición) de todo lo que pertenece a un usuario, en orden
    seguro para borrar (hijos antes que padres)."""
    workout_ids = sa.select(Workout.id).where(Workout.user_id == user_id)
    routine_ids = sa.select(Routine.id).where(Routine.user_id == user_id)
    return [
        (SetEntry, SetEntry.workout_id.in_(workout_ids)),
        (Workout, Workout.user_id == user_id),
        (RoutineExercise, RoutineExercise.routine_id.in_(routine_ids)),
        (Routine, Routine.user_id == user_id),
        (RoutineBlock, RoutineBlock.user_id == user_id),
        (ExerciseNote, ExerciseNote.user_id == user_id),
        (ExerciseFavorite, ExerciseFavorite.user_id == user_id),
        (AiAnalysis, AiAnalysis.user_id == user_id),
        (BodyWeightEntry, BodyWeightEntry.user_id == user_id),
        (WeeklyGoalHistory, WeeklyGoalHistory.user_id == user_id),
        (UserAchievement, UserAchievement.user_id == user_id),
        (DailyActivity, DailyActivity.user_id == user_id),
        (DailyCheckin, DailyCheckin.user_id == user_id),
    ]


def delete_user_data(user_id):
    """Borra la cuenta y TODOS sus datos (petición de borrado por email,
    ver privacy.html). Con sentencias directas: el ORM no puede borrar un
    User (User.workouts es WriteOnly)."""
    for model, cond in _user_tables(user_id):
        db.session.execute(sa.delete(model).where(cond).execution_options(xp_irrelevant=True))
    db.session.execute(sa.delete(User).where(User.id == user_id))
    db.session.commit()


def export_user_data(user_id):
    """Todos los datos del usuario como dict serializable (portabilidad)."""
    def plain(obj):
        out = {}
        for col in obj.__table__.columns:
            value = getattr(obj, col.key)
            if col.key in ("password_hash", "google_sub"):
                continue
            out[col.key] = value.isoformat() if isinstance(value, (datetime, date)) else value
        return out

    user = db.session.get(User, user_id)
    data = {"user": plain(user)}
    for model, cond in reversed(_user_tables(user_id)):
        data[model.__tablename__] = [plain(o) for o in db.session.scalars(sa.select(model).where(cond))]
    return data


@app.cli.command("delete-user")
@click.argument("user_id", type=int)
@click.option("--yes", is_flag=True, help="Confirmar: el borrado no se puede deshacer.")
def delete_user_command(user_id, yes):
    """Borra un usuario y todos sus datos."""
    user = db.session.get(User, user_id)
    if user is None:
        raise click.ClickException(f"No existe el usuario {user_id}.")
    if not yes:
        raise click.ClickException(f"Esto borra para siempre a {user.username!r} y todos sus datos. Repite con --yes.")
    delete_user_data(user_id)
    click.echo(f"Usuario {user_id} borrado con todos sus datos.")


@app.cli.command("export-user")
@click.argument("user_id", type=int)
@click.option("--out", "out_path", type=click.Path(dir_okay=False), default=None, help="Fichero JSON de salida.")
def export_user_command(user_id, out_path):
    """Exporta en JSON todos los datos de un usuario."""
    if db.session.get(User, user_id) is None:
        raise click.ClickException(f"No existe el usuario {user_id}.")
    text = json.dumps(export_user_data(user_id), ensure_ascii=False, indent=2)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        click.echo(f"Exportado a {out_path}.")
    else:
        click.echo(text)
