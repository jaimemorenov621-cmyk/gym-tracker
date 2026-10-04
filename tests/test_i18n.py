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

    def test_english_pages_are_translated(self):
        self.login(self.uid)
        en = {"Accept-Language": "en-US,en;q=0.9"}
        html = self.client.get("/index", headers=en).get_data(as_text=True)
        self.assertIn("Home", html)
        self.assertNotIn("Inicio", html)
        html = self.client.get("/rango", headers=en).get_data(as_text=True)
        self.assertIn("Iron", html)
        self.assertNotIn("Hierro", html)
        html = self.client.get("/settings", headers=en).get_data(as_text=True)
        self.assertIn('window.GYRE_NUM_LOCALE = "en-US"', html)
        self.assertIn('"Cerrar": "Close"', html)  # textos de los .js estáticos

    def test_numbers_and_dates_follow_the_language(self):
        from app.routes import fmt_num
        with app.test_request_context(headers={"Accept-Language": "en"}):
            self.assertEqual(fmt_num(1234.5), "1,234.5")
        with app.test_request_context(headers={"Accept-Language": "es"}):
            self.assertEqual(fmt_num(1234.5), "1.234,5")


class CatalogTests(DbTestCase):
    """El catálogo inglés está completo y compilado (pybabel compile)."""

    PO = "app/translations/en/LC_MESSAGES/messages.po"

    def catalog(self):
        import io
        from babel.messages.pofile import read_po
        with io.open(self.PO, "rb") as f:
            return read_po(f, locale="en")

    def test_everything_translated_and_compiled(self):
        from babel.support import Translations
        mo = Translations.load("app/translations", ["en"])
        for m in self.catalog():
            if not m.id:
                continue
            self.assertNotIn("fuzzy", m.flags, m.id)
            strings = m.string if isinstance(m.id, tuple) else (m.string,)
            self.assertTrue(all(strings), f"sin traducir: {m.id!r}")
            if isinstance(m.id, tuple):
                got = mo.unpgettext(m.context, m.id[0], m.id[1], 2) if m.context else mo.ungettext(m.id[0], m.id[1], 2)
                self.assertEqual(got, m.string[1], "messages.mo desactualizado: pybabel compile")
            else:
                got = mo.upgettext(m.context, m.id) if m.context else mo.ugettext(m.id)
                self.assertEqual(got, m.string, "messages.mo desactualizado: pybabel compile")

    def test_placeholders_match(self):
        import re
        ph = re.compile(r"%\(\w+\)[sd]|\{\w+\}")
        for m in self.catalog():
            if not m.id:
                continue
            pairs = zip(m.id, m.string) if isinstance(m.id, tuple) else [(m.id, m.string)]
            for src, tr in pairs:
                # el singular puede omitir el número ("Récord en esta sesión")
                self.assertEqual(set(ph.findall(src)) - {"%(num)d"}, set(ph.findall(tr)) - {"%(num)d"}, src)

    def test_js_strings_are_in_the_catalog(self):
        from app.i18n import JS_STRINGS
        ids = {m.id for m in self.catalog()}
        for text in JS_STRINGS:
            self.assertIn(text, ids, "falta en el catálogo: pybabel extract + update")

    def test_every_source_text_is_in_the_catalog(self):
        """Falla si se añade un texto traducible sin pasar tools/i18n_update.py."""
        import io
        from babel.messages.extract import DEFAULT_KEYWORDS, extract_from_dir
        from babel.messages.frontend import parse_keywords, parse_mapping_cfg
        from app.i18n import EXTRACT_KEYWORDS

        keywords = dict(DEFAULT_KEYWORDS)
        keywords.update(parse_keywords(EXTRACT_KEYWORDS))
        with io.open("babel.cfg", encoding="utf-8") as f:
            method_map, options_map = parse_mapping_cfg(f)
        known = {(m.id if isinstance(m.id, str) else m.id[0], m.context) for m in self.catalog()}
        missing, seen = set(), 0
        for _fn, _line, msg, _comments, ctx in extract_from_dir(".", method_map, options_map, keywords):
            seen += 1
            msgid = msg if isinstance(msg, str) else msg[0]
            if msgid and (msgid, ctx) not in known:
                missing.add(msgid)
        self.assertGreater(seen, 1000)  # la extracción de verdad ha encontrado los textos
        self.assertFalse(missing, f"textos sin catalogar (python tools/i18n_update.py): {sorted(missing)[:10]}")
