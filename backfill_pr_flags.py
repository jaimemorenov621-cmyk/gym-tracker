"""Backfill puntual: persiste SetEntry.is_pr=True en la serie ganadora de
cada sesion (Workout) que fue un PR en su momento, y False en el resto --
misma logica que ya usa api_update_set() al completar una serie, reutilizada
desde app.routes (get_exercise_sessions / apply_pr_flags_for_session /
count_pending_pr_changes), sin duplicar la deteccion de PR aqui.

Necesario porque is_pr se guarda a partir de ahora en tiempo real (al
completar o editar una serie), pero las filas ya existentes en la base de
datos nunca pasaron por ese codigo -- sin este backfill se verian sin
medalla aunque en su dia fueran record.

Uso:
    python backfill_pr_flags.py            # solo muestra cuantas filas cambiarian
    python backfill_pr_flags.py --apply    # aplica el cambio de verdad
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import sqlalchemy as sa

from app import app, db
from app.models import SetEntry, Workout
from app.routes import (
    apply_pr_flags_for_session,
    count_pending_pr_changes,
    get_exercise_sessions,
)

APPLY = "--apply" in sys.argv


def main():
    with app.app_context():
        pairs = db.session.execute(
            sa.select(Workout.user_id, SetEntry.exercise)
            .join(SetEntry, SetEntry.workout_id == Workout.id)
            .distinct()
        ).all()

        total = 0
        for user_id, exercise in pairs:
            session_list, _, _ = get_exercise_sessions(exercise, user_id=user_id)
            for session in session_list:
                if APPLY:
                    total += apply_pr_flags_for_session(session)
                else:
                    total += count_pending_pr_changes(session)

        print(f"Series cuyo estado de medalla cambiaria: {total}")

        if not APPLY:
            print("Modo simulacion -- ejecuta con --apply para aplicar el cambio.")
            return

        db.session.commit()
        print("Backfill aplicado.")


if __name__ == "__main__":
    main()
