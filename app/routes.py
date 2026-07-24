from flask import render_template, flash, redirect, url_for, request
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
)
from app.models import User, Workout, SetEntry


@app.route("/")
@app.route("/index")
@login_required
def index():
    workouts = db.session.scalars(
        current_user.workouts.select().order_by(Workout.timestamp.desc())
    ).all()
    return render_template("index.html", title="Inicio", workouts=workouts)


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
    form = WorkoutForm()
    if form.validate_on_submit():
        workout = Workout(
            note=form.note.data,
            author=current_user,
        )
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

    if request.method == "GET":
        exercise_prefill = request.args.get("exercise")
        if exercise_prefill:
            form.exercise.data = exercise_prefill

    if form.validate_on_submit():
        scale = current_user.effort_scale
        entry = SetEntry(
            exercise=form.exercise.data.strip().lower(),
            weight=form.weight.data,
            reps=form.reps.data,
            rir=form.effort_value.data if scale == "rir" else None,
            rpe=form.effort_value.data if scale == "rpe" else None,
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
    empty_form = EmptyForm()
    return render_template(
        "workout_detail.html",
        title=workout.note or "Entrenamiento",
        workout=workout,
        grouped_sets=grouped_sets,
        form=form,
        empty_form=empty_form,
        effort_scale=current_user.effort_scale,
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
            chart_colors.append("#2e7d32")  # verde: nuevo récord
        elif id(s) in lastN_ids and stagnation:
            chart_colors.append("#c62828")  # rojo: parte de la racha de estancamiento
        else:
            chart_colors.append("#1565c0")  # azul: normal

    return render_template(
        "exercise_progress.html", title=name.title(), exercise=name,
        sessions=list(reversed(session_list)),
        stagnation=stagnation, improvement=improvement, threshold=threshold,
        chart_labels=chart_labels, chart_values=chart_values, chart_colors=chart_colors,
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


def effective_reps(entry):
    if entry.rir is not None:
        return entry.reps + entry.rir
    elif entry.rpe is not None:
        return entry.reps + (10 - entry.rpe)
    return entry.reps


def estimated_1rm(entry):
    """Fórmula de Epley, usando repeticiones efectivas en vez de las repeticiones hechas."""
    return entry.weight * (1 + effective_reps(entry) / 30)
