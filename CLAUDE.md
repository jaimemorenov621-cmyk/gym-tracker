# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Gym Tracker: a Flask app (server-rendered Jinja templates, no JS framework/build step) for logging workouts, tracking per-exercise progress/PRs, and managing reusable routines. UI text and flash messages are in Spanish.

## Commands

Activate the venv first (Windows): `venv\Scripts\activate` (PowerShell: `venv\Scripts\Activate.ps1`).

```
flask run                          # run dev server (reads .flaskenv: FLASK_APP=gymtracker.py, FLASK_DEBUG=1)
flask shell                        # shell with db, User, Workout, SetEntry preloaded (see gymtracker.py)
flask db migrate -m "message"      # generate a new migration after editing app/models.py
flask db upgrade                   # apply migrations
flask db downgrade                 # revert last migration
python import_exercises.py         # populate the Exercise catalog from an external JSON dataset (one-off/reseed)
```

There is no test suite and no lint/format config in this repo.

## Architecture

Classic single-package Flask app, not an application factory — `app` and `db` are module-level singletons created in `app/__init__.py` and imported everywhere (`from app import app, db`). `app/__init__.py` also wires `format_rest` and `get_exercise_image` (defined in `app/routes.py`) into `app.jinja_env.globals` so templates can call them directly.

- `app/__init__.py` — creates the Flask app, SQLAlchemy `db`, Flask-Migrate `migrate`, Flask-Login `login`; imports routes/models at the bottom (avoids circular imports).
- `app/models.py` — all SQLAlchemy models, using SQLAlchemy 2.0 typed `Mapped`/`mapped_column` style. Collections that can grow large use `WriteOnlyMapped` (e.g. `User.workouts`, `Routine.exercises`) — query them with `.select()` + `db.session.scalars(...)`, not by iterating the relationship directly.
- `app/routes.py` — all view functions and JSON API endpoints in one file, plus a few plain helper functions at the bottom (`effective_reps`, `estimated_1rm`, `format_rest`, `get_exercise_image`) that are not routes.
- `app/forms.py` — Flask-WTF forms used by the routes above.
- `app/templates/`, `app/static/style.css` — Jinja templates and the single stylesheet; no bundler.
- `migrations/` — Flask-Migrate/Alembic migrations. Always add one when `app/models.py` changes.
- `import_exercises.py` — standalone script (run outside the request lifecycle via `app.app_context()`) that seeds the `Exercise` catalog from the `yuhonas/free-exercise-db` GitHub dataset; used for exercise autocomplete/search and images.
- `config.py` — `SECRET_KEY` and `SQLALCHEMY_DATABASE_URI` from env vars, falling back to a local SQLite `app.db`.

### Domain model

- `User` has many `Workout`s and `Routine`s; also stores per-user preferences: `stagnation_threshold` (sessions without a PR before warning) and `effort_scale` (`"rir"`, `"rpe"`, or `"none"`).
- `Workout` is a single training session, optionally linked to the `Routine` it was started from. `performance_rating`/`performance_comment`/`ended_at` are only set when the workout is finished (`finish_workout` route) — an unfinished `Workout` (`performance_rating IS NULL`) within the last 6 hours is treated as the user's "active workout" (see `inject_active_workout` context processor and the guard in `new_workout`/`start_routine`, which block starting a second concurrent workout).
- `SetEntry` is one set within a workout: `exercise` (free-text, lowercased), `weight`, `reps`, and effort as either `rir` or `rpe` (mutually exclusive, matching `User.effort_scale`), plus `set_type` (normal/calentamiento/fallo/dropset).
- `ExerciseNote` is per-user, per-exercise metadata: freeform notes and a default rest timer (`default_rest_seconds`), unique on `(user_id, exercise)`.
- `Routine` has ordered `RoutineExercise` entries (`order_index`, reorderable via `/routines/<id>/reorder`) that define target sets/reps; starting a routine creates a `Workout` linked back to it.
- `Exercise` is a separate global catalog (id/name/category/muscles/equipment/image) used only for search/autocomplete/images (`/api/exercises/search`, `get_exercise_image`) — unrelated to `SetEntry.exercise`, which is just a string.

### Key conventions

- Exercise names are always normalized with `.strip().lower()` before being stored or queried against `SetEntry.exercise` / `ExerciseNote.exercise`, and titlecased (`.title()`) for display.
- Progress/PR logic (`exercise_progress` route) estimates 1RM via Epley's formula using "effective reps" (`effective_reps`/`estimated_1rm` in `app/routes.py`), which adds RIR or converts RPE to extra reps before applying the formula — do this consistently if you add related features.
- Ownership checks are manual per-route (`if workout.author != current_user`), not enforced via query filtering — follow the existing pattern (flash + redirect for page routes, `jsonify({"ok": False}), 403` for API routes) when adding new routes.
- JSON API routes (`/workout/<id>/set`, `/set/<id>`, `/routines/<id>/reorder`, etc.) return `{"ok": bool, ...}` and are called from inline `<script>` in the templates (no separate JS files/build step).
