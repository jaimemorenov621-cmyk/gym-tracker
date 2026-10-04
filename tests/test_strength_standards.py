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
            "goblet squat", "prensa", "peso muerto rumano con mancuernas", "romanian deadlift dumbbell",
            "sentadilla búlgara en smith", "peso muerto rumano a una pierna",
            "peso muerto piernas rígidas", "trap bar deadlift", "press militar sentado",
            "press militar con mancuernas", "push press", "press inclinado",
        ):
            self.assertIsNone(std.lift_of(name), name)


    def test_smith_squat_and_rdl_have_their_own_table(self):
        cases = {
            "sentadilla en smith": "smith_squat", "Sentadilla en máquina Smith": "smith_squat",
            "smith machine squat": "smith_squat", "sentadilla multipower": "smith_squat",
            "peso muerto rumano": "rdl", "Peso Muerto Rumano Con Barra": "rdl", "romanian deadlift": "rdl",
            "RDL": "rdl",
        }
        for name, lift in cases.items():
            self.assertEqual(std.lift_of(name), lift, name)
        self.assertEqual(std.thresholds("hombre", "smith_squat", 80), [57, 84, 118, 158, 202])
        self.assertEqual(std.thresholds("mujer", "rdl", 60), [31, 47, 67, 90, 116])

    def test_smith_row_uses_the_barbell_row_table_as_approximation(self):
        for name in ("remo en smith", "Remo en máquina Smith", "smith machine row", "remo multipower"):
            self.assertEqual(std.lift_of(name), "smith_row", name)
        for name in ("remo al mentón en smith", "remo invertido en smith", "remo en smith a una mano"):
            self.assertIsNone(std.lift_of(name), name)
        self.assertEqual(std.thresholds("hombre", "smith_row", 80), std.thresholds("hombre", "row", 80))
        self.assertIn("smith_row", std.APPROX_TABLE)
        self.assertIn("smith_row", std.BASIC_SOURCES["row"])


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


class RankMathTests(unittest.TestCase):
    THS = [60.0, 75.0, 90.0, 125.0, 157.5]

    def test_score_is_continuous_along_the_table(self):
        sc = std.strength_score
        self.assertAlmostEqual(sc(30, self.THS), -0.5)
        self.assertAlmostEqual(sc(60, self.THS), 0)
        self.assertAlmostEqual(sc(82.5, self.THS), 1.5)
        self.assertAlmostEqual(sc(157.5, self.THS), 4)
        self.assertAlmostEqual(sc(190, self.THS), 5)  # un tramo (32,5 kg) por encima de Élite

    def test_kg_for_score_is_the_inverse(self):
        for score in (-0.7, 0, 0.4, 1.5, 2.99, 3.2, 4.6):
            self.assertAlmostEqual(std.strength_score(std.kg_for_score(score, self.THS), self.THS), score)

    def test_ranks_and_divisions(self):
        label = lambda x: std.rank_for(x)["label"]
        self.assertEqual(label(-0.5), "Hierro II")
        self.assertEqual(label(0), "Bronce I")
        self.assertEqual(label(0.34), "Bronce II")
        self.assertEqual(label(2.2), "Oro II")          # Intermedio
        self.assertEqual(label(2.7), "Platino II")      # Intermedio alto
        self.assertEqual(label(3.1), "Diamante I")      # Avanzado reciente
        self.assertEqual(label(3.9), "Esmeralda III")   # Avanzado consolidado
        self.assertEqual(label(4), "Campeón I")         # Élite
        self.assertEqual(label(6.5), "Campeón III")
        self.assertEqual(label(7), "Titán")
        self.assertEqual(std.next_rank_label(std.rank_for(2.7)), "Platino III")
        self.assertEqual(std.next_rank_label(std.rank_for(3.9)), "Campeón I")
        self.assertEqual(std.next_rank_label(std.rank_for(6.9)), "Titán")
        self.assertIsNone(std.next_rank_label(std.rank_for(8)))

    def test_next_score_is_the_next_division(self):
        for score in (-0.7, 0.2, 2.1, 2.6, 3.4, 3.6, 4.5):
            r = std.rank_for(score)
            nxt = std.rank_for(r["next_score"] + 1e-9)
            self.assertEqual(nxt["label"], std.next_rank_label(r), score)

    def test_titan_is_around_the_world_record(self):
        # Banca, hombre de 82 kg: ExRx da un récord mundial de 556 lb (≈ 252 kg).
        ths = std.thresholds("hombre", "bench", 82)
        self.assertAlmostEqual(std.kg_for_score(7, ths), 252, delta=6)


class RankProfileTests(_LifterCase):
    def setUp(self):
        super().setUp()
        self.set_sex("hombre")
        self.weigh(82, self.T0 - timedelta(days=1))

    def test_global_rank_is_the_average_so_any_improvement_counts(self):
        self.lift("sentadilla", 200, self.T0)
        self.lift("press de banca", 80, self.T0)
        self.lift("peso muerto", 180, self.T0)
        before = self.profile()["global_rank"]
        # Mejorar la sentadilla (que NO es el más flojo) también sube el global.
        self.lift("sentadilla", 215, self.T0 + timedelta(days=1))
        after_squat = self.profile()
        self.assertGreater(after_squat["lifts"]["squat"]["score"], 0)
        self.assertGreater(
            sum(after_squat["lifts"][l]["score"] for l in std.BIG_THREE),
            sum(std.strength_score(e, std.thresholds("hombre", l, 82)) for l, e in
                (("squat", 200), ("bench", 80), ("deadlift", 180))),
        )
        self.assertIsNotNone(before)
        self.assertEqual(after_squat["lagging"], "Press de banca")  # avisa del desequilibrio

    def test_rank_drops_after_90_days_without_the_lift_but_peak_stays(self):
        for lift in ("press de banca", "sentadilla", "peso muerto"):
            self.lift(lift, 140, self.T0)
        p = self.profile(now=self.T0 + timedelta(days=100))
        bench = p["lifts"]["bench"]
        self.assertIsNone(bench["rank"])
        self.assertTrue(bench["rank_stale"])
        self.assertIsNotNone(bench["rank_peak"])
        self.assertIsNone(p["global_rank"])
        self.assertEqual(p["rank_missing"], list(std.BASIC_LABELS.values()))

    def test_next_division_target(self):
        self.lift("press de banca", 100, self.T0)
        bench = self.profile()["lifts"]["bench"]
        ths = std.thresholds("hombre", "bench", 82)
        self.assertEqual(bench["rank"]["name"], "Oro")
        self.assertAlmostEqual(bench["rank_missing_kg"], bench["rank_next_kg"] - 100)
        self.assertAlmostEqual(std.strength_score(bench["rank_next_kg"], ths), bench["rank"]["next_score"])


class NewBasicsTests(unittest.TestCase):
    def test_detection(self):
        cases = {
            "remo con barra": "row", "Barbell Row": "row", "remo pendlay": "row",
            "dominadas": "pullup", "dominadas lastradas": "pullup", "pull-ups": "pullup",
            "jalón al pecho": "pulldown", "Lat Pulldown": "pulldown", "jalon al pecho en maquina": "pulldown",
        }
        for name, lift in cases.items():
            self.assertEqual(std.lift_of(name), lift, name)
        for name in ("remo con mancuerna", "remo en polea baja", "remo al mentón", "remo en barra T",
                     "dominadas asistidas", "jalón al pecho unilateral", "pulldown brazos rectos"):
            self.assertIsNone(std.lift_of(name), name)

    def test_strengthlevel_thresholds(self):
        self.assertEqual(std.thresholds("hombre", "row", 80), [48, 66, 88, 114, 141])
        mid = std.thresholds("hombre", "row", 82.5)
        self.assertAlmostEqual(mid[2], (88 + 93) / 2)
        self.assertEqual(std.thresholds("hombre", "row", 200), std.thresholds("hombre", "row", 140))  # sin extrapolar
        # Dominadas: la tabla es de lastre; los umbrales son de carga total.
        self.assertEqual(std.thresholds("hombre", "pullup", 80), [78, 94, 113, 134, 155])
        self.assertEqual(std.thresholds("mujer", "pullup", 60), [44, 56, 69, 83, 98])


class PullupAndGlobalTests(_LifterCase):
    def setUp(self):
        super().setUp()
        self.set_sex("hombre")
        self.weigh(80, self.T0 - timedelta(days=1))

    def test_bodyweight_pullups_count_with_your_weight(self):
        # 8 dominadas sin lastre a RIR 2: carga total 80 / 0,739 ≈ 108,3 kg,
        # es decir, un lastre equivalente de ≈ 28,3 kg -> entre Novato (+14) e Intermedio (+33).
        self.lift("dominadas", 0, self.T0, reps=8, rir=2)
        pull = self.profile()["lifts"]["pullup"]
        self.assertAlmostEqual(pull["rank_e1rm"], 80 / 0.739 - 80, places=3)
        self.assertEqual(pull["reached"], 1)
        self.assertEqual(pull["rank"]["name"], "Plata")
        self.assertIsNone(pull["ratio"])

    def test_vertical_pull_is_the_best_of_pullups_and_pulldown(self):
        self.lift("press de banca", 90, self.T0)
        self.lift("sentadilla", 120, self.T0)
        self.lift("jalón al pecho", 60, self.T0)
        p = self.profile()
        self.assertEqual(p["basics_counted"], 3)  # banca, sentadilla y tirón vertical
        self.assertIsNotNone(p["global_rank"])
        low = p["global_rank"]
        self.lift("dominadas", 30, self.T0 + timedelta(days=1), reps=1, rir=0)  # mucho mejor que el jalón
        self.assertGreater(self.profile()["global_rank"]["tier"] * 3 + self.profile()["global_rank"]["division"],
                           low["tier"] * 3 + low["division"])

    def test_smith_squat_and_rdl_fill_their_basic(self):
        self.lift("press de banca", 90, self.T0)
        self.lift("sentadilla en smith", 110, self.T0)
        self.lift("peso muerto rumano", 120, self.T0)
        p = self.profile()
        self.assertEqual(p["basics_counted"], 3)  # banca, sentadilla (Smith) y peso muerto (rumano)
        self.assertIsNotNone(p["global_rank"])
        self.assertNotIn("Sentadilla (libre o en Smith)", p["rank_missing"])
        self.assertIsNotNone(p["lifts"]["smith_squat"]["rank"])
        # Si además hace sentadilla libre, cuenta la mejor de las dos.
        best = max(p["lifts"]["smith_squat"]["score"], 0)
        self.lift("sentadilla", 200, self.T0 + timedelta(days=1))
        self.assertGreater(self.profile()["lifts"]["squat"]["score"], best)

    def test_global_needs_three_basics(self):
        self.lift("press de banca", 90, self.T0)
        self.lift("sentadilla", 120, self.T0)
        p = self.profile()
        self.assertEqual(p["basics_counted"], 2)
        self.assertIsNone(p["global_rank"])


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


class ProgressTextTests(unittest.TestCase):
    def test_unearned_progress_never_looks_complete(self):
        a = achievements.BY_CODE["bench_15bw"]
        with app.app_context():
            self.assertEqual(achievements.progress_text(a, 1.497, False), "1,49 / 1,5 × tu peso")
            self.assertEqual(achievements.progress_text(a, 1.5, True), "1,5 / 1,5 × tu peso")
            hours = achievements.BY_CODE["hours_50"]
            self.assertEqual(achievements.progress_text(hours, 49.96, False), "49,9 / 50 h")


class RankPageTests(DbTestCase):
    def test_rank_tab_shows_what_is_missing_with_buttons(self):
        uid = self.make_user("atleta")
        self.login(uid)
        html = self.client.get("/rango").get_data(as_text=True)
        self.assertIn("Por levantamiento", html)
        self.assertIn("Aún sin rango", html)
        self.assertIn("Para darte un rango falta", html)
        self.assertIn('class="btn-inline" href="/settings"', html)   # botones, no enlaces sueltos
        self.assertIn("exrx.net", html)
        # Progreso ya no lleva la tarjeta de rango (pestaña propia) y el orden es fuerza -> volumen -> peso.
        progress = self.client.get("/progress").get_data(as_text=True)
        self.assertNotIn('id="estandares"', progress)
        self.assertLess(progress.index('id="fuerza"'), progress.index('id="volumen"'))
        self.assertLess(progress.index('id="volumen"'), progress.index("progress-weight"))


class RankCelebrationTests(_LifterCase):
    def setUp(self):
        super().setUp()
        self.set_sex("hombre")
        self.weigh(80, datetime.now() - timedelta(days=30))
        recent = datetime.now() - timedelta(days=3)
        for ex, kg in (("press de banca", 90), ("sentadilla", 120), ("peso muerto", 150)):
            self.lift(ex, kg, recent)
        self.login(self.uid)

    def test_intro_once_then_celebrates_only_going_up(self):
        html = self.client.get("/index").get_data(as_text=True)
        self.assertIn("rankCelebration", html)
        self.assertIn("Tu rango de fuerza", html)                       # presentación
        self.assertNotIn('id="rankCelebration"', self.client.get("/index").get_data(as_text=True))
        self.lift("peso muerto", 260, datetime.now() - timedelta(days=1))
        html = self.client.get("/index").get_data(as_text=True)
        self.assertIn("¡Has subido de rango!", html)
        with app.app_context():
            u = db.session.get(User, self.uid)
            u.rank_seen = 99  # como si viniera de un rango más alto: bajar no se anuncia
            db.session.commit()
        self.assertNotIn('id="rankCelebration"', self.client.get("/index").get_data(as_text=True))

    def test_live_rank_up_while_training(self):
        self.client.get("/index")  # presentación hecha: rank_seen anotado
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=datetime.now() - timedelta(hours=1))
            db.session.add(w)
            db.session.flush()
            s = SetEntry(workout_id=w.id, exercise="peso muerto", weight=270, reps=1, rir=0)
            db.session.add(s)
            db.session.commit()
            sid = s.id
        data = self.client.put(f"/set/{sid}", json={"completed": True}).get_json()
        self.assertTrue(data["is_pr"])
        self.assertIn("rank_up", data)
        self.assertIn(data["rank_up"]["file"], ("titan",) + tuple(f"{k}-{d}" for k in std.RANK_KEYS for d in (1, 2, 3)))

    def test_rank_tab_has_showcase_and_animated_bar(self):
        html = self.client.get("/rango").get_data(as_text=True)
        self.assertIn("rank-showcase", html)
        self.assertIn("is-locked", html)
        self.assertIn('data-pct="', html)
        self.assertIn("rank_fx.js", html)
        self.assertIn("rankSplashData", self.client.get("/index").get_data(as_text=True) + self.client.get("/index").get_data(as_text=True))

if __name__ == "__main__":
    unittest.main()
