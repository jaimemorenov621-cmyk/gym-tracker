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
    HiddenField,
)


class CommaFloatField(FloatField):
    """FloatField que acepta coma o punto como separador decimal."""

    def process_formdata(self, valuelist):
        if valuelist and valuelist[0]:
            valuelist = [valuelist[0].replace(",", ".")]
        super().process_formdata(valuelist)
from wtforms.validators import (
    DataRequired,
    InputRequired,
    Optional,
    Email,
    EqualTo,
    ValidationError,
    NumberRange,
    Length,
    Regexp,
)
import sqlalchemy as sa
from app import db
from app.models import User


class LoginForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired("Campo obligatorio.")])
    password = PasswordField("Contraseña", validators=[DataRequired("Campo obligatorio.")])
    remember_me = BooleanField("Recordarme")
    submit = SubmitField("Iniciar sesión")


class RegistrationForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired("Elige un nombre de usuario.")])
    email = StringField(
        "Email",
        validators=[DataRequired("Escribe tu email."), Email("Ese email no parece válido.")],
    )
    password = PasswordField("Contraseña", validators=[DataRequired("Elige una contraseña.")])
    password2 = PasswordField(
        "Repite la contraseña",
        validators=[
            DataRequired("Repite la contraseña."),
            EqualTo("password", "Las contraseñas no coinciden."),
        ],
    )
    submit = SubmitField("Crear cuenta gratis")

    def validate_username(self, username):
        user = db.session.scalar(sa.select(User).where(User.username == username.data))
        if user is not None:
            raise ValidationError("Ese usuario ya existe, prueba con otro.")

    def validate_email(self, email):
        user = db.session.scalar(sa.select(User).where(User.email == email.data))
        if user is not None:
            raise ValidationError("Ya hay una cuenta con ese email. ¿Quieres iniciar sesión?")


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


class AiCheckinForm(FlaskForm):
    how_you_feel = TextAreaField(
        "¿Cómo te sientes? (fatiga, agujetas, sueño, estrés...)",
        validators=[Optional(), Length(max=500)],
    )
    submit = SubmitField("🔍 Analizar mi progreso")


class WeightForm(FlaskForm):
    weight = CommaFloatField(
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
        choices=[("rir", "RIR"), ("rpe", "RPE")],
        default="rir",
    )
    rest_sound_enabled = BooleanField("Sonido de notificación del descanso")
    rest_vibration_enabled = BooleanField("Vibración del descanso")
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
    weekly_workout_goal = IntegerField(
        "Objetivo de entrenamientos por semana (para la racha)",
        validators=[Optional(), NumberRange(min=1, max=14)],
    )
    disable_weekly_goal = BooleanField(
        "Desactivar el objetivo semanal (volver a racha por días)"
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
    duration_hours = IntegerField(
        "Horas",
        validators=[InputRequired(), NumberRange(min=0, max=23)],
        render_kw={"min": 0, "max": 23},
    )
    duration_minutes = IntegerField(
        "Minutos",
        validators=[InputRequired(), NumberRange(min=0, max=59)],
        render_kw={"min": 0, "max": 59},
    )
    submit = SubmitField("Guardar entrenamiento")


class NotesForm(FlaskForm):
    notes = TextAreaField("Notas generales", validators=[Length(max=1000)])


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
    effort_value = StringField(
        "RIR/RPE objetivo (ej: 2 o 2-3)",
        validators=[
            Optional(),
            Length(max=16),
            Regexp(r"^\d{1,2}(-\d{1,2})?$", message="Usa un número (ej. 2) o un rango (ej. 2-3)"),
        ],
    )
    replace_ex_id = HiddenField(validators=[Optional()])
    submit = SubmitField("Añadir ejercicio")


class NewExerciseForm(FlaskForm):
    exercise = StringField("Ejercicio", validators=[DataRequired(), Length(max=64)])
    submit = SubmitField("Añadir ejercicio")


class ExerciseTranslationForm(FlaskForm):
    name_es = StringField(
        "Nombre en español", validators=[Optional(), Length(max=120)]
    )
    submit = SubmitField("Guardar")
