import unittest
from datetime import datetime, timedelta

from tests.dbcase import DbTestCase
from app import app, db, bodyweight as bw
from app.models import BodyWeightEntry, User

NOW = datetime(2026, 10, 4, 9, 0)


def series(start_kg, kg_per_week, days=28, every=3, noise=()):
    out = []
    for i, d in enumerate(range(days, -1, -every)):
        kg = start_kg + kg_per_week * (days - d) / 7 + (noise[i % len(noise)] if noise else 0)
        out.append((NOW - timedelta(days=d), kg))
    return out


class RateTests(unittest.TestCase):
    def test_rate_is_a_trend_not_two_points(self):
        rate = bw.weekly_rate(series(80, 0.4, noise=(0.6, -0.5, 0.3, -0.4)), NOW)
        self.assertAlmostEqual(rate["kg_week"], 0.4, delta=0.15)
        self.assertAlmostEqual(rate["pct_week"], 100 * rate["kg_week"] / 80.8, delta=0.05)

    def test_needs_enough_weigh_ins(self):
        self.assertIsNone(bw.weekly_rate(series(80, 0.4, days=6, every=2), NOW))   # menos de 2 semanas
        self.assertIsNone(bw.weekly_rate(series(80, 0.4, days=28, every=14), NOW))  # 3 pesos

    def test_assessment_per_phase(self):
        def status(kg_week, phase):
            return bw.assessment(bw.weekly_rate(series(80, kg_week), NOW), phase)["status"]
        self.assertEqual(status(0.3, "volumen"), "ok")        # ~0,37 %/sem
        self.assertEqual(status(0.8, "volumen"), "fast")      # ~1 %/sem
        self.assertEqual(status(0.1, "volumen"), "slow")
        self.assertEqual(status(-0.2, "volumen"), "wrong")
        self.assertEqual(status(-0.6, "definicion"), "ok")    # ~-0,75 %/sem
        self.assertEqual(status(-1.2, "definicion"), "fast")
        self.assertEqual(status(-0.2, "definicion"), "slow")
        self.assertEqual(status(0.3, "definicion"), "wrong")
        self.assertEqual(status(0.05, "recomposicion"), "ok")
        self.assertEqual(status(0.6, "recomposicion"), "fast")
        self.assertEqual(status(0.3, None), "none")           # sin fase: solo el ritmo


class PhaseRouteTests(DbTestCase):
    def test_choose_and_clear_phase(self):
        uid = self.make_user("peso")
        now = datetime.utcnow()
        with app.app_context():
            for d in range(28, -1, -2):  # bajando 0,6 kg/semana (~0,75 %): buen ritmo de definición
                db.session.add(BodyWeightEntry(user_id=uid, weight=80 - 0.6 * (28 - d) / 7, timestamp=now - timedelta(days=d)))
            db.session.commit()
        self.login(uid)
        self.client.post("/weight/fase", data={"phase": "definicion"})
        with app.app_context():
            self.assertEqual(db.session.get(User, uid).body_phase, "definicion")
        html = self.client.get("/weight").get_data(as_text=True)
        self.assertIn("Tu ritmo", html)
        self.assertIn("ritmo recomendado", html)
        self.client.post("/weight/fase", data={"phase": "inventada"})  # se ignora
        with app.app_context():
            self.assertEqual(db.session.get(User, uid).body_phase, "definicion")
        self.client.post("/weight/fase", data={"phase": ""})  # quitar la fase
        with app.app_context():
            self.assertIsNone(db.session.get(User, uid).body_phase)


class LevelTests(unittest.TestCase):
    def test_ranges_depend_on_level(self):
        self.assertEqual(bw.level_for_tier(None), "principiante")
        self.assertEqual(bw.level_for_tier(3), "principiante")   # Oro
        self.assertEqual(bw.level_for_tier(4), "intermedio")     # Platino
        self.assertEqual(bw.level_for_tier(6), "avanzado")       # Esmeralda
        rate = bw.weekly_rate(series(80, 0.32), NOW)             # ~0,4 %/sem
        self.assertEqual(bw.assessment(rate, "volumen", "principiante")["status"], "ok")
        self.assertEqual(bw.assessment(rate, "volumen", "avanzado")["status"], "fast")
        cut = bw.weekly_rate(series(80, -0.75), NOW)             # ~-0,95 %/sem
        self.assertEqual(bw.assessment(cut, "definicion", "principiante")["status"], "ok")
        self.assertEqual(bw.assessment(cut, "definicion", "avanzado")["status"], "fast")
        self.assertIn("0,1-0,25 %", bw.summary(series(80, 0.1), "volumen", NOW, tier=7)["target"])
