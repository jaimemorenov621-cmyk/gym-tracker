"""Idioma de la app (Flask-Babel).

Orden: 1) el que el usuario eligió en Ajustes (User.language); 2) sin
sesión, la cookie "lang"; 3) el idioma del navegador/móvil
(Accept-Language); 4) español.

Mientras I18N_ENABLED no esté activo (config), todo va en español: la
traducción se sube por partes y no debe verse a medias.

Textos nuevos: envolverlos en _() / ngettext() (plantillas y Python) o
lazy_gettext() si se definen al importar un módulo. Después:
    pybabel extract -F babel.cfg -o messages.pot .
    pybabel update -i messages.pot -d app/translations
    (traducir en app/translations/en/LC_MESSAGES/messages.po)
    pybabel compile -d app/translations
"""
from flask import current_app, has_request_context, request
from flask_login import current_user

LANGUAGES = {"es": "Español", "en": "English"}
DEFAULT = "es"


def enabled():
    return bool(current_app.config.get("I18N_ENABLED"))


def select_locale():
    if not enabled() or not has_request_context():
        return DEFAULT
    try:
        if current_user.is_authenticated and current_user.language in LANGUAGES:
            return current_user.language
    except Exception:  # sin usuario cargable (p. ej. errores tempranos)
        pass
    cookie = request.cookies.get("lang")
    if cookie in LANGUAGES:
        return cookie
    return request.accept_languages.best_match(list(LANGUAGES)) or DEFAULT
