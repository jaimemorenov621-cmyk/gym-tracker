"""Diagnostico de solo lectura: detalla EXACTAMENTE que filas cambiarian
con backfill_pr_flags.py --apply -- ejercicio, fecha de la sesion, y si
gana o pierde la medalla. No escribe nada en la base de datos.

Uso:
    python inspect_pr_backfill.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import sqlalchemy as sa

from app import app, db
from app.models import SetEntry, User, Workout
from app.routes import get_exercise_sessions, to_local


def main():
    with app.app_context():
        pairs = db.session.execute(
            sa.select(Workout.user_id, SetEntry.exercise)
            .join(SetEntry, SetEntry.workout_id == Workout.id)
            .distinct()
        ).all()
        usernames = {u.id: u.username for u in db.session.scalars(sa.select(User)).all()}

        changes = []
        for user_id, exercise in pairs:
            session_list, _, _ = get_exercise_sessions(exercise, user_id=user_id)
            for session in session_list:
                best = session["best_set"]
                for s in session["sets"]:
                    should_be_pr = best is not None and session["is_pr"] and s.id == best.id
                    if s.is_pr != should_be_pr:
                        changes.append(
                            (
                                usernames.get(user_id, f"user#{user_id}"),
                                exercise,
                                to_local(session["timestamp"]).strftime("%d/%m/%Y"),
                                s.id,
                                s.weight,
                                s.reps,
                                s.completed,
                                "PIERDE medalla" if s.is_pr else "GANA medalla",
                            )
                        )

        changes.sort(key=lambda c: (c[0], c[1], c[2]))
        print(f"Total de cambios: {len(changes)}\n")
        for username, exercise, date, set_id, weight, reps, completed, action in changes:
            print(
                f"  {username:12s} | {action:15s} | {exercise.title():30s} | {date} | "
                f"serie #{set_id} | {weight:g}kg x{reps} | completada={completed}"
            )


if __name__ == "__main__":
    main()
