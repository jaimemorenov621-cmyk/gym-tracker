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
    NewExerciseForm,
    ExerciseTranslationForm,
)
from app.models import (
    User,
    Workout,
    SetEntry,
    ExerciseNote,
    Routine,
    RoutineExercise,
    Exercise,
)
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

        sets = db.session.scalars(w.sets.select().order_by(SetEntry.id)).all()
        names = []
        for s in sets:
            if s.exercise.title() not in names:
                names.append(s.exercise.title())
        volume = sum(s.weight * s.reps for s in sets)

        current_group["workouts"].append(
            {
                "workout": w,
                "exercise_names": names,
                "volume": round(volume),
                "duration": w.duration_str(),
            }
        )

    total_workouts = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(Workout)
        .where(Workout.user_id == current_user.id)
    )

    # Racha: días consecutivos entrenando, contando hacia atrás desde hoy o ayer
    trained_dates = sorted({w.timestamp.date() for w in workouts}, reverse=True)
    streak = 0
    if trained_dates:
        today = datetime.now(timezone.utc).date()
        expected = (
            today
            if trained_dates[0] == today
            else (
                today - timedelta(days=1)
                if trained_dates[0] == today - timedelta(days=1)
                else None
            )
        )
        if expected:
            for d in trained_dates:
                if d == expected:
                    streak += 1
                    expected -= timedelta(days=1)
                else:
                    break

    # Calendario de los últimos 3 meses
    today = datetime.now(timezone.utc).date()
    start_date = today.replace(day=1)
    for _ in range(2):
        start_date = (start_date - timedelta(days=1)).replace(day=1)
    start_datetime = datetime.combine(start_date, datetime.min.time())

    trained_set = set(
        d.date()
        for d in db.session.scalars(
            sa.select(Workout.timestamp).where(
                Workout.user_id == current_user.id, Workout.timestamp >= start_datetime
            )
        ).all()
    )

    calendar_weeks = []
    week = [None] * start_date.weekday()
    day = start_date
    while day <= today:
        week.append({"date": day, "trained": day in trained_set})
        if len(week) == 7:
            calendar_weeks.append(week)
            week = []
        day += timedelta(days=1)
    if week:
        while len(week) < 7:
            week.append(None)
        calendar_weeks.append(week)

    calendar_weeks = [
        {
            "days": week,
            "new_month": any(d and d["date"].day == 1 for d in week),
        }
        for week in calendar_weeks
    ]
    if calendar_weeks:
        calendar_weeks[0]["new_month"] = False

    return render_template(
        "index.html",
        title="Inicio",
        grouped=grouped,
        total_workouts=total_workouts,
        streak=streak,
        calendar_weeks=calendar_weeks,
    )


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
        sa.select(Workout)
        .where(
            Workout.user_id == current_user.id,
            Workout.performance_rating.is_(None),
            Workout.timestamp >= cutoff,
        )
        .order_by(Workout.timestamp.desc())
    )
    if existing:
        flash(
            "⚠️ YA TIENES UN ENTRENAMIENTO EN CURSO — termínalo antes de empezar otro."
        )
        return redirect(url_for("workout_detail", workout_id=existing.id))

    form = WorkoutForm()
    if form.validate_on_submit():
        workout = Workout(note=form.note.data, author=current_user)
        db.session.add(workout)
        db.session.commit()
        flash("¡Entrenamiento creado! Añade tus series.")
        return redirect(url_for("workout_detail", workout_id=workout.id))
    return render_template("new_workout.html", title="Nuevo entrenamiento", form=form)


@app.route("/workout/<int:workout_id>/add_exercise", methods=["POST"])
@login_required
def add_exercise_to_workout(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash("No tienes acceso a este entrenamiento.")
        return redirect(url_for("index"))
    form = NewExerciseForm()
    if form.validate_on_submit():
        entry = SetEntry(
            exercise=form.exercise.data.strip().lower(),
            weight=0,
            reps=0,
            set_type="normal",
            workout=workout,
        )
        db.session.add(entry)
        db.session.commit()
    return redirect(url_for("workout_detail", workout_id=workout.id))


@app.route("/workout/<int:workout_id>/set", methods=["POST"])
@login_required
def api_create_set(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    exercise = (data.get("exercise") or "").strip().lower()
    if not exercise:
        return jsonify({"ok": False}), 400

    weight = max(0, min(500, float(data.get("weight") or 0)))
    reps = max(0, min(30, int(float(data.get("reps") or 0))))
    effort = data.get("effort")
    scale = current_user.effort_scale

    entry = SetEntry(
        exercise=exercise,
        weight=weight,
        reps=reps,
        rir=int(effort) if scale == "rir" and effort not in (None, "") else None,
        rpe=int(effort) if scale == "rpe" and effort not in (None, "") else None,
        set_type=data.get("set_type", "normal"),
        workout=workout,
    )
    db.session.add(entry)
    db.session.commit()

    return jsonify({"ok": True, "id": entry.id, "rest_seconds": get_rest_seconds(exercise)})


@app.route("/set/<int:set_id>", methods=["PUT"])
@login_required
def api_update_set(set_id):
    entry = db.get_or_404(SetEntry, set_id)
    if entry.workout.author != current_user:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    scale = current_user.effort_scale
    if "weight" in data:
        entry.weight = max(0, min(500, float(data["weight"] or 0)))
    if "reps" in data:
        entry.reps = max(0, min(30, int(float(data["reps"] or 0))))
    if "effort" in data:
        effort = data["effort"]
        if scale == "rir":
            entry.rir = int(effort) if effort not in (None, "") else None
            entry.rpe = None
        elif scale == "rpe":
            entry.rpe = int(effort) if effort not in (None, "") else None
            entry.rir = None
    if "set_type" in data:
        entry.set_type = data["set_type"]
    if "completed" in data:
        entry.completed = bool(data["completed"])
    db.session.commit()

    response = {"ok": True}
    if data.get("completed"):
        response["rest_seconds"] = get_rest_seconds(entry.exercise)
    return jsonify(response)


@app.route("/set/<int:set_id>/delete", methods=["POST"])
@login_required
def api_delete_set(set_id):
    entry = db.get_or_404(SetEntry, set_id)
    if entry.workout.author != current_user:
        return jsonify({"ok": False}), 403
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/workout/<int:workout_id>")
@login_required
def workout_detail(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash("No tienes acceso a este entrenamiento.")
        return redirect(url_for("index"))

    sets = db.session.scalars(workout.sets.select().order_by(SetEntry.id)).all()
    grouped_sets = {}
    exercise_order = []
    for s in sets:
        if s.exercise not in grouped_sets:
            grouped_sets[s.exercise] = []
            exercise_order.append(s.exercise)
        grouped_sets[s.exercise].append(s)

    exercise_notes_map = {}
    if grouped_sets:
        notes_rows = db.session.scalars(
            sa.select(ExerciseNote).where(
                ExerciseNote.user_id == current_user.id,
                ExerciseNote.exercise.in_(grouped_sets.keys()),
            )
        ).all()
        exercise_notes_map = {n.exercise: n for n in notes_rows}

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
    new_exercise_form = NewExerciseForm()
    return render_template(
        "workout_detail.html",
        title=workout.note or "Entrenamiento",
        workout=workout,
        grouped_sets=grouped_sets,
        exercise_order=exercise_order,
        empty_form=empty_form,
        effort_scale=current_user.effort_scale,
        exercise_notes_map=exercise_notes_map,
        routine_plan=routine_plan,
        new_exercise_form=new_exercise_form,
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
        workout.ended_at = datetime.now(timezone.utc)
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

    catalog_exercise = find_catalog_exercise(name)
    translation_form = ExerciseTranslationForm(
        name_es=catalog_exercise.name_es if catalog_exercise else None
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
        catalog_exercise=catalog_exercise,
        translation_form=translation_form,
    )


@app.route("/exercise/<name>/translate", methods=["POST"])
@login_required
def update_exercise_translation(name):
    name = name.strip().lower()
    catalog_exercise = find_catalog_exercise(name)
    if not catalog_exercise:
        flash("No se encontró este ejercicio en el catálogo.")
        return redirect(url_for("exercise_progress", name=name))
    form = ExerciseTranslationForm()
    if form.validate_on_submit():
        catalog_exercise.name_es = form.name_es.data.strip() or None
        db.session.commit()
        flash("Nombre en español guardado.")
    return redirect(url_for("exercise_progress", name=name))


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
        note.default_rest_seconds = (form.rest_minutes.data or 0) * 60 + (
            form.rest_seconds.data or 0
        )
        db.session.commit()
        flash("Notas guardadas.")
        return redirect(url_for("exercise_progress", name=name))
    elif request.method == "GET" and note and note.default_rest_seconds is not None:
        form.notes.data = note.notes
        form.rest_minutes.data = note.default_rest_seconds // 60
        form.rest_seconds.data = note.default_rest_seconds % 60
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
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

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

    exercise_notes_map = {}
    if exercises:
        names = [e.exercise for e in exercises]
        notes_rows = db.session.scalars(
            sa.select(ExerciseNote).where(
                ExerciseNote.user_id == current_user.id,
                ExerciseNote.exercise.in_(names),
            )
        ).all()
        exercise_notes_map = {n.exercise: n for n in notes_rows}

    empty_form = EmptyForm()
    return render_template(
        "routine_detail.html",
        title=routine.name,
        routine=routine,
        exercises=exercises,
        form=form,
        empty_form=empty_form,
        exercise_notes_map=exercise_notes_map,
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

    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    existing = db.session.scalar(
        sa.select(Workout)
        .where(
            Workout.user_id == current_user.id,
            Workout.performance_rating.is_(None),
            Workout.timestamp >= cutoff,
        )
        .order_by(Workout.timestamp.desc())
    )
    if existing:
        flash(
            "⚠️ YA TIENES UN ENTRENAMIENTO EN CURSO — termínalo antes de iniciar otro."
        )
        return redirect(url_for("workout_detail", workout_id=existing.id))

    workout = Workout(note=routine.name, routine_id=routine.id, author=current_user)
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
    if current_user.is_authenticated:
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


@app.route("/api/exercises/search")
@login_required
def api_search_exercises():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    results = db.session.scalars(
        sa.select(Exercise)
        .where(
            sa.or_(
                Exercise.name.ilike(f"%{q}%"), Exercise.name_es.ilike(f"%{q}%")
            )
        )
        .limit(8)
    ).all()
    return jsonify(
        [
            {
                "name": e.name_es or e.name,
                "image": e.image_url,
                "muscles": e.primary_muscles,
            }
            for e in results
        ]
    )


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


@app.route("/exercise/<name>/rest_default", methods=["POST"])
@login_required
def update_rest_default(name):
    name = name.strip().lower()
    data = request.get_json(silent=True) or {}
    seconds = data.get("seconds")
    if not isinstance(seconds, int) or seconds < 0 or seconds > 900:
        return jsonify({"ok": False}), 400
    note = db.session.scalar(
        sa.select(ExerciseNote).where(
            ExerciseNote.user_id == current_user.id, ExerciseNote.exercise == name
        )
    )
    if note is None:
        note = ExerciseNote(exercise=name, user_id=current_user.id)
        db.session.add(note)
    note.default_rest_seconds = seconds
    db.session.commit()
    return jsonify({"ok": True})


def effective_reps(entry):
    if entry.rir is not None:
        return entry.reps + entry.rir
    elif entry.rpe is not None:
        return entry.reps + (10 - entry.rpe)
    return entry.reps


def estimated_1rm(entry):
    """Fórmula de Epley, usando repeticiones efectivas en vez de las repeticiones hechas."""
    return entry.weight * (1 + effective_reps(entry) / 30)


def get_rest_seconds(exercise):
    note = db.session.scalar(
        sa.select(ExerciseNote).where(
            ExerciseNote.user_id == current_user.id, ExerciseNote.exercise == exercise
        )
    )
    return note.default_rest_seconds if note and note.default_rest_seconds else 90


def format_rest(seconds):
    if seconds is None:
        return None
    m, s = divmod(seconds, 60)
    if m and s:
        return f"{m}min {s}s"
    elif m:
        return f"{m}min"
    return f"{s}s"


def find_catalog_exercise(name):
    if not name:
        return None
    return db.session.scalar(
        sa.select(Exercise).where(
            sa.or_(Exercise.name.ilike(name), Exercise.name_es.ilike(name))
        )
    )


def get_exercise_image(name):
    ex = find_catalog_exercise(name)
    return ex.image_url if ex else None
