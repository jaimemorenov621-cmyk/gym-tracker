"""Primera cobertura automatizada del repo (unittest de la stdlib, sin
dependencia nueva). Cubre las rutas críticas de calculo de 1RM/PR/
estancamiento y el helper de RIR/RPE como rango, tras el fix de sesiones
fantasma en el historial de un ejercicio.

Uso:
    python -m unittest tests.test_progress
"""
import os
import unittest
from datetime import datetime, timezone

# Config.SQLALCHEMY_DATABASE_URI se lee de esta variable en el momento en
# que se importa `app` (app.config.from_object(Config) en app/__init__.py,
# que engancha el motor de Flask-SQLAlchemy de inmediato) -- fijarla DESPUÉS
# de importar no sirve, Flask-SQLAlchemy ya habría fijado el motor contra
# el app.db real. Tiene que ir antes de la primera importación de `app`.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app import app, db
from app.models import SetEntry, User, Workout
from app.routes import _parse_single_int, get_exercise_sessions, qualifying_sessions


class ParseSingleIntTests(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(_parse_single_int(None))

    def test_simple_number(self):
        self.assertEqual(_parse_single_int("2"), 2)

    def test_range_returns_none(self):
        self.assertIsNone(_parse_single_int("2-3"))

    def test_clamped_above_ten(self):
        self.assertEqual(_parse_single_int("50"), 10)

    def test_clamped_below_zero(self):
        self.assertEqual(_parse_single_int("-5"), 0)

    def test_non_numeric_text(self):
        self.assertIsNone(_parse_single_int("aprox 2"))


class QualifyingSessionsTests(unittest.TestCase):
    def test_filters_by_best_set(self):
        sessions = [
            {"timestamp": 1, "best_set": object(), "best_1rm": 50, "is_pr": True},
            {"timestamp": 2, "best_set": None, "best_1rm": 0, "is_pr": False},
            {"timestamp": 3, "best_set": object(), "best_1rm": 60, "is_pr": True},
        ]
        result = qualifying_sessions(sessions)
        self.assertEqual([s["timestamp"] for s in result], [1, 3])

    def test_empty_list(self):
        self.assertEqual(qualifying_sessions([]), [])


class GetExerciseSessionsIntegrationTests(unittest.TestCase):
    """Test de integración contra una base SQLite en memoria -- confirma que
    get_exercise_sessions() sigue devolviendo TODAS las sesiones (necesario
    para recompute_pr_badges/los scripts de backfill), pero que
    qualifying_sessions() excluye correctamente las sesiones fantasma
    (sin ninguna serie completada con peso/reps reales)."""

    @classmethod
    def setUpClass(cls):
        # Salvaguarda: si esto no es ":memory:", algo salió mal aislando la
        # base de datos -- abortar antes de que create_all()/drop_all()
        # toquen una base real (ya nos pasó una vez).
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        assert ":memory:" in uri, f"Test DB no aislada, abortando: {uri!r}"
        cls.ctx = app.app_context()
        cls.ctx.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.ctx.pop()

    def setUp(self):
        self.user = User(username="test_user", email="test@example.com")
        self.user.set_password("testpass")
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.create_all()

    def _add_workout(self, day, sets):
        w = Workout(user_id=self.user.id, timestamp=datetime(2026, 8, day, tzinfo=timezone.utc))
        db.session.add(w)
        db.session.flush()
        for weight, reps, completed in sets:
            db.session.add(
                SetEntry(
                    exercise="press banca",
                    weight=weight,
                    reps=reps,
                    completed=completed,
                    workout_id=w.id,
                )
            )
        return w

    def test_ghost_session_excluded_from_qualifying_but_not_from_full_list(self):
        # Sesión fantasma: placeholder de rutina sin rellenar.
        self._add_workout(20, [(0, 0, False)])
        # Sesión real, completada.
        self._add_workout(25, [(80, 5, True)])
        # Sesión mixta: una serie real completada, otra todavía vacía.
        self._add_workout(31, [(82, 5, True), (0, 0, False)])
        db.session.commit()

        session_list, _, _ = get_exercise_sessions("press banca", user_id=self.user.id)
        self.assertEqual(len(session_list), 3, "session_list debe seguir completo, sin filtrar")

        qualifying = qualifying_sessions(session_list)
        self.assertEqual(len(qualifying), 2, "la sesión 100% fantasma debe quedar fuera")
        self.assertTrue(all(s["best_1rm"] > 0 for s in qualifying))


if __name__ == "__main__":
    unittest.main()
