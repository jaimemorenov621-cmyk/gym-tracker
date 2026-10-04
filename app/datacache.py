"""Caché en memoria de cálculos derivados por usuario (pestañas más rápidas).

Lo caro de Inicio, Progreso y Rango es recorrer TODO el historial: perfil de
fuerza y rangos, índice de fuerza, resumen de ejercicios y volumen. Esos
resultados solo cambian cuando cambian los datos, así que se guardan en el
proceso junto con una "versión" del usuario:
  - xp_seq: sube en la misma transacción que cualquier cambio en entrenos,
    series, check-ins o mínimo semanal, también en escrituras masivas
    (app/progression.py);
  - nombre de usuario (por si se reutiliza un id), sexo y umbral de
    estancamiento;
  - peso corporal y alias de ejercicios (nº de filas y último id): no suben
    xp_seq pero cambian el perfil y el volumen;
  - el día local (ventanas de 7 y 90 días, semana actual).
Lo que cambie por una vía que no deja rastro (SQL a mano en la consola) lo
corrige el TTL. Los valores se devuelven tal cual: quien los use NO debe
modificarlos.
"""
import threading
import time
from collections import OrderedDict

import sqlalchemy as sa
from flask import g, has_request_context

from app import db

MAX_ENTRIES = 512
TTL_SECONDS = 600

_lock = threading.Lock()
_cache = OrderedDict()


def clear():
    with _lock:
        _cache.clear()


def data_version(user_id):
    """Versión de los datos de `user_id` (una vez por petición)."""
    from app.models import BodyWeightEntry, ExerciseAlias, User
    from app.usage import local_today

    memo = g.setdefault("_data_versions", {}) if has_request_context() else {}
    if user_id not in memo:
        user = db.session.execute(
            sa.select(User.xp_seq, User.username, User.sex, User.stagnation_threshold).where(User.id == user_id)
        ).one()
        bw = db.session.execute(
            sa.select(sa.func.count(BodyWeightEntry.id), sa.func.max(BodyWeightEntry.id))
            .where(BodyWeightEntry.user_id == user_id)
        ).one()
        alias = db.session.execute(
            sa.select(sa.func.count(ExerciseAlias.id), sa.func.max(ExerciseAlias.id))
            .where(ExerciseAlias.user_id == user_id)
        ).one()
        memo[user_id] = (tuple(user), tuple(bw), tuple(alias), local_today())
    return memo[user_id]


def invalidate(user_id):
    """Olvida la versión memorizada en esta petición (tras escribir datos)."""
    if has_request_context():
        g.setdefault("_data_versions", {}).pop(user_id, None)


def cached(name, user_id, compute, *extra):
    """compute() memorizado por (name, user_id, *extra) mientras la versión
    de los datos del usuario no cambie."""
    key = (name, user_id, extra)
    version = data_version(user_id)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == version and now - hit[1] < TTL_SECONDS:
            _cache.move_to_end(key)
            return hit[2]
    value = compute()
    with _lock:
        _cache[key] = (version, now, value)
        _cache.move_to_end(key)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)
    return value
