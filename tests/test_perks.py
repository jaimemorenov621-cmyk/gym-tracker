"""Ventajas por nivel (app/perks.py).

Uso:
    python -m unittest tests.test_perks
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app import perks, progression
from app.models import AiAnalysis, SetEntry, User, Workout


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PerkListTests(unittest.TestCase):
    def test_unlock_flags_and_ai_allowance(self):
        rows = perks.perk_list(10)
        self.assertTrue(all(r["unlocked"] == (r["level"] <= 10) for r in rows))
        self.assertEqual([r["level"] for r in rows], sorted(r["level"] for r in rows))
        self.assertEqual(perks.ai_per_week(19), 1)
        self.assertEqual(perks.ai_per_week(20), 2)
        self.assertEqual([d["key"] for d in perks.unlocked(perks.SHARE_DESIGNS, 5)], ["clasico", "medianoche"])


class _PerkCase(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        self.login(self.uid)

    def set_level(self, level):
        with app.app_context():
            db.session.execute(sa.update(User).where(User.id == self.uid)
                               .values(xp_total=progression.xp_to_reach(level))
                               .execution_options(synchronize_session=False))
            db.session.commit()


class AccentTests(_PerkCase):
    def test_unlocked_accents_are_exposed_to_the_page(self):
        html = self.client.get("/settings").get_data(as_text=True)
        self.assertIn('data-accents="morado"', html)
        self.assertIn("Nivel 10", html)
        self.set_level(15)
        html = self.client.get("/settings").get_data(as_text=True)
        self.assertIn('data-accents="morado,azul,verde"', html)
        self.assertIn("Nivel 25", html)  # naranja sigue bloqueado

    def test_landing_never_gets_accents(self):
        self.client.get("/logout")
        self.assertIn('<html lang="es">', self.client.get("/").get_data(as_text=True))


class ShareTests(_PerkCase):
    def add_set(self):
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=now())
            db.session.add(w)
            db.session.flush()
            s = SetEntry(workout_id=w.id, exercise="sentadilla", weight=100, reps=5, completed=True)
            db.session.add(s)
            db.session.commit()
            return s.id

    def test_designs_and_badge_depend_on_level(self):
        sid = self.add_set()
        data = self.client.get(f"/set/{sid}/share").get_json()
        self.assertEqual([d["key"] for d in data["designs"]], ["clasico"])
        self.assertIsNone(data["badge"])
        self.set_level(perks.BADGE_LEVEL)
        data = self.client.get(f"/set/{sid}/share").get_json()
        self.assertEqual(data["badge"], f"NIVEL {perks.BADGE_LEVEL}")  # sin rango: faltan datos
        self.assertIn("medianoche", [d["key"] for d in data["designs"]])


class AiAllowanceTests(_PerkCase):
    def add_analysis(self, days_ago):
        with app.app_context():
            db.session.add(AiAnalysis(user_id=self.uid, content=json.dumps({}), created_at=now() - timedelta(days=days_ago)))
            db.session.commit()

    def blocking(self, allowance):
        with app.app_context():
            from app.routes import ai_analysis_blocking

            return ai_analysis_blocking(self.uid, allowance)

    def test_window_and_allowance(self):
        self.assertIsNone(self.blocking(1))
        self.add_analysis(3)
        self.assertIsNotNone(self.blocking(1))
        self.assertIsNone(self.blocking(2))
        self.add_analysis(1)
        self.assertIsNotNone(self.blocking(2))
        self.add_analysis(10)  # fuera de la ventana de 7 días: no cuenta
        b = self.blocking(2)
        self.assertGreater(b.created_at, now() - timedelta(days=7))

    def test_level_20_can_generate_a_second_analysis(self):
        with app.app_context():
            for i in range(3):
                db.session.add(Workout(user_id=self.uid, timestamp=now() - timedelta(days=i)))
            db.session.commit()
        self.add_analysis(2)
        with mock.patch("app.routes.generate_ai_analysis", return_value=json.dumps({"ok": 1})):
            self.client.post("/ai/analyze")
            with app.app_context():
                self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AiAnalysis)), 1)
            self.set_level(perks.AI_EXTRA_LEVEL)
            self.client.post("/ai/analyze")
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AiAnalysis)), 2)


class LevelPageTests(_PerkCase):
    def test_level_page_lists_the_perks(self):
        html = self.client.get("/nivel").get_data(as_text=True)
        self.assertIn("Ventajas por nivel", html)
        self.assertIn("Un análisis de IA más por semana", html)


if __name__ == "__main__":
    unittest.main()
