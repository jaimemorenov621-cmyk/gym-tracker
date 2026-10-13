"""Mis tarjetas (/tarjetas) y las tarjetas de rango y de logro.

Uso:
    python -m unittest tests.test_share_gallery
"""
from datetime import datetime, timedelta, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

from app import app, db
from app import achievements
from app.models import BodyWeightEntry, SetEntry, User, UserAchievement, Workout


class ShareGalleryTests(DbTestCase):
    NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        with app.app_context():
            u = db.session.get(User, self.uid)
            u.sex = "hombre"
            db.session.add(BodyWeightEntry(user_id=self.uid, weight=80, timestamp=self.NOW - timedelta(days=40)))
            db.session.commit()

    def lift(self, exercise, weight, days_ago, is_pr=True):
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=self.NOW - timedelta(days=days_ago), performance_rating=7)
            db.session.add(w)
            db.session.flush()
            s = SetEntry(workout_id=w.id, exercise=exercise, weight=weight, reps=1, rir=0, completed=True, is_pr=is_pr)
            db.session.add(s)
            db.session.commit()
            return s.id

    def test_gallery_lists_ranks_current_records_and_achievements(self):
        for ex, kg in (("press de banca", 100), ("sentadilla", 140), ("peso muerto", 180)):
            self.lift(ex, kg, 10)
        # Récord vigente = el último por FECHA, aunque se apuntara antes.
        newer = self.lift("press de banca", 105, 2)
        older = self.lift("press de banca", 90, 30)  # importado después: id mayor, fecha anterior
        code = achievements.ACHIEVEMENTS[0].code
        with app.app_context():
            db.session.add(UserAchievement(user_id=self.uid, code=code))
            db.session.commit()
        self.login(self.uid)
        html = self.client.get("/tarjetas").get_data(as_text=True)
        self.assertIn('data-kind="rank" data-key="global"', html)
        self.assertIn('data-kind="rank" data-key="bench"', html)
        self.assertIn(f'data-kind="record" data-key="{newer}"', html)
        self.assertNotIn(f'data-key="{older}"', html)
        self.assertIn(f'data-kind="achievement" data-key="{code}"', html)
        self.assertIn("Mis tarjetas", self.client.get("/rango").get_data(as_text=True))

    def test_rank_card(self):
        self.lift("press de banca", 100, 10)
        self.login(self.uid)
        data = self.client.get("/share/rank/bench").get_json()
        self.assertTrue(data["ok"])
        self.assertEqual((data["kind"], data["global"]), ("rank", False))
        self.assertTrue(data["emblem"] and data["label"])
        self.assertIn("1RM estimado 100", data["detail"])
        self.assertEqual(self.client.get("/share/rank/global").status_code, 404)  # 1 básico: sin rango global
        self.assertEqual(self.client.get("/share/rank/squat").status_code, 404)

    def test_achievement_card_only_when_unlocked(self):
        a = achievements.ACHIEVEMENTS[0]
        self.login(self.uid)
        self.assertEqual(self.client.get(f"/share/achievement/{a.code}").status_code, 404)
        self.assertEqual(self.client.get("/share/achievement/no-existe").status_code, 404)
        with app.app_context():
            db.session.add(UserAchievement(user_id=self.uid, code=a.code))
            db.session.commit()
        data = self.client.get(f"/share/achievement/{a.code}").get_json()
        self.assertEqual((data["kind"], data["emoji"], data["title"]), ("achievement", a.emoji, str(a.title)))
        self.assertTrue(data["designs"])
        # Otro usuario no puede compartir el logro de este.
        self.login(self.make_user("otro"))
        self.assertEqual(self.client.get(f"/share/achievement/{a.code}").status_code, 404)


if __name__ == "__main__":
    import unittest
    unittest.main()
