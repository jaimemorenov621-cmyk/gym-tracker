"""Errores 500 guardados para verlos en /landing/stats (app/errorlog.py).

Uso:
    python -m unittest tests.test_errorlog
"""
from unittest import mock

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import ErrorLog
from app.routes import ADMIN_USERNAME


class ErrorLogTests(DbTestCase):
    def boom(self):
        raise ValueError("fallo de prueba")

    def test_unhandled_error_is_saved_and_shown_to_admin(self):
        uid = self.make_user("atleta")
        self.login(uid)
        with mock.patch.dict(app.view_functions, {"level_page": self.boom}):
            self.assertEqual(self.client.get("/nivel").status_code, 500)
        with app.app_context():
            row = db.session.scalar(sa.select(ErrorLog))
        self.assertEqual((row.method, row.path, row.user_id), ("GET", "/nivel", uid))
        self.assertIn("ValueError: fallo de prueba", row.error)
        self.assertIn("Traceback", row.traceback)
        admin = self.make_user(ADMIN_USERNAME)
        self.login(admin)
        html = self.client.get("/landing/stats").get_data(as_text=True)
        self.assertIn("Errores del servidor", html)
        self.assertIn("fallo de prueba", html)

    def test_keeps_only_the_latest(self):
        from app import errorlog
        uid = self.make_user("atleta")
        self.login(uid)
        with mock.patch.object(errorlog, "KEEP", 3), mock.patch.dict(app.view_functions, {"level_page": self.boom}):
            for _ in range(5):
                self.assertEqual(self.client.get("/nivel").status_code, 500)
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(ErrorLog)), 3)

    def test_failed_ai_analysis_is_recorded_too(self):
        from app.models import Workout
        uid = self.make_user("atleta")
        with app.app_context():
            for _ in range(5):
                db.session.add(Workout(user_id=uid))
            db.session.commit()
        self.login(uid)
        with mock.patch("app.routes.generate_ai_analysis", side_effect=RuntimeError("insufficient_quota")), \
                mock.patch("app.routes.MIN_WORKOUTS_FOR_AI_ANALYSIS", 1):
            resp = self.client.post("/ai/analyze", data={})
        self.assertEqual(resp.status_code, 302)  # el usuario ve el aviso, no un error
        with app.app_context():
            row = db.session.scalar(sa.select(ErrorLog))
        self.assertIn("insufficient_quota", row.error)

