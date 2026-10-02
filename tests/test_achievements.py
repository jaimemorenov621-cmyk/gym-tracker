"""Sistema de logros (app/achievements.py).

Uso:
    python -m unittest tests.test_achievements
"""
import unittest
from datetime import datetime, time, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import achievements, app, db
from app.models import BodyWeightEntry, SetEntry, User, UserAchievement, Workout

MADRID = ZoneInfo("Europe/Madrid")


class CatalogTests(unittest.TestCase):
    def test_codes_unique_and_categories_valid(self):
        codes = [a.code for a in achievements.ACHIEVEMENTS]
        self.assertEqual(len(codes), len(set(codes)))
        cats = {c for c, _, _ in achievements.CATEGORIES}
        for a in achievements.ACHIEVEMENTS:
            self.assertIn(a.category, cats, a.code)
            self.assertTrue(a.check is not None or (a.metric and a.target), a.code)
            self.assertLessEqual(len(a.code), 40)

    def test_there_are_lots(self):
        self.assertGreaterEqual(len(achievements.ACHIEVEMENTS), 100)


class AchievementTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")

    def workout(self, local_dt, sets, rating=None, minutes=60, comment=None):
        """sets: [(exercise, weight, reps, set_type, is_pr)]"""
        with app.app_context():
            ts = local_dt.replace(tzinfo=MADRID).astimezone(timezone.utc).replace(tzinfo=None)
            w = Workout(user_id=self.uid, timestamp=ts, ended_at=ts + timedelta(minutes=minutes),
                        performance_rating=rating, performance_comment=comment)
            db.session.add(w)
            db.session.flush()
            for ex, weight, reps, set_type, is_pr in sets:
                db.session.add(SetEntry(workout_id=w.id, exercise=ex, weight=weight, reps=reps,
                                        set_type=set_type, is_pr=is_pr, completed=True, rir=2))
            db.session.commit()

    def evaluate(self):
        with app.app_context():
            items, newly = achievements.evaluate(db.session.get(User, self.uid))
            return {it["a"].code: it for it in items}, [a.code for a in newly]

    def test_first_workout_and_persistence(self):
        self.workout(datetime(2026, 9, 1, 18, 0), [("press banca", 60, 8, "normal", True)])
        items, newly = self.evaluate()
        self.assertTrue(items["workouts_1"]["unlocked"])
        self.assertIn("workouts_1", newly)
        self.assertIn("prs_1", newly)
        _, newly_again = self.evaluate()
        self.assertEqual(newly_again, [])  # no se duplica
        with app.app_context():
            self.assertEqual(db.session.scalar(
                sa.select(sa.func.count()).select_from(UserAchievement).where(UserAchievement.code == "workouts_1")), 1)

    def test_progress_values(self):
        for d in range(3):
            self.workout(datetime(2026, 9, 1 + d, 18, 0), [("sentadilla", 100, 5, "normal", False)])
        items, _ = self.evaluate()
        it = items["workouts_5"]
        self.assertFalse(it["unlocked"])
        self.assertEqual((it["value"], it["target"], it["pct"]), (3, 5, 60))
        self.assertTrue(items["heavy_100"]["unlocked"])

    def test_habits_and_fun(self):
        self.workout(datetime(2026, 9, 7, 6, 30), [("press de banca", 80, 5, "fallo", False)])  # lunes, madrugada
        self.workout(datetime(2026, 9, 12, 22, 30), [("curl", 15, 25, "dropset", False)], rating=10)  # sábado noche
        items, _ = self.evaluate()
        for code in ("early_1", "late_1", "weekend_1", "monday_bench", "high_reps", "perfect_day"):
            self.assertTrue(items[code]["unlocked"], code)
        self.assertFalse(items["bad_day"]["unlocked"])

    def test_secret_dates(self):
        self.workout(datetime(2027, 1, 1, 12, 0), [("remo", 50, 10, "normal", False)])
        self.workout(datetime(2026, 11, 13, 12, 0), [("remo", 50, 10, "normal", False)])  # viernes 13
        items, _ = self.evaluate()
        self.assertTrue(items["new_year"]["unlocked"])
        self.assertTrue(items["friday13"]["unlocked"])
        self.assertFalse(items["christmas"]["unlocked"])

    def test_bodyweight_ratio(self):
        with app.app_context():
            db.session.add(BodyWeightEntry(user_id=self.uid, weight=80))
            db.session.commit()
        self.workout(datetime(2026, 9, 1, 18, 0), [("press banca", 80, 1, "normal", False)])
        items, _ = self.evaluate()
        # 80 kg x 1 a RIR 2 -> 1RM estimado ~86,8 kg > 80 kg de peso corporal
        self.assertTrue(items["bench_bw"]["unlocked"])
        self.assertFalse(items["bench_15bw"]["unlocked"])

    def test_unfinished_workouts_do_not_count(self):
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=datetime(2026, 9, 1, 18))
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise="x", weight=100, reps=5, completed=False))
            db.session.commit()
        items, newly = self.evaluate()
        self.assertEqual(newly, [])

    def test_unseen_marks_seen(self):
        self.workout(datetime(2026, 9, 1, 18, 0), [("press banca", 60, 8, "normal", False)])
        self.evaluate()
        with app.app_context():
            first = achievements.unseen(self.uid)
            second = achievements.unseen(self.uid)
        self.assertTrue(first)
        self.assertEqual(second, [])

    def test_page_and_home_toast(self):
        self.workout(datetime(2026, 9, 1, 18, 0), [("press banca", 60, 8, "normal", False)])
        self.login(self.uid)
        html = self.client.get("/index").get_data(as_text=True)   # primera vez: calcula y avisa
        self.assertIn("achv-toast", html)
        self.assertNotIn("achv-toast", self.client.get("/index").get_data(as_text=True))
        page = self.client.get("/logros").get_data(as_text=True)
        self.assertIn("Primer paso", page)
        self.assertIn("???", page)  # secretos ocultos
        self.assertNotIn("Turrón quemado", page)

    def test_failure_never_breaks_finishing(self):
        self.workout(datetime.now(MADRID).replace(tzinfo=None) - timedelta(minutes=30),
                     [("press banca", 60, 8, "normal", False)])
        with app.app_context():
            wid = db.session.scalar(sa.select(Workout.id))
        self.login(self.uid)
        with mock.patch.object(achievements, "evaluate", side_effect=RuntimeError("boom")):
            resp = self.client.post(f"/workout/{wid}/finish",
                                    data={"performance_rating": 7, "duration_hours": 1, "duration_minutes": 0})
        self.assertEqual(resp.status_code, 302)
        with app.app_context():
            self.assertEqual(db.session.get(Workout, wid).performance_rating, 7)


if __name__ == "__main__":
    unittest.main()
