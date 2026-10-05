"""Contador de uso respetuoso con la privacidad (DailyActivity).

Sirve para medir si la app da motivos para abrirla en días sin entreno
(criterio de éxito del check-in, fijado antes de lanzarlo):

  A  = % de días sin entreno con la app abierta
  A' = % de días sin entreno con la app abierta y SIN check-in
  B  = % de días sin entreno con check-in

Solo cuentan los usuarios activos de cada semana (al menos un día entrenado
en esa semana). "Entrenado" = algún entreno con series reales ese día (hora
de Madrid), terminado o no: un entreno en curso ya es un día de entreno.
Con pocos usuarios, los porcentajes son orientativos: el informe da también
los recuentos y el desglose por usuario (anónimo).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import DailyActivity, DailyCheckin, SetEntry, Workout

RETENTION_DAYS = 120


def local_today():
    from app.routes import to_local

    return to_local(datetime.now(timezone.utc)).date()


def _insert_stmt():
    """INSERT con ON CONFLICT del motor en uso (Postgres en producción,
    SQLite en local y en los tests)."""
    name = db.session.get_bind().dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover - no usamos otros motores
        raise RuntimeError(f"Motor no soportado para DailyActivity: {name}")
    return insert(DailyActivity)


def record_open(user):
    """Marca que `user` abrió la app hoy. Idempotente (una fila por día);
    aprovecha para purgar lo que tenga más de RETENTION_DAYS días."""
    from app.routes import planned_weekdays

    today = local_today()
    plan = planned_weekdays(user)
    planned_rest = bool(plan) and today.weekday() not in plan
    stmt = _insert_stmt().values(user_id=user.id, day=today, opened=True, planned_rest=planned_rest)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "day"],
        set_={"opened": True, "planned_rest": planned_rest},
    )
    db.session.execute(stmt)
    db.session.execute(
        sa.delete(DailyActivity).where(DailyActivity.day < today - timedelta(days=RETENTION_DAYS))
    )
    db.session.commit()


def record_css_retry(user):
    """Suma un reintento de carga del CSS al día de hoy de `user`."""
    stmt = _insert_stmt().values(user_id=user.id, day=local_today(), css_retries=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "day"],
        set_={"css_retries": DailyActivity.__table__.c.css_retries + 1},
    )
    db.session.execute(stmt)
    db.session.commit()


def _checkin_days(start):
    """{(user_id, día)} con check-in desde `start`."""
    return set(db.session.execute(
        sa.select(DailyCheckin.user_id, DailyCheckin.day).where(DailyCheckin.day >= start)
    ).tuples())


def _pct(part, whole):
    return round(100 * part / whole) if whole else None


def rest_day_report(weeks=6, today=None):
    """Semanas (lunes a domingo, de la más reciente a la más antigua) con
    A, A' y B, sus recuentos y el desglose por usuario. Solo desde el primer
    día con datos de DailyActivity: antes no se medía."""
    from app.routes import to_local

    today = today or local_today()
    first = db.session.scalar(sa.select(sa.func.min(DailyActivity.day)))
    if first is None:
        return {"since": None, "weeks": [], "has_checkin": False}
    monday = today - timedelta(days=today.weekday())
    start = max(first, monday - timedelta(weeks=weeks - 1))

    # Días entrenados por usuario (hora local). Margen de un día en UTC.
    start_utc = datetime.combine(start - timedelta(days=1), datetime.min.time())
    real_set = (
        sa.select(SetEntry.id)
        .where(
            SetEntry.workout_id == Workout.id,
            SetEntry.completed.is_(True),
            SetEntry.weight > 0,
            SetEntry.reps > 0,
        )
        .exists()
    )
    trained = defaultdict(set)
    for user_id, ts in db.session.execute(
        sa.select(Workout.user_id, Workout.timestamp).where(Workout.timestamp >= start_utc, real_set)
    ):
        trained[user_id].add(to_local(ts).date())

    activity = {
        (a.user_id, a.day): a
        for a in db.session.scalars(sa.select(DailyActivity).where(DailyActivity.day >= start))
    }
    checkins = _checkin_days(start)
    has_checkin = checkins is not None
    checkins = checkins or set()

    labels = {}  # usuario -> "Usuario A", estable dentro del informe

    def label(user_id):
        if user_id not in labels:
            n = len(labels)
            labels[user_id] = "Usuario " + (chr(ord("A") + n) if n < 26 else str(n + 1))
        return labels[user_id]

    result = []
    week_start = monday
    while week_start + timedelta(days=6) >= start:
        days = [
            week_start + timedelta(days=i)
            for i in range(7)
            if start <= week_start + timedelta(days=i) <= today
        ]
        active = sorted(u for u, ds in trained.items() if any(d in ds for d in days))
        totals = {"rest": 0, "opened": 0, "opened_no_checkin": 0, "checkin": 0}
        per_user = []
        for user_id in active:
            rest = [d for d in days if d not in trained[user_id]]
            opened = [d for d in rest if getattr(activity.get((user_id, d)), "opened", False)]
            with_checkin = [d for d in rest if (user_id, d) in checkins]
            opened_no_checkin = [d for d in opened if (user_id, d) not in checkins]
            row = {
                "label": label(user_id),
                "rest": len(rest),
                "opened": len(opened),
                "opened_no_checkin": len(opened_no_checkin),
                "checkin": len(with_checkin),
            }
            per_user.append(row)
            for key in totals:
                totals[key] += row[key]
        css_retries = sum(
            a.css_retries for (u, d), a in activity.items() if days and days[0] <= d <= days[-1]
        )
        result.append({
            "start": week_start,
            "end": week_start + timedelta(days=6),
            "current": week_start == monday,
            "active_users": len(active),
            **totals,
            "a": _pct(totals["opened"], totals["rest"]),
            "a2": _pct(totals["opened_no_checkin"], totals["rest"]),
            "b": _pct(totals["checkin"], totals["rest"]) if has_checkin else None,
            "css_retries": css_retries,
            "per_user": per_user,
        })
        week_start -= timedelta(weeks=1)
    return {"since": first, "weeks": result, "has_checkin": has_checkin}


ACTIVITY_BUCKETS = [(0, 0, "Hoy"), (1, 1, "Ayer"), (2, 7, "Hace 2-7 días"), (8, 30, "Hace 8-30 días"),
                    (31, RETENTION_DAYS, f"Hace 31-{RETENTION_DAYS} días")]


def activity_summary(today=None):
    """Usuarios activos (abrieron la app) hoy / 7 / 30 días y cuántos hay en
    cada tramo de "última vez que la abrieron". Solo recuentos, sin nombres:
    es lo que promete la política de privacidad. No hay hora ni "conectados
    ahora": DailyActivity guarda días, no momentos."""
    from app.models import User

    today = today or local_today()
    last = dict(db.session.execute(
        sa.select(DailyActivity.user_id, sa.func.max(DailyActivity.day))
        .where(DailyActivity.opened.is_(True)).group_by(DailyActivity.user_id)
    ).all())
    ages = [(today - day).days for day in last.values()]
    total = db.session.scalar(sa.select(sa.func.count()).select_from(User))
    buckets = [{"label": label, "users": sum(lo <= a <= hi for a in ages)} for lo, hi, label in ACTIVITY_BUCKETS]
    buckets.append({"label": "Sin registro de uso", "users": total - len(ages)})
    since = db.session.scalar(sa.select(sa.func.min(DailyActivity.day)))
    return {
        "total": total,
        "today": sum(a == 0 for a in ages),
        "week": sum(a <= 6 for a in ages),
        "month": sum(a <= 29 for a in ages),
        "buckets": buckets,
        "since": since,
    }
