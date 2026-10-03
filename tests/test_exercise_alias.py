"""Asignar nombres escritos a mano a un ejercicio del catálogo (ExerciseAlias).

Uso:
    python -m unittest tests.test_exercise_alias
"""
from datetime import datetime, timedelta, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import Exercise, ExerciseAlias, SetEntry, Workout
from app.routes import canonicalize_exercise_name


class AliasTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        self.other = self.make_user("otro")
        with app.app_context():
            db.session.add(Exercise(id="Bench_Press", name="Bench Press", name_es="Press de banca",
                                    primary_muscles="chest", secondary_muscles="triceps"))
            w = Workout(user_id=self.uid, timestamp=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2))
            db.session.add(w)
            db.session.flush()
            for _ in range(12):
                db.session.add(SetEntry(workout_id=w.id, exercise="mi press raro", weight=60, reps=8, completed=True))
            db.session.commit()
        self.login(self.uid)

    def assign(self, alias="mi press raro", exercise="Press de banca", client=None):
        return (client or self.client).post("/api/exercise-alias", json={"alias": alias, "exercise": exercise})

    def test_unmapped_name_is_listed_until_assigned(self):
        html = self.client.get("/ejercicios/musculos").get_data(as_text=True)
        self.assertIn("Mi Press Raro", html)
        self.assertIn("12 series", html)
        self.assertTrue(self.assign().get_json()["ok"])
        html = self.client.get("/ejercicios/musculos").get_data(as_text=True)
        self.assertIn("Todos tus ejercicios tienen músculos asignados", html)
        self.assertIn("Press De Banca", html)  # en "Ya asignados"

    def test_assigned_name_counts_for_weekly_volume(self):
        html = self.client.get("/progress").get_data(as_text=True)
        self.assertIn("Asignar músculos", html)
        self.assign()
        html = self.client.get("/progress").get_data(as_text=True)
        self.assertNotIn("Asignar músculos", html)
        self.assertIn("12 series", html)  # pecho

    def test_history_name_is_never_renamed(self):
        self.assign()
        with app.test_request_context():
            self.assertEqual(canonicalize_exercise_name("mi press raro"), "mi press raro")
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(SetEntry)
                                               .where(SetEntry.exercise == "mi press raro")), 12)

    def test_unknown_catalog_exercise_is_rejected(self):
        self.assertEqual(self.assign(exercise="no existe").status_code, 400)

    def test_aliases_are_per_user(self):
        self.assign()
        with app.app_context():
            alias_id = db.session.scalar(sa.select(ExerciseAlias.id))
        other = app.test_client()
        self.login(self.other, client=other)
        self.assertEqual(other.post(f"/api/exercise-alias/{alias_id}/delete").status_code, 403)
        self.assertTrue(self.client.post(f"/api/exercise-alias/{alias_id}/delete").get_json()["ok"])
        with app.app_context():
            self.assertIsNone(db.session.scalar(sa.select(ExerciseAlias.id)))
