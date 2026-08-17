from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    BooleanField,
    SubmitField,
    FloatField,
    IntegerField,
    SelectField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    InputRequired,
    Optional,
    Email,
    EqualTo,
    ValidationError,
    NumberRange,
    Length,
)
import sqlalchemy as sa
from app import db
from app.models import User


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember Me")
    submit = SubmitField("Sign In")


class RegistrationForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    password2 = PasswordField(
        "Repeat Password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Register")

    def validate_username(self, username):
        user = db.session.scalar(sa.select(User).where(User.username == username.data))
        if user is not None:
            raise ValidationError("Please use a different username.")

    def validate_email(self, email):
        user = db.session.scalar(sa.select(User).where(User.email == email.data))
        if user is not None:
            raise ValidationError("Please use a different email address.")


class WorkoutForm(FlaskForm):
    note = StringField("Nombre de la sesión (ej: Pecho y tríceps)")
    submit = SubmitField("Empezar entrenamiento")


class SetEntryForm(FlaskForm):
    exercise = StringField("Ejercicio", validators=[DataRequired()])
    weight = FloatField(
        "Peso (kg)",
        validators=[DataRequired(), NumberRange(min=0, max=500)],
        render_kw={"min": 0, "max": 500, "step": "any"},
    )
    reps = IntegerField(
        "Repeticiones",
        validators=[DataRequired(), NumberRange(min=1, max=30)],
        render_kw={"min": 1, "max": 30},
    )
    effort_value = IntegerField(
        "Valor de esfuerzo",
        validators=[Optional(), NumberRange(min=0, max=10)],
        render_kw={"min": 0, "max": 10},
    )
    set_type = SelectField(
        "Tipo de serie",
        choices=[
            ("normal", "Normal"),
            ("calentamiento", "Calentamiento"),
            ("fallo", "Al fallo"),
            ("dropset", "Dropset"),
        ],
        default="normal",
    )
    submit = SubmitField("Añadir serie")


class EmptyForm(FlaskForm):
    submit = SubmitField("Submit")


class WeightForm(FlaskForm):
    weight = FloatField(
        "Peso (kg)", validators=[DataRequired(), NumberRange(min=20, max=400)]
    )
    submit = SubmitField("Guardar")


class SettingsForm(FlaskForm):
    stagnation_threshold = IntegerField(
        "Sesiones sin récord para avisar de estancamiento",
        validators=[DataRequired(), NumberRange(min=1, max=20)],
    )
    effort_scale = SelectField(
        "¿Cómo quieres medir el esfuerzo?",
        choices=[("rir", "RIR"), ("rpe", "RPE"), ("none", "No anotar")],
        default="rir",
    )
    sex = SelectField(
        "Sexo",
        choices=[("", "Prefiero no decirlo"), ("hombre", "Hombre"), ("mujer", "Mujer")],
        validators=[Optional()],
    )
    height_cm = IntegerField(
        "Altura (cm)", validators=[Optional(), NumberRange(min=100, max=250)]
    )
    training_goal = SelectField(
        "Objetivo principal",
        choices=[
            ("", "Sin especificar"),
            ("hipertrofia", "Hipertrofia"),
            ("fuerza", "Fuerza"),
            ("perdida_grasa", "Pérdida de grasa"),
        ],
        validators=[Optional()],
    )
    submit = SubmitField("Guardar")


class FinishWorkoutForm(FlaskForm):
    performance_rating = SelectField(
        "¿Cómo ha sido tu rendimiento hoy?",
        coerce=int,
        choices=[
            (1, "1 - Pésimo: no pude completar el entrenamiento planeado"),
            (2, "2 - Muy mal: rendimiento muy por debajo de lo normal"),
            (3, "3 - Mal: peso o reps notablemente inferiores a lo habitual"),
            (4, "4 - Flojo: por debajo de lo normal"),
            (5, "5 - Regular: cumplí, sin más"),
            (6, "6 - Normal: sesión estándar, sin sorpresas"),
            (7, "7 - Bien: mejor de lo esperado en algún ejercicio"),
            (8, "8 - Muy bien: buena sensación general, progresé"),
            (9, "9 - Muy buena: cerca de mis mejores marcas"),
            (10, "10 - Excelente: nuevos récords, gran sesión"),
        ],
    )
    performance_comment = TextAreaField(
        "Comentario (opcional)", validators=[Length(max=255)]
    )
    submit = SubmitField("Guardar entrenamiento")


class ExerciseNoteForm(FlaskForm):
    notes = TextAreaField("Notas (una línea = un punto)", validators=[Length(max=1000)])
    rest_minutes = IntegerField(
        "Minutos de descanso",
        validators=[Optional(), NumberRange(min=0, max=15)],
        default=1,
    )
    rest_seconds = IntegerField(
        "Segundos de descanso",
        validators=[Optional(), NumberRange(min=0, max=59)],
        default=30,
    )
    submit = SubmitField("Guardar")


class RoutineForm(FlaskForm):
    name = StringField(
        "Nombre de la rutina (ej: Push A)", validators=[DataRequired(), Length(max=64)]
    )
    submit = SubmitField("Crear rutina")


class RoutineExerciseForm(FlaskForm):
    exercise = StringField("Ejercicio", validators=[DataRequired(), Length(max=64)])
    target_sets = IntegerField(
        "Series objetivo",
        validators=[DataRequired(), NumberRange(min=1, max=15)],
        default=3,
    )
    target_reps = StringField(
        "Reps objetivo (ej: 8-10)",
        validators=[DataRequired(), Length(max=16)],
        default="8-10",
    )
    submit = SubmitField("Añadir ejercicio")


class NewExerciseForm(FlaskForm):
    exercise = StringField("Ejercicio", validators=[DataRequired(), Length(max=64)])
    submit = SubmitField("Añadir ejercicio")


class ExerciseTranslationForm(FlaskForm):
    name_es = StringField(
        "Nombre en español", validators=[Optional(), Length(max=120)]
    )
    submit = SubmitField("Guardar")
