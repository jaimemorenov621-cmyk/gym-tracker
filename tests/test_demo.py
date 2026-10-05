"""flask seed-demo: cuenta de demostración con historial realista."""
import unittest

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db, progression, social, usage
from app.demo import seed_demo
from app.models import SetEntry, User, UserAchievement, Workout


class DemoSeedTests(DbTestCase):
    def test_short_history_gives_real_xp_achievements_and_friend(self):
        friend = self.make_user("amigo")
        with app.app_context():
            user, password = seed_demo("demo_test", weeks=6, friend="amigo")
            self.assertTrue(user.check_password(password))
            self.assertEqual(user.signup_method, "demo")
            self.assertGreater(db.session.scalar(
                sa.select(sa.func.count()).select_from(SetEntry).join(Workout).where(Workout.user_id == user.id)), 200)
            self.assertGreater(progression.current_xp(user.id), 1000)
            self.assertGreater(db.session.scalar(
                sa.select(sa.func.count()).select_from(UserAchievement).where(UserAchievement.user_id == user.id)), 5)
            self.assertTrue(social.are_friends(user.id, friend))
            self.assertEqual(usage.activity_summary()["total"], 1)  # la demo no cuenta como usuario real
        self.login(user.id)
        for url in ("/index", "/rango", "/nivel", "/progress", f"/atleta/{user.id}"):
            self.assertEqual(self.client.get(url).status_code, 200, url)


if __name__ == "__main__":
    unittest.main()


class DemoFromStatsPageTests(DbTestCase):
    def test_admin_creates_lists_and_deletes_a_demo_account(self):
        from unittest import mock
        from app import demo

        class InlineThread:  # el hilo en segundo plano, sin hilo (determinista)
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()

        admin = self.make_user("Jaime_309")
        self.login(admin)
        with mock.patch.object(demo.threading, "Thread", InlineThread):
            r = self.client.post("/landing/demo", data={"username": "VideoDemo", "password": "clave-larga", "rank": "campeon",
                                                         "lang": "es", "friend": "on"}, follow_redirects=True)
        html = r.get_data(as_text=True)
        self.assertIn("VideoDemo", html)
        with app.app_context():
            user = db.session.scalar(sa.select(User).where(User.username == "VideoDemo"))
            self.assertTrue(user.check_password("clave-larga"))
            self.assertTrue(social.are_friends(user.id, admin))
            uid = user.id
        self.client.post(f"/landing/demo/{uid}/delete")
        with app.app_context():
            self.assertIsNone(db.session.get(User, uid))
            # una cuenta normal no se puede borrar por esta vía
            self.client.post(f"/landing/demo/{admin}/delete")
            self.assertIsNotNone(db.session.get(User, admin))

    def test_only_admin(self):
        uid = self.make_user("cualquiera")
        self.login(uid)
        self.client.post("/landing/demo", data={"username": "x_demo", "password": "12345678"})
        with app.app_context():
            self.assertIsNone(db.session.scalar(sa.select(User).where(User.username == "x_demo")))
