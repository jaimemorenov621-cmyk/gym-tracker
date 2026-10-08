"""Probar sin cuenta: cuenta de invitado que luego se guarda sin perder nada."""
import unittest
from datetime import datetime, timedelta, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import LandingEvent, SetEntry, User, Workout
from app.routes import _purge_stale_guests


class GuestTests(DbTestCase):
    def start(self):
        resp = self.client.post("/probar")
        self.assertEqual(resp.status_code, 302)
        with app.app_context():
            return db.session.scalar(sa.select(User).where(User.signup_method == "guest")).id

    def test_landing_offers_trial(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Probar ahora, sin cuenta", html)
        self.assertIn('action="/probar"', html)

    def test_get_does_not_create_accounts(self):
        self.client.get("/probar")
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(User)), 0)

    def test_trial_creates_logged_in_guest(self):
        uid = self.start()
        html = self.client.get("/settings").get_data(as_text=True)
        self.assertIn("Guardar mi progreso", html)
        with app.app_context():
            self.assertTrue(db.session.get(User, uid).is_guest)
            self.assertEqual(db.session.scalar(sa.select(LandingEvent.event_type)), "guest_start")

    def test_save_account_keeps_data(self):
        uid = self.start()
        with app.app_context():
            w = Workout(user_id=uid)
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise="press banca", weight=60, reps=8, completed=True))
            db.session.commit()
        self.assertIn("Guarda tu cuenta", self.client.get("/register").get_data(as_text=True))
        resp = self.client.post("/register", data={"username": "ana", "email": "ana@example.com",
                                                   "password": "secreta1", "password2": "secreta1"})
        self.assertEqual(resp.status_code, 302)
        with app.app_context():
            u = db.session.get(User, uid)
            self.assertEqual((u.username, u.email, u.signup_method), ("ana", "ana@example.com", "guest_pw"))
            self.assertTrue(u.check_password("secreta1"))
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Workout).where(Workout.user_id == uid)), 1)
        self.assertNotIn("Guardar mi progreso", self.client.get("/settings").get_data(as_text=True))

    def test_trial_counted_apart_from_signup_clicks(self):
        self.start()
        self.client.get("/logout")
        admin = self.make_user("Jaime_309")
        self.login(admin)
        html = self.client.get("/landing/stats?periodo=todo").get_data(as_text=True)
        self.assertIn("Probaron sin cuenta", html)
        self.assertIn("1 siguen probando", html)
        tile = html.split("Clics para crear cuenta")[0].rsplit('stats-tile-value">', 1)[1]
        self.assertTrue(tile.startswith("0<"), tile[:20])  # probar no es un clic de crear cuenta

    def test_guest_can_open_login(self):
        self.start()
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_guest_cannot_use_ai_or_contact(self):
        self.start()
        self.assertTrue(self.client.post("/ai/analyze").headers["Location"].endswith("/register"))
        self.assertTrue(self.client.get("/contacto").headers["Location"].endswith("/register"))

    def test_stale_guests_are_purged(self):
        old = self.make_user("invitado_viejo")
        fresh = self.make_user("invitado_nuevo")
        real = self.make_user("de_verdad")
        long_ago = (datetime.now(timezone.utc) - timedelta(days=40)).replace(tzinfo=None)
        with app.app_context():
            for uid, method in ((old, "guest"), (fresh, "guest"), (real, "password")):
                u = db.session.get(User, uid)
                u.signup_method = method
                u.created_at = long_ago if uid != fresh else datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.get(User, real).created_at = long_ago
            db.session.commit()
            self.assertEqual(_purge_stale_guests(), 1)
            self.assertIsNone(db.session.get(User, old))
            self.assertIsNotNone(db.session.get(User, fresh))
            self.assertIsNotNone(db.session.get(User, real))


if __name__ == "__main__":
    unittest.main()
