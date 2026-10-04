"""Seguimiento por canal (?ref=) de la landing y endpoint de compartir récord.

Uso (desde la raíz del repo):
    python -m unittest discover -s tests -t .
    python -m unittest tests.test_landing_share
"""
import unittest
from datetime import datetime, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import LandingEvent, SetEntry, User, Workout
from app.routes import REF_COOKIE, _clean_ref, estimated_1rm


class CleanRefTests(unittest.TestCase):
    def test_valid_ref_kept(self):
        self.assertEqual(_clean_ref("mediavida"), "mediavida")

    def test_lowercased_and_trimmed(self):
        self.assertEqual(_clean_ref("  MediaVida "), "mediavida")

    def test_allowed_symbols(self):
        self.assertEqual(_clean_ref("gym_madrid-2"), "gym_madrid-2")

    def test_invalid_chars_rejected_not_sanitized(self):
        self.assertIsNone(_clean_ref("media vida"))
        self.assertIsNone(_clean_ref("<script>"))
        self.assertIsNone(_clean_ref("mediavida!"))
        self.assertIsNone(_clean_ref("ñandú"))

    def test_length_limit(self):
        self.assertEqual(_clean_ref("a" * 20), "a" * 20)
        self.assertIsNone(_clean_ref("a" * 21))

    def test_empty(self):
        self.assertIsNone(_clean_ref(None))
        self.assertIsNone(_clean_ref(""))
        self.assertIsNone(_clean_ref("   "))


class RefTrackingTests(DbTestCase):
    def _register(self, username="nuevo"):
        return self.client.post(
            "/register",
            data={
                "username": username,
                "email": f"{username}@example.com",
                "password": "tmpPass2026",
                "password2": "tmpPass2026",
            },
        )

    def _sources(self, event_type):
        with app.app_context():
            return db.session.scalars(
                sa.select(LandingEvent.source)
                .where(LandingEvent.event_type == event_type)
                .order_by(LandingEvent.id)
            ).all()

    def _new_user(self):
        with app.app_context():
            u = db.session.scalar(sa.select(User).where(User.username == "nuevo"))
            return {"source": u.signup_source, "method": u.signup_method, "created_at": u.created_at}

    def test_tagged_visit_sets_cookie_and_is_inherited_by_signup(self):
        resp = self.client.get("/?ref=mediavida")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(f"{REF_COOKIE}=mediavida", resp.headers.get("Set-Cookie", ""))

        self.client.get("/")  # vuelve sin etiqueta: la visita no hereda canal
        self.client.get("/landing/cta")  # el clic sí, vía cookie
        resp = self._register()
        self.assertEqual(resp.status_code, 302)

        self.assertEqual(self._sources("visit"), ["mediavida", None])
        self.assertEqual(self._sources("cta_click"), ["mediavida"])
        user = self._new_user()
        self.assertEqual(user["source"], "mediavida")
        self.assertEqual(user["method"], "password")
        self.assertIsNotNone(user["created_at"])

    def test_last_tagged_link_wins(self):
        self.client.get("/?ref=mediavida")
        self.client.get("/?ref=gym")
        self.client.get("/")  # sin etiqueta: no borra la cookie
        self.client.get("/landing/google")
        self._register()

        self.assertEqual(self._sources("google_click"), ["gym"])
        self.assertEqual(self._new_user()["source"], "gym")

    def test_invalid_ref_not_stored_nor_cookie(self):
        resp = self.client.get("/?ref=%3Cscript%3E")
        self.assertNotIn(REF_COOKIE, resp.headers.get("Set-Cookie", ""))
        self.assertEqual(self._sources("visit"), [None])
        self._register()
        self.assertIsNone(self._new_user()["source"])

    def test_no_contar_skips_logging(self):
        self.client.get("/?ref=mediavida&no_contar=1")
        self.assertEqual(self._sources("visit"), [])

    def test_healthz_does_not_log_visit(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"ok")
        self.assertEqual(self._sources("visit"), [])


class ShareSetTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.owner_id = self.make_user("owner")
        self.other_id = self.make_user("other")

    def _add_set(self, day, weight, reps, rir=None, completed=True, exercise="sentadilla"):
        """Devuelve (id de la serie, 1RM estimado con la fórmula de la app)."""
        with app.app_context():
            w = Workout(user_id=self.owner_id, timestamp=datetime(2026, 9, day, 18, 0, tzinfo=timezone.utc))
            db.session.add(w)
            db.session.flush()
            s = SetEntry(workout_id=w.id, exercise=exercise, weight=weight, reps=reps, rir=rir, completed=completed)
            db.session.add(s)
            db.session.commit()
            return s.id, estimated_1rm(s)

    def test_requires_login(self):
        set_id, _ = self._add_set(1, 100, 5)
        resp = self.client.get(f"/set/{set_id}/share")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_other_user_forbidden(self):
        set_id, _ = self._add_set(1, 100, 5)
        self.login(self.other_id)
        resp = self.client.get(f"/set/{set_id}/share")
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.get_json()["ok"])

    def test_missing_set_404(self):
        self.login(self.owner_id)
        self.assertEqual(self.client.get("/set/99999/share").status_code, 404)

    def test_incomplete_set_rejected(self):
        set_id, _ = self._add_set(1, 100, 5, completed=False)
        self.login(self.owner_id)
        self.assertEqual(self.client.get(f"/set/{set_id}/share").status_code, 400)

    def test_first_session_has_no_improvement(self):
        set_id, e1rm = self._add_set(1, 100, 5, rir=2)
        self.login(self.owner_id)
        data = self.client.get(f"/set/{set_id}/share").get_json()
        self.assertTrue(data["ok"])
        self.assertIsNone(data["improvement"])
        self.assertEqual(data["e1rm"], round(e1rm))
        self.assertEqual(data["exercise"], "Sentadilla")
        self.assertEqual(data["weight"], "100")
        self.assertIn("ref=compartir", data["share_url"])

    def test_improvement_against_previous_best(self):
        _, first_e1rm = self._add_set(1, 100, 5, rir=2)
        second_id, second_e1rm = self._add_set(8, 110, 5, rir=2)
        self.login(self.owner_id)
        data = self.client.get(f"/set/{second_id}/share").get_json()
        self.assertEqual(data["improvement"], round(second_e1rm - first_e1rm, 1))
        self.assertGreater(data["improvement"], 0)

    def test_later_sessions_do_not_count_as_previous(self):
        first_id, _ = self._add_set(1, 100, 5, rir=2)
        self._add_set(8, 120, 5, rir=2)  # posterior y mejor: no es "anterior"
        self.login(self.owner_id)
        data = self.client.get(f"/set/{first_id}/share").get_json()
        self.assertIsNone(data["improvement"])


class LanguageTests(DbTestCase):
    def test_browser_language_saved(self):
        self.client.get("/", headers={"Accept-Language": "en-US,en;q=0.9,es;q=0.8"})
        self.client.get("/", headers={"Accept-Language": "es-ES"})
        self.client.get("/", headers={"Accept-Language": "*"})
        with app.app_context():
            langs = db.session.scalars(sa.select(LandingEvent.language).order_by(LandingEvent.id)).all()
        self.assertEqual(langs, ["en", "es", None])


if __name__ == "__main__":
    unittest.main()


class SafeNextTests(unittest.TestCase):
    def test_only_local_paths(self):
        from app import app
        from app.routes import safe_next
        with app.test_request_context():
            home = safe_next(None)
            self.assertEqual(safe_next("/progress?x=1"), "/progress?x=1")
            for bad in ("//evil.com", "/\evil.com", "https://evil.com", "evil.com", "/\\evil.com"):
                self.assertEqual(safe_next(bad), home, bad)
