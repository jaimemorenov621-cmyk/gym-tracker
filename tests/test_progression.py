"""XP, niveles, check-in y la caché de XP con su invalidación (app/progression.py).

Uso:
    python -m unittest tests.test_progression
"""
import json
import pathlib
import re
import unittest
from collections import namedtuple
from datetime import date, datetime, timedelta

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app import progression as xp
from app.models import (
    BodyWeightEntry, DailyCheckin, Routine, SetEntry, User, UserAchievement, WeeklyGoalHistory, Workout,
)

Row = namedtuple("Row", "exercise weight reps rir rpe set_type completed")
MONDAY = datetime(2026, 3, 2, 16, 0)  # lunes; 17:00 en Madrid, mismo día


def s(exercise="sentadilla", weight=100.0, reps=8, set_type="normal", completed=True, rir=None):
    return Row(exercise, weight, reps, rir, None, set_type, completed)


def w(wid, day_offset, sets, finished=True, hour_offset=0):
    return xp._Workout(wid, MONDAY + timedelta(days=day_offset, hours=hour_offset), finished, list(sets))


def inputs(workouts, checkins=(), goals=()):
    return xp.XpInputs(list(workouts), set(checkins), list(goals))


# ------------------------------------------------------------------ reglas (puras)
class RuleTests(unittest.TestCase):
    def total(self, *args, **kw):
        with app.app_context():
            return xp.compute_xp(*args, **kw)

    def test_valid_workout_sets_and_weekly_bonus(self):
        r = self.total(inputs([w(1, 0, [s()] * 4)]))
        self.assertEqual(r.by_workout[1]["workout"], 100)
        self.assertEqual(r.by_workout[1]["sets"], 20)
        week = next(iter(r.weeks.values()))
        self.assertEqual(week["bonus"], 40)  # mínimo por defecto: 1
        self.assertEqual(r.total, 160)

    def test_unfinished_workout_only_counts_when_included(self):
        data = inputs([w(1, 0, [s()] * 4, finished=False)])
        self.assertEqual(self.total(data).total, 0)
        self.assertEqual(self.total(data, include_workout=1).total, 160)
        self.assertEqual(self.total(inputs([w(1, 0, [s()] * 4)]), exclude_workout=1).total, 0)

    def test_workout_needs_three_sets_and_ten_reps(self):
        r = self.total(inputs([w(1, 0, [s(reps=1)] * 3)]))
        self.assertEqual(r.by_workout[1]["workout"], 0)
        self.assertEqual(r.by_workout[1]["sets"], 15)
        r = self.total(inputs([w(1, 0, [s(reps=8)] * 2)]))
        self.assertEqual(r.by_workout[1]["workout"], 0)

    def test_one_workout_per_day_and_six_days_per_week(self):
        r = self.total(inputs([w(1, 0, [s()] * 3), w(2, 0, [s()] * 3, hour_offset=2)]))
        self.assertEqual([r.by_workout[i]["workout"] for i in (1, 2)], [100, 0])
        week7 = [w(i + 1, i, [s()] * 3) for i in range(7)]
        r = self.total(inputs(week7))
        self.assertEqual(sum(r.by_workout[i]["workout"] for i in range(1, 8)), 600)
        self.assertIn("días", next(iter(r.weeks.values()))["capped"])

    def test_25_sets_per_day(self):
        r = self.total(inputs([w(1, 0, [s()] * 20), w(2, 0, [s()] * 20, hour_offset=2)]))
        self.assertEqual(r.by_workout[1]["sets_n"] + r.by_workout[2]["sets_n"], 25)

    def test_warmups_and_near_empty_sets_do_not_count(self):
        heavy = w(1, 0, [s(weight=100, reps=5)] * 3)
        light = w(2, 1, [s(weight=10, reps=10)] * 3 + [s(weight=100, reps=5, set_type="calentamiento")])
        r = self.total(inputs([heavy, light]))
        self.assertEqual(r.by_workout[2]["sets_n"], 0)  # 10 kg < 40 % de su mejor 1RM
        self.assertEqual(r.by_workout[2]["workout"], 0)

    def test_records_skip_first_session_and_cap_at_three_per_day(self):
        names = ["a", "b", "c", "d"]
        first = w(1, 0, [s(exercise=n, weight=50) for n in names] * 3)
        better = w(2, 1, [s(exercise=n, weight=60) for n in names] * 3)
        r = self.total(inputs([first, better]))
        self.assertEqual(r.by_workout[1]["prs_n"], 0)  # la primera vez no es récord
        self.assertEqual(r.by_workout[2]["prs_n"], 3)  # 4 récords, tope 3
        self.assertEqual(r.by_workout[2]["prs"], 75)

    def test_weekly_bonus_scales_with_the_minimum(self):
        goals = [(date(2026, 1, 1), 3)]
        two_days = [w(1, 0, [s()] * 3), w(2, 1, [s()] * 3)]
        week = next(iter(self.total(inputs(two_days, goals=goals)).weeks.values()))
        self.assertEqual((week["minimum"], week["bonus"]), (3, 0))
        three_days = two_days + [w(3, 2, [s()] * 3)]
        week = next(iter(self.total(inputs(three_days, goals=goals)).weeks.values()))
        self.assertEqual(week["bonus"], 120)

    def test_checkin_gives_ten(self):
        r = self.total(inputs([], checkins=[date(2026, 3, 3), date(2026, 3, 4)]))
        self.assertEqual(r.total, 20)

    def test_cheap_farming_example_from_the_plan(self):
        # 7 días con 3 series de 1 repetición, mínimo 7, check-in diario.
        farm = [w(i + 1, i, [s(reps=1)] * 3) for i in range(7)]
        checkins = [date(2026, 3, 2) + timedelta(days=i) for i in range(7)]
        r = self.total(inputs(farm, checkins=checkins, goals=[(date(2026, 1, 1), 7)]))
        self.assertEqual(r.total, 105 + 280 + 70)  # ≤ 455 a la semana

    def test_levels(self):
        self.assertEqual(xp.xp_to_reach(1), 0)
        self.assertEqual(xp.xp_to_reach(2), 500)
        self.assertEqual(xp.xp_to_reach(3), 1100)
        self.assertEqual(xp.level_for(0)["level"], 1)
        self.assertEqual(xp.level_for(1099)["level"], 2)
        info = xp.level_for(1100)
        self.assertEqual((info["level"], info["into"], info["span"]), (3, 0, 700))


# ------------------------------------------------------------------ base de datos
class _XpCase(DbTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.make_user("a")
        self.b = self.make_user("b")

    def add_workout(self, uid, day_offset=0, n_sets=4, finished=True, weight=100.0):
        with app.app_context():
            wo = Workout(user_id=uid, timestamp=MONDAY + timedelta(days=day_offset),
                         performance_rating=7 if finished else None)
            db.session.add(wo)
            db.session.flush()
            for _ in range(n_sets):
                db.session.add(SetEntry(workout_id=wo.id, exercise="sentadilla", weight=weight, reps=8, completed=True))
            db.session.commit()
            return wo.id

    def seq(self, uid):
        with app.app_context():
            return db.session.scalar(sa.select(User.xp_seq).where(User.id == uid))

    def real(self, uid):
        with app.app_context():
            return xp.compute_xp(xp.load_xp_inputs(uid)).total

    def cached(self, uid):
        with app.app_context():
            return xp.current_xp(uid)

    def is_fresh(self, uid):
        with app.app_context():
            row = db.session.execute(
                sa.select(User.xp_seq, User.xp_total, User.xp_cached_seq, User.xp_rules, User.xp_cached_at)
                .where(User.id == uid)
            ).one()
            return xp.is_cache_fresh(row)


class CacheTests(_XpCase):
    def test_cache_is_used_until_something_changes(self):
        self.add_workout(self.a)
        self.assertEqual(self.cached(self.a), 160)
        self.assertTrue(self.is_fresh(self.a))
        self.add_workout(self.a, day_offset=1)
        self.assertFalse(self.is_fresh(self.a))
        self.assertEqual(self.cached(self.a), 280)

    def test_rules_version_and_ttl_invalidate(self):
        self.add_workout(self.a)
        self.cached(self.a)
        with app.app_context():
            db.session.execute(sa.update(User).where(User.id == self.a)
                               .values(xp_cached_at=datetime(2000, 1, 1)).execution_options(synchronize_session=False))
            db.session.commit()
        self.assertFalse(self.is_fresh(self.a))
        self.cached(self.a)
        with app.app_context():
            db.session.execute(sa.update(User).where(User.id == self.a)
                               .values(xp_rules=xp.XP_RULES_VERSION - 1).execution_options(synchronize_session=False))
            db.session.commit()
        self.assertFalse(self.is_fresh(self.a))

    def test_concurrent_write_never_leaves_an_old_total_as_fresh(self):
        self.add_workout(self.a)

        def write_in_between():  # otra petición guarda un entreno entre la carga y el UPDATE
            wid = Workout(user_id=self.a, timestamp=MONDAY + timedelta(days=1), performance_rating=7)
            db.session.add(wid)
            db.session.flush()
            for _ in range(4):
                db.session.add(SetEntry(workout_id=wid.id, exercise="sentadilla", weight=100, reps=8, completed=True))
            db.session.commit()

        with app.app_context():
            report, stored = xp.refresh_xp(self.a, _after_load=write_in_between)
        self.assertFalse(stored)
        self.assertEqual(report.total, 160)  # lo leído antes de la escritura
        self.assertFalse(self.is_fresh(self.a))
        self.assertEqual(self.cached(self.a), 280)
        self.assertTrue(self.is_fresh(self.a))


class OrmInvalidationTests(_XpCase):
    def test_new_set_bumps_only_its_owner(self):
        wid = self.add_workout(self.a)
        a0, b0 = self.seq(self.a), self.seq(self.b)
        with app.app_context():
            db.session.add(SetEntry(workout_id=wid, exercise="press", weight=50, reps=5, completed=True))
            db.session.commit()
        self.assertEqual((self.seq(self.a), self.seq(self.b)), (a0 + 1, b0))

    def test_workout_created_through_relationship(self):
        a0 = self.seq(self.a)
        with app.app_context():
            db.session.add(Workout(note="x", author=db.session.get(User, self.a)))
            db.session.commit()
        self.assertEqual(self.seq(self.a), a0 + 1)

    def test_editing_and_deleting_sets(self):
        wid = self.add_workout(self.a)
        a0 = self.seq(self.a)
        with app.app_context():
            entry = db.session.scalar(sa.select(SetEntry).where(SetEntry.workout_id == wid).limit(1))
            entry.weight = 120
            db.session.commit()
        self.assertEqual(self.seq(self.a), a0 + 1)
        with app.app_context():
            db.session.delete(db.session.scalar(sa.select(SetEntry).where(SetEntry.workout_id == wid).limit(1)))
            db.session.commit()
        self.assertEqual(self.seq(self.a), a0 + 2)

    def test_untouched_flush_does_not_bump(self):
        self.add_workout(self.a)
        a0 = self.seq(self.a)
        with app.app_context():
            db.session.get(User, self.a).notes = "hola"  # no es dato del XP
            db.session.commit()
        self.assertEqual(self.seq(self.a), a0)

    def test_delete_workout_route_lowers_xp(self):
        wid = self.add_workout(self.a)
        self.add_workout(self.a, day_offset=1)
        self.assertEqual(self.cached(self.a), 280)
        self.login(self.a)
        self.client.post(f"/workout/{wid}/delete")
        self.assertFalse(self.is_fresh(self.a))
        self.assertEqual(self.cached(self.a), 160)

    def test_changing_the_weekly_minimum_invalidates(self):
        self.add_workout(self.a)
        self.cached(self.a)
        with app.app_context():
            db.session.add(WeeklyGoalHistory(user_id=self.a, goal=3))
            db.session.commit()
        self.assertFalse(self.is_fresh(self.a))


class BulkInvalidationTests(_XpCase):
    """Una prueba por cada vía de escritura que no pasa por el flush del ORM."""

    def setUp(self):
        super().setUp()
        app.config["XP_STRICT_BULK_DML"] = False
        self.wa = self.add_workout(self.a)
        self.wb = self.add_workout(self.b)
        self.a0, self.b0 = self.seq(self.a), self.seq(self.b)

    def tearDown(self):
        app.config["XP_STRICT_BULK_DML"] = True
        super().tearDown()

    def assertAllBumped(self):
        self.assertGreater(self.seq(self.a), self.a0)
        self.assertGreater(self.seq(self.b), self.b0)

    def test_session_execute_update_bumps_everyone(self):
        with app.app_context():
            db.session.execute(sa.update(SetEntry).where(SetEntry.workout_id == self.wa).values(reps=10))
            db.session.commit()
        self.assertAllBumped()

    def test_marked_statement_does_not_bump(self):
        with app.app_context():
            db.session.execute(sa.update(Workout).where(Workout.id == self.wa).values(note="x")
                               .execution_options(xp_irrelevant=True))
            db.session.commit()
        self.assertEqual((self.seq(self.a), self.seq(self.b)), (self.a0, self.b0))

    def test_strict_mode_rejects_unreviewed_bulk_writes(self):
        app.config["XP_STRICT_BULK_DML"] = True
        with app.app_context():
            with self.assertRaises(RuntimeError):
                db.session.execute(sa.update(SetEntry).values(reps=10))
            db.session.rollback()

    def test_engine_connection(self):
        with app.app_context():
            with db.engine.begin() as conn:
                conn.execute(sa.delete(SetEntry).where(SetEntry.workout_id == self.wb))
        self.assertAllBumped()

    def test_bulk_update_mappings(self):
        with app.app_context():
            sid = db.session.scalar(sa.select(SetEntry.id).where(SetEntry.workout_id == self.wa).limit(1))
            db.session.bulk_update_mappings(SetEntry, [{"id": sid, "reps": 3}])
            db.session.commit()
        self.assertAllBumped()

    def test_raw_sql_text(self):
        with app.app_context():
            db.session.execute(sa.text("DELETE FROM set_entry WHERE workout_id = :w"), {"w": self.wa})
            db.session.commit()
        self.assertAllBumped()

    def test_database_cascade_when_deleting_a_workout_without_the_orm(self):
        with app.app_context():
            with db.engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")  # SQLite no lo trae activado
                conn.execute(sa.delete(Workout).where(Workout.id == self.wa))
                conn.commit()
                conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            left = db.session.scalar(sa.select(sa.func.count()).select_from(SetEntry).where(SetEntry.workout_id == self.wa))
        self.assertEqual(left, 0)  # la cascada de la BD borró las series
        self.assertAllBumped()

    def test_everything_matches_after_all_bulk_paths(self):
        with app.app_context():
            db.session.execute(sa.update(SetEntry).values(weight=SetEntry.weight + 5))
            db.session.execute(sa.text("UPDATE set_entry SET reps = 6 WHERE workout_id = :w"), {"w": self.wb})
            db.session.commit()
        for uid in (self.a, self.b):
            self.assertEqual(self.cached(uid), self.real(uid))


class MigrationGuardTests(unittest.TestCase):
    def test_migrations_touching_xp_tables_are_marked(self):
        versions = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "versions"
        watched = "|".join(sorted(xp.WATCHED_TABLES))
        pattern = re.compile(rf"op\.(execute|bulk_insert)\([^)]*\b({watched})\b", re.S)
        for path in versions.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                self.assertIn("# xp: requiere flask recompute-xp", text, path.name)


class LevelNoticeTests(_XpCase):
    def notice(self, total):
        with app.app_context():
            return xp.level_up_notice(self.a, total)

    def test_first_calculation_is_silent_and_levels_are_announced_once(self):
        self.assertIsNone(self.notice(1200))  # nivel 3, primera vez: sin aviso
        self.assertIsNone(self.notice(1300))
        self.assertEqual(self.notice(1900), 4)
        self.assertIsNone(self.notice(1000))  # baja (borró un entreno)...
        self.assertIsNone(self.notice(1900))  # ...y al volver al 4 no se repite


class CheckinRouteTests(_XpCase):
    def post(self, **data):
        return self.client.post("/checkin", data={"sleep": 4, "energy": 3, "soreness": 1, **data}, follow_redirects=True)

    def test_checkin_gives_ten_xp_once_per_day(self):
        self.login(self.a)
        html = self.post().get_data(as_text=True)
        self.assertIn("+10 XP", html)
        html = self.post(sleep=2).get_data(as_text=True)
        self.assertIn("+0 XP", html)
        with app.app_context():
            rows = db.session.scalars(sa.select(DailyCheckin).where(DailyCheckin.user_id == self.a)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].sleep, 2)
        self.assertEqual(self.cached(self.a), 10)

    def test_incomplete_checkin_is_rejected(self):
        self.login(self.a)
        self.client.post("/checkin", data={"sleep": 4})
        with app.app_context():
            self.assertIsNone(db.session.scalar(sa.select(DailyCheckin.id)))

    def test_csrf_is_required(self):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            self.login(self.a)
            self.client.post("/checkin", data={"sleep": 4, "energy": 3, "soreness": 1})
        finally:
            app.config["WTF_CSRF_ENABLED"] = False
        with app.app_context():
            self.assertIsNone(db.session.scalar(sa.select(DailyCheckin.id)))

    def test_low_day_hint_is_a_suggestion(self):
        self.login(self.a)
        html = self.post(sleep=1, energy=2).get_data(as_text=True)
        self.assertIn("Es solo una sugerencia", html)


class PagesTests(_XpCase):
    def test_home_shows_level_after_the_professional_block(self):
        self.add_workout(self.a)
        self.login(self.a)
        html = self.client.get("/index").get_data(as_text=True)
        self.assertIn("Nivel 1", html)
        self.assertIn("¿Cómo llegas hoy?", html)
        self.assertLess(html.index("dash-tiles"), html.index("dash-level-link"))

    def test_rest_day_shows_facts_only(self):
        from app.usage import local_today

        with app.app_context():
            user = db.session.get(User, self.a)
            user.training_days = str((local_today().weekday() + 1) % 7)
            db.session.commit()
        self.login(self.a)
        html = self.client.get("/index").get_data(as_text=True)
        self.assertIn("esta semana", html)
        self.assertNotIn("recuperado", html.lower())

    def test_level_page_documents_the_rules(self):
        self.add_workout(self.a)
        self.login(self.a)
        html = self.client.get("/nivel").get_data(as_text=True)
        self.assertIn(f"reglas v{xp.XP_RULES_VERSION}", html)
        self.assertIn("Se limita el farmeo barato", html)
        self.assertIn("Curva de niveles", html)

    def test_finish_page_shows_what_the_workout_gives(self):
        wid = self.add_workout(self.a, finished=False)
        self.login(self.a)
        html = self.client.get(f"/workout/{wid}/finish").get_data(as_text=True)
        self.assertIn("+160 XP", html)
        self.assertIn("semana cumplida +40", html)
        self.assertLess(html.index("finish-hero"), html.index("finish-xp"))


class CommandTests(_XpCase):
    def test_recompute_check_and_store(self):
        self.add_workout(self.a)
        runner = app.test_cli_runner()
        result = runner.invoke(args=["recompute-xp", "--check"])
        self.assertIn("diferencias: 0", result.output)
        self.assertFalse(self.is_fresh(self.a))  # --check no guarda
        runner.invoke(args=["recompute-xp"])
        self.assertTrue(self.is_fresh(self.a))

    def test_export_and_delete_user(self):
        self.add_workout(self.a)
        self.add_workout(self.b)
        with app.app_context():
            db.session.add_all([
                BodyWeightEntry(user_id=self.a, weight=80),
                DailyCheckin(user_id=self.a, day=date(2026, 3, 2), sleep=3, energy=3, soreness=0),
                Routine(name="Pierna", user_id=self.a),
                UserAchievement(user_id=self.a, code="workouts_1"),
            ])
            db.session.commit()
        runner = app.test_cli_runner()
        data = json.loads(runner.invoke(args=["export-user", str(self.a)]).output)
        self.assertEqual(len(data["workout"]), 1)
        self.assertEqual(len(data["set_entry"]), 4)
        self.assertNotIn("password_hash", data["user"])
        self.assertIn("--yes", runner.invoke(args=["delete-user", str(self.a)]).output)
        runner.invoke(args=["delete-user", str(self.a), "--yes"])
        with app.app_context():
            self.assertIsNone(db.session.get(User, self.a))
            for model in (Workout, BodyWeightEntry, DailyCheckin, Routine, UserAchievement):
                left = sa.select(sa.func.count()).select_from(model).where(model.user_id == self.a)
                self.assertEqual(db.session.scalar(left), 0, model)
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(SetEntry)), 4)  # las de b
            self.assertIsNotNone(db.session.get(User, self.b))


if __name__ == "__main__":
    unittest.main()
