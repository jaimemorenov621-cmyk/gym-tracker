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
    routine_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.ForeignKey("routine.id", name="fk_workout_routine_id"), index=True
    )
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    author: so.Mapped[User] = so.relationship(back_populates="workouts")
    routine: so.Mapped[Optional["Routine"]] = so.relationship(back_populates="workouts")
    sets: so.WriteOnlyMapped["SetEntry"] = so.relationship(
        back_populates="workout", passive_deletes=True
    )

    def __repr__(self):
        return f"<Workout {self.note} {self.timestamp}>"


class SetEntry(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    exercise: so.Mapped[str] = so.mapped_column(sa.String(64), index=True)
    weight: so.Mapped[float] = so.mapped_column()
    reps: so.Mapped[int] = so.mapped_column()
    rir: so.Mapped[Optional[int]] = so.mapped_column()
    rpe: so.Mapped[Optional[int]] = so.mapped_column()
    workout_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Workout.id), index=True)
    workout: so.Mapped[Workout] = so.relationship(back_populates="sets")
    set_type: so.Mapped[Optional[str]] = so.mapped_column(sa.String(16))

    def __repr__(self):
        return f"<SetEntry {self.exercise} {self.weight}x{self.reps}>"


class ExerciseNote(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    exercise: so.Mapped[str] = so.mapped_column(sa.String(64), index=True)
    notes: so.Mapped[Optional[str]] = so.mapped_column(sa.String(1000))
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)

    __table_args__ = (
        sa.UniqueConstraint("user_id", "exercise", name="uq_user_exercise_note"),
    )

    def __repr__(self):
        return f"<ExerciseNote {self.exercise}>"


class Routine(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(64))
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
    order_index: so.Mapped[int] = so.mapped_column(default=0)
    routine_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Routine.id), index=True)

    routine: so.Mapped[Routine] = so.relationship(back_populates="exercises")

    def __repr__(self):
        return f"<RoutineExercise {self.exercise}>"
