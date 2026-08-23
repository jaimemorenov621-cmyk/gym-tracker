from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login = LoginManager(app)
login.login_view = "login"

from app import routes, models
from app.routes import format_rest, get_exercise_image, to_local

app.jinja_env.globals["format_rest"] = format_rest
app.jinja_env.globals["get_exercise_image"] = get_exercise_image
app.jinja_env.globals["to_local"] = to_local
