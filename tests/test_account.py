"""Ajustes > Descargar mis datos, Borrar mi cuenta y Contacto."""
import json
import unittest
from datetime import datetime, timezone

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db
from app.models import ContactMessage, SetEntry, User, Workout


class AccountTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("borrable")
        self.other = self.make_user("otro")
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=datetime.now(timezone.utc).replace(tzinfo=None), performance_rating=7)
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise="press de banca", weight=60, reps=5, completed=True))
            db.session.commit()

    def test_export_downloads_own_data_without_secrets(self):
        self.login(self.uid)
        r = self.client.get("/cuenta/exportar")
        self.assertIn("attachment", r.headers["Content-Disposition"])
        data = json.loads(r.get_data(as_text=True))
        self.assertEqual(data["user"]["username"], "borrable")
        self.assertNotIn("password_hash", data["user"])
        self.assertEqual(len(data["set_entry"]), 1)

    def test_delete_needs_the_exact_username(self):
        self.login(self.uid)
        html = self.client.post("/cuenta/borrar", data={"confirm": "otro"}).get_data(as_text=True)
        self.assertIn("exactamente igual", html)
        with app.app_context():
            self.assertIsNotNone(db.session.get(User, self.uid))
        r = self.client.post("/cuenta/borrar", data={"confirm": "borrable"})
        self.assertEqual(r.status_code, 302)
        with app.app_context():
            self.assertIsNone(db.session.get(User, self.uid))
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(SetEntry)), 0)
            self.assertIsNotNone(db.session.get(User, self.other))  # los demás, intactos
        self.assertEqual(self.client.get("/index").status_code, 302)  # sesión cerrada

    def test_contact_message_is_stored_rate_limited_and_deleted_with_the_account(self):
        self.login(self.uid)
        for i in range(7):
            self.client.post("/contacto", data={"body": f"hola {i}"})
        self.client.post("/contacto", data={"body": "   "})
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(ContactMessage)), 5)
        self.client.post("/cuenta/borrar", data={"confirm": "borrable"})
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(ContactMessage)), 0)


if __name__ == "__main__":
    unittest.main()
