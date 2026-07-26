from flask import render_template, flash, redirect, url_for, request, jsonify
from flask_login import current_user, login_user, logout_user, login_required
from urllib.parse import urlsplit
import sqlalchemy as sa
from app import app, db
from app.forms import (
    LoginForm,
    RegistrationForm,
    WorkoutForm,
    SetEntryForm,
    EmptyForm,
    SettingsForm,
    FinishWorkoutForm,
    ExerciseNoteForm,
    RoutineForm,
    RoutineExerciseForm,
)
from app.models import User, Workout, SetEntry, ExerciseNote, Routine, RoutineExercise
from datetime import datetime, timezone, timedelta


@app.route("/")
@app.route("/index")
@login_required
def index():
    workouts = db.session.scalars(
        current_user.workouts.select().order_by(Workout.timestamp.desc())
    ).all()

    grouped = []
    current_week_key = None
    current_group = None
    for w in workouts:
        iso_year, iso_week, _ = w.timestamp.isocalendar()
        week_key = (iso_year, iso_week)
        if week_key != current_week_key:
            week_start = w.timestamp - timedelta(days=w.timestamp.weekday())
            week_end = week_start + timedelta(days=6)
            current_group = {
                "label": f"{week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}",
                "workouts": [],
            }
            grouped.append(current_group)
            current_week_key = week_key
        current_group["workouts"].append(w)

    return render_template("index.html", title="Inicio", grouped=grouped)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(User).where(User.username == form.username.data)
        )
        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password")
            return redirect(url_for("login"))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get("next")
        if not next_page or urlsplit(next_page).netloc != "":
            next_page = url_for("index")
        return redirect(next_page)
    return render_template("login.html", title="Sign In", form=form)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("¡Registro completado! Ya puedes iniciar sesión.")
        return redirect(url_for("login"))
    return render_template("register.html", title="Register", form=form)


@app.route("/workout/new", methods=["GET", "POST"])
@login_required
def new_workout():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    existing = db.session.scalar(
        sa.select(Workout).where(
            Workout.user_id == current_user.id,
            Workout.performance_rating.is_(None),
            Workout.timestamp >= cutoff,
        ).order_by(Workout.timestamp.desc())
    )
    if existing:
        flash("⚠️ YA TIENES UN ENTRENAMIENTO EN CURSO — termínalo antes de empezar otro.")
        return redirect(url_for("workout_detail", workout_id=existing.id))

    form = WorkoutForm()
    if form.validate_on_submit():
        workout = Workout(note=form.note.data, author=current_user)
        db.session.add(workout)
        db.session.commit()
        flash("¡Entrenamiento creado! Añade tus series.")
        return redirect(url_for("workout_detail", workout_id=workout.id))
    return render_template("new_workout.html", title="Nuevo entrenamiento", form=form)


@app.route("/workout/<int:workout_id>", methods=["GET", "POST"])
@login_required
def workout_detail(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash("No tienes acceso a este entrenamiento.")
        return redirect(url_for("index"))

    form = SetEntryForm()

    prefill_notes = None
    if request.method == "GET":
        exercise_prefill = request.args.get("exercise")
        if exercise_prefill:
            form.exercise.data = exercise_prefill
            prefill_notes = db.session.scalar(
                sa.select(ExerciseNote).where(
                    ExerciseNote.user_id == current_user.id,
                    ExerciseNote.exercise == exercise_prefill.strip().lower(),
                )
            )

    if form.validate_on_submit():
        scale = current_user.effort_scale
        entry = SetEntry(
            exercise=form.exercise.data.strip().lower(),
            weight=form.weight.data,
            reps=form.reps.data,
            rir=form.effort_value.data if scale == "rir" else None,
            rpe=form.effort_value.data if scale == "rpe" else None,
            set_type=form.set_type.data,
            workout=workout,
        )
        db.session.add(entry)
        db.session.commit()
        flash("Serie añadida.")
        return redirect(url_for("workout_detail", workout_id=workout.id))

    sets = db.session.scalars(workout.sets.select().order_by(SetEntry.id)).all()

    grouped_sets = {}
    for s in sets:
        grouped_sets.setdefault(s.exercise, []).append(s)

    exercise_notes_map = {}
    if grouped_sets:
        notes_rows = db.session.scalars(
            sa.select(ExerciseNote).where(
                ExerciseNote.user_id == current_user.id,
                ExerciseNote.exercise.in_(grouped_sets.keys()),
            )
        ).all()
        for n in notes_rows:
            exercise_notes_map[n.exercise] = n

    routine_plan = []
    if workout.routine_id:
        routine_exercises = db.session.scalars(
            sa.select(RoutineExercise)
            .where(RoutineExercise.routine_id == workout.routine_id)
            .order_by(RoutineExercise.order_index)
        ).all()
        for re in routine_exercises:
            done = len(grouped_sets.get(re.exercise.strip().lower(), []))
            routine_plan.append(
                {
                    "exercise": re.exercise,
                    "target_sets": re.target_sets,
                    "target_reps": re.target_reps,
                    "done": done,
                }
            )

    empty_form = EmptyForm()
    return render_template(
        "workout_detail.html",
        title=workout.note or "Entrenamiento",
        workout=workout,
        grouped_sets=grouped_sets,
        form=form,
        empty_form=empty_form,
        effort_scale=current_user.effort_scale,
        prefill_notes=prefill_notes,
        exercise_notes_map=exercise_notes_map,
        routine_plan=routine_plan,
    )


@app.route("/workout/<int:workout_id>/finish", methods=["GET", "POST"])
@login_required
def finish_workout(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash("No tienes acceso a este entrenamiento.")
        return redirect(url_for("index"))

    form = FinishWorkoutForm()
    if form.validate_on_submit():
        workout.performance_rating = form.performance_rating.data
        workout.performance_comment = form.performance_comment.data
        db.session.commit()
        flash("Entrenamiento guardado.")
        return redirect(url_for("index"))
    elif request.method == "GET" and workout.performance_rating is not None:
        form.performance_rating.data = workout.performance_rating
        form.performance_comment.data = workout.performance_comment

    return render_template(
        "finish_workout.html",
        title="Finalizar entrenamiento",
        form=form,
        workout=workout,
    )


@app.route("/workout/<int:workout_id>/delete", methods=["POST"])
@login_required
def delete_workout(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash("No tienes acceso a este entrenamiento.")
        return redirect(url_for("index"))
    sets = db.session.scalars(workout.sets.select()).all()
    for s in sets:
        db.session.delete(s)
    db.session.delete(workout)
    db.session.commit()
    flash("Entrenamiento eliminado.")
    return redirect(url_for("index"))


@app.route("/exercise/<name>")
@login_required
def exercise_progress(name):
    name = name.strip().lower()

    query = (
        sa.select(Workout, SetEntry)
        .join(SetEntry, SetEntry.workout_id == Workout.id)
        .where(Workout.user_id == current_user.id, SetEntry.exercise == name)
        .order_by(Workout.timestamp.asc())
    )
    rows = db.session.execute(query).all()

    sessions = {}
    for workout, entry in rows:
        sessions.setdefault(workout.id, {"timestamp": workout.timestamp, "sets": []})
        sessions[workout.id]["sets"].append(entry)

    session_list = sorted(sessions.values(), key=lambda s: s["timestamp"])

    running_max = float("-inf")
    for s in session_list:
        s["best_set"] = max(s["sets"], key=estimated_1rm)
        s["best_1rm"] = estimated_1rm(s["best_set"])
        s["is_pr"] = s["best_1rm"] > running_max
        running_max = max(running_max, s["best_1rm"])

    threshold = current_user.stagnation_threshold
    stagnation = False
    improvement = False
    lastN_ids = set()
    if len(session_list) >= threshold:
        lastN = session_list[-threshold:]
        lastN_ids = {id(s) for s in lastN}
        stagnation = not any(s["is_pr"] for s in lastN)
        improvement = lastN[-1]["is_pr"]

    chart_labels = [s["timestamp"].strftime("%d/%m %H:%M") for s in session_list]
    chart_values = [round(s["best_1rm"], 1) for s in session_list]
    chart_colors = []
    for s in session_list:
        if s["is_pr"]:
            chart_colors.append("#2e7d32")
        elif id(s) in lastN_ids and stagnation:
            chart_colors.append("#c62828")
        else:
            chart_colors.append("#1565c0")

    note = db.session.scalar(
        sa.select(ExerciseNote).where(
            ExerciseNote.user_id == current_user.id, ExerciseNote.exercise == name
        )
    )

    return render_template(
        "exercise_progress.html",
        title=name.title(),
        exercise=name,
        sessions=list(reversed(session_list)),
        stagnation=stagnation,
        improvement=improvement,
        threshold=threshold,
        chart_labels=chart_labels,
        chart_values=chart_values,
        chart_colors=chart_colors,
        exercise_note=note,
    )


@app.route("/exercise/<name>/notes", methods=["GET", "POST"])
@login_required
def exercise_notes(name):
    name = name.strip().lower()
    note = db.session.scalar(
        sa.select(ExerciseNote).where(
            ExerciseNote.user_id == current_user.id, ExerciseNote.exercise == name
        )
    )
    form = ExerciseNoteForm()
    if form.validate_on_submit():
        if note is None:
            note = ExerciseNote(exercise=name, user_id=current_user.id)
            db.session.add(note)
        note.notes = form.notes.data
        db.session.commit()
        flash("Notas guardadas.")
        return redirect(url_for("exercise_progress", name=name))
    elif request.method == "GET" and note:
        form.notes.data = note.notes
    return render_template(
        "exercise_notes.html",
        title=f"Notas de {name.title()}",
        form=form,
        exercise=name,
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    form = SettingsForm()
    if form.validate_on_submit():
        current_user.stagnation_threshold = form.stagnation_threshold.data
        current_user.effort_scale = form.effort_scale.data
        db.session.commit()
        flash("Configuración guardada.")
        return redirect(url_for("settings"))
    elif request.method == "GET":
        form.stagnation_threshold.data = current_user.stagnation_threshold
        form.effort_scale.data = current_user.effort_scale
    return render_template("settings.html", title="Configuración", form=form)


@app.route("/routines")
@login_required
def routines():
    routine_list = db.session.scalars(
        current_user.routines.select().order_by(Routine.name)
    ).all()

    routines_info = []
    for r in routine_list:
        exercises = db.session.scalars(
            sa.select(RoutineExercise)
            .where(RoutineExercise.routine_id == r.id)
            .order_by(RoutineExercise.order_index)
        ).all()
        last_workout = db.session.scalar(
            sa.select(Workout)
            .where(Workout.routine_id == r.id)
            .order_by(Workout.timestamp.desc())
        )
        dias = [
            "Lunes",
            "Martes",
            "Miércoles",
            "Jueves",
            "Viernes",
            "Sábado",
            "Domingo",
        ]
        last_day = dias[last_workout.timestamp.weekday()] if last_workout else None
        routines_info.append(
            {
                "routine": r,
                "exercise_names": [e.exercise.title() for e in exercises],
                "last_day": last_day,
                "last_date": (
                    last_workout.timestamp.strftime("%d/%m/%Y")
                    if last_workout
                    else None
                ),
            }
        )

    empty_form = EmptyForm()
    return render_template(
        "routines.html",
        title="Mis rutinas",
        routines_info=routines_info,
        empty_form=empty_form,
    )


@app.route("/routines/new", methods=["GET", "POST"])
@login_required
def new_routine():
    form = RoutineForm()
    if form.validate_on_submit():
        routine = Routine(name=form.name.data, author=current_user)
        db.session.add(routine)
        db.session.commit()
        flash("Rutina creada. Añade ejercicios.")
        return redirect(url_for("routine_detail", routine_id=routine.id))
    return render_template("new_routine.html", title="Nueva rutina", form=form)


@app.route("/routines/<int:routine_id>", methods=["GET", "POST"])
@login_required
def routine_detail(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        flash("No tienes acceso a esta rutina.")
        return redirect(url_for("routines"))

    form = RoutineExerciseForm()
    if form.validate_on_submit():
        count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(RoutineExercise)
            .where(RoutineExercise.routine_id == routine.id)
        )
        ex = RoutineExercise(
            exercise=form.exercise.data.strip().lower(),
            target_sets=form.target_sets.data,
            target_reps=form.target_reps.data,
            order_index=count,
            routine_id=routine.id,
        )
        db.session.add(ex)
        db.session.commit()
        flash("Ejercicio añadido a la rutina.")
        return redirect(url_for("routine_detail", routine_id=routine.id))

    exercises = db.session.scalars(
        sa.select(RoutineExercise)
        .where(RoutineExercise.routine_id == routine.id)
        .order_by(RoutineExercise.order_index)
    ).all()
    empty_form = EmptyForm()
    return render_template(
        "routine_detail.html",
        title=routine.name,
        routine=routine,
        exercises=exercises,
        form=form,
        empty_form=empty_form,
    )


@app.route("/routines/<int:routine_id>/exercise/<int:ex_id>/delete", methods=["POST"])
@login_required
def delete_routine_exercise(routine_id, ex_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        flash("No tienes acceso a esta rutina.")
        return redirect(url_for("routines"))
    ex = db.get_or_404(RoutineExercise, ex_id)
    db.session.delete(ex)
    db.session.commit()
    flash("Ejercicio eliminado de la rutina.")
    return redirect(url_for("routine_detail", routine_id=routine.id))


@app.route("/routines/<int:routine_id>/delete", methods=["POST"])
@login_required
def delete_routine(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        flash("No tienes acceso a esta rutina.")
        return redirect(url_for("routines"))
    exercises = db.session.scalars(
        sa.select(RoutineExercise).where(RoutineExercise.routine_id == routine.id)
    ).all()
    for ex in exercises:
        db.session.delete(ex)
    db.session.execute(
        sa.update(Workout)
        .where(Workout.routine_id == routine.id)
        .values(routine_id=None)
    )
    db.session.delete(routine)
    db.session.commit()
    flash("Rutina eliminada.")
    return redirect(url_for("routines"))


@app.route("/routines/<int:routine_id>/start", methods=["POST"])
@login_required
def start_routine(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        flash("No tienes acceso a esta rutina.")
        return redirect(url_for("routines"))
    workout = Workout(note=routine.name, routine_id=routine.id, author=current_user)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    existing = db.session.scalar(
        sa.select(Workout).where(
            Workout.user_id == current_user.id,
            Workout.performance_rating.is_(None),
            Workout.timestamp >= cutoff,
        ).order_by(Workout.timestamp.desc())
    )
    if existing:
        flash("⚠️ YA TIENES UN ENTRENAMIENTO EN CURSO — termínalo antes de iniciar otro.")
        return redirect(url_for("workout_detail", workout_id=existing.id))
    db.session.add(workout)
    db.session.commit()
    flash(f"¡Entrenamiento '{routine.name}' iniciado!")
    return redirect(url_for("workout_detail", workout_id=workout.id))


@app.route("/api/exercise_info")
@login_required
def api_exercise_info():
    name = request.args.get("name", "").strip().lower()
    if not name:
        return jsonify({"notes": None, "previous": None})

    note = db.session.scalar(
        sa.select(ExerciseNote).where(
            ExerciseNote.user_id == current_user.id, ExerciseNote.exercise == name
        )
    )
    last_entry = db.session.scalar(
        sa.select(SetEntry)
        .join(Workout)
        .where(Workout.user_id == current_user.id, SetEntry.exercise == name)
        .order_by(SetEntry.id.desc())
    )
    previous = None
    if last_entry:
        effort = None
        if last_entry.rir is not None:
            effort = f"RIR {last_entry.rir}"
        elif last_entry.rpe is not None:
            effort = f"RPE {last_entry.rpe}"
        previous = f"{last_entry.weight}kg x {last_entry.reps} reps" + (
            f" ({effort})" if effort else ""
        )

    return jsonify({"notes": note.notes if note else None, "previous": previous})


@app.route("/routines/<int:routine_id>/reorder", methods=["POST"])
@login_required
def reorder_routine(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    order = data.get("order", [])
    exercises = {
        e.id: e
        for e in db.session.scalars(
            sa.select(RoutineExercise).where(RoutineExercise.routine_id == routine.id)
        ).all()
    }
    for index, ex_id in enumerate(order):
        if ex_id in exercises:
            exercises[ex_id].order_index = index
    db.session.commit()
    return jsonify({"ok": True})


@app.context_processor
def inject_active_workout():
    if current_user.is_authenticated and request.endpoint not in (
        "new_workout",
        "workout_detail",
    ):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        active = db.session.scalar(
            sa.select(Workout)
            .where(
                Workout.user_id == current_user.id,
                Workout.performance_rating.is_(None),
                Workout.timestamp >= cutoff,
            )
            .order_by(Workout.timestamp.desc())
        )
        return {"active_workout": active}
    return {"active_workout": None}


@app.route("/workout/<int:workout_id>/save_as_routine", methods=["POST"])
@login_required
def save_as_routine(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash("No tienes acceso a este entrenamiento.")
        return redirect(url_for("index"))

    sets = db.session.scalars(workout.sets.select().order_by(SetEntry.id)).all()
    exercise_order = []
    exercise_counts = {}
    for s in sets:
        if s.exercise not in exercise_counts:
            exercise_order.append(s.exercise)
            exercise_counts[s.exercise] = 0
        exercise_counts[s.exercise] += 1

    if not exercise_order:
        flash("Este entrenamiento no tiene series registradas.")
        return redirect(url_for("workout_detail", workout_id=workout.id))

    routine = Routine(name=workout.note or "Nueva rutina", author=current_user)
    db.session.add(routine)
    db.session.flush()

    for i, exercise in enumerate(exercise_order):
        first_set = next(s for s in sets if s.exercise == exercise)
        ex = RoutineExercise(
            exercise=exercise,
            target_sets=exercise_counts[exercise],
            target_reps=str(first_set.reps),
            order_index=i,
            routine_id=routine.id,
        )
        db.session.add(ex)

    db.session.commit()
    flash(f"Rutina '{routine.name}' creada a partir de este entrenamiento.")
    return redirect(url_for("routine_detail", routine_id=routine.id))



def effective_reps(entry):
    if entry.rir is not None:
        return entry.reps + entry.rir
    elif entry.rpe is not None:
        return entry.reps + (10 - entry.rpe)
    return entry.reps


def estimated_1rm(entry):
    """Fórmula de Epley, usando repeticiones efectivas en vez de las repeticiones hechas."""
    return entry.weight * (1 + effective_reps(entry) / 30)


