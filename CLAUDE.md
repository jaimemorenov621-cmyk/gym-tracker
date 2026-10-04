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

```
python -m unittest discover -s tests -t .   # run all tests (in-memory SQLite)
```

Run discovery from `tests/` (`-s tests`), not the repo root: root-level discovery imports the `app` package before the tests can point `DATABASE_URL` at in-memory SQLite, so the DB tests abort via their safety assert instead of touching `app.db`. There is no lint/format config in this repo.

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
- `app/achievements.py` — achievements catalog (in code; `code` values are stored per user in `UserAchievement` and must never change), `compute_stats(user)` (one query over the whole history) and `evaluate(user)`.
- `app/strength_standards.py` — Lon Kilgore's strength standards (ExRx, kept in pounds as published, converted to kg in code), strict barbell-lift detection (`lift_of`), DOTS, and `strength_profile(user)` (per-lift "reached" level using the body weight logged at each session; ranks Hierro→Bronce→Plata→Oro→Platino→Diamante→Esmeralda→Campeón→Titán from a continuous score over the last 90 days; global rank = mean of the basics trained in that window, min 3; each basic is the best-scoring of its variants, each against its own table: bench, squat or Smith squat, deadlift or Romanian deadlift, press, row or Smith row (`APPROX_TABLE`: no own table, uses the barbell row one and the app says so), pull-ups or lat pulldown). Row, pull-ups and lat pulldown use StrengthLevel tables (community percentiles, different method — disclosed in the app); pull-ups are logged as added weight (0 = bodyweight) and compared as bodyweight + added. Shown in `/progress` and used by the "Estándares de fuerza" achievements.
- `app/progression.py` — XP and levels. `compute_xp()` is pure over `load_xp_inputs()` (3 column-only queries); `User.xp_total` is only a cache, valid while `xp_cached_seq == xp_seq`, `xp_rules == XP_RULES_VERSION` and younger than 24 h. `xp_seq` is bumped atomically by ORM flush listeners (per user) and by a cursor-level listener for any other DML on `workout`/`set_entry`/`daily_checkin`/`weekly_goal_history` (bumps everyone). **Any bulk `update`/`delete`/`insert` on those tables must either be fine invalidating everyone or carry `.execution_options(xp_irrelevant=True)`** — tests run with `XP_STRICT_BULK_DML` and fail otherwise. Migrations disable the listener (`migrations/env.py`); a migration that changes those tables' data needs the comment `# xp: requiere flask recompute-xp`. Changing an XP rule = bump `XP_RULES_VERSION` and update `level.html`. CLI: `flask recompute-xp [--user ID] [--check]`, `flask export-user ID [--out f.json]`, `flask delete-user ID --yes` (data-deletion requests; the ORM can't delete a `User` because `User.workouts` is WriteOnly).
- `PersonalBasic` (model) — exercises a user marks as *their* basics in the Rango tab (`/rango/basicos`): rank if the lift has a standards table, otherwise their progression (`exercise_stats`). Included in `_user_tables` (delete/export) and `rename_exercise_everywhere`.
- `app/volume.py` — weekly hard sets per muscle group (catalog primary = 1, secondary = 0.5; RIR ≤ 4 or RPE ≥ 6, or no effort logged) vs the 10-20 sets/week evidence range; shown in `/progress`. Factual only: never "recovered"/"fatigued".
- `app/perks.py` — level perks, cosmetic or convenience only (no data/analysis depends on level): accent colours (per device in localStorage `gyre-accent`, applied in the `<head>` script of `base.html` only if listed in `<html data-accents>`; colours are CSS tokens `--accent*`/`--color-brand*` under `:root[data-accent=...]`), share-card designs (`share_card.js`, chosen in the share sheet), level/rank badge on the card from level 10, and 2 AI analyses per 7 days from level 20 (`ai_analysis_blocking`). Level is read from the cached `User.xp_total` (no recompute). New in-app purple should use `var(--accent)` / `rgba(var(--accent-rgb), …)`, not hardcoded `#7c4dff` (the landing keeps the fixed brand purple).
- `app/usage.py` — privacy-respecting usage counter (`DailyActivity`: one row per user/day, 120-day retention) and the rest-day usage report in `/landing/stats`.

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
