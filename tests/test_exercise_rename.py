"""Cambiar el nombre (traducción) de un ejercicio del catálogo no rompe el historial.

Uso:
    python -m unittest tests.test_exercise_rename
"""
from datetime import datetime, timedelta, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import Exercise, ExerciseNote, Routine, RoutineExercise, SetEntry, User, Workout


class RenameTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.make_user("a")
        self.b = self.make_user("b")
        with app.app_context():
            db.session.add(Exercise(id="Lat_Pulldown", name="Lat Pulldown", name_es="Jalón al pecho",
                                    primary_muscles="lats"))
            for uid in (self.a, self.b):
                w = Workout(user_id=uid, timestamp=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1))
                db.session.add(w)
                db.session.flush()
                for _ in range(3):
                    db.session.add(SetEntry(workout_id=w.id, exercise="jalón al pecho", weight=60, reps=10, completed=True))
            r = Routine(name="Espalda", user_id=self.a)
            db.session.add(r)
            db.session.flush()
            db.session.add(RoutineExercise(routine_id=r.id, exercise="jalón al pecho"))
            db.session.add(ExerciseNote(user_id=self.a, exercise="jalón al pecho", notes="agarre abierto"))
            db.session.add(ExerciseNote(user_id=self.a, exercise="jalón en polea", notes="nota previa"))
            db.session.commit()
        self.login(self.a)

    def count(self, model, name):
        with app.app_context():
            return db.session.scalar(sa.select(sa.func.count()).select_from(model).where(model.exercise == name))

    def test_renaming_moves_history_for_everyone(self):
        resp = self.client.post("/exercise/jalón al pecho/translate", data={"name_es": "Jalón en polea"})
        self.assertIn("/exercise/jal%C3%B3n%20en%20polea", resp.headers["Location"])
        self.assertEqual(self.count(SetEntry, "jalón al pecho"), 0)
        self.assertEqual(self.count(SetEntry, "jalón en polea"), 6)       # las de los dos usuarios
        self.assertEqual(self.count(RoutineExercise, "jalón en polea"), 1)
        with app.app_context():
            note = db.session.scalar(sa.select(ExerciseNote).where(ExerciseNote.user_id == self.a))
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(ExerciseNote)), 1)
            self.assertIn("nota previa", note.notes)
            self.assertIn("agarre abierto", note.notes)                  # fusionadas, sin perder texto

    def test_xp_cache_is_invalidated_only_for_affected_users(self):
        with app.app_context():
            seq = {u: db.session.scalar(sa.select(User.xp_seq).where(User.id == u)) for u in (self.a, self.b)}
            c = self.make_user("c")
            seq_c = db.session.scalar(sa.select(User.xp_seq).where(User.id == c))
        self.client.post("/exercise/jalón al pecho/translate", data={"name_es": "Jalón en polea"})
        with app.app_context():
            for u in (self.a, self.b):
                self.assertGreater(db.session.scalar(sa.select(User.xp_seq).where(User.id == u)), seq[u])
            self.assertEqual(db.session.scalar(sa.select(User.xp_seq).where(User.id == c)), seq_c)

    def test_too_long_name_is_rejected(self):
        self.client.post("/exercise/jalón al pecho/translate", data={"name_es": "x" * 70})
        self.assertEqual(self.count(SetEntry, "jalón al pecho"), 6)
