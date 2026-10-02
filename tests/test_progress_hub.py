"""Fase 2 de UX: pantalla de Progreso, cifras por ejercicio y formato de
números en español.

Uso:
    python -m unittest tests.test_progress_hub
"""
import unittest
from datetime import datetime, timedelta, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

from app import app, db
from app.models import SetEntry, Workout
from app.routes import estimated_1rm, fmt_num, progress_overview, relative_day, strength_progress


class FmtNumTests(unittest.TestCase):
    def test_spanish_format(self):
        self.assertEqual(fmt_num(82.5), "82,5")
        self.assertEqual(fmt_num(100.0), "100")
        self.assertEqual(fmt_num(1200), "1.200")
        self.assertEqual(fmt_num(12345.67, 2), "12.345,67")
        self.assertEqual(fmt_num(63.333), "63,3")
        self.assertEqual(fmt_num(63.96, 0), "64")
        self.assertEqual(fmt_num(-4.5), "-4,5")
        self.assertEqual(fmt_num(None), "—")
        self.assertEqual(fmt_num(0.3), "0,3")


class RelativeDayTests(unittest.TestCase):
    def test_labels(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(relative_day(now), "hoy")
        self.assertEqual(relative_day(now - timedelta(days=1)), "ayer")
        self.assertEqual(relative_day(now - timedelta(days=5)), "hace 5 días")
        self.assertEqual(relative_day(now - timedelta(days=21)), "hace 3 semanas")
        self.assertRegex(relative_day(now - timedelta(days=100)), r"^\d{2}/\d{2}/\d{4}$")
        self.assertEqual(relative_day(None), "—")


class ProgressOverviewTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")

    def add(self, days_ago, exercise, weight, reps, completed=True):
        with app.app_context():
            w = Workout(user_id=self.uid, performance_rating=6,
                        timestamp=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago))
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise=exercise, weight=weight, reps=reps, completed=completed))
            db.session.commit()

    def test_trend_ordering_and_skips_exercises_without_real_sets(self):
        self.add(40, "sentadilla", 100, 5)
        self.add(10, "sentadilla", 110, 5)
        self.add(3, "press banca", 80, 5)
        self.add(1, "remo", 60, 8, completed=False)  # sin series reales: no aparece
        with app.app_context():
            items = progress_overview(self.uid, threshold=3)
        self.assertEqual([i["exercise"] for i in items], ["press banca", "sentadilla"])
        squat = items[1]
        self.assertEqual(squat["sessions"], 2)
        self.assertEqual(squat["trend_pct"], 10)  # 1RM sube en la misma proporción que el peso
        self.assertIsNotNone(squat["last_pr"])
        self.assertIsNone(items[0]["trend_pct"])  # una sola sesión: sin tendencia

    def test_trend_ignores_sessions_older_than_60_days(self):
        self.add(200, "sentadilla", 50, 5)
        self.add(30, "sentadilla", 100, 5)
        self.add(1, "sentadilla", 105, 5)
        with app.app_context():
            squat = progress_overview(self.uid, threshold=3)[0]
        self.assertEqual(squat["trend_pct"], 5)

    def test_stagnation_flag(self):
        self.add(30, "sentadilla", 120, 5)
        for d in (20, 10, 2):
            self.add(d, "sentadilla", 100, 5)
        with app.app_context():
            squat = progress_overview(self.uid, threshold=3)[0]
        self.assertTrue(squat["stagnation"])
        with app.app_context():
            expected = estimated_1rm(SetEntry(weight=120, reps=5))
        self.assertAlmostEqual(squat["best_1rm"], expected)

    def test_progress_page(self):
        self.assertIn("/login", self.client.get("/progress").headers["Location"])
        self.add(3, "sentadilla", 100, 5)
        self.login(self.uid)
        html = self.client.get("/progress").get_data(as_text=True)
        self.assertIn("Sentadilla", html)
        self.assertIn("/exercise/sentadilla", html)

    def test_exercise_page_shows_stats(self):
        self.add(10, "sentadilla", 100, 5)
        self.add(2, "sentadilla", 102.5, 5)
        self.login(self.uid)
        html = self.client.get("/exercise/sentadilla").get_data(as_text=True)
        self.assertIn("exercise-stats", html)
        self.assertIn("102,5 kg", html)
        self.assertNotIn("102.5kg", html)


class StrengthIndexTests(ProgressOverviewTests):
    def test_single_exercise_index_equals_ratio(self):
        self.add(35, "sentadilla", 100, 5)
        self.add(1, "sentadilla", 110, 5)
        with app.app_context():
            st = strength_progress(self.uid)
        self.assertAlmostEqual(st["series"][-1][1], 110.0, places=3)

    def test_new_exercise_does_not_move_index(self):
        self.add(21, "sentadilla", 100, 5)
        self.add(14, "sentadilla", 100, 5)
        self.add(7, "curl", 20, 10)        # entra nuevo: no compara con nada
        with app.app_context():
            st = strength_progress(self.uid)
        self.assertAlmostEqual(st["series"][-1][1], 100.0, places=3)

    def test_bad_then_normal_session_cancels_out(self):
        self.add(21, "sentadilla", 100, 5)
        self.add(14, "sentadilla", 90, 5)
        self.add(7, "sentadilla", 100, 5)
        with app.app_context():
            st = strength_progress(self.uid)
        self.assertAlmostEqual(st["series"][-1][1], 100.0, places=3)

    def test_outlier_is_capped(self):
        self.add(14, "sentadilla", 100, 5)
        self.add(7, "sentadilla", 300, 5)   # peso mal apuntado
        with app.app_context():
            st = strength_progress(self.uid)
        self.assertAlmostEqual(st["series"][-1][1], 125.0, places=3)

    def test_needs_two_weeks_and_reports_movers(self):
        self.add(1, "sentadilla", 100, 5)
        with app.app_context():
            self.assertIsNone(strength_progress(self.uid))
        self.add(35, "press", 60, 5)
        self.add(2, "press", 66, 5)
        with app.app_context():
            st = strength_progress(self.uid)
        self.assertEqual(st["weeks"], 4)
        self.assertEqual(st["movers"][0]["exercise"], "press")
        self.assertAlmostEqual(st["movers"][0]["pct"], 10.0, places=3)


if __name__ == "__main__":
    unittest.main()
