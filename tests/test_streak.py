"""Racha en días con mínimo semanal (compute_smart_streak).

Uso:
    python -m unittest tests.test_streak
"""
import unittest
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import SetEntry, WeeklyGoalHistory, Workout
from app.routes import compute_smart_streak

MADRID = ZoneInfo("Europe/Madrid")


def this_monday():
    today = datetime.now(MADRID).date()
    return today - timedelta(days=today.weekday())


class StreakTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")

    def train(self, day, completed=True, hour=18):
        """Entreno el `day` (fecha local de Madrid) a las `hour` locales."""
        local = datetime.combine(day, time(hour, 0), tzinfo=MADRID)
        with app.app_context():
            w = Workout(user_id=self.uid, performance_rating=6,
                        timestamp=local.astimezone(timezone.utc).replace(tzinfo=None))
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise="sentadilla", weight=100, reps=5, completed=completed))
            db.session.commit()

    def set_minimum(self, minimum, from_monday):
        with app.app_context():
            db.session.add(WeeklyGoalHistory(user_id=self.uid, goal=minimum,
                                             effective_from=datetime.combine(from_monday, time())))
            db.session.commit()

    def streak(self):
        with app.app_context():
            workouts = db.session.scalars(sa.select(Workout).where(Workout.user_id == self.uid)).all()
            return compute_smart_streak(self.uid, workouts)

    def week(self, weeks_ago, *weekdays):
        monday = this_monday() - timedelta(days=7 * weeks_ago)
        for wd in weekdays:
            self.train(monday + timedelta(days=wd))

    def test_counts_days_of_consecutive_weeks_meeting_minimum(self):
        self.set_minimum(2, this_monday() - timedelta(days=70))
        self.week(3, 0, 2, 4, 5)   # 4 días
        self.week(2, 0, 3)         # 2 días (descarga: llega justo al mínimo)
        self.week(1, 1, 2, 4, 6)   # 4 días
        self.assertEqual(self.streak()["days"], 10)

    def test_week_below_minimum_breaks_the_streak(self):
        self.set_minimum(2, this_monday() - timedelta(days=70))
        self.week(3, 0, 2, 4)      # no cuenta: la semana siguiente rompe
        self.week(2, 1)            # 1 < 2
        self.week(1, 0, 3)
        self.assertEqual(self.streak()["days"], 2)

    def test_current_week_never_breaks_and_its_days_count(self):
        self.set_minimum(3, this_monday() - timedelta(days=70))
        self.week(1, 0, 2, 4)
        today = datetime.now(MADRID).date()
        self.train(today)          # 1 día esta semana (aún < 3)
        info = self.streak()
        self.assertEqual((info["days"], info["this_week"], info["minimum"]), (4, 1, 3))

    def test_same_day_counts_once_and_unfinished_workouts_do_not_count(self):
        monday = this_monday() - timedelta(days=7)
        self.train(monday, hour=9)
        self.train(monday, hour=19)                 # mismo día: 1
        self.train(monday + timedelta(days=1), completed=False)  # sin series hechas: 0
        self.assertEqual(self.streak()["days"], 1)

    def test_default_minimum_is_one_day(self):
        self.week(2, 3)
        self.week(1, 5)
        info = self.streak()
        self.assertEqual((info["days"], info["minimum"]), (2, 1))

    def test_minimum_change_is_not_retroactive(self):
        self.set_minimum(1, this_monday() - timedelta(days=70))
        self.week(2, 0)                         # vale con el mínimo antiguo (1)
        self.set_minimum(3, this_monday() - timedelta(days=7))
        self.week(1, 0, 2, 4)                   # cumple el nuevo (3)
        self.assertEqual(self.streak()["days"], 4)

    def test_local_midnight_belongs_to_the_local_day(self):
        # Domingo 00:30 en Madrid es sábado en UTC: debe contar en la semana del domingo.
        sunday = this_monday() - timedelta(days=1)
        self.train(sunday, hour=0)
        self.train(sunday - timedelta(days=1))  # sábado
        self.assertEqual(self.streak()["days"], 2)


class StreakSettingsTests(DbTestCase):
    def test_minimum_saved_and_shown(self):
        uid = self.make_user("atleta")
        self.login(uid)
        data = {"stagnation_threshold": 3, "effort_scale": "rir", "sex": "", "training_goal": "",
                "weekly_workout_goal": 2}
        self.assertEqual(self.client.post("/settings", data=data).status_code, 302)
        with app.app_context():
            row = db.session.scalar(sa.select(WeeklyGoalHistory).where(WeeklyGoalHistory.user_id == uid))
            self.assertEqual(row.goal, 2)
        html = self.client.get("/index").get_data(as_text=True)
        self.assertIn("0 de 2 días mínimos esta semana", html)
        self.assertEqual(self.client.post("/settings", data={**data, "weekly_workout_goal": 9}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
