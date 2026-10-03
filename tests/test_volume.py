"""Volumen semanal por grupo muscular (app/volume.py).

Uso:
    python -m unittest tests.test_volume
"""
import unittest
from collections import namedtuple
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

from app import app, db
from app import volume
from app.models import Exercise, SetEntry, Workout

MADRID = ZoneInfo("Europe/Madrid")
Row = namedtuple("Row", "weight reps rir rpe set_type completed")


class HardSetTests(unittest.TestCase):
    def hard(self, **kw):
        data = dict(weight=80, reps=8, rir=None, rpe=None, set_type="normal", completed=True)
        data.update(kw)
        with app.app_context():
            return volume.is_hard_set(Row(**data))

    def test_effort_rules(self):
        self.assertTrue(self.hard())                    # sin esfuerzo anotado: cuenta
        self.assertTrue(self.hard(rir=4))
        self.assertFalse(self.hard(rir=5))
        self.assertTrue(self.hard(rpe=6))
        self.assertFalse(self.hard(rpe=5))
        self.assertFalse(self.hard(set_type="calentamiento"))
        self.assertFalse(self.hard(completed=False))
        self.assertFalse(self.hard(weight=0))

    def test_status_bands(self):
        self.assertEqual([volume.status_for(x) for x in (0, 9.5, 10, 20, 20.5)], ["none", "low", "ok", "ok", "high"])


class WeeklyVolumeTests(DbTestCase):
    TODAY = date(2026, 3, 20)

    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        with app.app_context():
            db.session.add_all([
                Exercise(id="Bench_Press", name="Bench Press", name_es="Press de banca",
                         primary_muscles="chest", secondary_muscles="shoulders, triceps"),
                Exercise(id="Barbell_Curl", name="Barbell Curl", name_es="Curl con barra",
                         primary_muscles="biceps", secondary_muscles="forearms"),
            ])
            db.session.commit()

    def sets(self, exercise, n, days_ago, **kw):
        when = datetime.combine(self.TODAY - timedelta(days=days_ago), time(18, 0), tzinfo=MADRID)
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=when.astimezone(timezone.utc).replace(tzinfo=None))
            db.session.add(w)
            db.session.flush()
            for _ in range(n):
                db.session.add(SetEntry(workout_id=w.id, exercise=exercise, weight=60, reps=8, completed=True, **kw))
            db.session.commit()

    def report(self):
        with app.app_context():
            r = volume.weekly_volume(self.uid, today=self.TODAY)
        return r, {i["group"]: i for i in r["items"]}

    def test_primary_counts_one_and_secondary_half(self):
        self.sets("press de banca", 12, days_ago=1)
        r, g = self.report()
        self.assertEqual(g["pecho"]["last7"], 12)
        self.assertEqual(g["hombros"]["last7"], 6)
        self.assertEqual(g["triceps"]["last7"], 6)
        self.assertEqual(g["pecho"]["status"], "ok")
        self.assertEqual(g["hombros"]["status"], "low")
        self.assertEqual(r["status"]["antebrazos"], "none")  # todos los grupos tienen color en el mapa

    def test_rolling_week_and_four_week_average(self):
        self.sets("press de banca", 10, days_ago=0)   # hoy cuenta
        self.sets("press de banca", 10, days_ago=6)   # límite de los 7 días
        self.sets("press de banca", 10, days_ago=7)   # fuera de la semana, dentro del mes
        self.sets("press de banca", 10, days_ago=28)  # fuera de todo
        _, g = self.report()
        self.assertEqual(g["pecho"]["last7"], 20)
        self.assertEqual(g["pecho"]["avg4"], 30 / 4)

    def test_easy_warmup_and_unknown_sets(self):
        self.sets("press de banca", 3, days_ago=1, rir=6)
        self.sets("press de banca", 3, days_ago=1, set_type="calentamiento")
        self.sets("press de banca", 2, days_ago=1, rir=2)
        self.sets("remo raro", 4, days_ago=1)
        self.sets("curl con barra", 2, days_ago=1)
        r, g = self.report()
        self.assertEqual(g["pecho"]["last7"], 2)
        self.assertEqual(g["biceps"]["last7"], 2)
        self.assertEqual(g["antebrazos"]["last7"], 1)  # se muestra porque se ha entrenado
        self.assertEqual(r["unmapped"], 4)
        self.assertEqual(r["no_effort"], 6)  # 4 del remo + 2 del curl

    def test_progress_page_shows_the_card_with_the_sources(self):
        self.sets("press de banca", 12, days_ago=0)
        self.login(self.uid)
        html = self.client.get("/progress").get_data(as_text=True)
        self.assertIn("Volumen semanal por músculo", html)
        self.assertIn("Schoenfeld", html)
        self.assertIn("Pelland", html)
        self.assertNotIn("recuperado", html.lower())


class PersonalRangeTests(DbTestCase):
    TODAY = date(2026, 6, 30)

    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        with app.app_context():
            db.session.add(Exercise(id="Bench_Press", name="Bench Press", name_es="Press de banca",
                                    primary_muscles="chest", secondary_muscles="triceps"))
            db.session.commit()

    def build(self, pattern, rounds):
        """Una sesión por semana. El cambio de 1RM de cada sesión depende de las
        series de la sesión anterior (12 -> +2 %, 8 -> +0,5 %, 20 -> -0,5 %)."""
        effect = {12: 0.02, 8: 0.005, 20: -0.005}
        counts = pattern * rounds
        weight = 100.0
        start = self.TODAY - timedelta(weeks=len(counts))
        with app.app_context():
            for i, n in enumerate(counts + [12]):
                if i:
                    weight *= 1 + effect[counts[i - 1]]
                when = datetime.combine(start + timedelta(weeks=i), time(18, 0), tzinfo=MADRID)
                w = Workout(user_id=self.uid, timestamp=when.astimezone(timezone.utc).replace(tzinfo=None))
                db.session.add(w)
                db.session.flush()
                for _ in range(n):
                    db.session.add(SetEntry(workout_id=w.id, exercise="press de banca", weight=round(weight, 2),
                                            reps=1, rir=0, completed=True))
            db.session.commit()

    def test_learns_the_sweet_spot_and_the_ceiling(self):
        self.build([12, 8, 20], 5)
        with app.app_context():
            ranges = volume.personal_ranges(self.uid, today=self.TODAY)
            vol = volume.weekly_volume(self.uid, today=self.TODAY, personal=ranges)
        chest = ranges["pecho"]
        self.assertEqual((chest["low"], chest["high"]), (10, 14))
        self.assertEqual(chest["over_from"], 18)
        self.assertAlmostEqual(chest["gain_pct"], 2.0, places=1)
        self.assertEqual(chest["confidence"], "baja")
        item = next(i for i in vol["items"] if i["group"] == "pecho")
        self.assertEqual(item["status"], "ok")          # 12 series dentro de su 10-14
        self.assertTrue(item["personal"])
        triceps = next(i for i in vol["items"] if i["group"] == "triceps")
        self.assertFalse(triceps["personal"])           # sin ejercicios principales: rango por defecto
        self.assertEqual((triceps["low"], triceps["high"]), (10, 20))

    def test_not_enough_data_keeps_the_default_range(self):
        self.build([12, 8], 2)
        with app.app_context():
            self.assertEqual(volume.personal_ranges(self.uid, today=self.TODAY), {})

    def test_map_colors_cover_every_group(self):
        from app.routes import MUSCLE_GROUPS

        self.build([12, 8, 20], 5)
        with app.app_context():
            colors = volume.map_colors(volume.weekly_volume(self.uid, today=self.TODAY))
        self.assertEqual(set(colors), set(MUSCLE_GROUPS))
        self.assertEqual(colors["pecho"], volume.MAP_COLORS["ok"])
        self.assertEqual(colors["dorsales"], volume.MAP_COLORS["none"])


if __name__ == "__main__":
    unittest.main()
