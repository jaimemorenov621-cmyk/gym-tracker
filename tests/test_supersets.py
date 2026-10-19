"""Biseries (app/supersets.py y sus rutas).

Uso:
    python -m unittest tests.test_supersets
"""
import json
import unittest

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app import supersets
from app.models import Routine, RoutineExercise, SetEntry, Workout


class PureTests(unittest.TestCase):
    def test_link_split_and_merge(self):
        order, groups = ["a", "b", "c", "d"], {}
        order, groups = supersets.toggle_with_next(order, groups, "a")
        self.assertEqual(groups, {"a": 1, "b": 1})
        order, groups = supersets.toggle_with_next(order, groups, "b")   # triserie
        self.assertEqual(groups, {"a": 1, "b": 1, "c": 1})
        order, groups = supersets.toggle_with_next(order, groups, "a")   # separar a | b c
        self.assertEqual(groups, {"b": 1, "c": 1})
        order, groups = supersets.toggle_with_next(order, groups, "b")   # b | c: ya no queda grupo
        self.assertEqual(groups, {})
        order, groups = supersets.toggle_with_next(order, groups, "d")   # el último: nada
        self.assertEqual((order, groups), (["a", "b", "c", "d"], {}))

    def test_merge_two_groups(self):
        order, groups = supersets.toggle_with_next(["a", "b", "c", "d"], {"a": 1, "b": 1, "c": 2, "d": 2}, "b")
        self.assertEqual(groups, {k: 1 for k in "abcd"})

    def test_normalize_keeps_groups_together_and_renumbers(self):
        order, groups = supersets.normalize(["x", "a", "y", "b", "solo"], {"a": 7, "b": 7, "solo": 3, "y": 9})
        self.assertEqual(order, ["x", "a", "b", "y", "solo"])
        self.assertEqual(groups, {"a": 1, "b": 1})  # "solo" y "y" no tienen pareja

    def test_display_info(self):
        with app.test_request_context():
            info = supersets.display_info(["a", "b", "c"], {"a": 1, "b": 1})
        self.assertEqual((info["a"]["label"], info["a"]["letter"], info["a"]["pos"], info["a"]["size"]), ("Biserie", "A", 1, 2))
        self.assertTrue(info["a"]["linked_next"])
        self.assertFalse(info["b"]["linked_next"])
        self.assertTrue(info["b"]["last"])
        self.assertNotIn("c", info)


class WorkoutRouteTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        with app.app_context():
            w = Workout(user_id=self.uid)
            db.session.add(w)
            db.session.flush()
            for ex in ("press de banca", "remo con barra", "curl"):
                db.session.add(SetEntry(workout_id=w.id, exercise=ex, weight=0, reps=0))
            db.session.commit()
            self.wid = w.id

    def groups(self):
        with app.app_context():
            return supersets.load(db.session.get(Workout, self.wid))

    def toggle(self, exercise):
        return self.client.post(f"/workout/{self.wid}/exercise/superset", json={"exercise": exercise})

    def test_toggle_and_page(self):
        self.login(self.uid)
        self.assertTrue(self.toggle("press de banca").get_json()["linked"])
        self.assertEqual(self.groups(), {"press de banca": 1, "remo con barra": 1})
        html = self.client.get(f"/workout/{self.wid}").get_data(as_text=True)
        self.assertIn("Biserie A · 1/2", html)
        self.assertIn("Separar del siguiente", html)
        self.assertFalse(self.toggle("press de banca").get_json()["linked"])
        self.assertEqual(self.groups(), {})

    def test_reorder_keeps_superset_together(self):
        self.login(self.uid)
        self.toggle("press de banca")
        self.client.post(f"/workout/{self.wid}/exercise/reorder",
                         json={"order": ["press de banca", "curl", "remo con barra"]})
        with app.app_context():
            order = json.loads(db.session.get(Workout, self.wid).exercise_order)
        self.assertEqual(order, ["press de banca", "remo con barra", "curl"])

    def test_replace_and_delete_update_groups(self):
        self.login(self.uid)
        self.toggle("press de banca")
        self.client.post(f"/workout/{self.wid}/exercise/replace",
                         json={"old_exercise": "remo con barra", "exercise": "dominadas"})
        self.assertEqual(self.groups(), {"press de banca": 1, "dominadas": 1})
        self.client.post(f"/workout/{self.wid}/exercise/delete", json={"exercise": "dominadas"})
        self.assertEqual(self.groups(), {})  # una biserie de uno ya no lo es

    def test_other_users_forbidden(self):
        self.login(self.make_user("otro"))
        self.assertEqual(self.toggle("press de banca").status_code, 403)
        self.assertEqual(self.groups(), {})

    def test_save_as_routine_keeps_supersets(self):
        self.login(self.uid)
        self.toggle("remo con barra")  # remo + curl
        self.client.post(f"/workout/{self.wid}/save_as_routine")
        with app.app_context():
            rows = db.session.scalars(sa.select(RoutineExercise).order_by(RoutineExercise.order_index)).all()
            self.assertEqual([(r.exercise, r.superset_group) for r in rows],
                             [("press de banca", None), ("remo con barra", 1), ("curl", 1)])


    def test_superset_timers_default_set_and_kept(self):
        self.login(self.uid)
        self.toggle("press de banca")  # press + remo
        html = self.client.get(f"/workout/{self.wid}").get_data(as_text=True)
        self.assertIn('data-ss-transition="40"', html)          # por defecto 40 s
        self.assertIn('data-ss-rest="40"', html)                # descanso de la ronda por defecto: 40 s
        resp = self.client.post(f"/workout/{self.wid}/superset/timers",
                                json={"exercise": "remo con barra", "transition": 20, "rest": 90})
        self.assertTrue(resp.get_json()["ok"])
        with app.app_context():
            w = db.session.get(Workout, self.wid)
            self.assertEqual(supersets.load_timers(w), {"press de banca": [20, 90], "remo con barra": [20, 90]})
        html = self.client.get(f"/workout/{self.wid}").get_data(as_text=True)
        self.assertIn('data-ss-transition="20" data-ss-rest="90"', html)
        # Sin biserie no hay tiempos que guardar; al separarla se olvidan.
        self.assertEqual(self.client.post(f"/workout/{self.wid}/superset/timers",
                                          json={"exercise": "curl", "transition": 5, "rest": 60}).status_code, 400)
        self.toggle("press de banca")
        with app.app_context():
            self.assertEqual(supersets.load_timers(db.session.get(Workout, self.wid)), {})


class RoutineRouteTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("atleta")
        with app.app_context():
            r = Routine(name="Torso", user_id=self.uid)
            db.session.add(r)
            db.session.flush()
            self.ids = []
            for i, ex in enumerate(("press de banca", "remo con barra", "curl")):
                row = RoutineExercise(routine_id=r.id, exercise=ex, target_sets=3, target_reps="8", order_index=i)
                db.session.add(row)
                db.session.flush()
                self.ids.append(row.id)
            db.session.commit()
            self.rid = r.id

    def rows(self):
        with app.app_context():
            return [(r.exercise, r.superset_group) for r in db.session.scalars(
                sa.select(RoutineExercise).order_by(RoutineExercise.order_index))]

    def test_toggle_page_and_start_copies_groups(self):
        self.login(self.uid)
        resp = self.client.post(f"/routines/{self.rid}/exercise/{self.ids[0]}/superset")
        self.assertTrue(resp.get_json()["linked"])
        self.assertEqual(self.rows(), [("press de banca", 1), ("remo con barra", 1), ("curl", None)])
        self.assertIn("Biserie A · 2/2", self.client.get(f"/routines/{self.rid}").get_data(as_text=True))
        self.client.post(f"/routines/{self.rid}/start")
        with app.app_context():
            w = db.session.scalars(sa.select(Workout)).one()
            self.assertEqual(supersets.load(w), {"press de banca": 1, "remo con barra": 1})

    def test_routine_timers_go_to_the_workout(self):
        self.login(self.uid)
        self.client.post(f"/routines/{self.rid}/exercise/{self.ids[0]}/superset")
        resp = self.client.post(f"/routines/{self.rid}/exercise/{self.ids[1]}/superset/timers",
                                json={"transition": 10, "rest": 75})
        self.assertTrue(resp.get_json()["ok"])
        with app.app_context():
            rows = db.session.scalars(sa.select(RoutineExercise).order_by(RoutineExercise.order_index)).all()
            self.assertEqual([(r.superset_transition, r.superset_rest) for r in rows], [(10, 75), (10, 75), (None, None)])
        self.client.post(f"/routines/{self.rid}/start")
        with app.app_context():
            w = db.session.scalars(sa.select(Workout)).one()
            self.assertEqual(supersets.load_timers(w), {"press de banca": [10, 75], "remo con barra": [10, 75]})
        other = self.make_user("otro")
        self.login(other)
        self.assertEqual(self.client.post(f"/routines/{self.rid}/exercise/{self.ids[0]}/superset/timers",
                                          json={"transition": 1, "rest": 1}).status_code, 403)

    def test_reorder_and_delete(self):
        self.login(self.uid)
        self.client.post(f"/routines/{self.rid}/exercise/{self.ids[0]}/superset")
        self.client.post(f"/routines/{self.rid}/reorder", json={"order": [self.ids[0], self.ids[2], self.ids[1]]})
        self.assertEqual([e for e, _ in self.rows()], ["press de banca", "remo con barra", "curl"])
        self.client.post(f"/routines/{self.rid}/exercise/{self.ids[1]}/delete")
        self.assertEqual(self.rows(), [("press de banca", None), ("curl", None)])

    def test_other_users_forbidden(self):
        self.login(self.make_user("otro"))
        self.assertEqual(self.client.post(f"/routines/{self.rid}/exercise/{self.ids[0]}/superset").status_code, 403)
        self.assertEqual(self.rows()[0][1], None)


if __name__ == "__main__":
    unittest.main()
