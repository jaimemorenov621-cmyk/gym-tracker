"""Nombres en español del catálogo revisados a mano (app/catalog_names.py).

Uso:
    python -m unittest tests.test_catalog_names
"""
import unicodedata
import unittest
from unittest import mock

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app import catalog_names
from app.models import Exercise, RoutineExercise, Routine, SetEntry, Workout
from app.routes import ADMIN_USERNAME
from app.strength_standards import lift_of


class DataFileTests(unittest.TestCase):
    def setUp(self):
        self.names = catalog_names.curated()

    def test_unique_and_fit_in_the_set_column(self):
        def norm(s):
            return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))

        self.assertGreater(len(self.names), 800)
        self.assertEqual(len({norm(n) for n in self.names.values()}), len(self.names))
        self.assertTrue(all(0 < len(n) <= 64 for n in self.names.values()))  # SetEntry.exercise es String(64)

    def test_english_names_unique_and_same_lift_as_spanish(self):
        english = catalog_names.curated_en()
        self.assertEqual(set(english), set(self.names))
        self.assertEqual(len({n.lower() for n in english.values()}), len(english))
        for ex_id, name in english.items():
            self.assertLessEqual(len(name), 120)
            self.assertEqual(lift_of(name), lift_of(self.names[ex_id]), (name, self.names[ex_id]))
        self.assertEqual(english["Barbell_Bench_Press_-_Medium_Grip"], "Bench Press")

    def test_main_lifts_keep_counting_for_rank(self):
        expected = {
            "Barbell_Bench_Press_-_Medium_Grip": "bench", "Barbell_Squat": "squat", "Barbell_Deadlift": "deadlift",
            "Standing_Military_Press": "press", "Bent_Over_Barbell_Row": "row", "Pullups": "pullup",
            "Wide-Grip_Lat_Pulldown": "pulldown", "Romanian_Deadlift": "rdl", "Smith_Machine_Squat": "smith_squat",
            # Variantes que NO son el levantamiento de los estándares:
            "Chin-Up": None, "Leverage_Deadlift": None, "Hurdle_Hops": None,
        }
        for ex_id, lift in expected.items():
            self.assertEqual(lift_of(self.names[ex_id]), lift, self.names[ex_id])


class ApplyTests(DbTestCase):
    """Si el nombre nuevo de A es el que hoy tiene B, sus series no se mezclan."""

    NAMES = {"A": "Press de banca", "B": "Press declinado con barra"}

    def setUp(self):
        super().setUp()
        self.admin = self.make_user(ADMIN_USERNAME)
        self.other = self.make_user("otro")
        with app.app_context():
            db.session.add_all([
                Exercise(id="A", name="Barbell Bench Press", name_es="Press banca barra"),
                Exercise(id="B", name="Decline Barbell Bench Press", name_es="Press de banca"),  # mal traducido
            ])
            w = Workout(user_id=self.other)
            db.session.add(w)
            db.session.flush()
            for name, n in (("press banca barra", 3), ("press de banca", 2)):
                for _ in range(n):
                    db.session.add(SetEntry(workout_id=w.id, exercise=name, weight=60, reps=8, completed=True))
            r = Routine(name="Pecho", user_id=self.other)
            db.session.add(r)
            db.session.flush()
            db.session.add(RoutineExercise(routine_id=r.id, exercise="press banca barra"))
            db.session.commit()
        self.patch = mock.patch.object(catalog_names, "curated", return_value=self.NAMES)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        super().tearDown()

    def counts(self):
        with app.app_context():
            return dict(db.session.execute(sa.select(SetEntry.exercise, sa.func.count()).group_by(SetEntry.exercise)).all())

    def test_preview_then_apply_swaps_without_mixing(self):
        self.login(self.admin)
        html = self.client.get("/landing/catalog-names").get_data(as_text=True)
        self.assertIn("Press declinado con barra", html)
        self.client.post("/landing/catalog-names", data={"ids": ["A", "B"]})
        self.assertEqual(self.counts(), {"press de banca": 3, "press declinado con barra": 2})
        with app.app_context():
            self.assertEqual(db.session.get(Exercise, "A").name_es, "Press de banca")
            self.assertEqual(db.session.scalar(sa.select(RoutineExercise.exercise)), "press de banca")
        self.assertIn("al día", self.client.get("/landing/catalog-names").get_data(as_text=True))

    def test_only_checked_ones_and_admin_only(self):
        self.login(self.other)
        self.client.post("/landing/catalog-names", data={"ids": ["A", "B"]})
        self.assertEqual(self.counts(), {"press banca barra": 3, "press de banca": 2})
        self.login(self.admin)
        self.client.post("/landing/catalog-names", data={"ids": ["B"]})
        self.assertEqual(self.counts(), {"press banca barra": 3, "press declinado con barra": 2})


if __name__ == "__main__":
    unittest.main()


class LanguageIndependentNameTests(DbTestCase):
    """El mismo ejercicio del catálogo se guarda igual en los dos idiomas y
    se muestra en el de la app; lo guardado antes en inglés se une."""

    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        self.admin = self.make_user(ADMIN_USERNAME)
        with app.app_context():
            db.session.add(Exercise(id="Bench", name="Barbell Bench Press", name_es="Press de banca",
                                    primary_muscles="chest"))
            w = Workout(user_id=self.uid)
            db.session.add(w)
            db.session.commit()
            self.wid = w.id

    def set_language(self, lang):
        from app.models import User
        with app.app_context():
            db.session.get(User, self.uid).language = lang
            db.session.commit()

    def test_english_ui_stores_the_same_name_and_shows_english(self):
        self.set_language("en")
        self.login(self.uid)
        self.client.post(f"/workout/{self.wid}/add_exercise", data={"exercise": "Barbell Bench Press"})
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(SetEntry.exercise)), "press de banca")
        html = self.client.get(f"/workout/{self.wid}").get_data(as_text=True)
        self.assertIn("Barbell Bench Press", html)
        self.set_language("es")
        self.assertIn("Press De Banca", self.client.get(f"/workout/{self.wid}").get_data(as_text=True))

    def test_merge_history_saved_in_english(self):
        from datetime import datetime, timedelta, timezone
        with app.app_context():
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for days, name, kg in ((10, "press de banca", 100), (5, "barbell bench press", 90), (1, "barbell bench press", 105)):
                w = Workout(user_id=self.uid, timestamp=now - timedelta(days=days), performance_rating=3)
                db.session.add(w)
                db.session.flush()
                # Por separado, cada sesión era récord de su historial (también la de 90 kg).
                db.session.add(SetEntry(workout_id=w.id, exercise=name, weight=kg, reps=5, completed=True,
                                        is_pr=True))
            db.session.commit()
        self.login(self.admin)
        self.assertIn("Barbell Bench Press", self.client.get("/landing/catalog-names").get_data(as_text=True))
        self.client.post("/landing/catalog-names", data={"action": "merge_english"})
        with app.app_context():
            rows = db.session.execute(sa.select(SetEntry.exercise, SetEntry.weight, SetEntry.is_pr)
                                      .order_by(SetEntry.weight)).all()
        self.assertEqual({r.exercise for r in rows}, {"press de banca"})
        self.assertEqual([(r.weight, r.is_pr) for r in rows], [(90, False), (100, True), (105, True)])
