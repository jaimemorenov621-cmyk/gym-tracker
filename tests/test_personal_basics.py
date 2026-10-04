from datetime import datetime, timedelta

import sqlalchemy as sa

from tests.dbcase import DbTestCase
from app import app, db
from app.models import BodyWeightEntry, PersonalBasic, SetEntry, User, Workout
from app import progression


class PersonalBasicsTests(DbTestCase):
    NOW = datetime.utcnow().replace(microsecond=0)

    def setUp(self):
        super().setUp()
        self.uid = self.make_user("basicos")
        self.other = self.make_user("otro")

    def lift(self, exercise, weight, days_ago, uid=None):
        with app.app_context():
            w = Workout(user_id=uid or self.uid, timestamp=self.NOW - timedelta(days=days_ago), performance_rating=7)
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise=exercise, weight=weight, reps=1, rir=0, completed=True))
            db.session.commit()

    def chosen(self):
        with app.app_context():
            return list(db.session.scalars(
                sa.select(PersonalBasic.exercise).where(PersonalBasic.user_id == self.uid).order_by(PersonalBasic.position)
            ))

    def test_pick_only_your_own_exercises_in_order(self):
        self.lift("prensa de piernas", 150, 10)
        self.lift("hip thrust", 100, 9)
        self.lift("curl femoral", 40, 8, uid=self.other)  # de otro usuario: no se puede elegir
        self.login(self.uid)
        html = self.client.get("/rango/basicos").get_data(as_text=True)
        self.assertIn("Prensa De Piernas", html)
        self.assertNotIn("Curl Femoral", html)
        self.client.post("/rango/basicos", data={"exercise": ["hip thrust", "prensa de piernas", "curl femoral", "inventado"]})
        self.assertEqual(self.chosen(), ["hip thrust", "prensa de piernas"])
        self.client.post("/rango/basicos", data={})  # desmarcar todo
        self.assertEqual(self.chosen(), [])

    def test_rank_tab_shows_rank_with_table_and_progress_without(self):
        with app.app_context():
            db.session.get(User, self.uid).sex = "hombre"
            db.session.add(BodyWeightEntry(user_id=self.uid, weight=80, timestamp=self.NOW - timedelta(days=30)))
            db.session.commit()
        self.lift("prensa de piernas", 150, 20)
        self.lift("prensa de piernas", 165, 5)
        self.lift("remo en smith", 90, 5)
        self.login(self.uid)
        self.client.post("/rango/basicos", data={"exercise": ["prensa de piernas", "remo en smith"]})
        html = self.client.get("/rango").get_data(as_text=True)
        self.assertIn("Tus básicos", html)
        self.assertIn("+10 %", html)        # prensa: sin tabla, su progresión (150 -> 165)
        self.assertIn("aprox.", html)       # remo en Smith: rango con tabla aproximada
        self.assertIn("rank-oro", html)     # 90 kg con 80 kg de peso = Intermedio en remo

    def test_rename_and_delete_user_keep_it_consistent(self):
        from app.routes import rename_exercise_everywhere

        self.lift("prensa", 150, 3)
        self.login(self.uid)
        self.client.post("/rango/basicos", data={"exercise": ["prensa"]})
        with app.app_context():
            rename_exercise_everywhere("prensa", "prensa de piernas")
            db.session.commit()
        self.assertEqual(self.chosen(), ["prensa de piernas"])
        with app.app_context():
            progression.delete_user_data(self.uid)
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(PersonalBasic)), 0)
