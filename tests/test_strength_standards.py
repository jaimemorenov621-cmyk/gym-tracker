"""Estándares de fuerza (app/strength_standards.py) y sus logros.

Uso:
    python -m unittest tests.test_strength_standards
"""
import unittest
from datetime import datetime, timedelta

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app import achievements
from app import strength_standards as std
from app.models import BodyWeightEntry, SetEntry, User, UserAchievement, Workout

LB = 0.45359237


class TableTests(unittest.TestCase):
    """Guardas contra errores de copia de las tablas (en libras, ExRx)."""

    def test_spot_checks_against_the_source(self):
        # Filas copiadas a mano de la fuente al escribir este test.
        self.assertEqual(std.TABLES_LB[("hombre", "bench")][5], (130, 165, 200, 275, 345))   # 181 lb
        self.assertEqual(std.TABLES_LB[("mujer", "squat")][5], (65, 120, 140, 185, 230))     # 148 lb
        self.assertEqual(std.TABLES_LB[("hombre", "deadlift")][-1], (185, 340, 390, 510, 615))  # 320+
        self.assertEqual(std.TABLES_LB[("mujer", "press")][0], (30, 40, 50, 65, 85))         # 97 lb

    def test_levels_increase_and_heavier_classes_never_need_less(self):
        for key, rows in std.TABLES_LB.items():
            for row in rows:
                self.assertEqual(list(row), sorted(row), (key, row))
            for level in range(5):
                column = [row[level] for row in rows]
                self.assertEqual(column, sorted(column), (key, level))

    def test_conversion_to_kg_is_exact(self):
        limit, *ths = std.TABLES[("hombre", "bench")][5]
        self.assertAlmostEqual(limit, 181 * LB)
        self.assertAlmostEqual(ths[2], 200 * LB)
        self.assertIsNone(std.TABLES[("hombre", "bench")][-1][0])


class LiftDetectionTests(unittest.TestCase):
    def test_recognises_the_barbell_lifts(self):
        cases = {
            "press de banca": "bench", "Press Banca": "bench", "bench press": "bench", "banca": "bench",
            "press banca plano": "bench", "sentadilla": "squat", "sentadilla con barra": "squat",
            "back squat": "squat", "peso muerto": "deadlift", "peso muerto sumo": "deadlift",
            "Deadlift": "deadlift", "press militar": "press", "Standing Military Press": "press",
        }
        for name, lift in cases.items():
            self.assertEqual(std.lift_of(name), lift, name)

    def test_ignores_variants_with_other_loads(self):
        for name in (
            "press de banca inclinado", "press banca declinado", "press banca con mancuernas",
            "dumbbell bench press", "press de banca en multipower", "fondos en banca",
            "press banca agarre cerrado", "sentadilla búlgara", "sentadilla hack", "sentadilla frontal",
            "goblet squat", "smith machine squat", "prensa", "peso muerto rumano", "romanian deadlift",
            "peso muerto piernas rígidas", "trap bar deadlift", "press militar sentado",
            "press militar con mancuernas", "push press", "press inclinado",
        ):
            self.assertIsNone(std.lift_of(name), name)


class ThresholdTests(unittest.TestCase):
    def kg(self, *lb):
        return [v * LB for v in lb]

    def assertAllAlmostEqual(self, a, b):
        self.assertEqual(len(a), len(b))
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y)

    def test_exact_class_uses_its_row(self):
        self.assertAllAlmostEqual(std.thresholds("hombre", "bench", 181 * LB), self.kg(130, 165, 200, 275, 345))

    def test_interpolates_between_classes(self):
        lo, hi = 181 * LB, 198 * LB
        mid = std.thresholds("hombre", "bench", (lo + hi) / 2)
        self.assertAllAlmostEqual(mid, self.kg(132.5, 170, 207.5, 282.5, 352.5))

    def test_never_extrapolates(self):
        self.assertAllAlmostEqual(std.thresholds("hombre", "squat", 40), std.thresholds("hombre", "squat", 114 * LB))
        self.assertAllAlmostEqual(std.thresholds("hombre", "squat", 319 * LB), self.kg(145, 270, 325, 445, 580))
        self.assertAllAlmostEqual(std.thresholds("hombre", "squat", 170), self.kg(150, 275, 330, 455, 595))
        self.assertAllAlmostEqual(std.thresholds("mujer", "squat", 95), self.kg(85, 160, 185, 240, 305))

    def test_needs_sex_and_weight(self):
        self.assertIsNone(std.thresholds(None, "bench", 80))
        self.assertIsNone(std.thresholds("hombre", "bench", None))

    def test_level_index(self):
        ths = [60.0, 75.0, 90.0, 125.0, 157.5]
        self.assertEqual(std.level_index(50, ths), -1)
        self.assertEqual(std.level_index(60, ths), 0)
        self.assertEqual(std.level_index(124.9, ths), 2)
        self.assertEqual(std.level_index(200, ths), 4)


class DotsTests(unittest.TestCase):
    def test_formula_and_clamping(self):
        # 600 kg de total con 100 kg de peso (hombre): 500 / poly(100) * 600.
        poly = -0.0000010930 * 100 ** 4 + 0.0007391293 * 100 ** 3 - 0.1918759221 * 100 ** 2 + 24.0900756 * 100 - 307.75076
        self.assertAlmostEqual(std.dots(600, 100, "hombre"), 600 * 500 / poly)
        self.assertAlmostEqual(std.dots(300, 30, "mujer"), std.dots(300, 40, "mujer"))  # límite inferior
        self.assertIsNone(std.dots(300, 70, None))

    def test_heavier_lifter_needs_more_total(self):
        self.assertGreater(std.dots(500, 70, "hombre"), std.dots(500, 100, "hombre"))


class _LifterCase(DbTestCase):
    T0 = datetime(2026, 1, 10, 18, 0)

    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")

    def set_sex(self, sex):
        with app.app_context():
            db.session.get(User, self.uid).sex = sex
            db.session.commit()

    def weigh(self, kg, when):
        with app.app_context():
            db.session.add(BodyWeightEntry(user_id=self.uid, weight=kg, timestamp=when))
            db.session.commit()

    def lift(self, exercise, weight, when, reps=1, rir=0, set_type="normal", completed=True):
        """Con reps=1 y RIR 0 el 1RM estimado es exactamente `weight`."""
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=when, performance_rating=7)
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise=exercise, weight=weight, reps=reps, rir=rir,
                                    set_type=set_type, completed=completed))
            db.session.commit()

    def profile(self, now=None):
        with app.app_context():
            return std.strength_profile(db.session.get(User, self.uid), now=now or self.T0 + timedelta(days=60))


class ProfileTests(_LifterCase):
    def test_without_sex_or_weight_there_is_no_level(self):
        self.lift("press de banca", 90, self.T0)
        p = self.profile()
        self.assertEqual(p["missing"], ["sexo", "peso corporal"])
        self.assertIsNone(p["lifts"]["bench"]["reached"])
        self.assertIsNone(p["global"])
        self.assertTrue(p["lifts"]["bench"]["has_data"])

    def test_level_uses_body_weight_at_the_time(self):
        self.set_sex("hombre")
        self.weigh(80, self.T0 - timedelta(days=5))
        self.lift("press de banca", 90, self.T0)
        # A 80 kg el umbral de Intermedio es ≈ 88,8 kg (entre 165 y 181 lb).
        self.assertAlmostEqual(std.thresholds("hombre", "bench", 80)[2], 88.75, places=1)
        self.assertEqual(self.profile()["lifts"]["bench"]["reached"], 2)
        # Engordar después no le quita el nivel ya alcanzado...
        self.weigh(100, self.T0 + timedelta(days=10))
        bench = self.profile()["lifts"]["bench"]
        self.assertEqual(bench["reached"], 2)
        self.assertEqual(bench["reached_label"], "Intermedio")
        # ...pero el siguiente nivel se mide con el peso actual (Avanzado a 100 kg).
        advanced_now = std.thresholds("hombre", "bench", 100)[3]
        self.assertEqual(bench["next_label"], "Avanzado")
        self.assertAlmostEqual(bench["next_kg"], advanced_now)
        self.assertAlmostEqual(bench["missing_kg"], advanced_now - 90)

    def test_weight_shortly_after_the_session_is_accepted(self):
        self.set_sex("hombre")
        self.lift("press de banca", 90, self.T0)
        self.weigh(80, self.T0 + timedelta(days=20))
        self.assertEqual(self.profile()["lifts"]["bench"]["reached"], 2)

    def test_weight_long_after_the_session_does_not_count(self):
        self.set_sex("hombre")
        self.lift("press de banca", 90, self.T0)
        self.weigh(80, self.T0 + timedelta(days=45))
        self.assertIsNone(self.profile()["lifts"]["bench"]["reached"])

    def test_high_reps_warmups_and_variants_are_not_valid(self):
        self.set_sex("hombre")
        self.weigh(80, self.T0 - timedelta(days=1))
        self.lift("press de banca", 80, self.T0, reps=12, rir=0)                       # > 10 reps efectivas
        self.lift("press de banca", 80, self.T0 + timedelta(days=1), reps=8, rir=3)    # 11 efectivas
        self.lift("press de banca", 120, self.T0 + timedelta(days=2), set_type="calentamiento")
        self.lift("press de banca inclinado", 120, self.T0 + timedelta(days=3))
        bench = self.profile()["lifts"]["bench"]
        self.assertFalse(bench["has_data"])
        self.assertIsNone(bench["reached"])

    def test_below_beginner_is_a_result_not_a_default(self):
        self.set_sex("mujer")
        self.weigh(60, self.T0 - timedelta(days=1))
        self.lift("sentadilla", 20, self.T0)  # umbral de Principiante a 60 kg: ≈ 27,3
        squat = self.profile()["lifts"]["squat"]
        self.assertEqual(squat["reached"], -1)
        self.assertEqual(squat["reached_label"], "Por debajo de Principiante")
        self.assertEqual(squat["next_label"], "Principiante")

    def test_global_is_the_lowest_of_the_big_three(self):
        self.set_sex("hombre")
        self.weigh(82, self.T0 - timedelta(days=1))
        self.lift("press de banca", 125, self.T0)   # Avanzado (≈ 124,3 kg a 82 kg)
        self.lift("sentadilla", 125, self.T0)       # Intermedio (≈ 122 kg)
        p = self.profile()
        self.assertIsNone(p["global"])
        self.assertEqual(p["missing_lifts"], ["Peso muerto"])
        self.lift("peso muerto", 260, self.T0)      # Élite (≈ 249 kg)
        p = self.profile()
        self.assertEqual(p["global"], 2)
        self.assertEqual(p["global_label"], "Intermedio")
        self.assertIsNotNone(p["dots"])

    def test_current_best_only_looks_at_the_last_year(self):
        self.set_sex("hombre")
        self.weigh(82, self.T0 - timedelta(days=1))
        self.lift("press de banca", 100, self.T0)
        bench = self.profile(now=self.T0 + timedelta(days=400))["lifts"]["bench"]
        self.assertIsNone(bench["best_e1rm"])
        self.assertEqual(bench["best_e1rm_all"], 100)
        self.assertEqual(bench["reached"], 2)  # lo alcanzado no caduca


class StandardsAchievementTests(_LifterCase):
    def unlocked(self):
        with app.app_context():
            achievements.evaluate(db.session.get(User, self.uid))
            return set(db.session.scalars(sa.select(UserAchievement.code).where(UserAchievement.user_id == self.uid)))

    def test_levels_plates_and_big_three(self):
        self.set_sex("hombre")
        self.weigh(82, self.T0 - timedelta(days=1))
        self.lift("press de banca", 100, self.T0)
        self.lift("sentadilla", 125, self.T0)
        self.lift("peso muerto", 145, self.T0)
        codes = self.unlocked()
        self.assertTrue({"std_bench_principiante", "std_bench_novato", "std_bench_intermedio"} <= codes)
        self.assertNotIn("std_bench_avanzado", codes)
        self.assertIn("std_big3_intermedio", codes)
        self.assertIn("plates_bench_60", codes)
        self.assertIn("plates_bench_100", codes)
        self.assertNotIn("plates_bench_140", codes)
        self.assertIn("plates_deadlift_140", codes)

    def test_relative_strength_ignores_variants(self):
        self.set_sex("hombre")
        self.weigh(80, self.T0 - timedelta(days=1))
        self.lift("press de banca inclinado", 100, self.T0)
        self.assertNotIn("bench_bw", self.unlocked())
        self.lift("press de banca", 82, self.T0 + timedelta(days=1))
        self.assertIn("bench_bw", self.unlocked())

    def test_unlocked_level_survives_gaining_weight(self):
        self.set_sex("hombre")
        self.weigh(80, self.T0 - timedelta(days=1))
        self.lift("press de banca", 90, self.T0)
        self.assertIn("std_bench_intermedio", self.unlocked())
        self.weigh(110, self.T0 + timedelta(days=5))
        self.assertIn("std_bench_intermedio", self.unlocked())


class ProgressPageTests(DbTestCase):
    def test_card_shows_what_is_missing(self):
        uid = self.make_user("atleta")
        self.login(uid)
        html = self.client.get("/progress").get_data(as_text=True)
        self.assertIn("Estándares de fuerza", html)
        self.assertIn("Para darte un nivel falta", html)
        self.assertIn("exrx.net", html)
        # El bloque profesional va primero: índice de fuerza, estándares y peso.
        self.assertLess(html.index('id="fuerza"'), html.index('id="estandares"'))
        self.assertLess(html.index('id="estandares"'), html.index("progress-weight"))


if __name__ == "__main__":
    unittest.main()
