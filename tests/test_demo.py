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
