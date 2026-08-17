import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import sqlalchemy as sa

from app import app, db
from app.models import ExerciseNote, RoutineExercise, SetEntry
from app.routes import canonicalize_exercise_name

APPLY = "--apply" in sys.argv

MODELS = [
    ("set_entry", SetEntry),
    ("exercise_note", ExerciseNote),
    ("routine_exercise", RoutineExercise),
]


def find_changes(model):
    values = db.session.scalars(sa.select(model.exercise).distinct()).all()
    return {
        v: canonicalize_exercise_name(v)
        for v in values
        if canonicalize_exercise_name(v) != v
    }


def apply_exercise_note_change(old, new):
    """ExerciseNote tiene UNIQUE(user_id, exercise): fusiona en vez de sobreescribir sin más."""
    rows = db.session.scalars(
        sa.select(ExerciseNote).where(ExerciseNote.exercise == old)
    ).all()
    for row in rows:
        existing = db.session.scalar(
            sa.select(ExerciseNote).where(
                ExerciseNote.user_id == row.user_id, ExerciseNote.exercise == new
            )
        )
        if existing and existing.id != row.id:
            if row.notes:
                existing.notes = (
                    f"{existing.notes}\n{row.notes}" if existing.notes else row.notes
                )
            if existing.default_rest_seconds is None:
                existing.default_rest_seconds = row.default_rest_seconds
            db.session.delete(row)
        else:
            row.exercise = new


def apply_simple_change(model, old, new):
    rows = db.session.scalars(sa.select(model).where(model.exercise == old)).all()
    for row in rows:
        row.exercise = new


with app.app_context():
    all_changes = {label: find_changes(model) for label, model in MODELS}
    total = sum(len(c) for c in all_changes.values())

    if total == 0:
        print("✅ No hay variantes que corregir.")
    else:
        print(
            "Aplicando cambios:"
            if APPLY
            else "Dry-run (usa --apply para aplicar de verdad):"
        )
        for label, changes in all_changes.items():
            if not changes:
                continue
            print(f"\n{label}:")
            for old, new in changes.items():
                print(f"  {old!r} -> {new!r}")

        if APPLY:
            for label, model in MODELS:
                for old, new in all_changes[label].items():
                    if model is ExerciseNote:
                        apply_exercise_note_change(old, new)
                    else:
                        apply_simple_change(model, old, new)
            db.session.commit()
            print("\n✅ Cambios aplicados.")
        else:
            print("\nNada aplicado todavía. Ejecuta con --apply para confirmar los cambios.")
