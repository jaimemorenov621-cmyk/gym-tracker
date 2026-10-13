"""Caché de datos derivados (app/datacache.py): cálculo compartido entre hilos.

Uso:
    python -m unittest tests.test_datacache
"""
import threading
import time

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

from app import app, datacache


class InflightTests(DbTestCase):
    def test_second_caller_waits_instead_of_recomputing(self):
        uid = self.make_user("atleta")
        calls = []

        def slow():
            calls.append(1)
            time.sleep(0.3)
            return "hecho"

        version = ("v",)
        results = []
        with mock_version(version):
            def first():
                with app.test_request_context():
                    results.append(datacache.cached("x", uid, slow))
            t = threading.Thread(target=first)
            t.start()
            time.sleep(0.05)  # el primero ya está calculando
            with app.test_request_context():
                from flask import g
                results.append(datacache.cached("x", uid, slow))
                noted = list(g.get("_recomputed", []))
            t.join()
        self.assertEqual(results, ["hecho", "hecho"])
        self.assertEqual(len(calls), 1)
        # La espera sale en el indicador del admin: si no, ese tiempo no tenía explicación.
        self.assertEqual(len(noted), 1)
        self.assertTrue(noted[0].startswith("x espera "), noted)


class mock_version:
    """data_version fija (la de verdad consulta la base, y cada hilo de un
    test con SQLite en memoria vería otra base vacía)."""
    def __init__(self, version):
        self.version = version

    def __enter__(self):
        self._orig = datacache.data_version
        datacache.data_version = lambda user_id: self.version

    def __exit__(self, *exc):
        datacache.data_version = self._orig
