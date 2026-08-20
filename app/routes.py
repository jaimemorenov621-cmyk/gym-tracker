from flask import render_template, flash, redirect, url_for, request, jsonify
from flask_login import current_user, login_user, logout_user, login_required
from urllib.parse import urlsplit
from collections import defaultdict
import json
import unicodedata
import sqlalchemy as sa
from openai import OpenAI
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
    WeightForm,
    AiCheckinForm,
    NotesForm,
)
from app.models import (
    User,
    Workout,
    SetEntry,
    ExerciseNote,
    Routine,
    RoutineExercise,
    Exercise,
    AiAnalysis,
    BodyWeightEntry,
    WeeklyGoalHistory,
)
from app.muscle_svg_data import BODY_PARTS, AUXILIARY_SLUGS
from datetime import datetime, timezone, timedelta


@app.route("/sw.js")
def service_worker():
    return app.send_static_file("sw.js")


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

    streak, streak_unit = compute_smart_streak(current_user.id, workouts)

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

    weight_entries = db.session.scalars(
        sa.select(BodyWeightEntry)
        .where(BodyWeightEntry.user_id == current_user.id)
        .order_by(BodyWeightEntry.timestamp.asc())
    ).all()
    latest_weight = weight_entries[-1] if weight_entries else None

    strength_result = compute_strength_change()
    strength_change, strength_window_days = strength_result if strength_result else (None, None)

    notes_form = NotesForm()
    notes_form.notes.data = current_user.notes or ""

    return render_template(
        "index.html",
        title="Inicio",
        grouped=grouped,
        total_workouts=total_workouts,
        streak=streak,
        streak_unit=streak_unit,
        calendar_weeks=calendar_weeks,
        strength_change=strength_change,
        strength_window_days=strength_window_days,
        latest_weight=latest_weight,
        weight_chart_labels=[e.timestamp.strftime("%d/%m") for e in weight_entries],
        weight_chart_values=[e.weight for e in weight_entries],
        muscle_colors=compute_muscle_intensity(),
        muscle_svg=build_muscle_svg_parts(current_user.sex),
        notes_form=notes_form,
    )


@app.route("/notes", methods=["POST"])
@login_required
def update_notes():
    form = NotesForm()
    if form.validate_on_submit():
        current_user.notes = form.notes.data
        db.session.commit()
        flash("Notas guardadas.")
    return redirect(url_for("index"))


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
        scale = current_user.effort_scale
        entry = SetEntry(
            exercise=canonicalize_exercise_name(form.exercise.data),
            weight=0,
            reps=0,
            rir=2 if scale == "rir" else None,
            rpe=8 if scale == "rpe" else None,
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

    weight = max(0, min(500, float(str(data.get("weight") or 0).replace(",", "."))))
    reps = max(0, min(30, int(float(data.get("reps") or 0))))
    effort = data.get("effort")
    scale = current_user.effort_scale

    entry = SetEntry(
        exercise=exercise,
        weight=weight,
        reps=reps,
        rir=max(0, min(10, int(effort))) if scale == "rir" and effort not in (None, "") else None,
        rpe=max(0, min(10, int(effort))) if scale == "rpe" and effort not in (None, "") else None,
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
    pr_relevant_changed = False
    if "weight" in data:
        entry.weight = max(0, min(500, float(str(data["weight"] or 0).replace(",", "."))))
        pr_relevant_changed = True
    if "reps" in data:
        entry.reps = max(0, min(30, int(float(data["reps"] or 0))))
        pr_relevant_changed = True
    if "effort" in data:
        effort = data["effort"]
        if scale == "rir":
            entry.rir = max(0, min(10, int(effort))) if effort not in (None, "") else None
            entry.rpe = None
        elif scale == "rpe":
            entry.rpe = max(0, min(10, int(effort))) if effort not in (None, "") else None
            entry.rir = None
        pr_relevant_changed = True
    if "set_type" in data:
        entry.set_type = data["set_type"]

    just_completed = False
    if "completed" in data:
        was_completed = entry.completed
        entry.completed = bool(data["completed"])
        just_completed = entry.completed and not was_completed
        if not entry.completed and entry.is_pr:
            entry.is_pr = False

    # Mismo recálculo tanto al completar como al corregir peso/reps/esfuerzo
    # de una serie ya completada -- nunca al editar una que no lo está.
    if entry.completed and (just_completed or pr_relevant_changed):
        recompute_pr_badges(entry)

    db.session.commit()

    response = {"ok": True, "is_pr": bool(entry.is_pr)}
    if just_completed:
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
            # "Hecho" = series marcadas con el tick, no series que simplemente
            # existen -- desde que start_routine() precarga las series del
            # plan, contar solo la existencia haría que esto marcara 100% nada
            # más iniciar el entrenamiento, sin haber rellenado nada todavía.
            done = sum(
                1 for s in grouped_sets.get(re.exercise.strip().lower(), []) if s.completed
            )
            routine_plan.append(
                {
                    "exercise": re.exercise,
                    "target_sets": re.target_sets,
                    "target_reps": re.target_reps,
                    "done": done,
                }
            )

    # Total de series registradas vs. planeadas en toda la sesión, para el
    # anillo de progreso -- solo tiene sentido si hay un plan de rutina (un
    # entrenamiento libre no tiene "objetivo" contra el que medir progreso).
    ring_done = sum(p["done"] for p in routine_plan)
    ring_target = sum(p["target_sets"] for p in routine_plan)
    ring_pct = min(1.0, ring_done / ring_target) if ring_target else 0.0

    empty_form = EmptyForm()
    new_exercise_form = NewExerciseForm()
    previous_sets_map = get_previous_sets_map(workout, exercise_order)
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
        ring_done=ring_done,
        ring_target=ring_target,
        ring_pct=ring_pct,
        new_exercise_form=new_exercise_form,
        previous_sets_map=previous_sets_map,
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
        non_empty_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(SetEntry)
            .where(SetEntry.workout_id == workout.id, SetEntry.reps > 0)
        )
        if not non_empty_count:
            flash(
                "No puedes finalizar un entrenamiento sin ninguna serie con "
                "repeticiones registradas."
            )
            return redirect(url_for("workout_detail", workout_id=workout.id))

        empty_sets = db.session.scalars(
            sa.select(SetEntry).where(
                SetEntry.workout_id == workout.id, SetEntry.reps == 0
            )
        ).all()
        for entry in empty_sets:
            db.session.delete(entry)

        workout.performance_rating = form.performance_rating.data
        workout.performance_comment = form.performance_comment.data
        workout.ended_at = datetime.now(timezone.utc)
        db.session.commit()

        if empty_sets:
            n = len(empty_sets)
            if n == 1:
                flash("Entrenamiento guardado. Se eliminó 1 serie vacía sin rellenar.")
            else:
                flash(f"Entrenamiento guardado. Se eliminaron {n} series vacías sin rellenar.")
        else:
            flash("Entrenamiento guardado.")
        return redirect(url_for("index", celebrate=1))
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

    session_list, stagnation, improvement = get_exercise_sessions(name)

    threshold = current_user.stagnation_threshold
    lastN_ids = (
        {id(s) for s in session_list[-threshold:]}
        if len(session_list) >= threshold
        else set()
    )

    chart_labels = [s["timestamp"].strftime("%d/%m %H:%M") for s in session_list]
    chart_values = [round(s["best_1rm"], 1) for s in session_list]
    chart_colors = []
    for s in session_list:
        if s["is_pr"]:
            chart_colors.append("#17a973")
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


def _latest_weekly_goal_row(user_id):
    return db.session.scalar(
        sa.select(WeeklyGoalHistory)
        .where(WeeklyGoalHistory.user_id == user_id)
        .order_by(WeeklyGoalHistory.effective_from.desc())
        .limit(1)
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    form = SettingsForm()
    if form.validate_on_submit():
        current_user.stagnation_threshold = form.stagnation_threshold.data
        current_user.effort_scale = form.effort_scale.data
        current_user.sex = form.sex.data or None
        current_user.height_cm = form.height_cm.data
        current_user.training_goal = form.training_goal.data or None

        latest = _latest_weekly_goal_row(current_user.id)
        current_goal = latest.goal if latest else None
        if form.disable_weekly_goal.data:
            if current_goal is not None:
                db.session.add(WeeklyGoalHistory(user_id=current_user.id, goal=None))
        elif form.weekly_workout_goal.data and form.weekly_workout_goal.data != current_goal:
            db.session.add(
                WeeklyGoalHistory(
                    user_id=current_user.id, goal=form.weekly_workout_goal.data
                )
            )

        db.session.commit()
        flash("Configuración guardada.")
        return redirect(url_for("settings"))
    elif request.method == "GET":
        form.stagnation_threshold.data = current_user.stagnation_threshold
        form.effort_scale.data = current_user.effort_scale
        form.sex.data = current_user.sex or ""
        form.height_cm.data = current_user.height_cm
        form.training_goal.data = current_user.training_goal or ""
        latest = _latest_weekly_goal_row(current_user.id)
        form.weekly_workout_goal.data = latest.goal if latest else None
        form.disable_weekly_goal.data = bool(latest and latest.goal is None)
    return render_template("settings.html", title="Configuración", form=form)


@app.route("/weight", methods=["GET", "POST"])
@login_required
def weight():
    form = WeightForm()
    if form.validate_on_submit():
        db.session.add(BodyWeightEntry(weight=form.weight.data, user_id=current_user.id))
        db.session.commit()
        flash("Peso registrado.")
        return redirect(url_for("weight"))

    entries = db.session.scalars(
        sa.select(BodyWeightEntry)
        .where(BodyWeightEntry.user_id == current_user.id)
        .order_by(BodyWeightEntry.timestamp.asc())
    ).all()

    return render_template(
        "weight.html",
        title="Peso corporal",
        form=form,
        empty_form=EmptyForm(),
        entries=list(reversed(entries)),
        chart_labels=[e.timestamp.strftime("%d/%m/%Y") for e in entries],
        chart_values=[e.weight for e in entries],
    )


@app.route("/weight/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete_weight_entry(entry_id):
    entry = db.get_or_404(BodyWeightEntry, entry_id)
    if entry.user_id != current_user.id:
        flash("No tienes acceso a ese registro de peso.")
        return redirect(url_for("weight"))
    db.session.delete(entry)
    db.session.commit()
    flash("Registro de peso eliminado.")
    return redirect(url_for("weight"))


@app.route("/ai/analysis")
@login_required
def ai_analysis():
    latest = db.session.scalar(
        sa.select(AiAnalysis)
        .where(AiAnalysis.user_id == current_user.id)
        .order_by(AiAnalysis.created_at.desc())
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    next_available = None
    if latest:
        available_at = latest.created_at + timedelta(days=7)
        if available_at > now:
            next_available = available_at

    try:
        analysis = json.loads(latest.content) if latest else None
    except json.JSONDecodeError:
        analysis = None
    # NOTA: esto solo cubre JSON inválido (texto libre antiguo, o cualquier
    # fallo de parseo). Si en el futuro se amplía AI_ANALYSIS_SCHEMA con un
    # campo nuevo, las filas ya guardadas con el schema viejo siguen siendo
    # JSON válido pero sin esa clave -- json.loads() no fallará aquí, y Jinja
    # no lanza excepción por una clave ausente (renderiza vacío en silencio).
    # Ese caso NO está cubierto todavía -- si se toca el schema, decidir
    # entonces si se versiona o si el fallback debe activarse también cuando
    # faltan claves esperadas, no solo cuando el JSON es inválido.

    return render_template(
        "ai_analysis.html",
        title="Análisis de IA",
        latest=latest,
        analysis=analysis,
        next_available=next_available,
        checkin_form=AiCheckinForm(),
    )


@app.route("/ai/analyze", methods=["POST"])
@login_required
def request_ai_analysis():
    checkin_form = AiCheckinForm()
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    has_recent = db.session.scalar(
        sa.select(AiAnalysis.id)
        .where(AiAnalysis.user_id == current_user.id, AiAnalysis.created_at >= cutoff)
        .limit(1)
    )
    if has_recent:
        flash("Ya generaste un análisis esta semana. Vuelve a intentarlo más adelante.")
        return redirect(url_for("ai_analysis"))

    try:
        how_you_feel = checkin_form.how_you_feel.data if checkin_form.validate_on_submit() else None
        content = generate_ai_analysis(how_you_feel=how_you_feel)
        json.loads(content)  # validar antes de guardar -- ver nota en ai_analysis()
        # sobre por qué un JSON truncado/inválido no debe llegar a AiAnalysis:
        # si esto falla no se gasta el cupo semanal (no se guarda nada) y el
        # usuario ve el mismo aviso de "vuelve a intentarlo" que un fallo de
        # la API, en vez de una tarjeta rota con JSON crudo sin renderizar.
    except Exception:
        flash("No se pudo generar el análisis ahora mismo. Inténtalo de nuevo en unos minutos.")
        return redirect(url_for("ai_analysis"))

    db.session.add(AiAnalysis(content=content, user_id=current_user.id))
    db.session.commit()
    flash("¡Análisis generado!")
    return redirect(url_for("ai_analysis"))


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
            exercise=canonicalize_exercise_name(form.exercise.data),
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
    db.session.flush()

    # Precarga ejercicios y series desde el plan de la rutina, en vez de dejar
    # el entrenamiento vacío -- el usuario solo rellena peso/reps y marca el
    # tick. El nombre se copia tal cual de RoutineExercise (ya fijado al crear
    # la rutina), nunca se retipea, así que no hay riesgo de que no coincida
    # con el plan. Peso/reps se dejan a 0 (a rellenar) -- no se adivinan
    # valores; la columna "Anterior" ya da la referencia de la sesión pasada.
    routine_exercises = db.session.scalars(
        sa.select(RoutineExercise)
        .where(RoutineExercise.routine_id == routine.id)
        .order_by(RoutineExercise.order_index)
    ).all()
    for re_ in routine_exercises:
        for _ in range(re_.target_sets):
            db.session.add(
                SetEntry(
                    exercise=re_.exercise,
                    weight=0.0,
                    reps=0,
                    set_type="normal",
                    workout=workout,
                )
            )

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
    word_conditions = [
        sa.or_(Exercise.name.ilike(f"%{word}%"), Exercise.name_es.ilike(f"%{word}%"))
        for word in q.split()
    ]
    results = db.session.scalars(
        sa.select(Exercise).where(sa.and_(*word_conditions)).limit(24)
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


def _slugify_exercise_name(name):
    """Genera un id de catálogo a partir de un nombre -- sin usar el módulo `re`
    a propósito: `re` ya se usa como nombre de variable de bucle en otras
    funciones de este archivo (RoutineExercise), y un `import re` a nivel de
    módulo sería confuso mezclado con eso."""
    stripped = _strip_accents(name)
    slug = "".join(c if c.isalnum() else "_" for c in stripped)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "exercise"


@app.route("/api/exercises/create", methods=["POST"])
@login_required
def api_create_exercise():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    muscles = [m for m in (data.get("muscles") or []) if m in MUSCLE_GROUP_MAP]
    category = (data.get("category") or "").strip() or None
    equipment = (data.get("equipment") or "").strip() or None

    if not name:
        return jsonify({"ok": False, "error": "El nombre es obligatorio."}), 400
    if not muscles:
        return jsonify({"ok": False, "error": "Elige al menos un músculo."}), 400

    base_slug = _slugify_exercise_name(name)
    new_id = base_slug
    suffix = 2
    while db.session.get(Exercise, new_id) is not None:
        new_id = f"{base_slug}_{suffix}"
        suffix += 1

    exercise = Exercise(
        id=new_id,
        name=name,
        name_es=name,
        category=category,
        primary_muscles=", ".join(muscles),
        equipment=equipment,
        image_url=None,
    )
    db.session.add(exercise)
    db.session.commit()
    return jsonify({"ok": True, "name": name})


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


def compute_streak(workouts):
    """Días consecutivos entrenando, contando hacia atrás desde hoy o ayer."""
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
    return streak


def compute_smart_streak(user_id, workouts):
    """(valor, unidad). Sin objetivo semanal nunca configurado, o desactivado
    explícitamente (última fila de WeeklyGoalHistory con goal=None) ->
    fallback a compute_streak() (días). Con objetivo activo -> semanas
    consecutivas cumpliendo el objetivo que estaba VIGENTE en cada semana
    (no el objetivo actual) -- ver WeeklyGoalHistory en app/models.py."""
    history = db.session.scalars(
        sa.select(WeeklyGoalHistory)
        .where(WeeklyGoalHistory.user_id == user_id)
        .order_by(WeeklyGoalHistory.effective_from.desc())
    ).all()
    if not history or history[0].goal is None:
        return compute_streak(workouts), "días"

    week_counts = defaultdict(int)
    for w in workouts:
        week_start = w.timestamp.date() - timedelta(days=w.timestamp.weekday())
        week_counts[week_start] += 1

    def goal_for_week(week_start):
        # naive, igual que WeeklyGoalHistory.effective_from -- ver comentario
        # en el modelo sobre por qué Workout.timestamp vuelve naive de SQLite.
        week_start_dt = datetime.combine(week_start, datetime.min.time())
        for h in history:  # ya ordenado desc por effective_from
            if h.effective_from <= week_start_dt:
                return h.goal
        return None  # anterior a que existiera cualquier objetivo, o antes
        # de una fila con goal=None (desactivado)

    today = datetime.now(timezone.utc).date()
    current_week_start = today - timedelta(days=today.weekday())
    week = current_week_start
    streak = 0

    current_goal = goal_for_week(week)
    if current_goal is not None:
        if week_counts.get(week, 0) >= current_goal:
            streak += 1
            week -= timedelta(days=7)
        elif today.weekday() == 6:
            # semana en curso YA terminó (es domingo) y no llegó al objetivo
            return 0, "semanas"
        else:
            # semana en curso todavía sin terminar y sin cumplir aún -- no
            # rompe la racha, simplemente no cuenta todavía; se sigue
            # evaluando desde la semana anterior, ya cerrada
            week -= timedelta(days=7)
    else:
        return 0, "semanas"

    while True:
        goal = goal_for_week(week)
        if goal is None:
            break
        if week_counts.get(week, 0) >= goal:
            streak += 1
            week -= timedelta(days=7)
        else:
            break

    return streak, "semanas"


def get_previous_sets_map(workout, exercise_names):
    """Para cada ejercicio de `exercise_names`, las series (peso×reps) de la última vez
    que current_user lo entrenó antes de `workout`. Una sola consulta, sin N+1."""
    if not exercise_names:
        return {}
    rows = db.session.execute(
        sa.select(Workout.id, SetEntry.exercise, SetEntry.weight, SetEntry.reps)
        .join(SetEntry, SetEntry.workout_id == Workout.id)
        .where(
            Workout.user_id == current_user.id,
            Workout.timestamp < workout.timestamp,
            SetEntry.exercise.in_(exercise_names),
        )
        .order_by(SetEntry.exercise, Workout.timestamp.desc(), SetEntry.id)
    ).all()

    result = {}
    last_workout_id = {}
    for wid, exercise, weight, reps in rows:
        last_workout_id.setdefault(exercise, wid)
        if last_workout_id[exercise] == wid:
            result.setdefault(exercise, []).append(f"{weight:g}kg×{reps}")
    return result


def get_exercise_sessions(name, user_id=None):
    """Sesiones históricas de `name`, con 1RM estimado, PRs y estancamiento.
    Por defecto usa current_user; acepta user_id explícito para poder
    llamarse fuera de un request autenticado (backfill)."""
    if user_id is None:
        user_id = current_user.id
        threshold = current_user.stagnation_threshold
    else:
        threshold = db.session.get(User, user_id).stagnation_threshold

    query = (
        sa.select(Workout, SetEntry)
        .join(SetEntry, SetEntry.workout_id == Workout.id)
        .where(Workout.user_id == user_id, SetEntry.exercise == name)
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

    stagnation = False
    improvement = False
    if len(session_list) >= threshold:
        lastN = session_list[-threshold:]
        stagnation = not any(s["is_pr"] for s in lastN)
        improvement = lastN[-1]["is_pr"]

    return session_list, stagnation, improvement


def apply_pr_flags_for_session(session):
    """Persiste is_pr en la serie ganadora de una sesión (dict de
    get_exercise_sessions) y lo limpia en el resto de esa MISMA sesión.
    Compartida entre completar/editar una serie y el backfill masivo."""
    changed = 0
    for s in session["sets"]:
        should_be_pr = session["is_pr"] and s.id == session["best_set"].id
        if s.is_pr != should_be_pr:
            s.is_pr = should_be_pr
            changed += 1
    return changed


def count_pending_pr_changes(session):
    """Versión de solo lectura de apply_pr_flags_for_session -- no muta
    nada, solo cuenta. Para el modo simulación del backfill."""
    return sum(
        1
        for s in session["sets"]
        if s.is_pr != (session["is_pr"] and s.id == session["best_set"].id)
    )


def recompute_pr_badges(entry):
    """Recalcula y persiste qué SetEntry de la sesión de `entry` (mismo
    workout+ejercicio) debe lucir la medalla. Se llama tanto al completar
    una serie como al editar peso/reps/esfuerzo de una ya completada.
    No hace commit -- el llamador decide cuándo."""
    session_list, _, _ = get_exercise_sessions(entry.exercise, user_id=entry.workout.user_id)
    current = next((s for s in session_list if s["sets"][0].workout_id == entry.workout_id), None)
    if current is not None:
        apply_pr_flags_for_session(current)


def compute_strength_change():
    """% de cambio de fuerza entre el periodo actual y el anterior, ponderado por
    nº de sesiones recientes de cada ejercicio. Devuelve (pct, window_days) o None
    si no hay datos suficientes en ningún ejercicio.

    La ventana es adaptativa (hasta 90 días) en vez de fija: con una cuenta nueva,
    exigir siempre 90+91 días de historial deja el dato en "—" durante meses sin
    remedio posible, por mucho que se entrene. En su lugar se parte el historial
    real del usuario por la mitad (mínimo 7 días de ventana), y ese reparto crece
    hasta el estándar de 90 días según se acumula historial."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    oldest = db.session.scalar(
        sa.select(sa.func.min(Workout.timestamp)).where(Workout.user_id == current_user.id)
    )
    if oldest is None:
        return None
    window_days = min(90, max(7, (now - oldest).days // 2))

    current_start = now - timedelta(days=window_days)
    previous_start = now - timedelta(days=window_days * 2)

    exercises = db.session.scalars(
        sa.select(SetEntry.exercise)
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(Workout.user_id == current_user.id)
        .distinct()
    ).all()

    weighted_sum = 0.0
    total_weight = 0
    for name in exercises:
        session_list, _, _ = get_exercise_sessions(name)
        current_sessions = [s for s in session_list if s["timestamp"] >= current_start]
        previous_sessions = [
            s for s in session_list if previous_start <= s["timestamp"] < current_start
        ]
        if len(current_sessions) < 2 or len(previous_sessions) < 2:
            continue
        best_current = max(s["best_1rm"] for s in current_sessions)
        best_previous = max(s["best_1rm"] for s in previous_sessions)
        if best_previous <= 0:
            continue
        pct_change = (best_current - best_previous) / best_previous * 100
        weight = len(current_sessions)
        weighted_sum += pct_change * weight
        total_weight += weight

    if total_weight == 0:
        return None

    pct = max(-50, min(100, weighted_sum / total_weight))
    return pct, window_days


def build_progress_summary():
    """Resumen compacto del historial de current_user, listo para pasarle a la IA."""
    workouts = db.session.scalars(
        current_user.workouts.select().order_by(Workout.timestamp.desc())
    ).all()

    exercise_rows = db.session.execute(
        sa.select(
            SetEntry.exercise,
            sa.func.count(sa.func.distinct(SetEntry.workout_id)).label("n"),
        )
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(Workout.user_id == current_user.id)
        .group_by(SetEntry.exercise)
        .order_by(sa.desc("n"))
        .limit(20)
    ).all()

    exercises = []
    for name, n_sessions in exercise_rows:
        session_list, stagnation, _ = get_exercise_sessions(name)
        if not session_list:
            continue
        catalog = find_catalog_exercise(name)
        muscle_group = None
        if catalog and catalog.primary_muscles:
            for muscle in catalog.primary_muscles.split(", "):
                muscle_group = MUSCLE_GROUP_MAP.get(muscle)
                if muscle_group:
                    break
        recent = session_list[-current_user.stagnation_threshold :]
        rirs = [s["best_set"].rir for s in recent if s["best_set"].rir is not None]
        rpes = [s["best_set"].rpe for s in recent if s["best_set"].rpe is not None]
        exercises.append(
            {
                "name": name.title(),
                "sessions": n_sessions,
                "best_1rm": round(max(s["best_1rm"] for s in session_list), 1),
                "stagnation": stagnation,
                "last_trained": session_list[-1]["timestamp"].strftime("%d/%m/%Y"),
                "muscle_group": muscle_group,
                "avg_rir": round(sum(rirs) / len(rirs), 1) if rirs else None,
                "avg_rpe": round(sum(rpes) / len(rpes), 1) if rpes else None,
            }
        )

    recent_workouts = []
    for w in workouts[:8]:
        sets = db.session.scalars(w.sets.select()).all()
        recent_workouts.append(
            {
                "date": w.timestamp.strftime("%d/%m/%Y"),
                "note": w.note or "Entrenamiento",
                "rating": w.performance_rating,
                "comment": w.performance_comment,
                "volume": round(sum(s.weight * s.reps for s in sets)),
                "duration": w.duration_str(),
            }
        )

    streak, streak_unit = compute_smart_streak(current_user.id, workouts)
    return {
        "total_workouts": len(workouts),
        "streak": streak,
        "streak_unit": streak_unit,
        "exercises": exercises,
        "recent_workouts": recent_workouts,
    }


AI_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "resumen": {
            "type": "string",
            "description": "1-2 frases de resumen general del progreso reciente",
        },
        "fortalezas": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Cosas que van bien, concretas y basadas en los datos",
        },
        "areas_mejora": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ejercicio": {"type": "string"},
                    "motivo": {"type": "string"},
                },
                "required": ["ejercicio", "motivo"],
                "additionalProperties": False,
            },
        },
        "proximos_pasos": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Recomendaciones concretas y accionables",
        },
    },
    "required": ["resumen", "fortalezas", "areas_mejora", "proximos_pasos"],
    "additionalProperties": False,
}


def generate_ai_analysis(how_you_feel=None):
    """Llama a la IA con el resumen de progreso de current_user y devuelve el texto generado."""
    summary = build_progress_summary()

    lines = [
        f"Entrenamientos totales: {summary['total_workouts']}",
        f"Racha actual: {summary['streak']} {summary['streak_unit']} consecutivos entrenando"
        if summary["streak_unit"] == "días"
        else f"Racha actual: {summary['streak']} semanas consecutivas cumpliendo el objetivo semanal",
    ]

    goal_labels = {
        "hipertrofia": "hipertrofia",
        "fuerza": "fuerza",
        "perdida_grasa": "pérdida de grasa",
    }
    profile_parts = []
    if current_user.sex:
        profile_parts.append(current_user.sex)
    if current_user.height_cm:
        profile_parts.append(f"{current_user.height_cm}cm")
    if current_user.training_goal:
        profile_parts.append(
            f"objetivo: {goal_labels.get(current_user.training_goal, current_user.training_goal)}"
        )
    if profile_parts:
        lines.append(f"Perfil: {', '.join(profile_parts)}.")

    lines += [
        "",
        "Ejercicios registrados (nombre: nº sesiones, mejor 1RM estimado, estado, última vez, "
        "grupo muscular, esfuerzo medio reciente):",
    ]
    for ex in summary["exercises"]:
        estado = "ESTANCADO" if ex["stagnation"] else "progresando"
        parts = [
            f"{ex['sessions']} sesiones",
            f"1RM est. {ex['best_1rm']}kg",
            estado,
            f"última vez {ex['last_trained']}",
        ]
        if ex["muscle_group"]:
            parts.append(f"grupo: {ex['muscle_group']}")
        if ex["avg_rir"] is not None:
            parts.append(f"RIR medio reciente: {ex['avg_rir']}")
        elif ex["avg_rpe"] is not None:
            parts.append(f"RPE medio reciente: {ex['avg_rpe']}")
        lines.append(f"- {ex['name']}: " + ", ".join(parts))

    stagnant_groups = {
        ex["muscle_group"] for ex in summary["exercises"] if ex["stagnation"] and ex["muscle_group"]
    }
    if stagnant_groups:
        volumes = compute_muscle_volumes(days=14)
        max_volume = max(volumes.values()) if volumes else 0
        lines.append("")
        lines.append(
            "Volumen relativo por grupo muscular en los últimos 14 días (100% = grupo más "
            "trabajado; solo se listan los grupos de ejercicios estancados, para valorar si "
            "conviene más volumen/frecuencia para ese grupo, o si ya está muy trabajado y lo "
            "que hace falta es una descarga):"
        )
        for group in stagnant_groups:
            pct = round(volumes.get(group, 0) / max_volume * 100) if max_volume else 0
            lines.append(f"- {group}: {pct}%")

    weight_entries = db.session.scalars(
        sa.select(BodyWeightEntry)
        .where(BodyWeightEntry.user_id == current_user.id)
        .order_by(BodyWeightEntry.timestamp.asc())
    ).all()
    if len(weight_entries) >= 2:
        first, last = weight_entries[0], weight_entries[-1]
        delta = round(last.weight - first.weight, 1)
        days_span = (last.timestamp - first.timestamp).days
        lines.append("")
        lines.append(
            f"Peso corporal: de {first.weight}kg ({first.timestamp.strftime('%d/%m/%Y')}) a "
            f"{last.weight}kg ({last.timestamp.strftime('%d/%m/%Y')}), {delta:+}kg en "
            f"{days_span} días."
        )

    lines.append("")
    lines.append("Últimos entrenamientos (fecha · nombre · valoración · volumen · duración · comentario):")
    for w in summary["recent_workouts"]:
        rating = f"{w['rating']}/10" if w["rating"] else "sin valorar"
        parts = [w["date"], w["note"], rating, f"{w['volume']}kg de volumen"]
        if w["duration"]:
            parts.append(w["duration"])
        if w["comment"]:
            parts.append(f"comentario: {w['comment']}")
        lines.append("- " + " · ".join(parts))

    if how_you_feel:
        lines.append("")
        lines.append(f"Cómo dice sentirse el usuario ahora mismo: {how_you_feel}")

    prompt = "\n".join(lines)

    api_key = app.config.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada")

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model="gpt-5.6-luna",
        instructions=(
            "Eres un entrenador personal experto analizando el historial de entrenamientos "
            "de un usuario de una app de gimnasio. Responde en español, con recomendaciones "
            "concretas y accionables basadas ÚNICAMENTE en los datos proporcionados. No "
            "inventes datos que no se te han dado. Evita consejos genéricos ('sigue "
            "esforzándote'); sé específico sobre qué ejercicios necesitan atención y por qué. "
            "Si de verdad no hay suficiente historial para alguna sección, devuelve esa lista "
            "vacía en vez de rellenarla con generalidades sin base en los datos.\n\n"
            "Para los ejercicios marcados como ESTANCADOS, el usuario ya sabe lo que es la "
            "sobrecarga progresiva -- NUNCA respondas simplemente 'sube el peso' o 'progresa "
            "de forma progresiva': si no ha subido el peso es porque no ha podido. En su lugar, "
            "usa los datos que tienes para razonar sobre la causa probable y proponer algo más "
            "específico, por ejemplo: si el RIR/RPE medio reciente indica que las series no van "
            "cerca del fallo, sugiere ajustar la intensidad; si el grupo muscular de ese "
            "ejercicio tiene un volumen relativo bajo frente a otros grupos, sugiere añadir más "
            "volumen o frecuencia para ese grupo; si el esfuerzo ya es alto y lleva muchas "
            "sesiones sin PR, considera si conviene una semana de descarga; si el peso corporal "
            "muestra una tendencia a la baja, considera si el problema puede ser un déficit "
            "calórico y sugiere revisar la ingesta. Si el usuario ha descrito cómo se siente "
            "(fatiga, agujetas, sueño...), ténlo en cuenta como una señal más, no la ignores. "
            "No propongas varias causas a la vez sin justificarlas con los datos -- elige la "
            "explicación mejor respaldada por lo que tienes."
        ),
        input=prompt,
        text={
            "format": {
                "type": "json_schema",
                "name": "analisis_entrenamiento",
                "schema": AI_ANALYSIS_SCHEMA,
                "strict": True,
            }
        },
        max_output_tokens=3000,
    )
    return response.output_text


def get_rest_seconds(exercise):
    note = db.session.scalar(
        sa.select(ExerciseNote).where(
            ExerciseNote.user_id == current_user.id, ExerciseNote.exercise == exercise
        )
    )
    return note.default_rest_seconds if note and note.default_rest_seconds else 120


def format_rest(seconds):
    if seconds is None:
        return None
    m, s = divmod(seconds, 60)
    if m and s:
        return f"{m}min {s}s"
    elif m:
        return f"{m}min"
    return f"{s}s"


def _strip_accents(s):
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


def find_catalog_exercise(name):
    if not name:
        return None
    match = db.session.scalar(
        sa.select(Exercise).where(
            sa.or_(Exercise.name.ilike(name), Exercise.name_es.ilike(name))
        )
    )
    if match:
        return match

    target = _strip_accents(name)
    for ex in db.session.scalars(sa.select(Exercise)):
        if _strip_accents(ex.name) == target:
            return ex
        if ex.name_es and _strip_accents(ex.name_es) == target:
            return ex
    return None


def canonicalize_exercise_name(name):
    """Si `name` coincide (ignorando acentos/mayúsculas) con el catálogo, devuelve la
    forma canónica del catálogo en vez del texto tal cual lo escribió el usuario."""
    name = name.strip().lower()
    match = find_catalog_exercise(name)
    if match:
        return (match.name_es or match.name).strip().lower()
    return name


def get_exercise_image(name):
    ex = find_catalog_exercise(name)
    return ex.image_url if ex else None


# Vocabulario de Exercise.primary_muscles -> grupo (en español, como el resto de
# la app). "abductors" no tiene path propio en los datos vectoriales de origen
# (verificado: cero coincidencias en los 4 ficheros fuente) — se aproxima a
# "cuadriceps" (cara externa del muslo, la región visualmente más próxima) en
# vez de fingir que es lo mismo que "adductors" (aductores, cara interna).
MUSCLE_GROUP_MAP = {
    "shoulders": "hombros",
    "neck": "cuello",
    "chest": "pecho",
    "abdominals": "abdomen",
    "biceps": "biceps",
    "triceps": "triceps",
    "forearms": "antebrazos",
    "quadriceps": "cuadriceps",
    "adductors": "aductores",
    "abductors": "cuadriceps",  # aproximación, sin path dedicado en la fuente — ver comentario arriba
    "glutes": "gluteos",
    "hamstrings": "isquiotibiales",
    "lats": "dorsales",
    "middle back": "dorsales",
    "lower back": "espalda_baja",
    "traps": "trapecios",
    "calves": "pantorrillas",
}
MUSCLE_GROUPS = (
    "trapecios", "hombros", "pecho", "biceps", "triceps", "antebrazos", "cuello",
    "abdomen", "dorsales", "espalda_baja", "cuadriceps", "aductores",
    "isquiotibiales", "gluteos", "pantorrillas",
)
# Grupo (español) -> slug del dataset vectorial (app/muscle_svg_data.py). Los
# slugs ausentes de este dict (head, hair, hands, feet, knees, ankles, tibialis)
# son piezas anatómicas auxiliares del dibujo, no músculos entrenables: se
# pintan siempre en color neutro, nunca a través de compute_muscle_intensity().
LIBRARY_SLUG_TO_GROUP = {
    "chest": "pecho",
    "abs": "abdomen",
    "obliques": "abdomen",
    "biceps": "biceps",
    "triceps": "triceps",
    "forearm": "antebrazos",
    "deltoids": "hombros",
    "neck": "cuello",
    "trapezius": "trapecios",
    "upper-back": "dorsales",
    "lower-back": "espalda_baja",
    "quadriceps": "cuadriceps",
    "adductors": "aductores",
    "gluteal": "gluteos",
    "hamstring": "isquiotibiales",
    "calves": "pantorrillas",
}
assert set(LIBRARY_SLUG_TO_GROUP) | AUXILIARY_SLUGS >= {
    slug for side in BODY_PARTS["male"].values() for slug in side
}, "hay un slug del dataset vectorial sin clasificar como grupo real o auxiliar"

_MUSCLE_NEUTRAL_RGB = (217, 213, 239)  # #d9d5ef, mismo tono neutro de la silueta base
# Color de "firma" por grupo muscular (a intensidad máxima) — un color vivo y
# distinto por cada uno de los 15 grupos, en un barrido de matiz tipo arcoíris
# para que sean fácilmente distinguibles entre sí. A intensidad 0 todas
# convergen al mismo gris neutro de arriba.
_MUSCLE_SIGNATURE_RGB = {
    "trapecios": (239, 68, 68),
    "hombros": (249, 115, 22),
    "pecho": (245, 158, 11),
    "biceps": (234, 179, 8),
    "antebrazos": (132, 204, 22),
    "cuello": (34, 197, 94),
    "abdomen": (16, 185, 129),
    "dorsales": (20, 184, 166),
    "espalda_baja": (6, 182, 212),
    "cuadriceps": (14, 165, 233),
    "aductores": (59, 130, 246),
    "isquiotibiales": (99, 102, 241),
    "triceps": (139, 92, 246),
    "gluteos": (168, 85, 247),
    "pantorrillas": (236, 72, 153),
}


def _interpolate_muscle_color(group, t):
    t = max(0.0, min(1.0, t))
    # Raíz cuadrada en vez de lineal: sin esto, solo el grupo con más volumen
    # (t=1) se ve realmente vivo y el resto queda casi en el gris neutro,
    # aunque se hayan entrenado con cierta intensidad relativa. Con la curva,
    # un grupo a la mitad del volumen máximo (t=0.5) ya llega a ~71% de
    # saturación en vez de quedarse en el 50% lineal -- el mapa se ve
    # colorido de verdad, no solo el pico.
    t = t ** 0.5
    target = _MUSCLE_SIGNATURE_RGB[group]
    r = round(_MUSCLE_NEUTRAL_RGB[0] + (target[0] - _MUSCLE_NEUTRAL_RGB[0]) * t)
    g = round(_MUSCLE_NEUTRAL_RGB[1] + (target[1] - _MUSCLE_NEUTRAL_RGB[1]) * t)
    b = round(_MUSCLE_NEUTRAL_RGB[2] + (target[2] - _MUSCLE_NEUTRAL_RGB[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def build_muscle_svg_parts(sex):
    """Devuelve {"front": [...], "back": [...]} listos para iterar en la plantilla:
    cada elemento es {"group": <grupo español o None>, "paths": [d, d, ...]}.
    group=None son piezas auxiliares (cabeza, manos, pies...) que la plantilla
    pinta siempre en color neutro."""
    gender = "female" if sex == "mujer" else "male"
    result = {}
    for side in ("front", "back"):
        parts = []
        for slug, paths in BODY_PARTS[gender][side].items():
            group = LIBRARY_SLUG_TO_GROUP.get(slug)
            all_paths = paths["left"] + paths["right"] + paths["common"]
            parts.append({"group": group, "paths": all_paths})
        result[side] = parts
    return result


def _effort_factor(entry):
    """Multiplicador de estrés según cercanía al fallo: 1.0x si la serie fue al fallo,
    0.5x si tenía mucho margen. Deliberadamente NO reutiliza effective_reps() —
    esa función va en la dirección contraria a propósito (más RIR = 1RM estimado
    más alto, porque para estimar fuerza máxima importa cuánto margen quedaba).
    Aquí el objetivo es el opuesto: una serie al fallo estimula más el músculo
    que la misma serie con mucho margen, así que a menos RIR (o más RPE) le
    corresponde más factor, no menos."""
    if entry.rir is not None:
        proximity = max(0, 10 - entry.rir) / 10
    elif entry.rpe is not None:
        proximity = entry.rpe / 10
    else:
        proximity = 0.7
    return 0.5 + proximity * 0.5


def compute_muscle_volumes(days=14):
    """Volumen bruto (peso × reps × cercanía al fallo) por grupo muscular en
    los últimos `days` días. Números absolutos, sin normalizar -- lo comparten
    compute_muscle_intensity() (colores del mapa muscular) y
    generate_ai_analysis() (para razonar sobre qué músculos están poco
    trabajados en relación al resto, no solo por ejercicio suelto)."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    entries = db.session.scalars(
        sa.select(SetEntry)
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(Workout.user_id == current_user.id, Workout.timestamp >= cutoff)
    ).all()

    volumes = {group: 0.0 for group in MUSCLE_GROUPS}
    catalog_cache = {}
    for entry in entries:
        if entry.exercise not in catalog_cache:
            catalog_cache[entry.exercise] = find_catalog_exercise(entry.exercise)
        catalog = catalog_cache[entry.exercise]
        if not catalog or not catalog.primary_muscles:
            continue
        stress = entry.weight * entry.reps * _effort_factor(entry)
        for muscle in catalog.primary_muscles.split(", "):
            group = MUSCLE_GROUP_MAP.get(muscle)
            if group:
                volumes[group] += stress
    return volumes


def compute_muscle_intensity(days=14):
    """Color por grupo muscular según el volumen entrenado en los últimos
    `days` días. Relativo al grupo más trabajado, no a un umbral absoluto."""
    volumes = compute_muscle_volumes(days)
    max_volume = max(volumes.values()) if volumes else 0
    return {
        group: _interpolate_muscle_color(group, volume / max_volume if max_volume else 0)
        for group, volume in volumes.items()
    }
