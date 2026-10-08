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
    SelectMultipleField,
    RadioField,
)
from wtforms.widgets import CheckboxInput, ListWidget


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
from flask_babel import lazy_gettext as _l, lazy_pgettext as _lp

from app import db
from app.models import User


class LoginForm(FlaskForm):
    username = StringField(_l("Usuario"), validators=[DataRequired(_l("Campo obligatorio."))])
    password = PasswordField(_l("Contraseña"), validators=[DataRequired(_l("Campo obligatorio."))])
    submit = SubmitField(_l("Iniciar sesión"))


class RegistrationForm(FlaskForm):
    username = StringField(_l("Usuario"), validators=[DataRequired(_l("Elige un nombre de usuario."))])
    email = StringField(
        _l("Email"),
        validators=[DataRequired(_l("Escribe tu email.")), Email(_l("Ese email no parece válido."))],
    )
    password = PasswordField(_l("Contraseña"), validators=[DataRequired(_l("Elige una contraseña."))])
    password2 = PasswordField(
        _l("Repite la contraseña"),
        validators=[
            DataRequired(_l("Repite la contraseña.")),
            EqualTo("password", _l("Las contraseñas no coinciden.")),
        ],
    )
    submit = SubmitField(_l("Crear cuenta gratis"))

    def validate_username(self, username):
        user = db.session.scalar(sa.select(User).where(User.username == username.data))
        if user is not None:
            raise ValidationError(_l("Ese usuario ya existe, prueba con otro."))

    def validate_email(self, email):
        user = db.session.scalar(sa.select(User).where(User.email == email.data))
        if user is not None:
            raise ValidationError(_l("Ya hay una cuenta con ese email. ¿Quieres iniciar sesión?"))


class SetEntryForm(FlaskForm):
    exercise = StringField(_l("Ejercicio"), validators=[DataRequired()])
    weight = FloatField(
        _l("Peso (kg)"),
        validators=[DataRequired(), NumberRange(min=0, max=500)],
        render_kw={"min": 0, "max": 500, "step": "any"},
    )
    reps = IntegerField(
        _l("Repeticiones"),
        validators=[DataRequired(), NumberRange(min=1, max=30)],
        render_kw={"min": 1, "max": 30},
    )
    effort_value = IntegerField(
        _l("Valor de esfuerzo"),
        validators=[Optional(), NumberRange(min=0, max=10)],
        render_kw={"min": 0, "max": 10},
    )
    set_type = SelectField(
        _l("Tipo de serie"),
        choices=[
            ("normal", _l("Normal")),
            ("calentamiento", _l("Calentamiento")),
            ("fallo", _l("Al fallo")),
            ("dropset", _l("Dropset")),
        ],
        default="normal",
    )
    submit = SubmitField(_l("Añadir serie"))


class EmptyForm(FlaskForm):
    submit = SubmitField("Submit")


class AiCheckinForm(FlaskForm):
    how_you_feel = TextAreaField(
        _l("¿Cómo te sientes? (fatiga, agujetas, sueño, estrés...)"),
        validators=[Optional(), Length(max=500)],
    )
    submit = SubmitField(_l("🔍 Analizar mi progreso"))


class RecoveryCheckinForm(FlaskForm):
    """Check-in de recuperación (≤ 30 s). Valoración autodeclarada."""
    sleep = RadioField(
        _l("Sueño"), coerce=int, validators=[InputRequired()],
        choices=[(1, _l("Fatal")), (2, _l("Mal")), (3, _l("Normal")), (4, _l("Bien")), (5, _l("Genial"))],
    )
    energy = RadioField(
        _l("Energía"), coerce=int, validators=[InputRequired()],
        choices=[(1, _l("Muy baja")), (2, _l("Baja")), (3, _l("Normal")), (4, _l("Alta")), (5, _l("Muy alta"))],
    )
    soreness = RadioField(
        _l("Agujetas"), coerce=int, validators=[InputRequired()],
        choices=[(0, _l("Nada")), (1, _l("Leves")), (2, _l("Moderadas")), (3, _l("Fuertes"))],
    )
    submit = SubmitField(_l("Guardar check-in"))


class WeightForm(FlaskForm):
    weight = CommaFloatField(
        _l("Peso (kg)"), validators=[DataRequired(), NumberRange(min=20, max=400)]
    )
    submit = SubmitField(_l("Guardar"))


class SettingsForm(FlaskForm):
    stagnation_threshold = IntegerField(
        _l("Sesiones sin récord para avisar de estancamiento"),
        validators=[DataRequired(), NumberRange(min=1, max=20)],
    )
    effort_scale = SelectField(
        _l("¿Cómo quieres medir el esfuerzo?"),
        choices=[("rir", "RIR"), ("rpe", "RPE")],
        default="rir",
    )
    reps_warning = SelectField(
        _l("Avisar si apuntas más repeticiones de"),
        coerce=int,
        choices=[(0, _l("No avisar")), (15, "15"), (20, "20"), (25, "25"), (30, "30"), (40, "40"), (50, "50")],
        default=30,
    )
    rest_sound_enabled = BooleanField(_l("Sonido de notificación del descanso"))
    rest_vibration_enabled = BooleanField(_l("Vibración del descanso"))
    sex = SelectField(
        _l("Sexo"),
        choices=[("", _l("Prefiero no decirlo")), ("hombre", _l("Hombre")), ("mujer", _l("Mujer"))],
        validators=[Optional()],
    )
    height_cm = IntegerField(
        _l("Altura (cm)"), validators=[Optional(), NumberRange(min=100, max=250)]
    )
    training_goal = SelectField(
        _l("Objetivo principal"),
        choices=[
            ("", _l("Sin especificar")),
            ("hipertrofia", _l("Hipertrofia")),
            ("fuerza", _l("Fuerza")),
            ("perdida_grasa", _l("Pérdida de grasa")),
        ],
        validators=[Optional()],
    )
    training_days = SelectMultipleField(
        _l("Días que sueles entrenar"),
        choices=[(0, _lp("inicial de lunes", "L")), (1, _lp("inicial de martes", "M")), (2, _lp("inicial de miércoles", "X")), (3, _lp("inicial de jueves", "J")), (4, _lp("inicial de viernes", "V")), (5, _lp("inicial de sábado", "S")), (6, _lp("inicial de domingo", "D"))],
        coerce=int,
        validators=[Optional()],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInput(),
    )
    weekly_workout_goal = IntegerField(
        _l("Mínimo de días por semana para no perder la racha"),
        validators=[Optional(), NumberRange(min=1, max=7, message=_l("Entre 1 y 7 días."))],
    )
    submit = SubmitField(_l("Guardar"))


class FinishWorkoutForm(FlaskForm):
    performance_rating = SelectField(
        _l("¿Cómo ha sido tu rendimiento hoy?"),
        coerce=int,
        choices=[
            (1, _l("1 - Pésimo: no pude completar el entrenamiento planeado")),
            (2, _l("2 - Muy mal: rendimiento muy por debajo de lo normal")),
            (3, _l("3 - Mal: peso o reps notablemente inferiores a lo habitual")),
            (4, _l("4 - Flojo: por debajo de lo normal")),
            (5, _l("5 - Regular: cumplí, sin más")),
            (6, _l("6 - Normal: sesión estándar, sin sorpresas")),
            (7, _l("7 - Bien: mejor de lo esperado en algún ejercicio")),
            (8, _l("8 - Muy bien: buena sensación general, progresé")),
            (9, _l("9 - Muy buena: cerca de mis mejores marcas")),
            (10, _l("10 - Excelente: nuevos récords, gran sesión")),
        ],
    )
    performance_comment = TextAreaField(
        _l("Comentario (opcional)"), validators=[Length(max=255)]
    )
    duration_hours = IntegerField(
        _l("Horas"),
        validators=[InputRequired(), NumberRange(min=0, max=23)],
        render_kw={"min": 0, "max": 23},
    )
    duration_minutes = IntegerField(
        _l("Minutos"),
        validators=[InputRequired(), NumberRange(min=0, max=59)],
        render_kw={"min": 0, "max": 59},
    )
    submit = SubmitField(_l("Guardar entrenamiento"))


class NotesForm(FlaskForm):
    notes = TextAreaField(_l("Notas generales"), validators=[Length(max=1000)])


class ExerciseNoteForm(FlaskForm):
    notes = TextAreaField(_l("Notas (una línea = un punto)"), validators=[Length(max=1000)])
    rest_minutes = IntegerField(
        _l("Minutos de descanso"),
        validators=[Optional(), NumberRange(min=0, max=15)],
        default=1,
    )
    rest_seconds = IntegerField(
        _l("Segundos de descanso"),
        validators=[Optional(), NumberRange(min=0, max=59)],
        default=30,
    )
    submit = SubmitField(_l("Guardar"))


class RoutineForm(FlaskForm):
    name = StringField(
        _l("Nombre de la rutina (ej: Push A)"), validators=[DataRequired(), Length(max=64)]
    )
    submit = SubmitField(_l("Crear rutina"))


class RoutineExerciseForm(FlaskForm):
    exercise = StringField(_l("Ejercicio"), validators=[DataRequired(), Length(max=64)])
    target_sets = IntegerField(
        _l("Series objetivo"),
        validators=[DataRequired(), NumberRange(min=1, max=15)],
        default=3,
    )
    target_reps = StringField(
        _l("Reps objetivo (ej: 8-10)"),
        validators=[DataRequired(), Length(max=16)],
        default="8-10",
    )
    effort_value = StringField(
        _l("RIR/RPE objetivo (ej: 2 o 2-3)"),
        validators=[
            Optional(),
            Length(max=16),
            Regexp(r"^\d{1,2}(-\d{1,2})?$", message=_l("Usa un número (ej. 2) o un rango (ej. 2-3)")),
        ],
    )
    replace_ex_id = HiddenField(validators=[Optional()])
    submit = SubmitField(_l("Añadir ejercicio"))


class NewExerciseForm(FlaskForm):
    exercise = StringField(_l("Ejercicio"), validators=[DataRequired(), Length(max=64)])
    submit = SubmitField(_l("Añadir ejercicio"))


class ExerciseTranslationForm(FlaskForm):
    name_es = StringField(
        _l("Nombre en español"), validators=[Optional(), Length(max=120)]
    )
    submit = SubmitField(_l("Guardar"))
