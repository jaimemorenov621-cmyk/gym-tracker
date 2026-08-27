from datetime import datetime, timezone
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login


class User(UserMixin, db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True, unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True, unique=True)
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))
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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
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


class Routine(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64))
    order_index: so.Mapped[int] = so.mapped_column(default=0)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    author: so.Mapped[User] = so.relationship(back_populates="routines")
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
    rir: so.Mapped[Optional[int]] = so.mapped_column()
    rpe: so.Mapped[Optional[int]] = so.mapped_column()
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
    category: so.Mapped[Optional[str]] = so.mapped_column(sa.String(64))
    primary_muscles: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    secondary_muscles: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))
    equipment: so.Mapped[Optional[str]] = so.mapped_column(sa.String(64))
    image_url: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))

    def __repr__(self):
        return f"<Exercise {self.name}>"


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
    event_type: so.Mapped[str] = so.mapped_column(sa.String(20), index=True)  # "visit" | "cta_click"
    timestamp: so.Mapped[datetime] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc), index=True
    )
    referrer: so.Mapped[Optional[str]] = so.mapped_column(sa.String(255))

    def __repr__(self):
        return f"<LandingEvent {self.event_type} {self.timestamp}>"
