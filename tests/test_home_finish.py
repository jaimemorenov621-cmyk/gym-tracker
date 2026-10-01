"""Fase 1 de UX: acción principal de Inicio, primeros pasos, entreno libre
instantáneo, renombrar entreno y resumen/duración al terminar.

Uso:
    python -m unittest tests.test_home_finish
"""
import unittest
from datetime import datetime, timedelta, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import Routine, RoutineBlock, RoutineExercise, SetEntry, Workout
from app.routes import (
    default_workout_name,
    estimate_workout_end,
    home_cta,
    onboarding_status,
    suggest_next_routine,
    workout_summary,
)


def naive_utc(**delta):
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(**delta)


class DefaultNameTests(unittest.TestCase):
    def test_spanish_weekday_in_madrid_time(self):
        # Martes 30/09/2026 23:30 UTC = miércoles 01:30 en Madrid.
        self.assertEqual(default_workout_name(datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)), "Entreno del jueves")
        self.assertEqual(default_workout_name(datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)), "Entreno del martes")


class _Fixtures(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")

    def add_routine(self, name, order, block_id=None, exercises=1):
        with app.app_context():
            r = Routine(name=name, order_index=order, block_id=block_id, user_id=self.uid)
            db.session.add(r)
            db.session.flush()
            for i in range(exercises):
                db.session.add(RoutineExercise(routine_id=r.id, exercise=f"ej{i}", target_sets=3, target_reps="8", order_index=i))
            db.session.commit()
            return r.id

    def add_block(self, name, default=False):
        with app.app_context():
            b = RoutineBlock(name=name, is_default=default, user_id=self.uid)
            db.session.add(b)
            db.session.commit()
            return b.id

    def add_workout(self, hours_ago, routine_id=None, rating=None, sets=()):
        """sets: (weight, reps, completed, is_pr, completed_minutes_ago|None)"""
        with app.app_context():
            w = Workout(user_id=self.uid, routine_id=routine_id, performance_rating=rating,
                        timestamp=naive_utc(hours=hours_ago))
            db.session.add(w)
            db.session.flush()
            for weight, reps, completed, is_pr, done_ago in sets:
                db.session.add(SetEntry(
                    workout_id=w.id, exercise="sentadilla", weight=weight, reps=reps,
                    completed=completed, is_pr=is_pr,
                    completed_at=naive_utc(minutes=done_ago) if done_ago is not None else None,
                ))
            db.session.commit()
            return w.id


class SuggestNextRoutineTests(_Fixtures):
    def test_none_without_routines(self):
        with app.app_context():
            self.assertIsNone(suggest_next_routine(self.uid))
            self.assertEqual(home_cta(self.uid)["kind"], "empty")

    def test_first_routine_when_none_done(self):
        a = self.add_routine("A", 0)
        self.add_routine("B", 1)
        with app.app_context():
            self.assertEqual(suggest_next_routine(self.uid).id, a)

    def test_rotates_after_last_done_and_wraps(self):
        a = self.add_routine("A", 0)
        b = self.add_routine("B", 1)
        self.add_workout(48, routine_id=a, rating=6)
        with app.app_context():
            self.assertEqual(suggest_next_routine(self.uid).id, b)
        self.add_workout(24, routine_id=b, rating=6)
        with app.app_context():
            self.assertEqual(suggest_next_routine(self.uid).id, a)

    def test_default_block_wins(self):
        self.add_routine("Suelta", 0)
        fuerza = self.add_block("Fuerza", default=True)
        f1 = self.add_routine("F1", 0, block_id=fuerza, exercises=4)
        with app.app_context():
            cta = home_cta(self.uid)
        self.assertEqual(cta["kind"], "routine")
        self.assertEqual(cta["routine"].id, f1)
        self.assertEqual(cta["exercise_count"], 4)

    def test_empty_default_block_falls_back_to_all(self):
        self.add_block("Descarga", default=True)
        a = self.add_routine("A", 0)
        with app.app_context():
            self.assertEqual(suggest_next_routine(self.uid).id, a)

    def test_empty_routines_are_skipped(self):
        self.add_routine("Vacía", 0, exercises=0)
        b = self.add_routine("Con ejercicios", 1)
        with app.app_context():
            self.assertEqual(suggest_next_routine(self.uid).id, b)

    def test_only_empty_routines_offers_free_workout(self):
        self.add_routine("Vacía", 0, exercises=0)
        with app.app_context():
            self.assertEqual(home_cta(self.uid)["kind"], "empty")

    def test_active_workout_takes_priority(self):
        self.add_routine("A", 0)
        wid = self.add_workout(1, sets=[(100, 5, True, False, 10), (0, 0, False, False, None)])
        with app.app_context():
            cta = home_cta(self.uid)
        self.assertEqual((cta["kind"], cta["workout"].id, cta["done"], cta["total"]), ("continue", wid, 1, 2))


class OnboardingTests(_Fixtures):
    def test_progression_and_disappears_when_done(self):
        with app.app_context():
            self.assertEqual(onboarding_status(self.uid)["done"], 0)
        self.add_routine("A", 0)
        with app.app_context():
            st = onboarding_status(self.uid)
        self.assertEqual((st["done"], st["current"]), (1, 1))
        self.add_workout(30, rating=7, sets=[(100, 5, True, False, None)])
        with app.app_context():
            self.assertIsNone(onboarding_status(self.uid))


class NewWorkoutTests(_Fixtures):
    def test_get_does_not_create(self):
        self.login(self.uid)
        resp = self.client.get("/workout/new")
        self.assertEqual(resp.status_code, 302)
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Workout)), 0)

    def test_post_creates_instantly_with_default_name(self):
        self.login(self.uid)
        resp = self.client.post("/workout/new")
        self.assertEqual(resp.status_code, 302)
        with app.app_context():
            w = db.session.scalar(sa.select(Workout))
            self.assertTrue(w.note.startswith("Entreno del "))
            self.assertIn(f"/workout/{w.id}", resp.headers["Location"])

    def test_second_concurrent_workout_blocked(self):
        existing = self.add_workout(1)
        self.login(self.uid)
        resp = self.client.post("/workout/new")
        self.assertIn(f"/workout/{existing}", resp.headers["Location"])
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Workout)), 1)

    def test_requires_login(self):
        resp = self.client.post("/workout/new")
        self.assertIn("/login", resp.headers["Location"])


class RenameWorkoutTests(_Fixtures):
    def test_rename_trims_and_limits(self):
        wid = self.add_workout(1)
        self.login(self.uid)
        data = self.client.post(f"/workout/{wid}/rename", json={"name": "  Pierna   pesada  " + "x" * 80}).get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["name"].startswith("Pierna pesada "))
        self.assertEqual(len(data["name"]), 64)

    def test_empty_name_rejected(self):
        wid = self.add_workout(1)
        self.login(self.uid)
        self.assertEqual(self.client.post(f"/workout/{wid}/rename", json={"name": "   "}).status_code, 400)

    def test_other_user_forbidden(self):
        wid = self.add_workout(1)
        other = self.make_user("otro")
        self.login(other)
        self.assertEqual(self.client.post(f"/workout/{wid}/rename", json={"name": "Hack"}).status_code, 403)


class CompletedAtTests(_Fixtures):
    def test_set_and_cleared_via_api(self):
        wid = self.add_workout(1, sets=[(100, 5, False, False, None)])
        with app.app_context():
            sid = db.session.scalar(sa.select(SetEntry.id).where(SetEntry.workout_id == wid))
        self.login(self.uid)
        self.client.put(f"/set/{sid}", json={"completed": True})
        with app.app_context():
            self.assertIsNotNone(db.session.get(SetEntry, sid).completed_at)
        self.client.put(f"/set/{sid}", json={"completed": False})
        with app.app_context():
            self.assertIsNone(db.session.get(SetEntry, sid).completed_at)


class FinishTests(_Fixtures):
    def test_forgotten_workout_ends_at_last_set(self):
        # Empezó hace 31 h, última serie hace 30 h: la duración es ~1 h, no 31.
        wid = self.add_workout(31, sets=[(100, 5, True, False, 30 * 60)])
        with app.app_context():
            w = db.session.get(Workout, wid)
            end, estimated = estimate_workout_end(w)
            self.assertTrue(estimated)
            self.assertLess(end - w.timestamp, timedelta(hours=1, minutes=10))

    def test_recent_activity_uses_now(self):
        wid = self.add_workout(1, sets=[(100, 5, True, False, 5)])
        with app.app_context():
            _, estimated = estimate_workout_end(db.session.get(Workout, wid))
        self.assertFalse(estimated)

    def test_old_sets_without_timestamp_use_now(self):
        wid = self.add_workout(31, sets=[(100, 5, True, False, None)])
        with app.app_context():
            _, estimated = estimate_workout_end(db.session.get(Workout, wid))
        self.assertFalse(estimated)

    def test_summary_counts_only_real_sets_and_compares_volume(self):
        r = self.add_routine("A", 0)
        self.add_workout(72, routine_id=r, rating=6, sets=[(100, 5, True, False, None)])  # 500 kg
        wid = self.add_workout(1, routine_id=r, sets=[
            (100, 5, True, True, 20),   # cuenta, PR
            (20, 10, True, False, 10),  # cuenta
            (100, 5, False, False, None),  # sin marcar: no cuenta
        ])
        with app.app_context():
            s = workout_summary(db.session.get(Workout, wid))
            self.assertEqual((s["sets_done"], s["volume"], s["exercise_count"]), (2, 700, 1))
            self.assertEqual(len(s["prs"]), 1)
            self.assertEqual(s["volume_change_pct"], 40)

    def test_finish_page_has_no_preselected_rating_and_caps_duration(self):
        wid = self.add_workout(31, sets=[(100, 5, True, False, None)])
        self.login(self.uid)
        html = self.client.get(f"/workout/{wid}/finish").get_data(as_text=True)
        self.assertNotIn("rating-chip rating-1 selected", html)
        self.assertNotIn('selected value="1"', html)
        self.assertRegex(html, r'<input[^>]*name="duration_hours"[^>]*value="23"')

    def test_finish_without_rating_is_rejected(self):
        wid = self.add_workout(1, sets=[(100, 5, True, False, 5)])
        self.login(self.uid)
        resp = self.client.post(f"/workout/{wid}/finish", data={"duration_hours": 1, "duration_minutes": 0})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Elige cómo te ha ido", resp.get_data(as_text=True))
        with app.app_context():
            self.assertIsNone(db.session.get(Workout, wid).performance_rating)

    def test_finish_saves(self):
        wid = self.add_workout(1, sets=[(100, 5, True, False, 5)])
        self.login(self.uid)
        resp = self.client.post(f"/workout/{wid}/finish",
                                data={"performance_rating": 8, "duration_hours": 1, "duration_minutes": 5})
        self.assertEqual(resp.status_code, 302)
        with app.app_context():
            w = db.session.get(Workout, wid)
            self.assertEqual(w.performance_rating, 8)
            self.assertEqual(w.ended_at - w.timestamp, timedelta(hours=1, minutes=5))


if __name__ == "__main__":
    unittest.main()
