from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth
from flask_babel import Babel, get_locale

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login = LoginManager(app)
login.login_view = "login"

from app import i18n  # noqa: E402

babel = Babel(app, locale_selector=i18n.select_locale)

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

from app import routes, models, progression  # progression: listeners de la caché de XP
from app.routes import format_rest, get_exercise_image, to_local, fmt_num, relative_day

app.jinja_env.globals["format_rest"] = format_rest
app.jinja_env.globals["get_exercise_image"] = get_exercise_image
app.jinja_env.globals["to_local"] = to_local
app.jinja_env.filters["num"] = fmt_num
app.jinja_env.filters["relative_day"] = relative_day
app.jinja_env.globals["reps_range"] = routes.reps_range
app.jinja_env.globals["LANGUAGES"] = i18n.LANGUAGES
app.jinja_env.globals["i18n_enabled"] = i18n.enabled
app.jinja_env.globals["get_locale"] = get_locale
