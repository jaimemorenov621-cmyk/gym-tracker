import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "you-will-never-guess"
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL"
    ) or "sqlite:///" + os.path.join(basedir, "app.db")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    # Inglés (app/i18n.py). I18N_ENABLED=0 lo apaga y deja todo en español.
    I18N_ENABLED = os.environ.get("I18N_ENABLED", "1") == "1"
    BABEL_DEFAULT_LOCALE = "es"
    BABEL_DEFAULT_TIMEZONE = "Europe/Madrid"

    # Cookies de sesión: SameSite=Lax explícito (sin él, Chrome deja pasar un
    # POST de otra web en los 2 primeros minutos; las rutas JSON no llevan token
    # CSRF) y solo por HTTPS en Render (en local se usa http).
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = REMEMBER_COOKIE_SECURE = bool(os.environ.get("RENDER"))
    SESSION_COOKIE_HTTPONLY = REMEMBER_COOKIE_HTTPONLY = True

