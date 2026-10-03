"""Fase 3 de UX: edición en la fila de la página de rutina, reemplazo,
borrado seguro de ejercicios de rutina y páginas con formularios nuevos.

Uso:
    python -m unittest tests.test_routine_forms
"""
import unittest

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import Routine, RoutineExercise, User


class _RoutineFixtures(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        self.rid, self.exid = self.add_routine(self.uid, "Pierna", "sentadilla")

    def add_routine(self, uid, name, exercise):
        with app.app_context():
            r = Routine(name=name, user_id=uid)
            db.session.add(r)
            db.session.flush()
            ex = RoutineExercise(routine_id=r.id, exercise=exercise, target_sets=3, target_reps="8-10", order_index=0)
            db.session.add(ex)
            db.session.commit()
            return r.id, ex.id

    def ex(self, ex_id):
        with app.app_context():
            e = db.session.get(RoutineExercise, ex_id)
            return None if e is None else {"sets": e.target_sets, "reps": e.target_reps, "rir": e.rir,
                                           "rpe": e.rpe, "exercise": e.exercise}

    def url(self, rid=None, exid=None, suffix=""):
        return f"/routines/{rid or self.rid}/exercise/{exid or self.exid}{suffix}"


class InlineEditTests(_RoutineFixtures):
    def test_updates_each_field(self):
        self.login(self.uid)
        self.assertTrue(self.client.post(self.url(), json={"target_sets": "5"}).get_json()["ok"])
        self.assertTrue(self.client.post(self.url(), json={"target_reps": "  5 @RIR3 "}).get_json()["ok"])
        data = self.client.post(self.url(), json={"effort": "2-3"}).get_json()
        self.assertEqual(data["effort"], "2-3")
        self.assertEqual(self.ex(self.exid), {"sets": 5, "reps": "5 @RIR3", "rir": "2-3", "rpe": None, "exercise": "sentadilla"})

    def test_effort_follows_user_scale_and_can_be_cleared(self):
        with app.app_context():
            db.session.get(User, self.uid).effort_scale = "rpe"
            db.session.commit()
        self.login(self.uid)
        self.client.post(self.url(), json={"effort": "8"})
        self.assertEqual((self.ex(self.exid)["rir"], self.ex(self.exid)["rpe"]), (None, "8"))
        self.client.post(self.url(), json={"effort": ""})
        self.assertIsNone(self.ex(self.exid)["rpe"])

    def test_invalid_values_rejected_and_not_saved(self):
        self.login(self.uid)
        for payload in ({"target_sets": 0}, {"target_sets": 16}, {"target_sets": "x"},
                        {"target_reps": "   "}, {"target_reps": "x" * 17}, {"effort": "dos"}, {"effort": "123"}):
            resp = self.client.post(self.url(), json=payload)
            self.assertEqual(resp.status_code, 400, payload)
            self.assertFalse(resp.get_json()["ok"])
        self.assertEqual(self.ex(self.exid)["sets"], 3)
        self.assertEqual(self.ex(self.exid)["reps"], "8-10")

    def test_other_users_and_mismatched_routine_forbidden(self):
        other = self.make_user("otro")
        other_rid, other_exid = self.add_routine(other, "Suya", "remo")
        self.login(self.uid)
        # Ejercicio ajeno colgado de MI rutina en la URL.
        self.assertEqual(self.client.post(self.url(exid=other_exid), json={"target_sets": 9}).status_code, 403)
        self.assertEqual(self.client.post(self.url(rid=other_rid, exid=other_exid), json={"target_sets": 9}).status_code, 403)
        self.assertEqual(self.ex(other_exid)["sets"], 3)

    def test_requires_login(self):
        self.assertIn("/login", self.client.post(self.url(), json={"target_sets": 4}).headers["Location"])


class RangeTests(_RoutineFixtures):
    def test_reps_range_with_numeric_boxes(self):
        self.login(self.uid)
        data = self.client.post(self.url(), json={"reps_max": "12"}).get_json()
        self.assertEqual((data["reps_min"], data["reps_max"], data["target_reps"]), (8, 12, "8-12"))
        data = self.client.post(self.url(), json={"reps_max": ""}).get_json()       # sin máximo: número fijo
        self.assertEqual(data["target_reps"], "8")
        self.assertFalse(self.client.post(self.url(), json={"reps_min": "abc"}).get_json()["ok"])
        self.client.post(self.url(), json={"reps_max": "10"})
        self.assertFalse(self.client.post(self.url(), json={"reps_min": "12"}).get_json()["ok"])  # mín > máx
        self.assertEqual(self.ex(self.exid)["reps"], "8-10")

    def test_sets_range_and_precreated_sets(self):
        self.login(self.uid)
        data = self.client.post(self.url(), json={"target_sets_max": "4"}).get_json()
        self.assertEqual(data["target_sets_max"], 4)
        self.assertFalse(self.client.post(self.url(), json={"target_sets_max": "2"}).get_json()["ok"])
        # Subir el mínimo al máximo deja de ser un rango.
        self.assertEqual(self.client.post(self.url(), json={"target_sets": "4"}).get_json()["target_sets_max"], "")
        self.client.post(self.url(), json={"target_sets": "3"})
        self.client.post(self.url(), json={"target_sets_max": "4"})
        from app.models import SetEntry, Workout
        import sqlalchemy as sa
        self.client.post(f"/routines/{self.rid}/start")
        with app.app_context():
            n = db.session.scalar(sa.select(sa.func.count()).select_from(SetEntry))
        self.assertEqual(n, 4)  # se crean las del máximo; las vacías se borran al terminar

    def test_routine_page_uses_numeric_keyboard(self):
        self.login(self.uid)
        html = self.client.get(f"/routines/{self.rid}").get_data(as_text=True)
        self.assertIn('inputmode="numeric" pattern="[0-9]*" maxlength="3" value="8" data-field="reps_min"', html)
        self.assertIn('value="10" placeholder="máx" data-field="reps_max"', html)


class ReplaceTests(_RoutineFixtures):
    def test_replace_keeps_plan(self):
        self.login(self.uid)
        self.client.post(self.url(), json={"target_sets": 4, "target_reps": "6"})
        self.assertTrue(self.client.post(self.url(suffix="/replace"), json={"exercise": "Prensa"}).get_json()["ok"])
        e = self.ex(self.exid)
        self.assertEqual((e["exercise"], e["sets"], e["reps"]), ("prensa", 4, "6"))

    def test_replace_validation_and_ownership(self):
        self.login(self.uid)
        self.assertEqual(self.client.post(self.url(suffix="/replace"), json={"exercise": " "}).status_code, 400)
        other = self.make_user("otro")
        _, other_exid = self.add_routine(other, "Suya", "remo")
        self.assertEqual(self.client.post(self.url(exid=other_exid, suffix="/replace"), json={"exercise": "x"}).status_code, 403)
        self.assertEqual(self.ex(other_exid)["exercise"], "remo")


class DeleteRoutineExerciseTests(_RoutineFixtures):
    def test_cannot_delete_other_users_exercise_via_own_routine(self):
        """Fallo previo: solo se comprobaba la rutina de la URL, no que el
        ejercicio fuera de ella."""
        other = self.make_user("otro")
        _, other_exid = self.add_routine(other, "Suya", "remo")
        self.login(self.uid)
        self.client.post(f"/routines/{self.rid}/exercise/{other_exid}/delete")
        self.assertIsNotNone(self.ex(other_exid))

    def test_owner_can_delete(self):
        self.login(self.uid)
        self.client.post(f"/routines/{self.rid}/exercise/{self.exid}/delete")
        self.assertIsNone(self.ex(self.exid))


class AddExerciseTests(_RoutineFixtures):
    def test_add_with_defaults_jumps_to_new_row(self):
        self.login(self.uid)
        resp = self.client.post(f"/routines/{self.rid}",
                                data={"exercise": "Press banca", "target_sets": 3, "target_reps": "8-10", "effort_value": ""})
        self.assertEqual(resp.status_code, 302)
        with app.app_context():
            new = db.session.scalar(sa.select(RoutineExercise).where(RoutineExercise.exercise == "press banca"))
            self.assertIsNotNone(new)
            self.assertEqual((new.target_sets, new.target_reps, new.order_index), (3, "8-10", 1))
            self.assertTrue(resp.headers["Location"].endswith(f"#rex-{new.id}"))

    def test_page_renders_inline_editors(self):
        self.login(self.uid)
        html = self.client.get(f"/routines/{self.rid}").get_data(as_text=True)
        self.assertIn('data-field="target_sets"', html)
        self.assertIn(f'id="rex-{self.exid}"', html)
        self.assertIn('data-autosubmit="1"', html)


class FormPagesRenderTests(DbTestCase):
    def test_settings_weight_new_routine_and_notes_render(self):
        uid = self.make_user("atleta")
        self.login(uid)
        for url in ("/settings", "/weight", "/routines/new", "/exercise/sentadilla/notes"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertIn("form-ui", resp.get_data(as_text=True), url)
        self.assertIn('class="toggle"', self.client.get("/settings").get_data(as_text=True))


class ThemeTests(DbTestCase):
    def test_app_pages_follow_preference_and_landing_is_locked_light(self):
        uid = self.make_user("atleta")
        landing = self.client.get("/?no_contar=1").get_data(as_text=True)
        self.assertIn('var lock = "light";', landing)
        self.login(uid)
        page = self.client.get("/settings").get_data(as_text=True)
        self.assertIn('var lock = "";', page)
        self.assertIn('id="themeSelect"', page)


if __name__ == "__main__":
    unittest.main()
