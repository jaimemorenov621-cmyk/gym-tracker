"""Base para tests que usan base de datos y cliente HTTP.

Importar este módulo ANTES que `app`: fija la base en memoria, que Flask-
SQLAlchemy lee al importar la app (mismo motivo que en test_progress.py).
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import unittest  # noqa: E402

from app import app, db  # noqa: E402
from app.models import User  # noqa: E402


class DbTestCase(unittest.TestCase):
    """Base en memoria. OJO: no se deja un app context abierto entre
    peticiones -- Flask-Login cachea el usuario en `g` (vive en el app
    context), y un contexto compartido haría que el usuario de una petición
    se colara en la siguiente (falsos "sin sesión -> 200"). Cada operación de
    BD del test abre su propio contexto con `with app.app_context()`."""

    @classmethod
    def setUpClass(cls):
        # Salvaguarda: nunca tocar una base real.
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        assert ":memory:" in uri, f"Test DB no aislada, abortando: {uri!r}"
        cls._csrf = app.config.get("WTF_CSRF_ENABLED", True)
        app.config["WTF_CSRF_ENABLED"] = False
        # Toda escritura masiva en tablas del XP sin revisar rompe el test
        # (ver app/progression.py).
        app.config["XP_STRICT_BULK_DML"] = True
        with app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.drop_all()
        app.config["WTF_CSRF_ENABLED"] = cls._csrf

    def setUp(self):
        self.client = app.test_client()

    def tearDown(self):
        with app.app_context():
            db.drop_all()
            db.create_all()

    def make_user(self, username):
        with app.app_context():
            user = User(username=username, email=f"{username}@example.com")
            user.set_password("testpass")
            db.session.add(user)
            db.session.commit()
            return user.id

    def login(self, user_id, client=None):
        with (client or self.client).session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True
