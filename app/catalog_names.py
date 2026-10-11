"""Nombres del catálogo (español e inglés), revisados a mano.

Los de app/data/exercise_names_es.json sustituyen a los que puso Google
Translate al importar el catálogo (import_exercises.py), y los de
exercise_names_en.json a los originales del dataset, que también sonaban
raros. Se aplican desde /landing/catalog-names (solo admin), con vista previa.

Las series guardan el ejercicio por su NOMBRE, así que renombrar mueve el
historial de todos los usuarios (rename_exercise_everywhere). Se hace en dos
fases (nombre viejo -> temporal -> nuevo) para que, si el nombre nuevo de A
es el que hoy tiene B, las series de A y B no se mezclen. Solo se mueve
historial de los nombres que alguien usa; el resto solo cambia en el catálogo.

Los nombres nuevos se validaron para que la detección de levantamientos del
rango (strength_standards.lift_of) dé lo mismo que con el nombre inglés.
"""
import json
import os

import sqlalchemy as sa

from app import db
from app.models import Exercise, ExerciseNote, PersonalBasic, RoutineExercise, SetEntry

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "exercise_names_es.json")
DATA_FILE_EN = os.path.join(os.path.dirname(__file__), "data", "exercise_names_en.json")


def curated():
    """{id del catálogo: nombre en español}."""
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def curated_en():
    """{id del catálogo: nombre en inglés} revisado (el original del dataset
    tenía nombres raros: "Butt Lift (Bridge)", "Bicycling, Stationary"...)."""
    with open(DATA_FILE_EN, encoding="utf-8") as f:
        return json.load(f)


def _key(name):
    return (name or "").strip().lower()


def _used_names():
    """{nombre guardado: nº de series} de todo lo que guarda ejercicios por nombre."""
    used = dict(db.session.execute(
        sa.select(SetEntry.exercise, sa.func.count()).group_by(SetEntry.exercise)
    ).all())
    for model in (RoutineExercise, ExerciseNote, PersonalBasic):
        for name in db.session.scalars(sa.select(model.exercise).distinct()):
            used.setdefault(name, 0)
    return used


def plan():
    """Cambios pendientes: [{id, old_es, new_es, old_en, new_en, sets, used}]
    (español o inglés distintos del revisado), primero los que alguien usa."""
    names, names_en = curated(), curated_en()
    used = _used_names()
    changes = []
    for ex in db.session.scalars(sa.select(Exercise).where(Exercise.id.in_(names))):
        new_es, new_en = names[ex.id], names_en.get(ex.id, ex.name)
        if (ex.name_es or "") == new_es and ex.name == new_en:
            continue
        old_key = _key(ex.name_es or ex.name)
        changes.append({
            "id": ex.id, "old_es": ex.name_es, "new_es": new_es, "old_en": ex.name, "new_en": new_en,
            "sets": used.get(old_key, 0), "used": old_key in used,
        })
    changes.sort(key=lambda c: (not c["used"], -c["sets"], c["new_es"]))
    return changes


def apply(ids):
    """Aplica los nombres revisados (español e inglés) a los ejercicios `ids`.
    Devuelve (ejercicios renombrados, series movidas). No hace commit."""
    from app.routes import _clear_catalog_cache, rename_exercise_everywhere

    # Lo guardado con el nombre inglés ANTIGUO se une antes de cambiarlo: si
    # no, esas series dejarían de casar con el catálogo.
    _merged, moved = merge_english()
    names, names_en = curated(), curated_en()
    wanted = set(ids) & set(names)
    used = _used_names()
    exercises = [ex for ex in db.session.scalars(sa.select(Exercise).where(Exercise.id.in_(wanted)))
                 if (ex.name_es or "") != names[ex.id] or ex.name != names_en.get(ex.id, ex.name)]
    moves = []  # (temporal, nombre nuevo)
    for n, ex in enumerate(exercises):
        old_key, new_key = _key(ex.name_es or ex.name), _key(names[ex.id])
        if old_key in used and old_key != new_key:
            tmp = f"__catalogo_{n}__"
            rename_exercise_everywhere(old_key, tmp)
            moves.append((tmp, new_key))
    moved += sum(rename_exercise_everywhere(tmp, new_key) for tmp, new_key in moves)
    for ex in exercises:
        ex.name_es = names[ex.id]
        ex.name = names_en.get(ex.id, ex.name)
    _clear_catalog_cache()
    recompute_prs(new_key for _tmp, new_key in moves)  # por si unió el historial con uno propio igual
    return len(exercises), moved


# ------------------------------------------------- historial guardado en inglés
# Antes, con la app en inglés las series se guardaban con el nombre inglés del
# catálogo ("bench press") y en español con el español ("press de banca"): dos
# historiales para el mismo ejercicio. Ahora siempre se guarda catalog_key()
# y se traduce al mostrarlo; esto une lo que ya estaba partido.
def english_plan():
    """[{id, english, key, sets}] de ejercicios con series guardadas con su
    nombre inglés que deberían estar con su nombre de guardado."""
    from app.routes import catalog_key

    used = _used_names()
    exercises = db.session.scalars(sa.select(Exercise)).all()
    keys = {catalog_key(ex) for ex in exercises}
    out = []
    for ex in exercises:
        english, key = _key(ex.name), catalog_key(ex)
        # Si el nombre inglés de uno es el de guardado de otro, es ambiguo: se deja.
        if english != key and english in used and english not in keys:
            out.append({"id": ex.id, "english": ex.name, "key": key, "sets": used[english]})
    out.sort(key=lambda c: -c["sets"])
    return out


def merge_english():
    """Une el historial guardado en inglés al nombre de guardado. Devuelve
    (ejercicios, series movidas). No hace commit."""
    from app.routes import rename_exercise_everywhere

    plan_rows = english_plan()
    moved = sum(rename_exercise_everywhere(_key(c["english"]), c["key"]) for c in plan_rows)
    recompute_prs(c["key"] for c in plan_rows)
    return len(plan_rows), moved


def recompute_prs(names):
    """Al juntar dos historiales, la medalla de récord de cada sesión se
    recalcula sobre el historial unido (si no, quedaban récords de más)."""
    from app.models import Workout
    from app.routes import apply_pr_flags_for_session, get_exercise_sessions

    for name in set(names):
        users = db.session.scalars(
            sa.select(Workout.user_id).join(SetEntry, SetEntry.workout_id == Workout.id)
            .where(SetEntry.exercise == name).distinct()
        ).all()
        for user_id in users:
            sessions, _, _ = get_exercise_sessions(name, user_id=user_id)
            for session in sessions:
                apply_pr_flags_for_session(session)
