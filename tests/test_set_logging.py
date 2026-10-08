"""Registro de series: tipo "Fallo" = RIR 0 / RPE 10, aviso de repeticiones,
series de más de 30 repeticiones sin 1RM y páginas fuera de la caché."""
import unittest
from datetime import datetime, timedelta, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import SetEntry, User, Workout
from app.routes import MAX_1RM_REPS, estimated_1rm, get_exercise_sessions, qualifying_sessions


def naive_utc(days=0):
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)


class _Fixtures(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")

    def add_set(self, weight, reps, days_ago=0, completed=True, rir=None):
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=naive_utc(days_ago), performance_rating=7)
            db.session.add(w)
            db.session.flush()
            s = SetEntry(workout_id=w.id, exercise="curl de piernas", weight=weight, reps=reps,
                         completed=completed, rir=rir)
            db.session.add(s)
            db.session.commit()
            return s.id


class FailureSetTypeTests(_Fixtures):
    def test_failure_sets_rir_zero(self):
        sid = self.add_set(40, 8, rir=2)
        self.login(self.uid)
        self.assertTrue(self.client.put(f"/set/{sid}", json={"set_type": "fallo"}).get_json()["ok"])
        with app.app_context():
            s = db.session.get(SetEntry, sid)
            self.assertEqual((s.set_type, s.rir, s.rpe), ("fallo", 0, None))

    def test_failure_sets_rpe_ten(self):
        with app.app_context():
            db.session.get(User, self.uid).effort_scale = "rpe"
            db.session.commit()
        sid = self.add_set(40, 8)
        self.login(self.uid)
        self.client.put(f"/set/{sid}", json={"set_type": "fallo"})
        with app.app_context():
            s = db.session.get(SetEntry, sid)
            self.assertEqual((s.rpe, s.rir), (10, None))

    def test_new_failure_set_gets_effort(self):
        with app.app_context():
            w = Workout(user_id=self.uid)
            db.session.add(w)
            db.session.commit()
            wid = w.id
        self.login(self.uid)
        data = self.client.post(f"/workout/{wid}/set", json={"exercise": "curl", "weight": 20, "reps": 10,
                                                              "set_type": "fallo"}).get_json()
        with app.app_context():
            self.assertEqual(db.session.get(SetEntry, data["id"]).rir, 0)

    def test_unknown_set_type_ignored(self):
        sid = self.add_set(40, 8)
        self.login(self.uid)
        self.client.put(f"/set/{sid}", json={"set_type": "<script>"})
        with app.app_context():
            self.assertNotEqual(db.session.get(SetEntry, sid).set_type, "<script>")


class RepsTests(_Fixtures):
    def test_reps_above_30_are_stored_but_capped_at_100(self):
        sid = self.add_set(10, 5)
        self.login(self.uid)
        self.client.put(f"/set/{sid}", json={"reps": 40})
        with app.app_context():
            self.assertEqual(db.session.get(SetEntry, sid).reps, 40)
        self.client.put(f"/set/{sid}", json={"reps": 999})
        with app.app_context():
            self.assertEqual(db.session.get(SetEntry, sid).reps, 100)

    def test_no_1rm_above_30_reps(self):
        s = SetEntry(exercise="curl", weight=40, reps=MAX_1RM_REPS + 34, completed=True)
        self.assertEqual(estimated_1rm(s), 0.0)
        self.assertGreater(estimated_1rm(SetEntry(exercise="curl", weight=40, reps=MAX_1RM_REPS, completed=True)), 40)

    def test_typo_set_is_not_a_record(self):
        # 40 kg × 64 (era 6) entre sesiones normales: ni mejor serie ni récord.
        self.add_set(50, 6, days_ago=10)
        self.add_set(40, 64, days_ago=5)
        self.add_set(50, 7, days_ago=1)
        with app.app_context():
            sessions, _, _ = get_exercise_sessions("curl de piernas", user_id=self.uid)
            shown = qualifying_sessions(sessions)
            self.assertEqual(len(shown), 2)  # la sesión con solo la serie de 64 no tiene 1RM
            self.assertTrue(shown[-1]["is_pr"])
            self.assertLess(max(s["best_1rm"] for s in shown), 70)

    def test_reps_warning_setting(self):
        self.login(self.uid)
        with app.app_context():
            self.assertEqual(db.session.get(User, self.uid).reps_warning, 30)
        form = {"stagnation_threshold": 3, "effort_scale": "rir", "reps_warning": 20}
        self.client.post("/settings", data=form)
        with app.app_context():
            self.assertEqual(db.session.get(User, self.uid).reps_warning, 20)


class NoStaleHtmlTests(_Fixtures):
    def test_logged_in_pages_not_cached(self):
        self.login(self.uid)
        self.assertEqual(self.client.get("/settings").headers.get("Cache-Control"), "no-store")

    def test_login_is_remembered(self):
        resp = self.client.post("/login", data={"username": "atleta", "password": "testpass"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("remember_token", " ".join(resp.headers.getlist("Set-Cookie")))

    def test_old_session_gets_remember_cookie(self):
        self.login(self.uid)
        resp = self.client.get("/settings")
        self.assertIn("remember_token", " ".join(resp.headers.getlist("Set-Cookie")))


if __name__ == "__main__":
    unittest.main()
