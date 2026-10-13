"""Corregir el historial de un ejercicio: mover una sesión a otro ejercicio,
borrarla o borrar una serie suelta, con la medalla de récord recalculada.

Uso:
    python -m unittest tests.test_session_fix
"""
from datetime import datetime, timedelta, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import SetEntry, Workout


class SessionFixTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        self.wids = []
        with app.app_context():
            # 80 kg (récord) -> 100 kg apuntado en el ejercicio equivocado (récord) -> 90 kg
            for days, weight in ((3, 80), (2, 100), (1, 90)):
                w = Workout(user_id=self.uid, timestamp=datetime.now(timezone.utc) - timedelta(days=days))
                db.session.add(w)
                db.session.flush()
                db.session.add(SetEntry(workout_id=w.id, exercise="press de banca", weight=weight, reps=5, completed=True))
                db.session.add(SetEntry(workout_id=w.id, exercise="press de banca", weight=20, reps=5, completed=False))
                self.wids.append(w.id)
            db.session.commit()
            from app.routes import recompute_exercise_prs
            recompute_exercise_prs(self.uid, "press de banca")
            db.session.commit()

    def prs(self, exercise):
        with app.app_context():
            return db.session.scalars(
                sa.select(SetEntry.weight).where(SetEntry.exercise == exercise, SetEntry.is_pr.is_(True))
                .order_by(SetEntry.weight)
            ).all()

    def test_move_session_recomputes_both_exercises(self):
        self.login(self.uid)
        self.assertEqual(self.prs("press de banca"), [80, 100])
        resp = self.client.post(f"/workout/{self.wids[1]}/exercise/replace",
                                json={"old_exercise": "press de banca", "exercise": "press militar"})
        self.assertTrue(resp.get_json()["ok"])
        self.assertEqual(self.prs("press de banca"), [80, 90])  # sin el 100, el 90 pasa a ser récord
        self.assertEqual(self.prs("press militar"), [100])
        with app.app_context():
            moved = db.session.scalars(sa.select(SetEntry.exercise).where(SetEntry.workout_id == self.wids[1])).all()
        self.assertEqual(set(moved), {"press militar"})  # también la serie sin hacer

    def test_delete_session_and_single_set(self):
        self.login(self.uid)
        self.client.post(f"/workout/{self.wids[1]}/exercise/delete", json={"exercise": "press de banca"})
        self.assertEqual(self.prs("press de banca"), [80, 90])
        with app.app_context():
            set_90 = db.session.scalar(sa.select(SetEntry.id).where(SetEntry.weight == 90))
        self.assertTrue(self.client.post(f"/set/{set_90}/delete").get_json()["ok"])
        self.assertEqual(self.prs("press de banca"), [80])

    def test_history_page_shows_tools_and_others_forbidden(self):
        self.login(self.uid)
        html = self.client.get("/exercise/press de banca").get_data(as_text=True)
        self.assertIn('class="session-menu-btn"', html)
        self.assertIn(f'data-workout="{self.wids[1]}"', html)
        self.assertIn('data-count="2"', html)  # cuenta también la serie sin hacer
        self.assertIn("exercise_picker.js", html)
        self.login(self.make_user("otro"))
        self.assertEqual(self.client.post(f"/workout/{self.wids[1]}/exercise/delete",
                                          json={"exercise": "press de banca"}).status_code, 403)
        self.assertEqual(self.prs("press de banca"), [80, 100])


if __name__ == "__main__":
    import unittest
    unittest.main()
