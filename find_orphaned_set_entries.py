"""Diagnostico puntual: busca SetEntry cuyo workout_id no apunte a ningun
Workout existente -- no deberian existir (delete_workout() ya borra sus
SetEntry a mano), pero antes de la migracion que anade ondelete=CASCADE a
set_entry.workout_id no habia ninguna red de seguridad a nivel de base de
datos, asi que conviene comprobarlo una vez.

Uso:
    python find_orphaned_set_entries.py            # solo cuenta y lista
    python find_orphaned_set_entries.py --apply     # borra las huerfanas encontradas
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import sqlalchemy as sa

from app import app, db
from app.models import SetEntry, Workout

APPLY = "--apply" in sys.argv


def main():
    with app.app_context():
        orphans = db.session.scalars(
            sa.select(SetEntry).where(SetEntry.workout_id.not_in(sa.select(Workout.id)))
        ).all()

        print(f"SetEntry huerfanas encontradas: {len(orphans)}")
        for s in orphans:
            print(f"  id={s.id} exercise={s.exercise!r} workout_id={s.workout_id}")

        if not APPLY:
            print("Modo simulacion -- ejecuta con --apply para borrarlas.")
            return

        for s in orphans:
            db.session.delete(s)
        db.session.commit()
        print("Huerfanas eliminadas.")


if __name__ == "__main__":
    main()
