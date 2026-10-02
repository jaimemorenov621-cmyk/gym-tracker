"""Contador de uso (DailyActivity) y aviso de reintento de CSS.

Uso:
    python -m unittest tests.test_usage
"""
import unittest
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import DailyActivity, SetEntry, User, Workout
from app import usage

MADRID = ZoneInfo("Europe/Madrid")


class DailyOpenTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")

    def rows(self):
        with app.app_context():
            return db.session.scalars(sa.select(DailyActivity)).all()

    def test_first_get_of_the_day_marks_open_once(self):
        self.login(self.uid)
        self.client.get("/index")
        self.client.get("/progress")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].opened)
        self.assertEqual(rows[0].day, usage.local_today())

    def test_session_flag_avoids_a_write_per_request(self):
        self.login(self.uid)
        self.client.get("/index")
        with app.app_context():
            db.session.execute(sa.delete(DailyActivity))
            db.session.commit()
        self.client.get("/index")  # mismo día: ni siquiera vuelve a escribir
        self.assertEqual(self.rows(), [])

    def test_prerender_and_prefetch_do_not_count(self):
        self.login(self.uid)
        self.client.get("/index", headers={"Sec-Purpose": "prefetch;prerender"})
        self.client.get("/progress", headers={"Purpose": "prefetch"})
        self.assertEqual(self.rows(), [])

    def test_non_page_requests_and_anonymous_do_not_count(self):
        self.client.get("/index")  # sin sesión
        self.client.get("/healthz")
        self.login(self.uid)
        self.client.get("/healthz")
        self.client.get("/sw.js")
        self.client.post("/usage/css-retry")
        rows = self.rows()
        self.assertTrue(all(not r.opened for r in rows))

    def test_planned_rest_comes_from_training_days(self):
        today_wd = usage.local_today().weekday()
        with app.app_context():
            user = db.session.get(User, self.uid)
            user.training_days = str((today_wd + 1) % 7)  # hoy no es día de entreno
            db.session.commit()
        self.login(self.uid)
        self.client.get("/index")
        self.assertTrue(self.rows()[0].planned_rest)

    def test_no_training_days_configured_is_not_planned_rest(self):
        self.login(self.uid)
        self.client.get("/index")
        self.assertFalse(self.rows()[0].planned_rest)

    def test_old_rows_are_purged(self):
        old_day = usage.local_today() - timedelta(days=usage.RETENTION_DAYS + 10)
        with app.app_context():
            db.session.add(DailyActivity(user_id=self.uid, day=old_day, opened=True))
            db.session.commit()
        self.login(self.uid)
        self.client.get("/index")
        self.assertEqual([r.day for r in self.rows()], [usage.local_today()])

    def test_css_retry_counts_per_day(self):
        self.login(self.uid)
        self.assertEqual(self.client.post("/usage/css-retry").status_code, 204)
        self.client.post("/usage/css-retry")
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].css_retries, 2)

    def test_css_retry_anonymous_is_accepted_but_not_stored(self):
        self.assertEqual(self.client.post("/usage/css-retry").status_code, 204)
        self.assertEqual(self.rows(), [])


class RestDayReportTests(DbTestCase):
    # Semana fija: lunes 21/09/2026 .. domingo 27/09/2026; "hoy" = domingo.
    MONDAY = date(2026, 9, 21)
    TODAY = date(2026, 9, 27)

    def setUp(self):
        super().setUp()
        self.a = self.make_user("a")
        self.b = self.make_user("b")
        self.idle = self.make_user("idle")

    def train(self, uid, day, completed=True):
        local = datetime.combine(day, time(23, 30), tzinfo=MADRID)  # tarde: otro día en UTC no
        with app.app_context():
            w = Workout(user_id=uid, timestamp=local.astimezone(timezone.utc).replace(tzinfo=None))
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise="sentadilla", weight=100, reps=5, completed=completed))
            db.session.commit()

    def opened(self, uid, *days):
        with app.app_context():
            for d in days:
                db.session.add(DailyActivity(user_id=uid, day=d, opened=True))
            db.session.commit()

    def report(self):
        with app.app_context():
            return usage.rest_day_report(weeks=2, today=self.TODAY)

    def test_no_data_yet(self):
        self.assertEqual(self.report()["weeks"], [])

    def test_counts_rest_days_of_active_users_only(self):
        d = lambda i: self.MONDAY + timedelta(days=i)
        self.train(self.a, d(0))
        self.train(self.a, d(2))
        self.train(self.b, d(1))
        self.train(self.b, d(3), completed=False)  # sin series reales: no es día entrenado
        self.opened(self.a, d(0), d(1), d(4))      # d(0) entrenó: no cuenta como descanso
        self.opened(self.b, d(5))
        self.opened(self.idle, d(1), d(2))         # no entrenó esa semana: no es usuario activo
        week = self.report()["weeks"][0]
        self.assertEqual(week["active_users"], 2)
        # a: 7 días - 2 entrenados = 5 de descanso; b: 7 - 1 = 6.
        self.assertEqual(week["rest"], 11)
        self.assertEqual(week["opened"], 3)  # a: d1, d4; b: d5
        self.assertEqual(week["a"], round(100 * 3 / 11))
        self.assertEqual(week["opened_no_checkin"], 3)
        self.assertIsNone(week["b"])  # el check-in aún no existe
        self.assertEqual(sorted(u["rest"] for u in week["per_user"]), [5, 6])

    def test_report_starts_at_first_tracked_day(self):
        d = lambda i: self.MONDAY + timedelta(days=i)
        self.train(self.a, d(1))   # antes de empezar a medir: no cuenta
        self.train(self.a, d(5))
        self.opened(self.a, d(4))  # se empezó a medir el viernes
        week = self.report()["weeks"][0]
        # Solo vie, sáb y dom (el sábado entrenó): 2 días de descanso, 1 abierto.
        self.assertEqual(week["rest"], 2)
        self.assertEqual(week["opened"], 1)
        self.assertEqual(len(self.report()["weeks"]), 1)


class StatsPageTests(DbTestCase):
    def test_stats_page_shows_rest_day_usage(self):
        uid = self.make_user("Jaime_309")
        self.login(uid)
        html = self.client.get("/landing/stats").get_data(as_text=True)
        self.assertIn("Uso en días sin entreno", html)
        # Al abrir la propia página de estadísticas ya hay una fila de hoy.
        self.assertIn("Solo usuarios que entrenaron esa semana", html)


if __name__ == "__main__":
    unittest.main()
