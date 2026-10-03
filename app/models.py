from datetime import date, datetime, timezone
from typing import Optional
import unicodedata
import sqlalchemy as sa
import sqlalchemy.orm as so
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login


def _strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


class User(UserMixin, db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True, unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True, unique=True)
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))
    google_sub: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255), unique=True, index=True)
    workouts: so.WriteOnlyMapped["Workout"] = so.relationship(back_populates="author")
    routines: so.WriteOnlyMapped["Routine"] = so.relationship(back_populates="author")
    stagnation_threshold: so.Mapped[int] = so.mapped_column(default=3)
    effort_scale: so.Mapped[str] = so.mapped_column(sa.String(4), default="rir")
    sex: so.Mapped[Optional[str]] = so.mapped_column(sa.String(10))
    height_cm: so.Mapped[Optional[int]] = so.mapped_column()
    training_goal: so.Mapped[Optional[str]] = so.mapped_column(sa.String(20))
    notes: so.Mapped[Optional[str]] = so.mapped_column(sa.Text)
    rest_sound_enabled: so.Mapped[bool] = so.mapped_column(default=True, server_default=sa.true())
    rest_vibration_enabled: so.Mapped[bool] = so.mapped_column(default=True, server_default=sa.true())
    # Para las estadísticas de la landing. Las cuentas anteriores a estas
    # columnas se quedan en NULL ("sin fecha"), no se inventa un valor.
    created_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc), index=True
    )
    signup_method: so.Mapped[Optional[str]] = so.mapped_column(sa.String(10))  # "password" | "google"
    # Canal de la última landing visitada con ?ref= (cookie gyre_ref), p.ej. "mediavida".
    signup_source: so.Mapped[Optional[str]] = so.mapped_column(sa.String(40))
    # Días de la semana en que suele entrenar, como dígitos 0=lunes..6=domingo
    # (p. ej. "0134"). Solo para el "hoy toca / hoy descanso" de Inicio; la
    # racha NO depende de qué días se entrene. NULL = sin configurar.
    training_days: so.Mapped[Optional[str]] = so.mapped_column(sa.String(7))  # _clean_ref limita a 20
    # XP y nivel (app/progression.py). xp_total es una caché de
    # compute_xp(): vale si xp_cached_seq == xp_seq, xp_rules es la versión
    # de reglas vigente y xp_cached_at tiene menos de 24 h. xp_seq sube (con
    # un UPDATE atómico, nunca leer-modificar-escribir) en la misma
    # transacción que cualquier cambio de entrenos, series, check-ins o
    # mínimo semanal. xp_level_seen = último nivel ya anunciado (NULL = aún
    # no se ha calculado nunca: el primer cálculo no avisa).
    xp_seq: so.Mapped[int] = so.mapped_column(default=0, server_default="0")
    xp_total: so.Mapped[int] = so.mapped_column(default=0, server_default="0")
    xp_cached_seq: so.Mapped[Optional[int]] = so.mapped_column()
    xp_rules: so.Mapped[Optional[int]] = so.mapped_column()
    xp_cached_at: so.Mapped[Optional[datetime]] = so.mapped_column()
    xp_level_seen: so.Mapped[Optional[int]] = so.mapped_column()
    # Último rango global anunciado (rango*3 + división). NULL = aún no se le
    # ha presentado su rango (la primera vez se le muestra, sin "subida").
    rank_seen: so.Mapped[Optional[int]] = so.mapped_column()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if self.password_hash is None:
            # Cuenta creada por Google -- no tiene contraseña que comprobar.
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"


@login.user_loader
def load_user(id):
    return db.session.get(User, int(id))


class Workout(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    note: so.Mapped[Optional[str]] = so.mapped_column(sa.String(64))
    performance_rating: so.Mapped[Optional[int]] = so.mapped_column()
    performance_comment: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    timestamp: so.Mapped[datetime] = so.mapped_column(
        index=True, default=lambda: datetime.now(timezone.utc)
    )
    ended_at: so.Mapped[Optional[datetime]] = so.mapped_column()
    # Lista JSON de nombres de ejercicio, en el orden elegido a mano por el
    # usuario (arrastrar en workout_detail.html). None -> orden por defecto
    # (primera aparición del SetEntry más antiguo de cada ejercicio).
    exercise_order: so.Mapped[Optional[str]] = so.mapped_column(sa.Text)
    routine_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("routine.id"), index=True
    )
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    author: so.Mapped[User] = so.relationship(back_populates="workouts")
    routine: so.Mapped[Optional["Routine"]] = so.relationship(back_populates="workouts")
    sets: so.WriteOnlyMapped["SetEntry"] = so.relationship(
        back_populates="workout", passive_deletes=True
    )

    def duration_str(self):
        if not self.ended_at:
            return None
        seconds = int((self.ended_at - self.timestamp).total_seconds())
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}min"
        return f"{m}min"

    def __repr__(self):
        return f"<Workout {self.note} {self.timestamp}>"


class SetEntry(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    exercise: so.Mapped[str] = so.mapped_column(sa.String(64), index=True)
    weight: so.Mapped[float] = so.mapped_column()
    reps: so.Mapped[int] = so.mapped_column()
    rir: so.Mapped[Optional[int]] = so.mapped_column()
    rpe: so.Mapped[Optional[int]] = so.mapped_column()
    workout_id: so.Mapped[int] = so.mapped_column(
        sa.ForeignKey(Workout.id, ondelete="CASCADE"), index=True
    )
    workout: so.Mapped[Workout] = so.relationship(back_populates="sets")
    set_type: so.Mapped[Optional[str]] = so.mapped_column(sa.String(16))
    completed: so.Mapped[bool] = so.mapped_column(default=False, server_default=sa.false())
    is_pr: so.Mapped[bool] = so.mapped_column(default=False, server_default=sa.false())
    # Cuándo se marcó como hecha (UTC naive). Sirve para estimar la duración
    # real de un entreno que se quedó abierto. NULL en series antiguas.
    completed_at: so.Mapped[Optional[datetime]] = so.mapped_column()

    def __repr__(self):
        return f"<SetEntry {self.exercise} {self.weight}x{self.reps}>"


class ExerciseNote(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    exercise: so.Mapped[str] = so.mapped_column(sa.String(64), index=True)
    notes: so.Mapped[Optional[str]] = so.mapped_column(sa.String(1000))
    default_rest_seconds: so.Mapped[Optional[int]] = so.mapped_column()
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    __table_args__ = (
        sa.UniqueConstraint("user_id", "exercise", name="uq_user_exercise_note"),
    )

    def __repr__(self):
        return f"<ExerciseNote {self.exercise}>"


class RoutineBlock(db.Model):
    """Bloque de entrenamiento (Hipertrofia, Fuerza, Descarga...) -- entidad
    propia (no solo texto libre en Routine) porque tiene atributos suyos:
    color para sombrear sus rutinas, y cuál es el bloque predeterminado que
    se abre solo en "Mis rutinas" (is_default, único por usuario -- ver
    set_default_routine_block() en app/routes.py)."""

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64))
    color: so.Mapped[str] = so.mapped_column(sa.String(7), default="#7c4dff")
    is_default: so.Mapped[bool] = so.mapped_column(default=False, server_default=sa.false())
    order_index: so.Mapped[int] = so.mapped_column(default=0)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    routines: so.WriteOnlyMapped["Routine"] = so.relationship(
        back_populates="block", passive_deletes=True
    )

    def __repr__(self):
        return f"<RoutineBlock {self.name}>"


class Routine(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64))
    order_index: so.Mapped[int] = so.mapped_column(default=0)
    block_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("routine_block.id", ondelete="SET NULL"), index=True
    )
    pinned: so.Mapped[bool] = so.mapped_column(default=False, server_default=sa.false())
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    author: so.Mapped[User] = so.relationship(back_populates="routines")
    block: so.Mapped[Optional[RoutineBlock]] = so.relationship(back_populates="routines")
    exercises: so.WriteOnlyMapped["RoutineExercise"] = so.relationship(
        back_populates="routine", passive_deletes=True
    )
    workouts: so.WriteOnlyMapped["Workout"] = so.relationship(
        back_populates="routine", passive_deletes=True
    )

    def __repr__(self):
        return f"<Routine {self.name}>"


class RoutineExercise(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    exercise: so.Mapped[str] = so.mapped_column(sa.String(64))
    target_sets: so.Mapped[int] = so.mapped_column(default=3)
    target_reps: so.Mapped[str] = so.mapped_column(sa.String(16), default="8-10")
    rir: so.Mapped[Optional[str]] = so.mapped_column(sa.String(16))
    rpe: so.Mapped[Optional[str]] = so.mapped_column(sa.String(16))
    order_index: so.Mapped[int] = so.mapped_column(default=0)
    routine_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Routine.id), index=True)

    routine: so.Mapped[Routine] = so.relationship(back_populates="exercises")

    def __repr__(self):
        return f"<RoutineExercise {self.exercise}>"


class AiAnalysis(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    content: so.Mapped[str] = so.mapped_column(sa.Text)
    created_at: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    def __repr__(self):
        return f"<AiAnalysis user={self.user_id} {self.created_at}>"


class BodyWeightEntry(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    weight: so.Mapped[float] = so.mapped_column()
    timestamp: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    def __repr__(self):
        return f"<BodyWeightEntry user={self.user_id} {self.weight}kg>"


class WeeklyGoalHistory(db.Model):
    """Historial append-only del objetivo semanal de entrenamientos (para la
    racha inteligente). Nunca se actualizan filas existentes -- cada cambio
    de objetivo inserta una fila nueva. goal=None significa "objetivo
    desactivado desde effective_from" (vuelve a racha por días)."""

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    goal: so.Mapped[Optional[int]] = so.mapped_column()
    # Naive a propósito (no timezone.utc-aware): Workout.timestamp usa el
    # mismo patrón y vuelve naive al leerlo de SQLite, así que effective_from
    # se normaliza igual para poder compararlos sin TypeError. Ver
    # compute_smart_streak() en app/routes.py.
    effective_from: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    def __repr__(self):
        return f"<WeeklyGoalHistory user={self.user_id} goal={self.goal} from={self.effective_from}>"


class Exercise(db.Model):
    id: so.Mapped[str] = so.mapped_column(sa.String(64), primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(120), index=True)
    name_es: so.Mapped[Optional[str]] = so.mapped_column(sa.String(120), index=True)
    # Sin acentos y en minúsculas, mantenidas en sincronía automáticamente
    # (ver el listener before_insert/before_update más abajo) -- permiten
    # que find_catalog_exercise() (app/routes.py) busque coincidencias sin
    # acentos con una consulta indexada, en vez de recorrer las 800+ filas
    # del catálogo en Python en cada búsqueda que no coincide exacto.
    name_normalized: so.Mapped[Optional[str]] = so.mapped_column(sa.String(120), index=True)
    name_es_normalized: so.Mapped[Optional[str]] = so.mapped_column(sa.String(120), index=True)
    category: so.Mapped[Optional[str]] = so.mapped_column(sa.String(64))
    primary_muscles: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    secondary_muscles: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    equipment: so.Mapped[Optional[str]] = so.mapped_column(sa.String(64))
    image_url: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))

    def __repr__(self):
        return f"<Exercise {self.name}>"


@sa.event.listens_for(Exercise, "before_insert")
@sa.event.listens_for(Exercise, "before_update")
def _exercise_sync_normalized_names(mapper, connection, target):
    target.name_normalized = _strip_accents(target.name)
    target.name_es_normalized = _strip_accents(target.name_es) if target.name_es else None


class ExerciseFavorite(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    exercise_id: so.Mapped[str] = so.mapped_column(
        sa.ForeignKey(Exercise.id, ondelete="CASCADE"), index=True
    )
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    __table_args__ = (
        sa.UniqueConstraint("user_id", "exercise_id", name="uq_user_exercise_favorite"),
    )

    def __repr__(self):
        return f"<ExerciseFavorite user={self.user_id} exercise={self.exercise_id}>"


class LandingEvent(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    event_type: so.Mapped[str] = so.mapped_column(sa.String(20), index=True)  # "visit" | "cta_click" | "google_click"
    timestamp: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc), index=True
    )
    referrer: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    # NULL = evento anterior a esta columna (sin clasificar); "" = la
    # petición no mandó User-Agent (se trata como robot).
    user_agent: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    # Canal etiquetado con ?ref= en el enlace (o, en clics, el de la cookie
    # de esa visita). NULL = enlace sin etiquetar.
    source: so.Mapped[Optional[str]] = so.mapped_column(sa.String(40), index=True)
    # Idioma principal del navegador (Accept-Language), p. ej. "es", "en".
    language: so.Mapped[Optional[str]] = so.mapped_column(sa.String(8))

    def __repr__(self):
        return f"<LandingEvent {self.event_type} {self.timestamp}>"


class UserAchievement(db.Model):
    """Logro desbloqueado por un usuario (el catálogo de logros vive en
    app/achievements.py, en código). seen=False hasta que se le ha
    mostrado el aviso de "logro desbloqueado"."""

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    code: so.Mapped[str] = so.mapped_column(sa.String(40))
    unlocked_at: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    seen: so.Mapped[bool] = so.mapped_column(default=False, server_default=sa.false())

    __table_args__ = (
        sa.UniqueConstraint("user_id", "code", name="uq_user_achievement"),
    )

    def __repr__(self):
        return f"<UserAchievement user={self.user_id} {self.code}>"


class DailyActivity(db.Model):
    """Contador de uso, una fila por usuario y día (hora de Madrid). Solo
    guarda lo que no se puede sacar de otras tablas: si abrió la app ese día,
    si era un día de descanso según su plan y cuántas veces hubo que
    reintentar cargar el CSS. Sin IP, sin navegador, sin horas. Si entrenó o
    hizo el check-in se calcula al hacer el informe (app/usage.py) desde
    Workout y el check-in, así no hay nada que mantener sincronizado.
    Se purga a los 120 días."""

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    day: so.Mapped[date] = so.mapped_column(sa.Date, index=True)
    opened: so.Mapped[bool] = so.mapped_column(default=False, server_default=sa.false())
    planned_rest: so.Mapped[bool] = so.mapped_column(default=False, server_default=sa.false())
    css_retries: so.Mapped[int] = so.mapped_column(default=0, server_default="0")

    __table_args__ = (
        sa.UniqueConstraint("user_id", "day", name="uq_daily_activity_user_day"),
    )

    def __repr__(self):
        return f"<DailyActivity user={self.user_id} {self.day}>"


class DailyCheckin(db.Model):
    """Check-in de recuperación del día (hora de Madrid): sueño y energía de
    1 a 5, agujetas de 0 (nada) a 3 (fuertes). Es una valoración
    AUTODECLARADA: nunca bloquea nada y se presenta siempre como tal."""

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    day: so.Mapped[date] = so.mapped_column(sa.Date, index=True)
    sleep: so.Mapped[int] = so.mapped_column()
    energy: so.Mapped[int] = so.mapped_column()
    soreness: so.Mapped[int] = so.mapped_column()
    created_at: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    __table_args__ = (
        sa.UniqueConstraint("user_id", "day", name="uq_daily_checkin_user_day"),
    )

    def __repr__(self):
        return f"<DailyCheckin user={self.user_id} {self.day}>"


class ExerciseAlias(db.Model):
    """"Mi ejercicio X es el Y del catálogo", por usuario. Para nombres
    escritos a mano que no coinciden con el catálogo: así cuentan para el
    mapa muscular, el volumen semanal y las imágenes SIN renombrar el
    historial (p. ej. "press de banca ligero técnico" sigue siendo su propio
    ejercicio, con su propia curva de 1RM). `name` va normalizado como
    Exercise.name_normalized (minúsculas, sin acentos)."""

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(120))
    exercise_id: so.Mapped[str] = so.mapped_column(sa.ForeignKey(Exercise.id, ondelete="CASCADE"), index=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    exercise: so.Mapped[Exercise] = so.relationship()

    __table_args__ = (
        sa.UniqueConstraint("user_id", "name", name="uq_exercise_alias_user_name"),
    )
