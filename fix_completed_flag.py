"""Backfill puntual: SetEntry.completed=True donde reps>0 en entrenamientos ya
finalizados (ended_at IS NOT NULL) pero completed seguia en False.

Necesario porque routine_plan/el anillo de progreso en workout_detail() pasaron
a contar "done" como series marcadas con el tick (completed=True) en vez de
series que simplemente existen -- sin este backfill, entrenamientos finalizados
antes de ese cambio mostrarian progreso incompleto retroactivamente, aunque en
su dia se dieran por terminados con normalidad.

Mismo criterio que ya usa finish_workout() para decidir que serie "cuenta"
(reps > 0) -- no se inventa un criterio nuevo. Alcance limitado a
entrenamientos ya finalizados: uno en curso no se toca.

Uso:
    python fix_completed_flag.py            # solo muestra cuantas filas se verian afectadas
    python fix_completed_flag.py --apply    # aplica el cambio de verdad
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import sqlalchemy as sa

from app import app, db
from app.models import SetEntry, Workout

APPLY = "--apply" in sys.argv


def affected_query():
    return (
        sa.select(sa.func.count())
        .select_from(SetEntry)
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(
            Workout.ended_at.is_not(None),
            SetEntry.reps > 0,
            SetEntry.completed.is_(False),
        )
    )


def main():
    with app.app_context():
        before = db.session.scalar(affected_query())
        print(f"Series afectadas (reps>0, completed=False, entrenamiento finalizado): {before}")

        if not APPLY:
            print("Modo simulacion -- ejecuta con --apply para aplicar el cambio.")
            return

        result = db.session.execute(
            sa.update(SetEntry)
            .where(
                SetEntry.workout_id.in_(
                    sa.select(Workout.id).where(Workout.ended_at.is_not(None))
                ),
                SetEntry.reps > 0,
                SetEntry.completed.is_(False),
            )
            .values(completed=True)
        )
        db.session.commit()
        print(f"Filas actualizadas: {result.rowcount}")

        after = db.session.scalar(affected_query())
        print(f"Series afectadas tras el backfill: {after}")


if __name__ == "__main__":
    main()
