"""Dominadas a 0 kg = dominadas con tu peso corporal.

Uso:
    python -m unittest tests.test_bodyweight_pullups
"""
from datetime import datetime, timedelta

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

from app import app, db
from app import progression
from app.models import BodyWeightEntry, SetEntry, User, Workout
from app.routes import estimated_1rm, get_exercise_sessions, is_real_set


class BodyweightPullupTests(DbTestCase):
    T0 = datetime(2026, 6, 1, 18, 0)

    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        with app.app_context():
            db.session.add(BodyWeightEntry(user_id=self.uid, weight=80, timestamp=self.T0 - timedelta(days=1)))
            db.session.commit()

    def session(self, day, weight, reps, exercise="dominadas"):
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=self.T0 + timedelta(days=day), performance_rating=7)
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise=exercise, weight=weight, reps=reps, rir=2, completed=True))
            db.session.commit()

    def test_zero_kg_pullups_are_real_sets_but_other_zero_kg_sets_are_not(self):
        with app.app_context():
            self.assertTrue(is_real_set(SetEntry(exercise="dominadas", weight=0, reps=8, completed=True)))
            self.assertFalse(is_real_set(SetEntry(exercise="dominadas asistidas", weight=0, reps=8, completed=True)))
            self.assertFalse(is_real_set(SetEntry(exercise="press de banca", weight=0, reps=8, completed=True)))

    def test_one_rep_max_uses_bodyweight_plus_added_weight(self):
        self.session(0, 0, 8)       # solo peso corporal
        self.session(7, 10, 6)      # +10 kg
        with app.app_context():
            sessions, _, _ = get_exercise_sessions("dominadas", user_id=self.uid)
        self.assertAlmostEqual(sessions[0]["best_1rm"], 80 / 0.739, places=3)   # 8 reps @ RIR 2
        self.assertAlmostEqual(sessions[1]["best_1rm"], 90 / 0.786, places=3)   # 6 reps @ RIR 2
        self.assertTrue(sessions[1]["is_pr"])
        with app.app_context():
            entry = SetEntry(exercise="press de banca", weight=60, reps=8, rir=2, completed=True)
            self.assertAlmostEqual(estimated_1rm(entry, 80), 60 / 0.739)  # el peso corporal solo afecta a dominadas

    def test_bodyweight_pullups_give_xp_sets(self):
        for _ in range(1):
            self.session(0, 0, 10)
        with app.app_context():
            report = progression.compute_xp(progression.load_xp_inputs(self.uid))
        self.assertEqual(next(iter(report.by_workout.values()))["sets_n"], 1)
