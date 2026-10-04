from tests.dbcase import DbTestCase
from app import app, db
from app.models import User


class LocaleTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self._enabled = app.config.get("I18N_ENABLED")
        app.config["I18N_ENABLED"] = True
        self.uid = self.make_user("lang")

    def tearDown(self):
        app.config["I18N_ENABLED"] = self._enabled
        super().tearDown()

    def lang_of(self, html):
        return html.split('<html lang="', 1)[1].split('"', 1)[0]

    def test_follows_the_browser(self):
        html = self.client.get("/login", headers={"Accept-Language": "en-US,en;q=0.9"}).get_data(as_text=True)
        self.assertEqual(self.lang_of(html), "en")
        html = self.client.get("/login", headers={"Accept-Language": "fr-FR,fr"}).get_data(as_text=True)
        self.assertEqual(self.lang_of(html), "es")  # idioma sin traducir: español

    def test_user_choice_wins_and_auto_goes_back_to_the_browser(self):
        self.login(self.uid)
        self.client.post("/idioma", data={"language": "en"})
        with app.app_context():
            self.assertEqual(db.session.get(User, self.uid).language, "en")
        html = self.client.get("/settings", headers={"Accept-Language": "es-ES"}).get_data(as_text=True)
        self.assertEqual(self.lang_of(html), "en")
        self.client.post("/idioma", data={"language": ""})
        html = self.client.get("/settings", headers={"Accept-Language": "es-ES"}).get_data(as_text=True)
        self.assertEqual(self.lang_of(html), "es")

    def test_hidden_until_enabled(self):
        app.config["I18N_ENABLED"] = False
        html = self.client.get("/login", headers={"Accept-Language": "en"}).get_data(as_text=True)
        self.assertEqual(self.lang_of(html), "es")
