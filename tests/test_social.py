import json
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from tests.dbcase import DbTestCase
from app import app, db, social, progression
from app import strength_standards as std
from app.models import AthleteCard, BodyWeightEntry, Friendship, SetEntry, User, UserAchievement, Workout


class SocialTests(DbTestCase):
    NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    def setUp(self):
        super().setUp()
        self.ana = self.make_user("ana")
        self.bea = self.make_user("bea")
        self.carl = self.make_user("carl")
        with app.app_context():
            for uid in (self.ana, self.bea):
                u = db.session.get(User, uid)
                u.sex = "hombre"
                db.session.add(BodyWeightEntry(user_id=uid, weight=80, timestamp=self.NOW - timedelta(days=40)))
            db.session.commit()

    def lift(self, uid, exercise, weight, days_ago):
        with app.app_context():
            w = Workout(user_id=uid, timestamp=self.NOW - timedelta(days=days_ago), performance_rating=7)
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise=exercise, weight=weight, reps=1, rir=0, completed=True))
            db.session.commit()

    def code_of(self, uid):
        with app.app_context():
            return social.friend_code(db.session.get(User, uid))

    def befriend(self, a, b):
        code = self.code_of(b)
        self.login(a)
        self.client.post("/amigos/anadir", data={"code": code})
        with app.app_context():
            fid = db.session.scalar(sa.select(Friendship.id).where(Friendship.requester_id == a, Friendship.addressee_id == b))
        self.login(b)
        self.client.post(f"/amigos/{fid}/aceptar")
        return fid

    def test_request_needs_acceptance(self):
        code = self.code_of(self.bea)
        self.login(self.ana)
        self.client.post("/amigos/anadir", data={"code": code.lower()})  # el código no distingue mayúsculas
        with app.app_context():
            self.assertFalse(social.are_friends(self.ana, self.bea))
        html = self.client.get(f"/atleta/{self.bea}", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Solo puedes ver la tarjeta de tus amigos", html)
        self.login(self.bea)
        self.assertIn("ana", self.client.get("/amigos").get_data(as_text=True))  # solicitud recibida
        with app.app_context():
            fid = db.session.scalar(sa.select(Friendship.id))
        self.client.post(f"/amigos/{fid}/aceptar")
        with app.app_context():
            self.assertTrue(social.are_friends(self.ana, self.bea))
            self.assertEqual(social.friend_ids(self.ana), [self.bea])

    def test_invite_link_asks_before_adding(self):
        code = self.code_of(self.ana)
        self.login(self.bea)
        html = self.client.get(f"/amigos/invitar/{code}").get_data(as_text=True)
        self.assertIn("ana te invita", html)
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Friendship)), 0)
        self.assertIn("propio", self.client.get(f"/amigos/invitar/{self.code_of(self.bea)}", follow_redirects=True).get_data(as_text=True))

    def test_card_hides_bodyweight_by_default_and_respects_choices(self):
        self.befriend(self.ana, self.bea)
        self.lift(self.bea, "press de banca", 100, 3)
        with app.app_context():
            db.session.add(UserAchievement(user_id=self.bea, code="workouts_1", unlocked_at=self.NOW))
            db.session.commit()
        self.login(self.bea)
        self.client.post("/rango/tarjeta", data={"in_rankings": "on", "show_rank": "on", "show_kg": "on",
                                                 "lift": ["press de banca"], "achievement": ["workouts_1", "no_existe"]})
        with app.app_context():
            card = db.session.get(AthleteCard, self.bea)
            self.assertFalse(card.show_bodyweight)
            self.assertFalse(card.show_level)
            self.assertEqual(json.loads(card.featured_achievements), ["workouts_1"])  # solo los suyos
        own = self.client.get(f"/atleta/{self.bea}").get_data(as_text=True)
        self.assertIn("oculto para tus amigos", own)  # ella ve lo que oculta
        self.login(self.ana)
        seen = self.client.get(f"/atleta/{self.bea}").get_data(as_text=True)
        self.assertIn("Press De Banca", seen)
        self.assertIn("100 × 1", seen)
        self.assertIn("Primer paso", seen)  # logro destacado
        self.assertNotIn("peso corporal", seen)
        self.assertNotIn("Nivel</small>", seen)
        self.assertNotIn("oculto para tus amigos", seen)

    def test_card_does_not_leak_bodyweight_or_hidden_rank(self):
        """Con el peso oculto, el 1RM de dominadas (peso + lastre) no se
        enseña; con el rango oculto, tampoco el de cada levantamiento."""
        self.befriend(self.ana, self.bea)
        self.lift(self.bea, "dominadas", 10, 3)
        self.lift(self.bea, "press de banca", 100, 3)
        self.login(self.bea)
        self.client.post("/rango/tarjeta", data={"in_rankings": "on", "show_kg": "on",
                                                 "lift": ["dominadas", "press de banca"]})
        own = self.client.get(f"/atleta/{self.bea}").get_data(as_text=True)
        self.assertEqual(own.count("1RM est."), 2)  # ella lo ve todo
        self.login(self.ana)
        seen = self.client.get(f"/atleta/{self.bea}").get_data(as_text=True)
        self.assertIn("10 × 1", seen)
        self.assertEqual(seen.count("1RM est."), 1)  # solo el de banca
        self.assertNotIn("rank-emblem", seen)

    def test_effort_boards_come_first_and_respect_the_card(self):
        """Progreso (contra uno mismo), récords del mes y constancia antes que el rango."""
        self.befriend(self.ana, self.bea)
        for days, kg in ((24, 100), (17, 102.5), (10, 105), (3, 107.5)):  # bea mejora cada semana
            self.lift(self.bea, "press de banca", kg, days)
        self.lift(self.ana, "press de banca", 140, 3)  # ana, más fuerte pero sin progreso medible
        with app.app_context():
            from app.routes import friends_rankings
            boards = friends_rankings(db.session.get(User, self.ana))["boards"]
            self.assertEqual(list(boards)[:4], ["progreso", "records", "constancia", "global"])
            self.assertEqual([r["user"].username for r in boards["progreso"]], ["bea"])
            self.assertGreater(boards["progreso"][0]["score"], 0)
            bea_prs = next(r["score"] for r in boards["records"] if r["user"].username == "bea")
            self.assertEqual(bea_prs, 3)  # la primera sesión no cuenta como récord
        self.login(self.bea)
        self.client.post("/rango/tarjeta", data={"in_rankings": "on", "show_rank": "on"})  # sin "show_progress"
        with app.app_context():
            from app import datacache
            datacache.clear()
            boards = friends_rankings(db.session.get(User, self.ana))["boards"]
            self.assertEqual(boards["progreso"], [])
            self.assertNotIn("bea", [r["user"].username for r in boards["records"]])

    def test_rankings_only_friends_and_opt_out(self):
        self.befriend(self.ana, self.bea)
        for uid, kg in ((self.ana, 100), (self.bea, 120), (self.carl, 200)):
            for lift in ("press de banca", "sentadilla", "peso muerto"):
                self.lift(uid, lift, kg, 5)
                self.lift(uid, lift, kg, 3)
        self.login(self.ana)
        html = self.client.get("/rango").get_data(as_text=True)
        self.assertIn("Con tus amigos", html)
        self.assertIn(">bea<", html.replace(" ", ""))
        self.assertNotIn("carl", html)  # no es amigo
        self.login(self.bea)
        self.client.post("/rango/tarjeta", data={})  # todo apagado: fuera de los rankings
        self.login(self.ana)
        self.assertNotIn(f"/atleta/{self.bea}\"", self.client.get("/rango").get_data(as_text=True))

    def test_unconfirmed_big_jump_does_not_count_in_rankings(self):
        self.lift(self.ana, "press de banca", 80, 30)
        self.lift(self.ana, "press de banca", 130, 2)  # +62 % de golpe, sin repetir
        with app.app_context():
            p = std.strength_profile(db.session.get(User, self.ana))
        bench = p["lifts"]["bench"]
        ths = std.thresholds("hombre", "bench", 80)
        self.assertAlmostEqual(bench["score"], std.strength_score(130, ths))          # en su perfil cuenta
        self.assertAlmostEqual(bench["ranking_score"], std.strength_score(80, ths))   # en el ranking, no
        self.lift(self.ana, "press de banca", 125, 1)  # lo confirma
        with app.app_context():
            p = std.strength_profile(db.session.get(User, self.ana))
        self.assertAlmostEqual(p["lifts"]["bench"]["ranking_score"], std.strength_score(130, ths))

    def test_delete_user_removes_social_data(self):
        self.befriend(self.ana, self.bea)
        self.login(self.ana)
        self.client.post("/rango/tarjeta", data={"show_rank": "on"})
        with app.app_context():
            progression.delete_user_data(self.ana)
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Friendship)), 0)
            self.assertIsNone(db.session.get(AthleteCard, self.ana))
