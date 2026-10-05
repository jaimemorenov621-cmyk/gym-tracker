from flask import render_template, flash, redirect, url_for, request, jsonify, make_response, g, session
from flask_babel import gettext, get_locale, lazy_gettext, lazy_pgettext, ngettext
from flask_login import current_user, login_user, logout_user, login_required
from markupsafe import Markup, escape
from urllib.parse import urlsplit
from collections import defaultdict
import colorsys
import functools
import json
import os
import math
import re
import unicodedata
from typing import NamedTuple, Optional
import sqlalchemy as sa
from openai import OpenAI
from app import app, db, oauth
from app.forms import (
    LoginForm,
    RegistrationForm,
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
    RecoveryCheckinForm,
)
from app.models import (
    User,
    Workout,
    SetEntry,
    ExerciseNote,
    Routine,
    RoutineBlock,
    RoutineExercise,
    Exercise,
    ExerciseFavorite,
    LandingEvent,
    AiAnalysis,
    ContactMessage,
    BodyWeightEntry,
    WeeklyGoalHistory,
    UserAchievement,
    DailyCheckin,
    ExerciseAlias,
    PersonalBasic,
    AthleteCard,
)
from app.muscle_svg_data import BODY_PARTS, AUXILIARY_SLUGS
from app import achievements, usage, datacache
from app import bodyweight as bodyweight_mod
from app import social
from app import strength_standards as standards
from app import progression
from app import volume as volume_mod
from app import perks
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


@app.route("/sw.js")
def service_worker():
    return app.send_static_file("sw.js")


# Estáticos versionados: url_for('static', ...) añade ?v=<fecha del archivo>
# y esas URLs se cachean un año. Antes el navegador revalidaba style.css en
# CADA cambio de pestaña antes de pintar (un viaje de ida y vuelta a Oregón).
# Al desplegar cambia la fecha -> URL nueva -> se descarga una vez. Las rutas
# /static/... escritas a mano (sin ?v=) siguen sin caché larga.
_static_versions = {}


@app.url_defaults
def _version_static_urls(endpoint, values):
    if endpoint == "static" and "filename" in values and "v" not in values:
        filename = values["filename"]
        if app.debug or filename not in _static_versions:  # en local, cada cambio de CSS cuenta
            try:
                _static_versions[filename] = int(os.stat(os.path.join(app.static_folder, filename)).st_mtime)
            except OSError:
                _static_versions[filename] = None
        if _static_versions[filename]:
            values["v"] = _static_versions[filename]


@app.after_request
def _cache_versioned_static(response):
    if request.path.startswith("/static/") and request.args.get("v") and response.status_code in (200, 304):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def check_achievements():
    """Evalúa los logros tras una acción que puede desbloquear alguno. Nunca
    rompe la acción principal: si algo falla, se registra y se sigue."""
    try:
        achievements.evaluate(current_user)
    except Exception:
        db.session.rollback()
        app.logger.exception("Error evaluando logros")


@app.route("/logros")
@login_required
def achievements_page():
    items, _ = achievements.evaluate(current_user)
    achievements.unseen(current_user.id)  # ya los está viendo aquí
    by_category = defaultdict(list)
    for it in items:
        by_category[it["a"].category].append(it)
    for cat_items in by_category.values():
        # Conseguidos primero (más recientes arriba), luego por cercanía.
        cat_items.sort(key=lambda it: (not it["unlocked"], -(it["unlocked_at"].timestamp() if it["unlocked_at"] else 0), -it["pct"]))
    recent = sorted((it for it in items if it["unlocked"]), key=lambda it: it["unlocked_at"], reverse=True)[:4]
    closest = sorted(
        (it for it in items if not it["unlocked"] and not it["a"].secret and it["target"]),
        key=lambda it: -it["pct"],
    )[:3]
    return render_template(
        "achievements.html",
        title=gettext("Logros"),
        categories=[(key, name, emoji, by_category.get(key, [])) for key, name, emoji in achievements.CATEGORIES],
        unlocked_count=sum(1 for it in items if it["unlocked"]),
        total=len(items),
        recent=recent,
        closest=closest,
    )


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", title=gettext("Política de privacidad"))


def queue_xp_gain(reason, gain, parts):
    """Deja el XP ganado para el aviso tipo videojuego de la siguiente carga
    de Inicio (xp_fx.js), en vez de un flash informativo."""
    session["xp_gain"] = {"reason": reason, "gain": gain, "parts": parts}


def xp_fx_data(xp_total, gain_info, level_up):
    """Datos del aviso de XP: barra de antes y de después y, si toca, la
    subida de nivel (solo la que level_up_notice no había anunciado ya)."""
    if not gain_info and not level_up:
        return None
    gain = gain_info["gain"] if gain_info else 0
    before = progression.level_for(max(0, xp_total - gain))
    after = progression.level_for(xp_total)
    return {
        "reason": gain_info["reason"] if gain_info else "",
        "gain": gain,
        "parts": gain_info["parts"] if gain_info else [],
        "from": {"level": before["level"], "pct": before["pct"]},
        "to": {"level": after["level"], "pct": after["pct"], "to_next": after["to_next"]},
        "level_up": level_up,
    }


@app.route("/checkin", methods=["POST"])
@login_required
def recovery_checkin():
    """Check-in de recuperación del día (uno por día; reenviarlo lo
    actualiza). Valoración autodeclarada: da XP y contexto, nunca bloquea."""
    form = RecoveryCheckinForm()
    if not form.validate_on_submit():
        flash(gettext("Marca sueño, energía y agujetas para guardar el check-in."))
        return redirect(url_for("index"))
    before = progression.current_xp(current_user.id)
    checkin = progression.today_checkin(current_user.id)
    if checkin is None:
        checkin = DailyCheckin(user_id=current_user.id, day=usage.local_today(),
                               sleep=0, energy=0, soreness=0)
        db.session.add(checkin)
    checkin.sleep, checkin.energy, checkin.soreness = form.sleep.data, form.energy.data, form.soreness.data
    db.session.commit()
    gained = progression.current_xp(current_user.id) - before
    if gained > 0:
        queue_xp_gain(gettext("Check-in"), gained, [[gettext("Check-in"), gained]])
    else:
        flash(gettext("Check-in actualizado (+0 XP: ya lo habías hecho hoy)."))
    session["checkin_saved"] = True
    return redirect(url_for("index"))


@app.route("/nivel")
@login_required
def level_page():
    """Nivel y XP con TODO documentado: reglas y su versión, topes, curva y
    desglose semanal."""
    report, _ = progression.refresh_xp(current_user.id)
    weeks = list(report.weeks.items())[:12]
    xp = progression.level_for(report.total)
    return render_template(
        "level.html",
        title=gettext("Nivel"),
        xp=xp,
        perk_rows=perks.perk_list(xp["level"]),
        weeks=weeks,
        profile=cached_profile(current_user),
        p=progression,
        curve=[(lvl, progression.xp_to_reach(lvl), progression.xp_to_reach(lvl + 1) - progression.xp_to_reach(lvl))
               for lvl in range(1, 31)],
    )


def exercises_without_muscles(user_id):
    """Nombres de ejercicio del usuario (entrenos y rutinas) que no aportan
    músculos: ni están en el catálogo ni los ha asignado. Más usados primero."""
    names = {}
    for name, n in db.session.execute(
        sa.select(SetEntry.exercise, sa.func.count())
        .join(Workout, Workout.id == SetEntry.workout_id)
        .where(Workout.user_id == user_id)
        .group_by(SetEntry.exercise)
    ):
        names[name] = n
    for (name,) in db.session.execute(
        sa.select(RoutineExercise.exercise).join(Routine, Routine.id == RoutineExercise.routine_id)
        .where(Routine.user_id == user_id)
    ):
        names.setdefault(name, 0)
    prefetch_catalog_exercises(names)
    missing = [
        {"name": name, "sets": n}
        for name, n in names.items()
        if not (ex := find_catalog_exercise(name)) or not ex.primary_muscles
    ]
    missing.sort(key=lambda m: (-m["sets"], m["name"]))
    return missing


@app.route("/ejercicios/musculos")
@login_required
def exercise_muscles():
    """Asignar a un ejercicio del catálogo los nombres escritos a mano, para
    que cuenten en el mapa muscular, el volumen semanal y la IA."""
    aliases = db.session.execute(
        sa.select(ExerciseAlias, Exercise)
        .join(Exercise, Exercise.id == ExerciseAlias.exercise_id)
        .where(ExerciseAlias.user_id == current_user.id)
        .order_by(ExerciseAlias.name)
    ).all()
    return render_template(
        "exercise_muscles.html",
        title=gettext("Músculos de tus ejercicios"),
        missing=exercises_without_muscles(current_user.id),
        aliases=aliases,
    )


@app.route("/api/exercise-alias", methods=["POST"])
@login_required
def api_set_exercise_alias():
    data = request.get_json(silent=True) or {}
    alias = (data.get("alias") or "").strip().lower()
    target = find_catalog_exercise((data.get("exercise") or "").strip(), use_alias=False)
    if not alias or target is None:
        return jsonify({"ok": False, "error": gettext("Elige un ejercicio del catálogo.")}), 400
    key = _strip_accents(alias)[:120]
    row = db.session.scalar(
        sa.select(ExerciseAlias).where(ExerciseAlias.user_id == current_user.id, ExerciseAlias.name == key)
    )
    if row is None:
        db.session.add(ExerciseAlias(user_id=current_user.id, name=key, exercise_id=target.id))
    else:
        row.exercise_id = target.id
    db.session.commit()
    _clear_catalog_cache()
    return jsonify({"ok": True})


@app.route("/api/exercise-alias/<int:alias_id>/delete", methods=["POST"])
@login_required
def api_delete_exercise_alias(alias_id):
    row = db.session.get(ExerciseAlias, alias_id)
    if row is None or row.user_id != current_user.id:
        return jsonify({"ok": False}), 403
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/healthz")
def healthz():
    # Para el ping externo (UptimeRobot / cron-job.org) que evita que Render
    # duerma la app. No toca la base de datos a propósito: así Neon sí puede
    # suspenderse (su plan gratis tiene horas de cómputo limitadas) y el ping
    # tampoco cuenta como visita en las estadísticas de la landing.
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}


# Peticiones que no son "abrir la app": estáticos, el service worker, el ping
# de UptimeRobot y el aviso de reintento de CSS (que ya cuenta por su lado).
_NOT_AN_OPEN = {None, "static", "service_worker", "healthz", "css_retry"}


@app.before_request
def _track_daily_open():
    """Contador de uso (app/usage.py): marca una vez al día que el usuario
    abrió la app. Las precargas de Chrome (speculation rules) no cuentan:
    las pide el navegador, no la persona. Nunca rompe la petición."""
    if request.method != "GET" or request.endpoint in _NOT_AN_OPEN:
        return
    purpose = (request.headers.get("Sec-Purpose", "") + request.headers.get("Purpose", "")).lower()
    if "prefetch" in purpose or "prerender" in purpose:
        return
    if not current_user.is_authenticated:
        return
    today = usage.local_today().isoformat()
    if session.get("opened_day") == today:
        return
    try:
        usage.record_open(current_user)
        session["opened_day"] = today
    except Exception:
        db.session.rollback()
        app.logger.exception("Error registrando la apertura diaria")


@app.route("/usage/css-retry", methods=["POST"])
def css_retry():
    """La página se pintó sin style.css y lo volvió a pedir (ver base.html).
    Sirve para saber si el fallo de "página sin estilos" sigue pasando."""
    app.logger.warning("Página sin CSS: reintento de carga (%s)", request.headers.get("Referer", "-"))
    if current_user.is_authenticated:
        try:
            usage.record_css_retry(current_user)
        except Exception:
            db.session.rollback()
            app.logger.exception("Error registrando el reintento de CSS")
    return "", 204


# Robots que descargan la página sin ser una persona: vistas previas de
# enlaces (Reddit, WhatsApp, Discord...), buscadores, monitores de uptime y
# clientes HTTP de scripts.
_BOT_UA_RE = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|whatsapp|telegram|"
    r"discord|slack|skype|vkshare|pinterest|headless|lighthouse|pagespeed|uptime|"
    r"monitor|pingdom|statuscake|curl|wget|python|httpx|aiohttp|go-http|okhttp|java/|"
    r"axios|node-fetch|libwww|scrapy|feedfetcher|validator|render",
    re.IGNORECASE,
)


def _is_bot_user_agent(user_agent):
    """None = evento antiguo, sin clasificar (no se considera robot)."""
    if user_agent is None:
        return False
    return user_agent == "" or bool(_BOT_UA_RE.search(user_agent))


REF_COOKIE = "gyre_ref"


_REF_RE = re.compile(r"[a-z0-9_-]{1,20}")


def _clean_ref(value):
    """Etiqueta de canal de ?ref= (p.ej. "mediavida", "tiktok"). Se acepta
    tal cual (en minúsculas) solo si es [a-z0-9_-] de 1 a 20 caracteres; si
    no, se rechaza entera (None) en vez de "arreglarla" quitando caracteres.
    Regex y no lista blanca: así un canal nuevo no exige desplegar."""
    if not value:
        return None
    value = value.strip().lower()
    return value if _REF_RE.fullmatch(value) else None


def _current_ref():
    """Canal de esta petición: el ?ref= del enlace o, si no, el que dejó la
    visita anterior en la cookie (para atribuir clics y registros).
    Atribución "último enlace etiquetado": landing() sobrescribe la cookie
    con cada ?ref= válido nuevo; una visita sin ?ref= no la toca."""
    return _clean_ref(request.args.get("ref")) or _clean_ref(request.cookies.get(REF_COOKIE))


_LANG_RE = re.compile(r"[a-z]{2,3}")
LANGUAGE_NAMES = {
    "es": "Español", "en": "Inglés", "pt": "Portugués", "fr": "Francés", "de": "Alemán",
    "it": "Italiano", "ca": "Catalán", "gl": "Gallego", "eu": "Euskera", "nl": "Neerlandés",
}


def _browser_language():
    """Idioma principal del navegador según Accept-Language ("es-ES,es;q=0.9,en"
    -> "es"). None si no viene o no tiene forma de código de idioma."""
    first = (request.headers.get("Accept-Language") or "").split(",")[0].split(";")[0]
    code = first.strip().lower().split("-")[0]
    return code if _LANG_RE.fullmatch(code) else None


def _log_landing_event(event_type, source=None):
    if request.cookies.get("no_contar") == "1" or request.args.get("no_contar") == "1":
        return
    db.session.add(
        LandingEvent(
            event_type=event_type,
            referrer=(request.referrer[:255] if request.referrer else None),
            user_agent=(request.headers.get("User-Agent") or "")[:255],
            source=source,
            language=_browser_language(),
        )
    )
    db.session.commit()


@app.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    # La visita solo se etiqueta con el ?ref= de SU enlace: una visita sin
    # etiqueta es "sin etiqueta" aunque la cookie recuerde un canal anterior.
    ref = _clean_ref(request.args.get("ref"))
    _log_landing_event("visit", source=ref)
    resp = make_response(render_template("landing.html"))
    if request.args.get("no_contar") == "1":
        resp.set_cookie("no_contar", "1", max_age=60 * 60 * 24 * 365 * 5)
    if ref:
        resp.set_cookie(REF_COOKIE, ref, max_age=60 * 60 * 24 * 30, samesite="Lax", httponly=True)
    return resp


@app.route("/landing/cta")
def landing_cta():
    _log_landing_event("cta_click", source=_current_ref())
    return redirect(url_for("register"))


@app.route("/landing/google")
def landing_google():
    # "Continuar con Google" desde la landing también es crear cuenta: se
    # cuenta aparte del botón de registro normal y luego sigue al OAuth.
    _log_landing_event("google_click", source=_current_ref())
    return redirect(url_for("login_google"))


# Despliegue de la landing nueva (commit 06aa0d5, 30/09/2026 12:07 hora local).
NEW_LANDING_SINCE = datetime(2026, 9, 30, 10, 10)  # UTC, naive como el resto


def _landing_stats_period():
    """Devuelve (clave, etiqueta, desde_utc_naive | None) según ?periodo= / ?desde=."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    desde = request.args.get("desde", "").strip()
    if desde:
        try:
            local_start = datetime.strptime(desde, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
            start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
            return "desde", f"Desde el {local_start.strftime('%d/%m/%Y')}", start
        except ValueError:
            flash("Fecha no válida; se muestra desde la landing nueva.")
    periodo = request.args.get("periodo", "nueva")
    if periodo == "7d":
        return periodo, "Últimos 7 días", now - timedelta(days=7)
    if periodo == "30d":
        return periodo, "Últimos 30 días", now - timedelta(days=30)
    if periodo == "todo":
        return periodo, "Desde el principio", None
    return "nueva", "Desde la landing nueva (30/09)", NEW_LANDING_SINCE


@app.route("/landing/stats")
@login_required
def landing_stats():
    if current_user.username != "Jaime_309":
        flash(gettext("No tienes acceso a esta página."))
        return redirect(url_for("index"))

    period_key, period_label, start = _landing_stats_period()

    events_q = sa.select(
        LandingEvent.event_type,
        LandingEvent.timestamp,
        LandingEvent.referrer,
        LandingEvent.user_agent,
        LandingEvent.source,
        LandingEvent.language,
    )
    users_q = sa.select(User.created_at, User.signup_method, User.signup_source).where(
        User.created_at.is_not(None), User.signup_method.is_distinct_from("demo")
    )
    if start is not None:
        events_q = events_q.where(LandingEvent.timestamp >= start)
        users_q = users_q.where(User.created_at >= start)

    visits_human = visits_bot = visits_legacy = 0
    cta_clicks = google_clicks = 0
    referrer_counts = defaultdict(int)
    daily = defaultdict(lambda: {"visits": 0, "clicks": 0, "signups": 0})
    by_source = defaultdict(lambda: {"visits": 0, "clicks": 0, "signups": 0})
    by_language = defaultdict(lambda: {"visits": 0, "clicks": 0})

    for event_type, ts, referrer, user_agent, source, language in db.session.execute(events_q):
        if _is_bot_user_agent(user_agent):
            if event_type == "visit":
                visits_bot += 1
            continue
        day = to_local(ts).date()
        if event_type == "visit":
            if user_agent is None:
                visits_legacy += 1
            else:
                visits_human += 1
            daily[day]["visits"] += 1
            by_source[source]["visits"] += 1
            by_language[language]["visits"] += 1
            key = (urlsplit(referrer).netloc if referrer else None) or "Directo / sin referrer"
            referrer_counts[key] += 1
        elif event_type in ("cta_click", "google_click"):
            if event_type == "cta_click":
                cta_clicks += 1
            else:
                google_clicks += 1
            daily[day]["clicks"] += 1
            by_source[source]["clicks"] += 1
            by_language[language]["clicks"] += 1

    signups_password = signups_google = 0
    for created_at, method, signup_source in db.session.execute(users_q):
        if method == "google":
            signups_google += 1
        else:
            signups_password += 1
        daily[to_local(created_at).date()]["signups"] += 1
        by_source[signup_source]["signups"] += 1

    visits = visits_human + visits_legacy
    clicks = cta_clicks + google_clicks
    signups = signups_password + signups_google
    total_users = db.session.scalar(sa.select(sa.func.count()).select_from(User))

    return render_template(
        "landing_stats.html",
        title="Estadísticas de la landing",
        period_key=period_key,
        period_label=period_label,
        desde=request.args.get("desde", ""),
        visits=visits,
        visits_bot=visits_bot,
        visits_legacy=visits_legacy,
        clicks=clicks,
        cta_clicks=cta_clicks,
        google_clicks=google_clicks,
        click_rate=(100 * clicks / visits) if visits else None,
        signups=signups,
        signups_password=signups_password,
        signups_google=signups_google,
        signup_rate=(100 * signups / visits) if visits else None,
        total_users=total_users,
        referrer_counts=dict(sorted(referrer_counts.items(), key=lambda kv: -kv[1])),
        daily=sorted(daily.items(), reverse=True)[:60],
        # Idiomas conocidos por nº de visitas; "desconocido" (eventos anteriores
        # a guardar el idioma) al final.
        by_language=sorted(
            ((LANGUAGE_NAMES.get(code, code) if code else None, d) for code, d in by_language.items()),
            key=lambda kv: (kv[0] is None, -kv[1]["visits"]),
        ),
        known_language_visits=sum(d["visits"] for code, d in by_language.items() if code),
        # Canales etiquetados primero (por cuentas, luego visitas); "sin etiqueta" al final.
        by_source=sorted(
            by_source.items(),
            key=lambda kv: (kv[0] is None, -kv[1]["signups"], -kv[1]["visits"]),
        ),
        # Uso de la app en días sin entreno (no depende del periodo elegido).
        usage_report=usage.rest_day_report(weeks=6),
        activity=usage.activity_summary(),
        contact_messages=db.session.execute(
            sa.select(ContactMessage, User).join(User, User.id == ContactMessage.user_id)
            .order_by(ContactMessage.created_at.desc()).limit(30)
        ).all(),
    )


def suggest_next_routine(user_id):
    """Rutina que toca hoy: dentro del bloque predeterminado (o de todas, si
    no hay bloque predeterminado o está vacío), la siguiente a la última que
    hiciste, en el orden de "Mis rutinas" y volviendo a empezar al final.
    None si el usuario no tiene rutinas con ejercicios."""
    default_block_id = db.session.scalar(
        sa.select(RoutineBlock.id).where(
            RoutineBlock.user_id == user_id, RoutineBlock.is_default.is_(True)
        )
    )
    # Solo rutinas con algún ejercicio: sugerir una vacía no sirve para entrenar.
    ordered = (
        sa.select(Routine)
        .where(
            Routine.user_id == user_id,
            Routine.id.in_(sa.select(RoutineExercise.routine_id)),
        )
        .order_by(Routine.order_index, Routine.id)
    )
    candidates = []
    if default_block_id is not None:
        candidates = db.session.scalars(ordered.where(Routine.block_id == default_block_id)).all()
    if not candidates:
        candidates = db.session.scalars(ordered).all()
    if not candidates:
        return None

    ids = [r.id for r in candidates]
    last_id = db.session.scalar(
        sa.select(Workout.routine_id)
        .where(Workout.user_id == user_id, Workout.routine_id.in_(ids))
        .order_by(Workout.timestamp.desc())
        .limit(1)
    )
    if last_id in ids:
        return candidates[(ids.index(last_id) + 1) % len(candidates)]
    return candidates[0]


_WEEKDAY_SHORT = [lazy_pgettext("inicial de lunes", "L"), lazy_pgettext("inicial de martes", "M"),
                  lazy_pgettext("inicial de miércoles", "X"), lazy_pgettext("inicial de jueves", "J"),
                  lazy_pgettext("inicial de viernes", "V"), lazy_pgettext("inicial de sábado", "S"),
                  lazy_pgettext("inicial de domingo", "D")]


def planned_weekdays(user):
    """Días (0=lunes..6=domingo) que el usuario marcó como de entreno; vacío si no configuró."""
    return {int(c) for c in (user.training_days or "") if c.isdigit()}


def _next_training_day_label(plan, today_wd):
    """"mañana" / "el jueves" para el siguiente día marcado después de hoy."""
    for offset in range(1, 8):
        wd = (today_wd + offset) % 7
        if wd in plan:
            return gettext("mañana") if offset == 1 else gettext("el %(day)s", day=WEEKDAY_NAMES[wd])
    return None


REST_TIPS = [
    lazy_gettext("El músculo crece mientras descansas."),
    lazy_gettext("Recuperar también es entrenar."),
    lazy_gettext("Duerme bien: mañana se nota."),
    lazy_gettext("Hoy toca cargar pilas, no barras."),
    lazy_gettext("Un buen descanso vale un récord."),
    lazy_gettext("Estira, camina, bebe agua. Mañana, a por ello."),
]
DONE_TIPS = [
    lazy_gettext("Buen trabajo. Ahora, a recuperar."),
    lazy_gettext("Un día más que suma."),
    lazy_gettext("Hecho. Come bien y descansa."),
    lazy_gettext("Constancia > intensidad. Hoy has cumplido."),
]


def _daily_pick(options, now_local):
    """La misma frase durante todo el día, distinta de un día a otro."""
    return options[now_local.date().toordinal() % len(options)]


def home_cta(user):
    """Acción principal de Inicio:
    - continue: hay un entreno en curso.
    - done: hoy ya entrenaste (con alguna serie hecha); se muestra el siguiente.
    - rest: el usuario marcó sus días de entreno y hoy no es uno; se ofrece
      el siguiente para "entrenar igualmente".
    - routine: la rutina que toca ("Hoy toca" si hoy es día de entreno
      marcado; "Siguiente entreno" si no hay días marcados, porque entonces
      la app no sabe si hoy toca).
    - empty: sin rutinas con ejercicios -> entreno libre."""
    active = get_active_workout(user.id)
    if active is not None:
        sets = db.session.scalars(active.sets.select()).all()
        return {
            "kind": "continue",
            "workout": active,
            "done": sum(1 for s in sets if s.completed),
            "total": len(sets),
        }

    routine = suggest_next_routine(user.id)
    exercise_count = 0
    if routine is not None:
        exercise_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(RoutineExercise)
            .where(RoutineExercise.routine_id == routine.id)
        )
    base = {"routine": routine, "exercise_count": exercise_count}

    now_local = to_local(datetime.now(timezone.utc))
    today_start_utc = (
        datetime.combine(now_local.date(), datetime.min.time(), tzinfo=LOCAL_TZ)
        .astimezone(timezone.utc).replace(tzinfo=None)
    )
    trained_today = db.session.scalar(
        sa.select(Workout.id)
        .join(SetEntry, SetEntry.workout_id == Workout.id)
        .where(Workout.user_id == user.id, Workout.timestamp >= today_start_utc, SetEntry.completed.is_(True))
        .limit(1)
    ) is not None
    if trained_today:
        return {"kind": "done", "tip": _daily_pick(DONE_TIPS, now_local), **base}

    plan = planned_weekdays(user)
    if plan and now_local.weekday() not in plan:
        return {
            "kind": "rest",
            "next_day": _next_training_day_label(plan, now_local.weekday()),
            "tip": _daily_pick(REST_TIPS, now_local),
            **base,
        }
    if routine is not None:
        return {"kind": "routine", "is_training_day": bool(plan), **base}
    return {"kind": "empty"}


def onboarding_status(user_id):
    """Primeros pasos de un usuario nuevo. None en cuanto los 3 están hechos
    (la tarjeta desaparece sola, no hay que "cerrarla")."""
    def any_row(query):
        return db.session.scalar(query.limit(1)) is not None

    has_plan = any_row(sa.select(Routine.id).where(Routine.user_id == user_id)) or any_row(
        sa.select(Workout.id).where(Workout.user_id == user_id)
    )
    has_set = any_row(
        sa.select(SetEntry.id)
        .join(Workout, SetEntry.workout_id == Workout.id)
        .where(Workout.user_id == user_id, SetEntry.completed.is_(True))
    )
    has_finished = any_row(
        sa.select(Workout.id).where(
            Workout.user_id == user_id, Workout.performance_rating.is_not(None)
        )
    )
    steps = [
        {"title": gettext("Crea una rutina o empieza un entreno libre"),
         "hint": gettext("Con una rutina, cada entreno viene con tus ejercicios ya puestos."), "done": has_plan},
        {"title": gettext("Marca tu primera serie"),
         "hint": gettext("Apunta peso y repeticiones y pulsa ✓: el descanso arranca solo."), "done": has_set},
        {"title": gettext("Termina tu primer entreno"),
         "hint": gettext("Verás el resumen de la sesión y empezará tu historial de progreso."), "done": has_finished},
    ]
    done = sum(1 for s in steps if s["done"])
    if done == len(steps):
        return None
    current = next(i for i, s in enumerate(steps) if not s["done"])
    return {"steps": steps, "done": done, "current": current}


def next_rank_goal(profile):
    """El objetivo de rango más cercano para Inicio: entre los levantamientos
    que cuentan para un básico y tienen rango ahora, el que menos kilos
    necesita (en proporción a su 1RM) para la siguiente división.
    None si no hay ninguno (sin sexo/peso, o sin básicos en 90 días)."""
    counted = {lift for sources in standards.BASIC_SOURCES.values() for lift in sources}
    best = None
    for lift, info in profile["lifts"].items():
        if lift not in counted or not info["rank"] or info["rank_next"] is None:
            continue
        base = info["rank_e1rm"] + (profile["latest_bw"] or 0) if lift == "pullup" else info["rank_e1rm"]
        effort = info["rank_missing_kg"] / base if base else float("inf")
        if best is None or effort < best[0]:
            best = (effort, {"lift": lift, "label": info["label"], "missing_kg": info["rank_missing_kg"],
                             "next": info["rank_next"], "rank": info["rank"],
                             "next_rank": standards.rank_for(info["rank"]["next_score"] + 1e-9)})
    return best[1] if best else None


RECENT_WORKOUTS = 8      # entrenos que se ven en Inicio; el resto, en /historial
HISTORY_PAGE = 30


def group_workouts_by_week(workouts):
    """Tarjetas del historial agrupadas por semana, con las series de esos
    entrenos en UNA consulta (solo de los que se pintan)."""
    sets_by_workout = defaultdict(list)
    if workouts:
        for s in db.session.scalars(
            sa.select(SetEntry)
            .where(SetEntry.workout_id.in_([w.id for w in workouts]))
            .order_by(SetEntry.id)
        ):
            sets_by_workout[s.workout_id].append(s)

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

        sets = sets_by_workout.get(w.id, [])
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
    return grouped


@app.route("/historial")
@login_required
def history():
    """Historial completo de entrenos, por páginas (Inicio solo enseña los
    últimos: pintar cientos de tarjetas hacía lenta la pestaña)."""
    page = max(1, request.args.get("page", 1, type=int))
    total = db.session.scalar(
        sa.select(sa.func.count()).select_from(Workout).where(Workout.user_id == current_user.id)
    )
    workouts = db.session.scalars(
        current_user.workouts.select().order_by(Workout.timestamp.desc())
        .offset((page - 1) * HISTORY_PAGE).limit(HISTORY_PAGE)
    ).all()
    return render_template(
        "history.html", title=gettext("Historial"), grouped=group_workouts_by_week(workouts),
        page=page, has_next=page * HISTORY_PAGE < total, total=total,
    )


@app.route("/index")
@login_required
def index():
    workouts = db.session.scalars(
        current_user.workouts.select().order_by(Workout.timestamp.desc())
    ).all()
    grouped = group_workouts_by_week(workouts[:RECENT_WORKOUTS])

    total_workouts = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(Workout)
        .where(Workout.user_id == current_user.id)
    )

    streak = compute_smart_streak(current_user.id, workouts)

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
    pace = bodyweight_mod.summary([(e.timestamp, e.weight) for e in weight_entries], current_user.body_phase,
                                  datetime.now(timezone.utc).replace(tzinfo=None), _global_tier(current_user))
    # Cambio de peso frente al registro más reciente de hace >= 30 días.
    weight_change = None
    if latest_weight:
        cutoff = latest_weight.timestamp - timedelta(days=30)
        older = [e for e in weight_entries if e.timestamp <= cutoff]
        if older:
            weight_change = round(latest_weight.weight - older[-1].weight, 1)

    month_start = to_local(datetime.now(timezone.utc)).date().replace(day=1)
    workouts_this_month = sum(1 for w in workouts if to_local(w.timestamp).date() >= month_start)

    strength = cached_strength(current_user.id)

    notes_form = NotesForm()
    notes_form.notes.data = current_user.notes or ""

    # Primera vez con logros: se calculan sobre todo el historial para que
    # quien ya entrenaba se encuentre con los que ya se había ganado.
    if db.session.scalar(
        sa.select(UserAchievement.id).where(UserAchievement.user_id == current_user.id).limit(1)
    ) is None and workouts:
        check_achievements()

    # Nivel y rango de fuerza: de la caché si tus datos no han cambiado.
    profile = cached_profile(current_user)
    # XP: de la caché si está al día (normalmente no recalcula nada).
    xp_total = progression.current_xp(current_user.id)
    cta = home_cta(current_user)
    checkin = progression.today_checkin(current_user.id)
    just_checked_in = session.pop("checkin_saved", False)
    show_facts = cta["kind"] == "rest" or just_checked_in

    return render_template(
        "index.html",
        title=gettext("Inicio"),
        grouped=grouped,
        total_workouts=total_workouts,
        streak=streak,
        calendar_weeks=calendar_weeks,
        weight_change=weight_change,
        workouts_this_month=workouts_this_month,
        rank_goal=next_rank_goal(profile),
        strength=strength,
        strength_spark=sparkline_points([v for _, v in strength["series"][-12:]]) if strength else "",
        latest_weight=latest_weight,
        pace=pace,
        weight_chart_labels=[to_local(e.timestamp).strftime("%d/%m") for e in weight_entries],
        weight_chart_values=[e.weight for e in weight_entries],
        # Mapa: series duras de 7 días frente a TU rango (personal si hay
        # datos, si no el respaldado de 10-20), no frente a tu músculo más entrenado.
        muscle_colors=volume_mod.map_colors(cached_volume(current_user.id)),
        muscle_svg=muscle_svg_markup(current_user.sex),
        notes_form=notes_form,
        home_cta=cta,
        new_achievements=achievements.unseen(current_user.id),
        profile=profile,
        rank_event=standards.rank_notice(current_user, profile["global_rank"]),
        xp=progression.level_for(xp_total),
        xp_fx=xp_fx_data(xp_total, session.pop("xp_gain", None),
                         progression.level_up_notice(current_user.id, xp_total)),
        checkin=checkin,
        checkin_form=RecoveryCheckinForm(),
        just_checked_in=just_checked_in,
        rest_facts=progression.rest_day_facts(current_user.id, cta.get("routine")) if show_facts else None,
        achievements_unlocked=db.session.scalar(
            sa.select(sa.func.count()).select_from(UserAchievement).where(UserAchievement.user_id == current_user.id)
        ),
        achievements_total=len(achievements.ACHIEVEMENTS),
        onboarding=onboarding_status(current_user.id),
        empty_form=EmptyForm(),
    )


@app.route("/notes", methods=["POST"])
@login_required
def update_notes():
    form = NotesForm()
    if form.validate_on_submit():
        current_user.notes = form.notes.data
        db.session.commit()
        flash(gettext("Notas guardadas."))
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
            flash(gettext("Usuario o contraseña incorrectos."))
            return redirect(url_for("login"))
        login_user(user, remember=form.remember_me.data)
        return redirect(safe_next(request.args.get("next")))
    return render_template("login.html", title=gettext("Iniciar sesión"), form=form)


def safe_next(target):
    """Destino tras iniciar sesión, solo dentro de esta web: "//otra.com" o
    "/\\otra.com" los navegadores los tratan como otro dominio."""
    if (not target or not target.startswith("/") or target.startswith("//")
            or "\\" in target or urlsplit(target).netloc):
        return url_for("index")
    return target


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))


def _unique_username_from_email(email):
    """Genera un username libre a partir de la parte local del email (antes de
    la @) para cuentas creadas por Google, que no piden username propio."""
    base = re.sub(r"[^a-z0-9_]", "", email.split("@")[0].lower()) or "usuario"
    candidate = base
    suffix = 1
    while db.session.scalar(sa.select(User).where(User.username == candidate)) is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


@app.route("/login/google")
def login_google():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    redirect_uri = url_for("login_google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def login_google_callback():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.google.userinfo(token=token)
    google_sub = userinfo["sub"]
    email = userinfo["email"]

    user = db.session.scalar(sa.select(User).where(User.google_sub == google_sub))
    if user is None:
        # Vincula automáticamente si ya existe una cuenta con ese email
        # (registrada antes con usuario/contraseña) -- Google ya verificó
        # la propiedad del email, así que es seguro enlazarla sin pedir nada más.
        user = db.session.scalar(sa.select(User).where(User.email == email))
        if user is not None and not userinfo.get("email_verified"):
            # Sin email verificado no se puede asegurar que sea su cuenta.
            flash(gettext("Ya hay una cuenta con ese email. Inicia sesión con tu usuario y contraseña."))
            return redirect(url_for("login"))
        if user is not None:
            user.google_sub = google_sub
        else:
            user = User(
                username=_unique_username_from_email(email),
                email=email,
                google_sub=google_sub,
                signup_method="google",
                signup_source=_current_ref(),
            )
            db.session.add(user)
        db.session.commit()

    login_user(user, remember=True)
    return redirect(safe_next(request.args.get("next")))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            signup_method="password",
            signup_source=_current_ref(),
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        # Entrar directamente: volver a pedir usuario y contraseña justo
        # después de crearlos es un paso más en el que se pierde gente.
        login_user(user, remember=True)
        flash(gettext("¡Bienvenido a Gyre! Empieza un entreno o crea tu primera rutina."))
        return redirect(url_for("index"))
    return render_template("register.html", title=gettext("Crear cuenta"), form=form)


ACTIVE_WORKOUT_WINDOW = timedelta(hours=6)


def get_active_workout(user_id):
    """Entreno sin terminar (sin valoración) empezado en las últimas 6 h.
    Única definición de "entreno en curso": la usan el aviso global, Inicio
    y los guardas que impiden empezar dos a la vez."""
    cutoff = datetime.now(timezone.utc) - ACTIVE_WORKOUT_WINDOW
    return db.session.scalar(
        sa.select(Workout)
        .where(
            Workout.user_id == user_id,
            Workout.performance_rating.is_(None),
            Workout.timestamp >= cutoff,
        )
        .order_by(Workout.timestamp.desc())
    )


WEEKDAY_NAMES = [lazy_gettext("lunes"), lazy_gettext("martes"), lazy_gettext("miércoles"), lazy_gettext("jueves"),
                 lazy_gettext("viernes"), lazy_gettext("sábado"), lazy_gettext("domingo")]


def default_workout_name(now_utc=None):
    """"Entreno del martes" en hora de Madrid -- nombre automático del
    entreno libre (se puede cambiar luego desde el propio entreno)."""
    local = to_local(now_utc or datetime.now(timezone.utc))
    return gettext("Entreno del %(day)s", day=WEEKDAY_NAMES[local.weekday()])


@app.route("/workout/new", methods=["GET", "POST"])
@login_required
def new_workout():
    # Empieza al instante: antes pedía un nombre en un formulario aparte,
    # un paso más justo antes de entrenar. GET (enlaces antiguos) no crea
    # nada -- crear algo con GET lo dispararía cualquier precarga de enlaces.
    if request.method == "GET":
        return redirect(url_for("index"))
    form = EmptyForm()
    if not form.validate_on_submit():
        flash(gettext("No se pudo empezar el entreno. Inténtalo de nuevo."))
        return redirect(url_for("index"))

    existing = get_active_workout(current_user.id)
    if existing:
        flash(gettext("Ya tienes un entreno en curso — termínalo antes de empezar otro."))
        return redirect(url_for("workout_detail", workout_id=existing.id))

    workout = Workout(note=default_workout_name(), author=current_user)
    db.session.add(workout)
    db.session.commit()
    return redirect(url_for("workout_detail", workout_id=workout.id))


@app.route("/workout/<int:workout_id>/rename", methods=["POST"])
@login_required
def rename_workout(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    name = " ".join(str(data.get("name", "")).split())[:64]
    if not name:
        return jsonify({"ok": False, "error": gettext("El nombre no puede estar vacío.")}), 400
    workout.note = name
    db.session.commit()
    return jsonify({"ok": True, "name": name})


@app.route("/workout/<int:workout_id>/add_exercise", methods=["POST"])
@login_required
def add_exercise_to_workout(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash(gettext("No tienes acceso a este entrenamiento."))
        return redirect(url_for("index"))
    form = NewExerciseForm()
    if form.validate_on_submit():
        name = canonicalize_exercise_name(form.exercise.data)
        entry = SetEntry(
            exercise=name,
            weight=0,
            reps=0,
            rir=None,
            rpe=None,
            set_type="normal",
            workout=workout,
        )
        db.session.add(entry)
        db.session.commit()
        # Vuelve directamente a la tarjeta del ejercicio recién añadido (se
        # resalta con :target en CSS) en vez de al principio de la página.
        return redirect(
            url_for("workout_detail", workout_id=workout.id, _anchor="ex-" + name.replace(" ", "-"))
        )
    return redirect(url_for("workout_detail", workout_id=workout.id))


@app.route("/workout/<int:workout_id>/exercise/replace", methods=["POST"])
@login_required
def replace_workout_exercise(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    old_name = (data.get("old_exercise") or "").strip().lower()
    new_name = (data.get("exercise") or "").strip()
    if not old_name or not new_name:
        return jsonify({"ok": False}), 400
    new_name = canonicalize_exercise_name(new_name)
    sets = db.session.scalars(
        workout.sets.select().where(SetEntry.exercise == old_name)
    ).all()
    for s in sets:
        s.exercise = new_name

    # Si el usuario ya reordenó a mano, el orden guardado sigue apuntando al
    # nombre viejo -- sin esto el reemplazo caía al final de la lista.
    if workout.exercise_order:
        try:
            order = json.loads(workout.exercise_order)
        except (ValueError, TypeError):
            order = []
        if old_name in order and new_name != old_name:
            # Si el nuevo ya estaba en el entreno (fusión), ocupa el hueco del viejo.
            order = [name for name in order if name != new_name]
            order[order.index(old_name)] = new_name
            workout.exercise_order = json.dumps(order)

    db.session.commit()
    return jsonify({"ok": True, "exercise": new_name})


@app.route("/workout/<int:workout_id>/exercise/delete", methods=["POST"])
@login_required
def delete_workout_exercise(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    exercise = (data.get("exercise") or "").strip().lower()
    if not exercise:
        return jsonify({"ok": False}), 400
    sets = db.session.scalars(
        workout.sets.select().where(SetEntry.exercise == exercise)
    ).all()
    for s in sets:
        db.session.delete(s)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/workout/<int:workout_id>/exercise/reorder", methods=["POST"])
@login_required
def reorder_workout_exercises(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    order = data.get("order", [])
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        return jsonify({"ok": False}), 400
    workout.exercise_order = json.dumps(order)
    db.session.commit()
    return jsonify({"ok": True})


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
        if just_completed:
            entry.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        elif not entry.completed:
            entry.completed_at = None
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
        # Subida de rango en directo: solo si es récord en un básico (no se
        # calcula el perfil en cada serie) y ya se le presentó su rango.
        if entry.is_pr and standards.lift_of(entry.exercise) and current_user.rank_seen is not None:
            try:
                rank = standards.strength_profile(current_user)["global_rank"]
                if standards.rank_notice(current_user, rank) == "up":
                    response["rank_up"] = {k: rank[k] for k in ("key", "label", "division", "file")}
            except Exception:
                db.session.rollback()
                app.logger.exception("Error comprobando la subida de rango")
    return jsonify(response)


@app.route("/set/<int:set_id>/share")
@login_required
def api_share_set(set_id):
    """Datos para la tarjeta "Nuevo récord" que se dibuja en el navegador
    (app/static/share_card.js). Mismo 1RM y mismo criterio de PR que el
    resto de la app (get_exercise_sessions), no un cálculo aparte."""
    entry = db.get_or_404(SetEntry, set_id)
    if entry.workout.author != current_user:
        return jsonify({"ok": False}), 403
    if not is_real_set(entry):
        return jsonify({"ok": False, "error": gettext("Marca la serie como hecha para compartirla.")}), 400

    session_list, _, _ = get_exercise_sessions(entry.exercise)
    previous_best = None
    for s in session_list:
        if s["sets"][0].workout_id == entry.workout_id:
            break
        if s["best_set"] is not None:
            previous_best = max(previous_best or 0, s["best_1rm"])

    e1rm = estimated_1rm(entry, latest_bodyweight(current_user.id))
    # Ventajas por nivel: diseños desbloqueados e insignia de nivel/rango.
    level = perks.level_of(current_user)
    badge = rank_key = None
    if level >= perks.BADGE_LEVEL:
        rank = cached_profile(current_user)["global_rank"]
        badge = gettext("NIVEL %(n)s", n=level) + (f" · {rank['label'].upper()}" if rank else "")
        rank_key = (rank["key"] if rank["key"] == "titan" else f"{rank['key']}-{rank['division']}") if rank else None
    return jsonify(
        {
            "ok": True,
            "designs": perks.unlocked(perks.SHARE_DESIGNS, level),
            "badge": badge,
            "rank_key": rank_key,
            "exercise": entry.exercise.title(),
            "weight": f"{entry.weight:g}",
            "reps": entry.reps,
            "e1rm": round(e1rm),
            "improvement": round(e1rm - previous_best, 1) if previous_best else None,
            "is_pr": bool(entry.is_pr),
            "date": to_local(entry.workout.timestamp).strftime("%d/%m/%Y"),
            "share_url": url_for("landing", ref="compartir", _external=True),
        }
    )


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
        flash(gettext("No tienes acceso a este entrenamiento."))
        return redirect(url_for("index"))

    sets = db.session.scalars(workout.sets.select().order_by(SetEntry.id)).all()
    grouped_sets = {}
    exercise_order = []
    for s in sets:
        if s.exercise not in grouped_sets:
            grouped_sets[s.exercise] = []
            exercise_order.append(s.exercise)
        grouped_sets[s.exercise].append(s)

    if workout.exercise_order:
        try:
            custom_order = json.loads(workout.exercise_order)
        except (ValueError, TypeError):
            custom_order = []
        known = set(exercise_order)
        ordered = [name for name in custom_order if name in known]
        ordered += [name for name in exercise_order if name not in ordered]
        exercise_order = ordered

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
                    "sets_label": sets_label(re),
                    "target_reps": re.target_reps,
                    "rir": re.rir,
                    "rpe": re.rpe,
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
    # Mismo valor que get_rest_seconds() -- se pasa al JS para arrancar el
    # descanso en cuanto se pulsa el tick, sin esperar la respuesta del servidor.
    rest_seconds_map = {
        name: (
            exercise_notes_map[name].default_rest_seconds
            if name in exercise_notes_map and exercise_notes_map[name].default_rest_seconds
            else 120
        )
        for name in exercise_order
    }
    prefetch_catalog_exercises(exercise_order)
    return render_template(
        "workout_detail.html",
        title=workout.note or gettext("Entrenamiento"),
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
        rest_seconds_map=rest_seconds_map,
    )


FORGOTTEN_GAP = timedelta(minutes=30)  # sin marcar nada en 30 min = se olvidó abierto
LAST_SET_TAIL = timedelta(minutes=5)   # la última serie no es el último minuto


def estimate_workout_end(workout, now=None):
    """(fin estimado, ¿estimado desde la última serie?). Si desde la última
    serie marcada han pasado más de 30 min, el entreno se quedó abierto: el
    fin es esa serie + 5 min, no "ahora" (antes salían duraciones de 31 h).
    Series antiguas sin completed_at -> se usa "ahora", como antes."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    last_done = db.session.scalar(
        sa.select(sa.func.max(SetEntry.completed_at)).where(SetEntry.workout_id == workout.id)
    )
    if last_done is not None and now - last_done > FORGOTTEN_GAP:
        return max(last_done + LAST_SET_TAIL, workout.timestamp), True
    return max(now, workout.timestamp), False


def _real_sets_volume(workout):
    sets = [s for s in db.session.scalars(workout.sets.select().order_by(SetEntry.id)) if is_real_set(s)]
    return sets, sum(s.weight * s.reps for s in sets)


def workout_summary(workout):
    """Cifras del resumen de fin de entreno: series hechas de verdad
    (is_real_set), volumen, ejercicios, récords de esta sesión y cambio de
    volumen frente a la última vez que hiciste la misma rutina."""
    done, volume = _real_sets_volume(workout)
    volume_change_pct = None
    if workout.routine_id is not None:
        previous = db.session.scalar(
            sa.select(Workout)
            .where(
                Workout.user_id == workout.user_id,
                Workout.routine_id == workout.routine_id,
                Workout.id != workout.id,
                Workout.timestamp < workout.timestamp,
                Workout.performance_rating.is_not(None),
            )
            .order_by(Workout.timestamp.desc())
            .limit(1)
        )
        if previous is not None:
            _, prev_volume = _real_sets_volume(previous)
            if prev_volume > 0:
                volume_change_pct = round(100 * (volume - prev_volume) / prev_volume)
    return {
        "sets_done": len(done),
        "volume": round(volume),
        "exercise_count": len({s.exercise for s in done}),
        "prs": [s for s in done if s.is_pr],
        "volume_change_pct": volume_change_pct,
    }


@app.route("/workout/<int:workout_id>/finish", methods=["GET", "POST"])
@login_required
def finish_workout(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash(gettext("No tienes acceso a este entrenamiento."))
        return redirect(url_for("index"))

    form = FinishWorkoutForm()
    if form.validate_on_submit():
        non_empty_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(SetEntry)
            .where(SetEntry.workout_id == workout.id, SetEntry.reps > 0)
        )
        if not non_empty_count:
            flash(gettext(
                "No puedes finalizar un entrenamiento sin ninguna serie con "
                "repeticiones registradas."
            ))
            return redirect(url_for("workout_detail", workout_id=workout.id))

        empty_sets = db.session.scalars(
            sa.select(SetEntry).where(
                SetEntry.workout_id == workout.id, SetEntry.reps == 0
            )
        ).all()
        for entry in empty_sets:
            db.session.delete(entry)

        first_finish = workout.performance_rating is None
        workout.performance_rating = form.performance_rating.data
        workout.performance_comment = form.performance_comment.data
        workout.ended_at = workout.timestamp + timedelta(
            hours=form.duration_hours.data, minutes=form.duration_minutes.data
        )
        db.session.commit()

        if empty_sets:
            n = len(empty_sets)
            flash(ngettext("Entrenamiento guardado. Se eliminó %(num)d serie vacía sin rellenar.",
                           "Entrenamiento guardado. Se eliminaron %(num)d series vacías sin rellenar.", n))
        else:
            flash(gettext("Entrenamiento guardado."))
        if first_finish:  # editar uno ya terminado no vuelve a "ganar" su XP
            preview = progression.workout_xp_preview(current_user.id, workout.id)
            if preview and preview["gain"] > 0:
                x = preview["workout"]
                parts = []
                if x["workout"]:
                    parts.append([gettext("Entreno"), x["workout"]])
                if x["sets"]:
                    parts.append([ngettext("%(num)d serie", "%(num)d series", x["sets_n"]), x["sets"]])
                if x["prs"]:
                    parts.append([ngettext("%(num)d récord", "%(num)d récords", x["prs_n"]), x["prs"]])
                if preview["bonus"]:
                    parts.append([gettext("Semana cumplida"), preview["bonus"]])
                queue_xp_gain(gettext("Entreno terminado"), preview["gain"], parts)
        check_achievements()
        return redirect(url_for("index", celebrate=1))
    duration_estimated_from = None
    duration_suspicious = False
    if request.method == "GET":
        if workout.performance_rating is not None:
            form.performance_rating.data = workout.performance_rating
            form.performance_comment.data = workout.performance_comment
        else:
            # Sin valoración previa no se preselecciona ninguna (antes salía
            # "1 - Pésimo" por defecto y se guardaba sin querer).
            form.performance_rating.data = None
        # workout.timestamp llega naive (mismo patrón que el resto del
        # código -- ver comentario en WeeklyGoalHistory.effective_from), así
        # que se compara contra "ahora" también naive.
        if workout.ended_at is not None:
            elapsed_end = workout.ended_at
        else:
            elapsed_end, estimated = estimate_workout_end(workout)
            if estimated:
                duration_estimated_from = to_local(elapsed_end - LAST_SET_TAIL)
            else:
                # Series antiguas sin hora: no hay con qué estimar, pero
                # al menos se avisa en vez de proponer 20+ h en silencio.
                duration_suspicious = elapsed_end - workout.timestamp > timedelta(hours=4)
        elapsed = max(elapsed_end - workout.timestamp, timedelta(0))
        total_minutes = int(elapsed.total_seconds() // 60)
        form.duration_hours.data, form.duration_minutes.data = divmod(min(total_minutes, 23 * 60 + 59), 60)

    return render_template(
        "finish_workout.html",
        title=gettext("Terminar entreno"),
        form=form,
        workout=workout,
        summary=workout_summary(workout),
        xp_preview=progression.workout_xp_preview(current_user.id, workout.id),
        duration_estimated_from=duration_estimated_from,
        duration_suspicious=duration_suspicious,
        rating_choices=[
            (value, label.split(" - ", 1)[1].split(":")[0], label.split(": ", 1)[1])
            for value, label in form.performance_rating.choices
        ],
    )


@app.route("/workout/<int:workout_id>/delete", methods=["POST"])
@login_required
def delete_workout(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash(gettext("No tienes acceso a este entrenamiento."))
        return redirect(url_for("index"))
    sets = db.session.scalars(workout.sets.select()).all()
    for s in sets:
        db.session.delete(s)
    db.session.delete(workout)
    db.session.commit()
    flash(gettext("Entrenamiento eliminado."))
    return redirect(url_for("index"))


@app.route("/exercise/<name>")
@login_required
def exercise_progress(name):
    name = name.strip().lower()

    session_list, stagnation, improvement = get_exercise_sessions(name)
    display_sessions = qualifying_sessions(session_list)

    threshold = current_user.stagnation_threshold
    lastN_ids = (
        {id(s) for s in display_sessions[-threshold:]}
        if len(display_sessions) >= threshold
        else set()
    )

    chart_labels = [to_local(s["timestamp"]).strftime("%d/%m") for s in display_sessions]
    chart_values = [round(s["best_1rm"], 1) for s in display_sessions]
    chart_colors = []
    for s in display_sessions:
        if s["is_pr"]:
            chart_colors.append("#17a973")
        elif id(s) in lastN_ids and stagnation:
            chart_colors.append("#c62828")
        else:
            chart_colors.append("#5a4fcf")  # = --color-brand-dark, igual que la leyenda

    note = db.session.scalar(
        sa.select(ExerciseNote).where(
            ExerciseNote.user_id == current_user.id, ExerciseNote.exercise == name
        )
    )

    catalog_exercise = find_catalog_exercise(name, use_alias=False)  # la traducción edita el catálogo global
    translation_form = ExerciseTranslationForm(
        name_es=catalog_exercise.name_es if catalog_exercise else None
    )

    return render_template(
        "exercise_progress.html",
        title=name.title(),
        exercise=name,
        sessions=list(reversed(display_sessions)),
        stagnation=stagnation,
        improvement=improvement,
        threshold=threshold,
        chart_labels=chart_labels,
        chart_values=chart_values,
        chart_colors=chart_colors,
        stats=exercise_stats(session_list, threshold),
        exercise_note=note,
        catalog_exercise=catalog_exercise,
        translation_form=translation_form,
    )


@app.route("/progress")
@login_required
def progress():
    """Todos tus ejercicios con 1RM, tendencia y último récord -- antes la
    página de cada ejercicio solo se alcanzaba desde dentro de un entreno."""
    latest_weight = db.session.scalar(
        sa.select(BodyWeightEntry)
        .where(BodyWeightEntry.user_id == current_user.id)
        .order_by(BodyWeightEntry.timestamp.desc())
        .limit(1)
    )
    strength = cached_strength(current_user.id)
    items = cached_overview(current_user.id, current_user.stagnation_threshold)
    prefetch_catalog_exercises(i["exercise"] for i in items)
    return render_template(
        "progress.html",
        title=gettext("Progreso"),
        strength=strength,
        strength_labels=[wk.strftime("%d/%m") for wk, _ in strength["series"][-26:]] if strength else [],
        strength_values=[round(v, 1) for _, v in strength["series"][-26:]] if strength else [],
        items=items,
        threshold=current_user.stagnation_threshold,
        latest_weight=latest_weight,
        volume=cached_volume(current_user.id),
        volume_mod=volume_mod,
        muscle_svg=muscle_svg_markup(current_user.sex),
    )


@app.route("/rango")
@login_required
def rank_page():
    """Pestaña Rango: tu emblema, el rango de cada básico (estándares), tu
    nivel y tus logros."""
    profile = cached_profile(current_user)
    return render_template(
        "rango.html",
        title=gettext("Rango"),
        profile=profile,
        personal_basics=personal_basics_data(current_user, profile),
        rankings=friends_rankings(current_user),
        standards=standards,
        next_label=standards.next_rank_label(profile["global_rank"]),
        xp=progression.level_for(progression.current_xp(current_user.id)),
        achievements_unlocked=db.session.scalar(
            sa.select(sa.func.count()).select_from(UserAchievement).where(UserAchievement.user_id == current_user.id)
        ),
        achievements_total=len(achievements.ACHIEVEMENTS),
    )


# ------------------------------------------------------------ amigos
def friends_rankings(user):
    """Rankings con tus amigos (tú siempre incluido): rango global, cada
    básico y constancia. Solo amigos aceptados que no se hayan salido de los
    rankings, y solo lo que cada uno deja ver en su tarjeta."""
    ids = social.friend_ids(user.id)
    people = [user] + [u for u in (db.session.get(User, i) for i in ids) if u is not None]
    boards = {"global": [], "constancia": [], **{b: [] for b in standards.BASICS}}
    for person in people:
        me = person.id == user.id
        card = social.card_for(person.id)
        if not me and not card.in_rankings:
            continue
        if me or card.show_rank:
            ranking = cached_profile(person)["ranking"]
            if ranking["global"] is not None:
                boards["global"].append({"user": person, "me": me, "score": ranking["global"],
                                         "rank": standards.rank_for(ranking["global"])})
            for basic, score in ranking["basics"].items():
                boards[basic].append({"user": person, "me": me, "score": score, "rank": standards.rank_for(score)})
        if me or card.show_consistency:
            days = datacache.cached("consistency", person.id, lambda p=person: social.training_days(p.id))
            boards["constancia"].append({"user": person, "me": me, "score": days, "rank": None})
    for rows in boards.values():
        rows.sort(key=lambda r: (-r["score"], r["user"].username.lower()))
        for i, row in enumerate(rows, 1):
            row["pos"] = i
    return {"friends": len(ids), "boards": boards, "basic_labels": standards.BASIC_LABELS}


def athlete_card_view(owner, viewer):
    """Lo que se ve de `owner` en su tarjeta. El dueño lo ve todo, con lo que
    oculta marcado; un amigo solo lo que el dueño enseña."""
    is_self = owner.id == viewer.id
    card = social.card_for(owner.id)
    lift_names, achievement_codes = social.featured(card)
    profile = cached_profile(owner)

    def item(shown, value):
        return {"value": value, "hidden": not shown} if (shown or is_self) else None

    workouts = db.session.scalars(owner.workouts.select().order_by(Workout.timestamp.desc())).all()
    lifts = []
    if lift_names:
        by_exercise = defaultdict(list)
        for w, s in history_rows(owner.id):
            if s.exercise in lift_names:
                by_exercise[s.exercise].append((w, s))
        for name in lift_names:
            sessions = qualifying_sessions(sessions_from_rows(by_exercise.get(name, [])))
            if not sessions:
                continue
            best = max(sessions, key=lambda s: s["best_1rm"])
            # En dominadas el 1RM incluye el peso corporal: con el peso oculto
            # se enseña solo la serie (lastre × reps), no el 1RM.
            hide_e1rm = is_bodyweight_exercise(name) and not (card.show_bodyweight or is_self)
            lifts.append({"exercise": name, "e1rm": None if hide_e1rm else best["best_1rm"], "set": best["best_set"],
                          "date": best["timestamp"],
                          "rank": profile["exercise_ranks"].get(name) if (card.show_rank or is_self) else None})
    unlocked = set(social.unlocked_codes(owner.id))
    return {
        "owner": owner, "is_self": is_self, "card": card,
        "rank": item(card.show_rank, profile["global_rank"]),
        "level": item(card.show_level, progression.level_for(progression.current_xp(owner.id))["level"]),
        "streak": item(card.show_streak, compute_smart_streak(owner.id, workouts)["days"]),
        "consistency": item(card.show_consistency, social.training_days(owner.id)),
        "bodyweight": item(card.show_bodyweight, profile["latest_bw"]),
        "show_kg": card.show_kg or is_self,
        "kg_hidden": not card.show_kg,
        "lifts": lifts,
        "achievements": [achievements.BY_CODE[c] for c in achievement_codes if c in unlocked and c in achievements.BY_CODE],
    }


@app.route("/amigos")
@login_required
def friends_page():
    incoming, outgoing = social.requests_for(current_user.id)
    code = social.friend_code(current_user)
    return render_template(
        "friends.html", title=gettext("Amigos"), form=EmptyForm(), code=code,
        invite_url=url_for("friend_invite", code=code, _external=True),
        incoming=incoming, outgoing=outgoing, friends=social.friends_with_links(current_user.id),
        max_friends=social.MAX_FRIENDS,
    )


@app.route("/amigos/anadir", methods=["POST"])
@login_required
def friend_add():
    form = EmptyForm()
    if form.validate_on_submit():
        flash(social.send_request(current_user, social.user_by_code(request.form.get("code"))))
    return redirect(url_for("friends_page"))


@app.route("/amigos/invitar/<code>")
@login_required
def friend_invite(code):
    """Enlace de invitación: confirma antes de pedir la amistad (el enlace
    puede haber llegado reenviado)."""
    other = social.user_by_code(code)
    if other is None or other.id == current_user.id:
        flash(gettext("Ese enlace de invitación no es válido.") if other is None else gettext("Ese es tu propio enlace de invitación."))
        return redirect(url_for("friends_page"))
    return render_template("friend_invite.html", title=gettext("Invitación"), form=EmptyForm(), other=other,
                           already=social.are_friends(current_user.id, other.id), code=other.friend_code)


@app.route("/amigos/<int:friendship_id>/aceptar", methods=["POST"])
@login_required
def friend_accept(friendship_id):
    if EmptyForm().validate_on_submit():
        flash(social.accept(current_user, friendship_id))
    return redirect(url_for("friends_page"))


@app.route("/amigos/<int:friendship_id>/quitar", methods=["POST"])
@login_required
def friend_remove(friendship_id):
    if EmptyForm().validate_on_submit():
        social.remove(current_user, friendship_id)
    return redirect(url_for("friends_page"))


@app.route("/atleta/<int:user_id>")
@login_required
def athlete_card(user_id):
    owner = db.session.get(User, user_id)
    if owner is None or (owner.id != current_user.id and not social.are_friends(current_user.id, owner.id)):
        flash(gettext("Solo puedes ver la tarjeta de tus amigos."))
        return redirect(url_for("friends_page"))
    return render_template("athlete_card.html", title=owner.username, v=athlete_card_view(owner, current_user))


@app.route("/rango/tarjeta", methods=["GET", "POST"])
@login_required
def athlete_card_edit():
    """Qué ven tus amigos de ti: interruptores y récords/logros destacados."""
    form = EmptyForm()
    overview = cached_overview(current_user.id, current_user.stagnation_threshold)
    unlocked = social.unlocked_codes(current_user.id)
    if form.validate_on_submit():
        card = db.session.get(AthleteCard, current_user.id)
        if card is None:
            card = social.card_for(current_user.id)
            db.session.add(card)
        for flag in ("in_rankings", "show_rank", "show_level", "show_streak", "show_consistency", "show_kg", "show_bodyweight"):
            setattr(card, flag, request.form.get(flag) == "on")
        valid_lifts = {i["exercise"] for i in overview}
        lifts = [n for n in dict.fromkeys(request.form.getlist("lift")) if n in valid_lifts][:social.MAX_FEATURED_LIFTS]
        codes = [c for c in dict.fromkeys(request.form.getlist("achievement")) if c in unlocked][:social.MAX_FEATURED_ACHIEVEMENTS]
        card.featured_lifts = json.dumps(lifts, ensure_ascii=False)
        card.featured_achievements = json.dumps(codes)
        db.session.commit()
        if wants_json():
            return jsonify({"ok": True})
        flash(gettext("Tarjeta guardada."))
        return redirect(url_for("athlete_card", user_id=current_user.id))
    if request.method == "POST" and wants_json():
        return jsonify({"ok": False, "error": gettext("La sesión ha caducado: recarga la página.")}), 400
    card = social.card_for(current_user.id)
    lift_names, codes = social.featured(card)
    exercises = sorted(overview, key=lambda i: -i["best_1rm"])
    return render_template(
        "athlete_card_edit.html", title=gettext("Tu tarjeta"), form=form, card=card,
        exercises=exercises, chosen_lifts=lift_names, chosen_codes=codes,
        unlocked=[achievements.BY_CODE[c] for c in unlocked if c in achievements.BY_CODE],
        max_lifts=social.MAX_FEATURED_LIFTS, max_achievements=social.MAX_FEATURED_ACHIEVEMENTS,
    )


MAX_PERSONAL_BASICS = 8


def wants_json():
    """Formularios con autoguardado (base.html, form[data-autosave])."""
    return request.headers.get("X-Requested-With") == "fetch"


def personal_basics_data(user, profile):
    """Básicos personales de `user`, en su orden: con el rango del
    levantamiento si tiene tabla de estándares (y datos para darlo) y, si
    no, su progresión (mismas cifras que Progreso). Una sola consulta."""
    names = list(db.session.scalars(
        sa.select(PersonalBasic.exercise).where(PersonalBasic.user_id == user.id)
        .order_by(PersonalBasic.position, PersonalBasic.id)
    ))
    if not names:
        return []
    rows = db.session.execute(
        sa.select(Workout, SetEntry).join(SetEntry, SetEntry.workout_id == Workout.id)
        .where(Workout.user_id == user.id, SetEntry.exercise.in_(names))
        .order_by(Workout.timestamp.asc())
    ).all()
    by_exercise = defaultdict(list)
    for workout, entry in rows:
        by_exercise[entry.exercise].append((workout, entry))
    items = []
    for name in names:
        sessions = sessions_from_rows(by_exercise.get(name, []))
        lift = standards.lift_of(name)
        recent = [s["best_1rm"] for s in qualifying_sessions(sessions)][-12:]
        items.append({
            "exercise": name,
            "lift": lift,
            "rank": profile["exercise_ranks"].get(name),
            "approx": lift in standards.APPROX_TABLE,
            "stats": exercise_stats(sessions, user.stagnation_threshold),
            "spark": sparkline_points(recent),
        })
    return items


@app.route("/rango/basicos", methods=["GET", "POST"])
@login_required
def personal_basics():
    """Elegir tus básicos personales entre los ejercicios que has hecho."""
    form = EmptyForm()
    overview = cached_overview(current_user.id, current_user.stagnation_threshold)
    available = [item["exercise"] for item in overview]
    chosen = list(db.session.scalars(
        sa.select(PersonalBasic.exercise).where(PersonalBasic.user_id == current_user.id)
        .order_by(PersonalBasic.position, PersonalBasic.id)
    ))
    if form.validate_on_submit():
        allowed = set(available) | set(chosen)
        picked = [n for n in dict.fromkeys(x.strip().lower() for x in request.form.getlist("exercise")) if n in allowed]
        message = None
        if len(picked) > MAX_PERSONAL_BASICS:
            message = gettext("Como mucho %(n)s básicos: se han guardado los %(n)s primeros.", n=MAX_PERSONAL_BASICS)
            picked = picked[:MAX_PERSONAL_BASICS]
        db.session.execute(sa.delete(PersonalBasic).where(PersonalBasic.user_id == current_user.id))
        for i, name in enumerate(picked):
            db.session.add(PersonalBasic(user_id=current_user.id, exercise=name, position=i))
        db.session.commit()
        if wants_json():
            return jsonify({"ok": True, "message": message})
        if message:
            flash(message)
        return redirect(url_for("rank_page") + "#basicos")
    if request.method == "POST" and wants_json():
        return jsonify({"ok": False, "error": gettext("La sesión ha caducado: recarga la página.")}), 400
    # Primero los elegidos (en su orden), luego el resto por último entrenado.
    # Con cuántas sesiones y cuándo, para distinguir nombres parecidos
    # ("press banca" / "press de banca"), y a qué tabla cuenta cada uno.
    stats = {item["exercise"]: item for item in overview}
    order = chosen + [n for n in available if n not in chosen]
    items = []
    for n in order:
        lift = standards.lift_of(n)
        items.append({
            "exercise": n, "checked": n in chosen, "stats": stats.get(n),
            "counts_as": standards.LIFT_LABELS[lift] if lift else None,
        })
    return render_template("personal_basics.html", title=gettext("Tus básicos"), form=form, items=items,
                           max_basics=MAX_PERSONAL_BASICS)


@app.route("/exercise/<name>/translate", methods=["POST"])
@login_required
def update_exercise_translation(name):
    name = name.strip().lower()
    catalog_exercise = find_catalog_exercise(name, use_alias=False)
    if not catalog_exercise:
        flash(gettext("No se encontró este ejercicio en el catálogo."))
        return redirect(url_for("exercise_progress", name=name))
    form = ExerciseTranslationForm()
    if form.validate_on_submit():
        old_key = (catalog_exercise.name_es or catalog_exercise.name).strip().lower()
        new_es = form.name_es.data.strip() or None
        new_key = (new_es or catalog_exercise.name).strip().lower()
        if len(new_key) > 64:
            flash(gettext("Ese nombre es demasiado largo (máximo 64 caracteres)."))
            return redirect(url_for("exercise_progress", name=name))
        catalog_exercise.name_es = new_es
        moved = rename_exercise_everywhere(old_key, new_key) if new_key != old_key else 0
        db.session.commit()
        _clear_catalog_cache()
        flash(gettext("Nombre en español guardado.") + (" " + ngettext("Se actualizó en %(num)d serie para que siga contando.", "Se actualizó en %(num)d series para que sigan contando.", moved) if moved else ""))
        if name == old_key:
            name = new_key
    return redirect(url_for("exercise_progress", name=name))


def rename_exercise_everywhere(old, new):
    """Al cambiar el nombre de un ejercicio del catálogo, lo guardado con el
    nombre antiguo (series, rutinas, notas) pasa al nuevo, para todos los
    usuarios: si no, ese historial dejaba de coincidir con el catálogo (sin
    músculos ni imagen) y quedaba partido en dos. Solo cambia lo que tenía
    EXACTAMENTE el nombre antiguo. Devuelve cuántas series se movieron."""
    affected = set(db.session.scalars(
        sa.select(Workout.user_id).join(SetEntry, SetEntry.workout_id == Workout.id)
        .where(SetEntry.exercise == old).distinct()
    ))
    moved = db.session.execute(
        sa.update(SetEntry).where(SetEntry.exercise == old).values(exercise=new)
        # Se invalida el XP solo de los usuarios afectados (abajo), no de todos.
        .execution_options(xp_irrelevant=True, synchronize_session=False)
    ).rowcount
    progression._bump_users(db.session.connection(), affected)
    db.session.execute(
        sa.update(RoutineExercise).where(RoutineExercise.exercise == old).values(exercise=new)
        .execution_options(synchronize_session=False)
    )
    # Básicos personales: si el usuario ya tenía el nombre nuevo, sobra el viejo.
    for basic in db.session.scalars(sa.select(PersonalBasic).where(PersonalBasic.exercise == old)).all():
        if db.session.scalar(sa.select(PersonalBasic.id).where(
                PersonalBasic.user_id == basic.user_id, PersonalBasic.exercise == new)) is None:
            basic.exercise = new
        else:
            db.session.delete(basic)
    # Notas: única por (usuario, ejercicio). Si ya hay una con el nombre
    # nuevo, se fusionan los textos en vez de perder ninguno.
    for note in db.session.scalars(sa.select(ExerciseNote).where(ExerciseNote.exercise == old)).all():
        existing = db.session.scalar(
            sa.select(ExerciseNote).where(ExerciseNote.user_id == note.user_id, ExerciseNote.exercise == new)
        )
        if existing is None:
            note.exercise = new
        else:
            if note.notes:
                existing.notes = (existing.notes + "\n\n" if existing.notes else "") + note.notes
            existing.default_rest_seconds = existing.default_rest_seconds or note.default_rest_seconds
            db.session.delete(note)
    return moved


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
        flash(gettext("Notas guardadas."))
        return redirect(url_for("exercise_progress", name=name))
    elif request.method == "GET" and note and note.default_rest_seconds is not None:
        form.notes.data = note.notes
        form.rest_minutes.data = note.default_rest_seconds // 60
        form.rest_seconds.data = note.default_rest_seconds % 60
    elif request.method == "GET" and note:
        form.notes.data = note.notes
    return render_template(
        "exercise_notes.html",
        title=gettext("Notas de %(name)s", name=name.title()),
        form=form,
        exercise=name,
    )


def _latest_weekly_goal_row(user_id):
    return db.session.scalar(
        sa.select(WeeklyGoalHistory)
        .where(WeeklyGoalHistory.user_id == user_id)
        .order_by(WeeklyGoalHistory.effective_from.desc(), WeeklyGoalHistory.id.desc())
        .limit(1)
    )


def _current_week_start_naive():
    """Lunes 00:00 (naive) de la semana en curso -- mismo criterio que
    compute_smart_streak() para "semana". Un objetivo guardado a mitad de
    semana debe contar como vigente desde el lunes de ESA semana, no desde
    el instante exacto en que se guarda -- si no, la semana en que se
    activa o se cambia el objetivo nunca tiene un objetivo "vigente" según
    goal_for_week() y compute_smart_streak() devuelve 0 de inmediato, sin
    mirar siquiera semanas anteriores ya cumplidas."""
    today = to_local(datetime.now(timezone.utc)).date()
    return datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    form = SettingsForm()
    if form.validate_on_submit():
        current_user.stagnation_threshold = form.stagnation_threshold.data
        current_user.effort_scale = form.effort_scale.data
        current_user.rest_sound_enabled = form.rest_sound_enabled.data
        current_user.rest_vibration_enabled = form.rest_vibration_enabled.data
        current_user.sex = form.sex.data or None
        current_user.height_cm = form.height_cm.data
        current_user.training_goal = form.training_goal.data or None
        days = sorted({d for d in (form.training_days.data or []) if 0 <= d <= 6})
        current_user.training_days = "".join(str(d) for d in days) or None

        # Mínimo semanal de la racha: se guarda como fila nueva (historial
        # append-only) solo si cambia; vacío = el mínimo por defecto (1).
        latest = _latest_weekly_goal_row(current_user.id)
        current_minimum = latest.goal if latest else None
        new_minimum = form.weekly_workout_goal.data or None
        if new_minimum != current_minimum:
            db.session.add(
                WeeklyGoalHistory(
                    user_id=current_user.id,
                    goal=new_minimum,
                    effective_from=_current_week_start_naive(),
                )
            )

        db.session.commit()
        flash(gettext("Configuración guardada."))
        return redirect(url_for("settings"))
    elif request.method == "GET":
        form.stagnation_threshold.data = current_user.stagnation_threshold
        form.effort_scale.data = current_user.effort_scale
        form.rest_sound_enabled.data = current_user.rest_sound_enabled
        form.rest_vibration_enabled.data = current_user.rest_vibration_enabled
        form.sex.data = current_user.sex or ""
        form.height_cm.data = current_user.height_cm
        form.training_goal.data = current_user.training_goal or ""
        form.training_days.data = [int(c) for c in (current_user.training_days or "")]
        latest = _latest_weekly_goal_row(current_user.id)
        form.weekly_workout_goal.data = latest.goal if latest else None
    return render_template("settings.html", title=gettext("Configuración"), form=form, accents=perks.ACCENTS,
                           empty_lang_form=EmptyForm())


@app.route("/weight", methods=["GET", "POST"])
@login_required
def weight():
    form = WeightForm()
    if form.validate_on_submit():
        db.session.add(BodyWeightEntry(weight=form.weight.data, user_id=current_user.id))
        db.session.commit()
        flash(gettext("Peso registrado."))
        check_achievements()
        return redirect(url_for("weight"))

    entries = db.session.scalars(
        sa.select(BodyWeightEntry)
        .where(BodyWeightEntry.user_id == current_user.id)
        .order_by(BodyWeightEntry.timestamp.asc())
    ).all()

    return render_template(
        "weight.html",
        title=gettext("Peso corporal"),
        form=form,
        empty_form=EmptyForm(),
        pace=bodyweight_mod.summary([(e.timestamp, e.weight) for e in entries], current_user.body_phase,
                                    datetime.now(timezone.utc).replace(tzinfo=None), _global_tier(current_user)),
        phases=bodyweight_mod.PHASES,
        entries=list(reversed(entries)),
        chart_labels=[to_local(e.timestamp).strftime("%d/%m/%Y") for e in entries],
        chart_values=[e.weight for e in entries],
    )


# ------------------------------------------------------------ cuenta
CONTACT_MAX_CHARS = 2000
CONTACT_PER_DAY = 5


@app.route("/cuenta/exportar")
@login_required
def export_account():
    """Descarga de todos tus datos en JSON (portabilidad, RGPD)."""
    data = json.dumps(progression.export_user_data(current_user.id), ensure_ascii=False, indent=2)
    response = make_response(data)
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    name = re.sub(r"[^A-Za-z0-9_-]", "", current_user.username) or "usuario"
    response.headers["Content-Disposition"] = f'attachment; filename="gyre-{name}-{usage.local_today().isoformat()}.json"'
    return response


@app.route("/cuenta/borrar", methods=["GET", "POST"])
@login_required
def delete_account():
    """Borrar tu cuenta y todos tus datos tú mismo. Para confirmar hay que
    escribir el nombre de usuario (vale también para cuentas de Google, que
    no tienen contraseña)."""
    form = EmptyForm()
    error = None
    if form.validate_on_submit():
        if (request.form.get("confirm") or "").strip() != current_user.username:
            error = gettext("Escribe tu nombre de usuario exactamente igual para confirmar.")
        else:
            uid = current_user.id
            logout_user()
            progression.delete_user_data(uid)
            datacache.clear()
            flash(gettext("Tu cuenta y todos tus datos se han borrado."))
            return redirect(url_for("landing"))
    return render_template("delete_account.html", title=gettext("Borrar mi cuenta"), form=form, error=error)


@app.route("/contacto", methods=["GET", "POST"])
@login_required
def contact():
    """Escribir al responsable de la app sin publicar un email."""
    form = EmptyForm()
    body = (request.form.get("body") or "").strip()
    if form.validate_on_submit():
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        sent_today = db.session.scalar(
            sa.select(sa.func.count()).select_from(ContactMessage)
            .where(ContactMessage.user_id == current_user.id, ContactMessage.created_at >= since)
        )
        if not body:
            flash(gettext("Escribe tu mensaje."))
        elif sent_today >= CONTACT_PER_DAY:
            flash(gettext("Has enviado muchos mensajes hoy. Inténtalo mañana."))
        else:
            db.session.add(ContactMessage(user_id=current_user.id, body=body[:CONTACT_MAX_CHARS]))
            db.session.commit()
            flash(gettext("Mensaje enviado. Te responderemos al email de tu cuenta."))
            return redirect(url_for("settings"))
    return render_template("contact.html", title=gettext("Contacto"), form=form, body=body,
                           max_chars=CONTACT_MAX_CHARS)


@app.route("/idioma", methods=["POST"])
def set_language():
    """Elegir idioma ("" = automático, el del navegador). Con sesión se
    guarda en el usuario; siempre en una cookie, para el login y la landing."""
    from app import i18n

    form = EmptyForm()
    code = request.form.get("language") or ""
    if not form.validate_on_submit() or (code and code not in i18n.LANGUAGES):
        return redirect(request.referrer or url_for("index"))
    if current_user.is_authenticated:
        current_user.language = code or None
        db.session.commit()
    response = make_response(redirect(request.referrer or url_for("index")))
    if code:
        response.set_cookie("lang", code, max_age=365 * 24 * 3600, samesite="Lax", secure=request.is_secure)
    else:
        response.delete_cookie("lang")
    return response


@app.route("/weight/fase", methods=["POST"])
@login_required
def set_body_phase():
    """Elegir (o quitar) la fase: volumen, definición o recomposición."""
    form = EmptyForm()
    if form.validate_on_submit():
        phase = request.form.get("phase") or None
        if phase is None or phase in bodyweight_mod.PHASES:
            current_user.body_phase = phase
            db.session.commit()
    return redirect(url_for("weight") + "#ritmo")


@app.route("/weight/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete_weight_entry(entry_id):
    entry = db.get_or_404(BodyWeightEntry, entry_id)
    if entry.user_id != current_user.id:
        flash(gettext("No tienes acceso a ese registro de peso."))
        return redirect(url_for("weight"))
    db.session.delete(entry)
    db.session.commit()
    flash(gettext("Registro de peso eliminado."))
    return redirect(url_for("weight"))


MIN_WORKOUTS_FOR_AI_ANALYSIS = 3


@app.route("/ai/analysis")
@login_required
def ai_analysis():
    total_workouts = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(Workout)
        .where(Workout.user_id == current_user.id)
    )
    latest = db.session.scalar(
        sa.select(AiAnalysis)
        .where(AiAnalysis.user_id == current_user.id)
        .order_by(AiAnalysis.created_at.desc())
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    next_available = None
    wait_label = None
    cooldown_pct = 0
    allowance = perks.ai_per_week(perks.level_of(current_user))
    blocking = ai_analysis_blocking(current_user.id, allowance, now)
    if blocking is not None:
        cooldown = timedelta(days=7)
        available_at = blocking.created_at + cooldown
        if available_at > now:
            next_available = available_at
            remaining = available_at - now
            if remaining < timedelta(days=1):
                hours = max(1, math.ceil(remaining.total_seconds() / 3600))
                wait_label = gettext("en %(n)s h", n=hours)
            else:
                days = math.ceil(remaining.total_seconds() / 86400)
                wait_label = gettext("mañana") if days == 1 else gettext("en %(n)s días", n=days)
            cooldown_pct = round(100 * (1 - remaining / cooldown))

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
        title=gettext("Análisis de IA"),
        latest=latest,
        analysis=analysis,
        next_available=next_available,
        wait_label=wait_label,
        cooldown_pct=cooldown_pct,
        total_workouts=total_workouts,
        min_workouts=MIN_WORKOUTS_FOR_AI_ANALYSIS,
        checkin_form=AiCheckinForm(),
        allowance=allowance,
        extra_level=perks.AI_EXTRA_LEVEL,
    )


def ai_analysis_blocking(user_id, allowance, now=None):
    """El análisis que impide generar otro, o None si queda cupo. Cupo:
    `allowance` análisis en los últimos 7 días (2 a partir del nivel 20).
    Con el cupo lleno, se libera cuando el más antiguo de esos cumple 7 días."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    recent = db.session.scalars(
        sa.select(AiAnalysis)
        .where(AiAnalysis.user_id == user_id, AiAnalysis.created_at >= now - timedelta(days=7))
        .order_by(AiAnalysis.created_at.desc())
    ).all()
    return recent[allowance - 1] if len(recent) >= allowance else None


@app.route("/ai/analyze", methods=["POST"])
@login_required
def request_ai_analysis():
    checkin_form = AiCheckinForm()
    allowance = perks.ai_per_week(perks.level_of(current_user))
    if ai_analysis_blocking(current_user.id, allowance) is not None:
        flash(gettext("Ya has usado tus análisis de esta semana. Vuelve a intentarlo más adelante.")
              if allowance > 1 else gettext("Ya generaste un análisis esta semana. Vuelve a intentarlo más adelante."))
        return redirect(url_for("ai_analysis"))

    total_workouts = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(Workout)
        .where(Workout.user_id == current_user.id)
    )
    if total_workouts < MIN_WORKOUTS_FOR_AI_ANALYSIS:
        flash(gettext(
            "Necesitas al menos %(min)s entrenamientos registrados para generar un análisis (llevas %(n)s).",
            min=MIN_WORKOUTS_FOR_AI_ANALYSIS, n=total_workouts))
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
        flash(gettext("No se pudo generar el análisis ahora mismo. Inténtalo de nuevo en unos minutos."))
        return redirect(url_for("ai_analysis"))

    db.session.add(AiAnalysis(content=content, user_id=current_user.id))
    db.session.commit()
    check_achievements()
    flash(gettext("¡Análisis generado!"))
    return redirect(url_for("ai_analysis"))


@app.route("/routines")
@login_required
def routines():
    routine_list = db.session.scalars(
        current_user.routines.select().order_by(Routine.order_index)
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
        last_day = str(WEEKDAY_NAMES[to_local(last_workout.timestamp).weekday()]).capitalize() if last_workout else None
        routines_info.append(
            {
                "routine": r,
                "exercise_names": [e.exercise.title() for e in exercises],
                "last_trained": last_workout.timestamp if last_workout else None,
                "last_day": last_day,
                "last_date": (
                    to_local(last_workout.timestamp).strftime("%d/%m/%Y")
                    if last_workout
                    else None
                ),
            }
        )

    # Fijadas primero (cualquier bloque), luego el resto agrupado por bloque
    # -- cada RoutineBlock es su propia sección plegable (abierta de entrada
    # solo si es la predeterminada), "Sin bloque" siempre visible y al final.
    # Arrastrar reordena dentro de cada sección por separado (reorder_routines()
    # ya funciona con subconjuntos de ids sin tocar el resto).
    blocks = db.session.scalars(
        sa.select(RoutineBlock)
        .where(RoutineBlock.user_id == current_user.id)
        .order_by(RoutineBlock.order_index)
    ).all()

    pinned_info = [info for info in routines_info if info["routine"].pinned]
    unpinned_info = [info for info in routines_info if not info["routine"].pinned]

    by_block_id = defaultdict(list)
    no_block_info = []
    for info in unpinned_info:
        block_id = info["routine"].block_id
        if block_id is None:
            no_block_info.append(info)
        else:
            by_block_id[block_id].append(info)

    block_sections = [(b, by_block_id.get(b.id, [])) for b in blocks]

    empty_form = EmptyForm()
    return render_template(
        "routines.html",
        title=gettext("Mis rutinas"),
        routines_info=routines_info,
        pinned_info=pinned_info,
        block_sections=block_sections,
        no_block_info=no_block_info,
        blocks=blocks,
        empty_form=empty_form,
    )


@app.route("/routines/<int:routine_id>/pin", methods=["POST"])
@login_required
def toggle_routine_pin(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        return jsonify({"ok": False}), 403
    routine.pinned = not routine.pinned
    db.session.commit()
    return jsonify({"ok": True, "pinned": routine.pinned})


@app.route("/routines/<int:routine_id>/block", methods=["POST"])
@login_required
def set_routine_block(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    new_name = (data.get("new_block_name") or "").strip()[:64]
    if new_name:
        max_order = db.session.scalar(
            sa.select(sa.func.max(RoutineBlock.order_index)).where(
                RoutineBlock.user_id == current_user.id
            )
        )
        block = RoutineBlock(
            name=new_name,
            order_index=(max_order + 1) if max_order is not None else 0,
            user_id=current_user.id,
        )
        db.session.add(block)
        db.session.flush()
        routine.block_id = block.id
    else:
        block_id = data.get("block_id")
        if block_id:
            block = db.get_or_404(RoutineBlock, block_id)
            if block.user_id != current_user.id:
                return jsonify({"ok": False}), 403
            routine.block_id = block.id
        else:
            routine.block_id = None
    db.session.commit()
    return jsonify({"ok": True, "block_id": routine.block_id})


def _normalize_block_color(hex_color):
    """Recorta la luminosidad a una franja media (35%-55%) antes de guardar
    un color de bloque -- elegido libremente con <input type=color>, un tono
    casi blanco apenas se nota al mezclarlo como sombra de tarjeta (8%/45%
    en CSS, ver .routine-card) y uno casi negro se ve demasiado duro de
    borde. Solo se toca la luminosidad, nunca el matiz/saturación, para que
    el color elegido siga siendo reconociblemente "ese" color, solo con
    contraste garantizado."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    # Blanco (o casi, sin apenas saturación) es una elección válida: "bloque
    # sin color", tarjetas sin sombrear. Se guarda tal cual en vez de
    # oscurecerlo a gris -- la plantilla lo trata como neutro.
    if l >= 0.9 and s <= 0.2:
        return "#ffffff"
    l = min(max(l, 0.35), 0.55)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


@app.route("/routine-blocks/<int:block_id>/color", methods=["POST"])
@login_required
def set_routine_block_color(block_id):
    block = db.get_or_404(RoutineBlock, block_id)
    if block.user_id != current_user.id:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    color = (data.get("color") or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return jsonify({"ok": False}), 400
    block.color = _normalize_block_color(color)
    db.session.commit()
    return jsonify({"ok": True, "color": block.color})


@app.route("/routine-blocks/<int:block_id>/default", methods=["POST"])
@login_required
def set_default_routine_block(block_id):
    block = db.get_or_404(RoutineBlock, block_id)
    if block.user_id != current_user.id:
        return jsonify({"ok": False}), 403
    data = request.get_json(silent=True) or {}
    make_default = bool(data.get("is_default", True))
    if make_default:
        db.session.execute(
            sa.update(RoutineBlock)
            .where(RoutineBlock.user_id == current_user.id, RoutineBlock.id != block.id)
            .values(is_default=False)
        )
        block.is_default = True
    else:
        block.is_default = False
    db.session.commit()
    return jsonify({"ok": True, "is_default": block.is_default})


@app.route("/routines/<int:routine_id>", methods=["GET", "POST"])
@login_required
def routine_detail(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        flash(gettext("No tienes acceso a esta rutina."))
        return redirect(url_for("routines"))

    form = RoutineExerciseForm()
    if form.validate_on_submit():
        # StringField deja "" (no None) cuando el campo queda vacío -- normalizar,
        # las plantillas comprueban "is not none" para decidir si mostrar @RIR/@RPE.
        rir = (form.effort_value.data or None) if current_user.effort_scale == "rir" else None
        rpe = (form.effort_value.data or None) if current_user.effort_scale == "rpe" else None

        replace_ex = None
        if form.replace_ex_id.data:
            replace_ex = db.session.get(RoutineExercise, int(form.replace_ex_id.data))
            if not replace_ex or replace_ex.routine_id != routine.id:
                flash(gettext("No se pudo actualizar ese ejercicio."))
                return redirect(url_for("routine_detail", routine_id=routine.id))

        if replace_ex:
            replace_ex.exercise = canonicalize_exercise_name(form.exercise.data)
            replace_ex.target_sets = form.target_sets.data
            replace_ex.target_reps = form.target_reps.data
            replace_ex.rir = rir
            replace_ex.rpe = rpe
            db.session.commit()
            flash(gettext("Ejercicio actualizado."))
        else:
            count = db.session.scalar(
                sa.select(sa.func.count())
                .select_from(RoutineExercise)
                .where(RoutineExercise.routine_id == routine.id)
            )
            ex = RoutineExercise(
                exercise=canonicalize_exercise_name(form.exercise.data),
                target_sets=form.target_sets.data,
                target_reps=form.target_reps.data,
                rir=rir,
                rpe=rpe,
                order_index=count,
                routine_id=routine.id,
            )
            db.session.add(ex)
            db.session.commit()
            return redirect(url_for("routine_detail", routine_id=routine.id, _anchor=f"rex-{ex.id}"))
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
    prefetch_catalog_exercises(e.exercise for e in exercises)
    return render_template(
        "routine_detail.html",
        title=routine.name,
        routine=routine,
        exercises=exercises,
        form=form,
        empty_form=empty_form,
        exercise_notes_map=exercise_notes_map,
        effort_scale=current_user.effort_scale,
    )


@app.route("/routines/new", methods=["GET", "POST"])
@login_required
def new_routine():
    form = RoutineForm()
    if form.validate_on_submit():
        count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(Routine)
            .where(Routine.user_id == current_user.id)
        )
        routine = Routine(name=form.name.data, order_index=count, author=current_user)
        db.session.add(routine)
        db.session.commit()
        check_achievements()
        flash(gettext("Rutina creada. Añade ejercicios."))
        return redirect(url_for("routine_detail", routine_id=routine.id))
    return render_template("new_routine.html", title=gettext("Nueva rutina"), form=form)


@app.route("/routines/<int:routine_id>/exercise/<int:ex_id>/delete", methods=["POST"])
@login_required
def delete_routine_exercise(routine_id, ex_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        flash(gettext("No tienes acceso a esta rutina."))
        return redirect(url_for("routines"))
    ex = db.get_or_404(RoutineExercise, ex_id)
    # El ejercicio tiene que ser de ESTA rutina: comprobar solo la rutina
    # dejaba borrar un ejercicio ajeno poniendo un ex_id de otra rutina.
    if ex.routine_id != routine.id:
        flash(gettext("No tienes acceso a esta rutina."))
        return redirect(url_for("routines"))
    db.session.delete(ex)
    db.session.commit()
    flash(gettext("Ejercicio eliminado de la rutina."))
    return redirect(url_for("routine_detail", routine_id=routine.id))


_EFFORT_RE = re.compile(r"\d{1,2}(-\d{1,2})?")


def _own_routine_exercise(routine_id, ex_id):
    """(rutina, ejercicio) si ambos existen, son del usuario y el ejercicio
    pertenece a esa rutina; si no, None."""
    routine = db.session.get(Routine, routine_id)
    ex = db.session.get(RoutineExercise, ex_id)
    if routine is None or ex is None or routine.author != current_user or ex.routine_id != routine.id:
        return None
    return routine, ex


@app.route("/routines/<int:routine_id>/exercise/<int:ex_id>", methods=["POST"])
@login_required
def update_routine_exercise(routine_id, ex_id):
    """Edición en la propia fila (series / reps / RIR-RPE), sin formulario
    aparte. Mismas reglas que RoutineExerciseForm."""
    found = _own_routine_exercise(routine_id, ex_id)
    if found is None:
        return jsonify({"ok": False}), 403
    _, ex = found
    data = request.get_json(silent=True) or {}

    if "target_sets" in data:
        try:
            sets = int(data["target_sets"])
        except (TypeError, ValueError):
            sets = 0
        if not 1 <= sets <= 15:
            return jsonify({"ok": False, "error": gettext("Las series van de 1 a 15.")}), 400
        ex.target_sets = sets
        if ex.target_sets_max is not None and ex.target_sets_max <= sets:
            ex.target_sets_max = None
    if "target_sets_max" in data:
        raw = str(data["target_sets_max"] or "").strip()
        if not raw:
            ex.target_sets_max = None
        else:
            try:
                top = int(raw)
            except ValueError:
                top = 0
            if not ex.target_sets <= top <= 15:
                return jsonify({"ok": False, "error": gettext("El máximo de series va de %(n)s a 15.", n=ex.target_sets)}), 400
            ex.target_sets_max = top if top > ex.target_sets else None
    if "reps_min" in data or "reps_max" in data:
        low, high = reps_range(ex.target_reps)
        try:
            if "reps_min" in data:
                low = int(str(data["reps_min"]).strip())
            if "reps_max" in data:
                raw = str(data["reps_max"] or "").strip()
                high = int(raw) if raw else None
        except ValueError:
            return jsonify({"ok": False, "error": gettext("Las repeticiones tienen que ser números.")}), 400
        if not low or not 1 <= low <= 100 or (high is not None and not low <= high <= 100):
            return jsonify({"ok": False, "error": gettext("Repeticiones de 1 a 100, y el máximo no puede ser menor que el mínimo.")}), 400
        ex.target_reps = f"{low}-{high}" if high and high > low else str(low)
    if "target_reps" in data:  # compatibilidad: texto libre
        reps = " ".join(str(data["target_reps"] or "").split())
        if not reps or len(reps) > 16:
            return jsonify({"ok": False, "error": gettext("Escribe las reps (máx. 16 caracteres), p. ej. 8-10.")}), 400
        ex.target_reps = reps
    if "effort" in data:
        effort = str(data["effort"] or "").replace(" ", "")
        if effort and not _EFFORT_RE.fullmatch(effort):
            return jsonify({"ok": False, "error": gettext("Usa un número (ej. 2) o un rango (ej. 2-3).")}), 400
        scale = current_user.effort_scale
        ex.rir = (effort or None) if scale == "rir" else None
        ex.rpe = (effort or None) if scale == "rpe" else None

    db.session.commit()
    low, high = reps_range(ex.target_reps)
    return jsonify({
        "ok": True,
        "target_sets": ex.target_sets,
        "target_sets_max": ex.target_sets_max or "",
        "reps_min": low or "",
        "reps_max": high or "",
        "target_reps": ex.target_reps,
        "effort": ex.rir if ex.rir is not None else (ex.rpe or ""),
    })


@app.route("/routines/<int:routine_id>/exercise/<int:ex_id>/replace", methods=["POST"])
@login_required
def replace_routine_exercise(routine_id, ex_id):
    """Cambia el ejercicio de la fila conservando series/reps/esfuerzo (lo
    usa el modo "reemplazar" del selector, igual que en el entreno)."""
    found = _own_routine_exercise(routine_id, ex_id)
    if found is None:
        return jsonify({"ok": False}), 403
    _, ex = found
    name = str((request.get_json(silent=True) or {}).get("exercise", "")).strip()
    if not name or len(name) > 64:
        return jsonify({"ok": False, "error": gettext("Elige un ejercicio.")}), 400
    ex.exercise = canonicalize_exercise_name(name)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/routines/<int:routine_id>/delete", methods=["POST"])
@login_required
def delete_routine(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        flash(gettext("No tienes acceso a esta rutina."))
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
        .execution_options(xp_irrelevant=True)  # el XP no depende de la rutina
    )
    db.session.delete(routine)
    db.session.commit()
    flash(gettext("Rutina eliminada."))
    return redirect(url_for("routines"))


_REPS_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+))?")


def reps_range(text):
    """"8-10" -> (8, 10); "5" -> (5, None); "5 @RIR3" -> (5, None)."""
    m = _REPS_RE.search(text or "")
    if not m:
        return None, None
    low = int(m.group(1))
    high = int(m.group(2)) if m.group(2) else None
    return low, (high if high and high > low else None)


def sets_label(ex):
    return f"{ex.target_sets}-{ex.target_sets_max}" if ex.target_sets_max else str(ex.target_sets)


def _parse_single_int(value):
    """Convierte un objetivo de RIR/RPE en un entero 0-10 solo si es un
    número simple (ej. "2") -- un rango (ej. "2-3") u otro texto no
    parseable devuelve None, para no adivinar qué extremo usar."""
    if value is None:
        return None
    try:
        return max(0, min(10, int(value)))
    except (TypeError, ValueError):
        return None


@app.route("/routines/<int:routine_id>/start", methods=["POST"])
@login_required
def start_routine(routine_id):
    routine = db.get_or_404(Routine, routine_id)
    if routine.author != current_user:
        flash(gettext("No tienes acceso a esta rutina."))
        return redirect(url_for("routines"))

    existing = get_active_workout(current_user.id)
    if existing:
        flash(gettext("Ya tienes un entreno en curso — termínalo antes de empezar otro."))
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
        for _ in range(re_.target_sets_max or re_.target_sets):  # las que sobren se borran al terminar
            db.session.add(
                SetEntry(
                    exercise=re_.exercise,
                    weight=0.0,
                    reps=0,
                    rir=_parse_single_int(re_.rir),
                    rpe=_parse_single_int(re_.rpe),
                    set_type="normal",
                    workout=workout,
                )
            )

    db.session.commit()
    flash(gettext("¡Entrenamiento '%(name)s' iniciado!", name=routine.name))
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


@app.route("/routines/reorder", methods=["POST"])
@login_required
def reorder_routines():
    data = request.get_json(silent=True) or {}
    order = data.get("order", [])
    routines_by_id = {
        r.id: r
        for r in db.session.scalars(
            sa.select(Routine).where(Routine.user_id == current_user.id)
        ).all()
    }
    for index, routine_id in enumerate(order):
        if routine_id in routines_by_id:
            routines_by_id[routine_id].order_index = index
    db.session.commit()
    return jsonify({"ok": True})


@app.context_processor
def inject_level_perks():
    """Nivel (de la caché de XP, sin recalcular) y colores de acento
    desbloqueados, para base.html y Configuración."""
    if current_user.is_authenticated:
        level = perks.level_of(current_user)
        return {"user_level": level, "unlocked_accents": [a["key"] for a in perks.unlocked(perks.ACCENTS, level)]}
    return {}


@app.context_processor
def inject_active_workout():
    if current_user.is_authenticated:
        return {"active_workout": get_active_workout(current_user.id)}
    return {"active_workout": None}


@app.route("/api/exercises/search")
@login_required
def api_search_exercises():
    q = request.args.get("q", "").strip()
    favorite_ids = set(
        db.session.scalars(
            sa.select(ExerciseFavorite.exercise_id).where(
                ExerciseFavorite.user_id == current_user.id
            )
        )
    )
    if len(q) < 2:
        if not favorite_ids:
            return jsonify([])
        results = db.session.scalars(
            sa.select(Exercise).where(Exercise.id.in_(favorite_ids))
        ).all()
    else:
        word_conditions = [
            sa.or_(Exercise.name.ilike(f"%{word}%"), Exercise.name_es.ilike(f"%{word}%"))
            for word in q.split()
        ]
        results = db.session.scalars(
            sa.select(Exercise).where(sa.and_(*word_conditions)).limit(24)
        ).all()
        results = sorted(results, key=lambda e: e.id not in favorite_ids)
    return jsonify(
        [
            {
                "id": e.id,
                "name": catalog_display_name(e),
                "image": e.image_url,
                "muscles": e.primary_muscles,
                "is_favorite": e.id in favorite_ids,
            }
            for e in results
        ]
    )


@app.route("/api/exercises/<exercise_id>/favorite", methods=["POST"])
@login_required
def toggle_exercise_favorite(exercise_id):
    if not db.session.get(Exercise, exercise_id):
        return jsonify({"ok": False, "error": gettext("Ejercicio no encontrado.")}), 404
    existing = db.session.scalar(
        sa.select(ExerciseFavorite).where(
            ExerciseFavorite.user_id == current_user.id,
            ExerciseFavorite.exercise_id == exercise_id,
        )
    )
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"ok": True, "favorite": False})
    db.session.add(ExerciseFavorite(user_id=current_user.id, exercise_id=exercise_id))
    db.session.commit()
    return jsonify({"ok": True, "favorite": True})


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
    secondary_muscles = [
        m for m in (data.get("secondary_muscles") or []) if m in MUSCLE_GROUP_MAP and m not in muscles
    ]
    category = (data.get("category") or "").strip() or None
    equipment = (data.get("equipment") or "").strip() or None

    if not name:
        return jsonify({"ok": False, "error": gettext("El nombre es obligatorio.")}), 400
    if not muscles:
        return jsonify({"ok": False, "error": gettext("Elige al menos un músculo primario.")}), 400

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
        secondary_muscles=", ".join(secondary_muscles) or None,
        equipment=equipment,
        image_url=None,
    )
    db.session.add(exercise)
    db.session.commit()
    _clear_catalog_cache()
    return jsonify({"ok": True, "name": name})


@app.route("/workout/<int:workout_id>/save_as_routine", methods=["POST"])
@login_required
def save_as_routine(workout_id):
    workout = db.get_or_404(Workout, workout_id)
    if workout.author != current_user:
        flash(gettext("No tienes acceso a este entrenamiento."))
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
        flash(gettext("Este entrenamiento no tiene series registradas."))
        return redirect(url_for("workout_detail", workout_id=workout.id))

    routine = Routine(name=workout.note or gettext("Nueva rutina"), author=current_user)
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
    flash(gettext("Rutina '%(name)s' creada a partir de este entrenamiento.", name=routine.name))
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


# Tabla RTS (Tuchscherer): % del 1RM real según reps × RIR, para reps 1-12 y
# RIR 0-4 (RPE 10-6). A diferencia de Epley, da el peso exacto en el caso
# reps=1/RIR=0 (un intento real a 1RM no necesita estimarse).
_RTS_PERCENT_1RM = {
    1: {0: 1.000, 1: 0.955, 2: 0.922, 3: 0.892, 4: 0.863},
    2: {0: 0.955, 1: 0.922, 2: 0.892, 3: 0.863, 4: 0.837},
    3: {0: 0.922, 1: 0.892, 2: 0.863, 3: 0.837, 4: 0.811},
    4: {0: 0.892, 1: 0.863, 2: 0.837, 3: 0.811, 4: 0.786},
    5: {0: 0.863, 1: 0.837, 2: 0.811, 3: 0.786, 4: 0.762},
    6: {0: 0.837, 1: 0.811, 2: 0.786, 3: 0.762, 4: 0.739},
    7: {0: 0.811, 1: 0.786, 2: 0.762, 3: 0.739, 4: 0.715},
    8: {0: 0.786, 1: 0.762, 2: 0.739, 3: 0.715, 4: 0.694},
    9: {0: 0.762, 1: 0.739, 2: 0.715, 3: 0.694, 4: 0.675},
    10: {0: 0.739, 1: 0.715, 2: 0.694, 3: 0.675, 4: 0.653},
    11: {0: 0.715, 1: 0.694, 2: 0.675, 3: 0.653, 4: 0.633},
    12: {0: 0.694, 1: 0.675, 2: 0.653, 3: 0.633, 4: 0.616},
}


def estimated_1rm(entry, bodyweight=0.0):
    """1RM real vía tabla RTS cuando reps/RIR caen en el rango cubierto
    (1-12 reps, RIR 0-4); si no (RIR>=5, reps>12, o sin RIR/RPE anotado),
    respaldo con Epley y repeticiones efectivas. En el límite RIR4/RIR5 el
    valor puede dar un salto pequeño no suave (Epley no empalma exacto con
    la tabla ahí) -- conocido, no corregido."""
    rir = entry.rir if entry.rir is not None else (
        10 - entry.rpe if entry.rpe is not None else None
    )
    # Dominadas: carga = tu peso + el lastre apuntado.
    weight = entry.weight
    if bodyweight and is_bodyweight_exercise(getattr(entry, "exercise", None)):
        weight += bodyweight
    row = _RTS_PERCENT_1RM.get(entry.reps)
    pct = row.get(rir) if row else None
    if pct is not None:
        return weight / pct
    return weight * (1 + effective_reps(entry) / 30)


DEFAULT_WEEKLY_MINIMUM = 1  # sin mínimo configurado: basta con entrenar 1 día a la semana


def compute_smart_streak(user_id, workouts):
    """Racha en DÍAS entrenados, mantenida semana a semana.

    Cada semana (lunes-domingo, hora de Madrid) en la que entrenas al menos
    tu mínimo semanal suma TODOS los días que entrenaste esa semana; una
    semana por debajo del mínimo corta la racha. La semana en curso nunca
    la corta (aún puede cumplirse) y sus días ya cuentan. Así una semana de
    descarga o con menos días que de costumbre no rompe la racha mientras
    llegue al mínimo, y no importa QUÉ días de la semana entrenes.

    Un día cuenta si ese día hay algún entreno con al menos una serie
    marcada como hecha (un entreno empezado por error no suma).
    El mínimo vigente de cada semana sale de WeeklyGoalHistory (append-only:
    cambiarlo no reevalúa semanas pasadas con el criterio nuevo).

    Devuelve {"days", "this_week", "minimum"}."""
    workout_ids = [w.id for w in workouts]
    done_ids = set()
    if workout_ids:
        done_ids = set(db.session.scalars(
            sa.select(SetEntry.workout_id)
            .where(SetEntry.workout_id.in_(workout_ids), SetEntry.completed.is_(True))
            .distinct()
        ))
    trained_days = {to_local(w.timestamp).date() for w in workouts if w.id in done_ids}
    days_by_week = defaultdict(int)
    for d in trained_days:
        days_by_week[d - timedelta(days=d.weekday())] += 1

    history = db.session.scalars(
        sa.select(WeeklyGoalHistory)
        .where(WeeklyGoalHistory.user_id == user_id)
        .order_by(WeeklyGoalHistory.effective_from.desc(), WeeklyGoalHistory.id.desc())
    ).all()

    def minimum_for(week_start):
        for h in history:  # desc por effective_from: el primero vigente gana
            if h.effective_from.date() <= week_start:
                return h.goal or DEFAULT_WEEKLY_MINIMUM
        return DEFAULT_WEEKLY_MINIMUM

    today = to_local(datetime.now(timezone.utc)).date()
    current_week = today - timedelta(days=today.weekday())
    this_week = days_by_week.get(current_week, 0)

    streak = this_week
    week = current_week - timedelta(days=7)
    while days_by_week.get(week, 0) >= minimum_for(week):
        streak += days_by_week[week]
        week -= timedelta(days=7)

    plan = planned_weekdays(db.session.get(User, user_id))
    week = [
        {
            "letter": str(_WEEKDAY_SHORT[i]),
            "trained": (current_week + timedelta(days=i)) in trained_days,
            "today": i == today.weekday(),
            "planned": i in plan,
        }
        for i in range(7)
    ]
    return {"days": streak, "this_week": this_week, "minimum": minimum_for(current_week), "week": week}


def get_previous_sets_map(workout, exercise_names):
    """Para cada ejercicio de `exercise_names`, las series (peso×reps) de la última vez
    que current_user lo entrenó antes de `workout`. Una sola consulta, sin N+1.
    Cada serie es un dict {weight, reps, effort, effort_scale, label} -- label para la
    columna "Anterior", weight/reps/effort sueltos para el placeholder de los inputs.
    effort_scale guarda con qué escala (rir/rpe) se grabó esa serie en su momento --
    no tiene por qué coincidir con la escala activa ahora si el usuario la cambió
    después en Configuración, y RIR/RPE no son intercambiables (mismo rango 0-10,
    significado opuesto), así que el consumidor debe comparar antes de usar `effort`."""
    if not exercise_names:
        return {}
    rows = db.session.execute(
        sa.select(Workout.id, SetEntry)
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
    for wid, entry in rows:
        if not is_real_set(entry):
            continue
        last_workout_id.setdefault(entry.exercise, wid)
        if last_workout_id[entry.exercise] == wid:
            effort_value = entry.rir if entry.rir is not None else entry.rpe
            entry_scale = "rir" if entry.rir is not None else ("rpe" if entry.rpe is not None else None)
            result.setdefault(entry.exercise, []).append(
                {
                    "weight": entry.weight,
                    "reps": entry.reps,
                    "effort": effort_value,
                    "effort_scale": entry_scale,
                    "label": f"{fmt_num(entry.weight, 2)}kg×{entry.reps}",
                }
            )
    return result


def sessions_from_rows(rows):
    """[(Workout, SetEntry)] de UN ejercicio -> sesiones en orden cronológico
    con best_set / best_1rm / is_pr. Separado de la consulta para que la
    pantalla de Progreso (todos los ejercicios en una sola consulta) use
    exactamente el mismo criterio de 1RM y récord que el resto de la app."""
    sessions = {}
    for workout, entry in rows:
        sessions.setdefault(workout.id, {"timestamp": workout.timestamp, "sets": []})
        sessions[workout.id]["sets"].append(entry)

    session_list = sorted(sessions.values(), key=lambda s: s["timestamp"])
    bw = 0.0
    if rows and is_bodyweight_exercise(rows[0][1].exercise):
        bw = latest_bodyweight(rows[0][0].user_id)

    running_max = float("-inf")
    for s in session_list:
        candidates = [st for st in s["sets"] if is_real_set(st)]
        if candidates:
            s["best_set"] = max(candidates, key=lambda st: estimated_1rm(st, bw))
            s["best_1rm"] = estimated_1rm(s["best_set"], bw)
            s["is_pr"] = s["best_1rm"] > running_max
            running_max = max(running_max, s["best_1rm"])
        else:
            s["best_set"] = None
            s["best_1rm"] = 0
            s["is_pr"] = False
    return session_list


def stagnation_flags(session_list, threshold):
    """(estancado, mejora) sobre las últimas `threshold` sesiones que cuentan."""
    qualifying = qualifying_sessions(session_list)
    if len(qualifying) < threshold:
        return False, False
    lastN = qualifying[-threshold:]
    return not any(s["is_pr"] for s in lastN), lastN[-1]["is_pr"]


TREND_WINDOW = timedelta(days=60)


def exercise_stats(session_list, threshold):
    """Cifras de cabecera de un ejercicio (Progreso y página del ejercicio).
    None si no hay ninguna sesión que cuente. trend_pct: cambio del 1RM
    entre la primera y la última sesión de los últimos 60 días (mín. 2)."""
    qualifying = qualifying_sessions(session_list)
    if not qualifying:
        return None
    last = qualifying[-1]
    window = [s for s in qualifying if s["timestamp"] >= last["timestamp"] - TREND_WINDOW]
    trend_pct = None
    if len(window) >= 2 and window[0]["best_1rm"] > 0:
        trend_pct = round(100 * (last["best_1rm"] - window[0]["best_1rm"]) / window[0]["best_1rm"])
    last_pr = next((s for s in reversed(qualifying) if s["is_pr"]), None)
    stagnation, _ = stagnation_flags(session_list, threshold)
    return {
        "last_1rm": last["best_1rm"],
        "best_1rm": max(s["best_1rm"] for s in qualifying),
        "last_trained": last["timestamp"],
        "last_pr": last_pr["timestamp"] if last_pr else None,
        "sessions": len(qualifying),
        "trend_pct": trend_pct,
        "stagnation": stagnation,
    }


def progress_overview(user_id, threshold, rows=None):
    """Todos los ejercicios del usuario con sus cifras, en UNA consulta (no
    una por ejercicio). Ordenados por el último entrenado primero."""
    if rows is None:
        rows = history_rows(user_id)
    by_exercise = defaultdict(list)
    for workout, entry in rows:
        by_exercise[entry.exercise].append((workout, entry))

    items = []
    for exercise, ex_rows in by_exercise.items():
        stats = exercise_stats(sessions_from_rows(ex_rows), threshold)
        if stats is not None:
            items.append({"exercise": exercise, **stats})
    items.sort(key=lambda i: i["last_trained"], reverse=True)
    return items


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
    session_list = sessions_from_rows(db.session.execute(query).all())
    stagnation, improvement = stagnation_flags(session_list, threshold)

    return session_list, stagnation, improvement


def qualifying_sessions(session_list):
    """Sesiones con al menos una serie que cuenta (completada, peso>0, reps>0).
    Filtra sobre el best_set que get_exercise_sessions ya calcula por sesión."""
    return [s for s in session_list if s["best_set"] is not None]


@functools.lru_cache(maxsize=2048)
def is_bodyweight_exercise(name):
    """Dominadas: el peso apuntado es el lastre y 0 = solo tu peso corporal
    (ver strength_standards). Las asistidas no entran."""
    return standards.lift_of(name or "") == "pullup"


def latest_bodyweight(user_id):
    """Último peso corporal registrado (kg) o 0; memorizado por petición."""
    cache = g.setdefault("_latest_bw", {})
    if user_id not in cache:
        cache[user_id] = db.session.scalar(
            sa.select(BodyWeightEntry.weight)
            .where(BodyWeightEntry.user_id == user_id)
            .order_by(BodyWeightEntry.timestamp.desc())
            .limit(1)
        ) or 0.0
    return cache[user_id]


def is_real_set(entry):
    """Serie que cuenta como dato real: completada, con peso y reps > 0
    (en dominadas, 0 kg también vale: es tu peso corporal).
    Único criterio para decidir qué serie de una sesión "cuenta" -- lo usan
    get_exercise_sessions() (para 1RM/PR) y get_previous_sets_map() (para
    la referencia "Anterior"), evita mantener el mismo criterio dos veces."""
    if not entry.completed or entry.reps <= 0:
        return False
    return entry.weight > 0 or (entry.weight == 0 and is_bodyweight_exercise(getattr(entry, "exercise", None)))


def apply_pr_flags_for_session(session):
    """Persiste is_pr en la serie ganadora de una sesión (dict de
    get_exercise_sessions) y lo limpia en el resto de esa MISMA sesión.
    Compartida entre completar/editar una serie y el backfill masivo."""
    changed = 0
    for s in session["sets"]:
        should_be_pr = session["best_set"] is not None and session["is_pr"] and s.id == session["best_set"].id
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
        if s.is_pr
        != (session["best_set"] is not None and session["is_pr"] and s.id == session["best_set"].id)
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


STRENGTH_STEP_CAP = (0.8, 1.25)  # un cambio sesión a sesión fuera de ±20-25% se recorta (dato mal apuntado)
STRENGTH_WINDOW_WEEKS = 4


def _week_start_local(dt):
    d = to_local(dt).date()
    return d - timedelta(days=d.weekday())


def strength_progress(user_id, rows=None):
    """Índice de fuerza semanal encadenado + resumen de las últimas 4 semanas.

    Cada semana, cada ejercicio entrenado se compara con su valor anterior
    (mejor 1RM estimado de la última semana en que se hizo) y la media
    geométrica de esos cambios mueve el índice (100 = tu primera semana).
    Encadenar así hace que ejercicios nuevos no hundan ni inflen el índice
    (entran sin comparar), y una sesión floja seguida de una normal se
    compensa sola (para un único ejercicio, índice = 1RM actual / 1RM inicial).
    Mismo 1RM y criterio de serie válida que el resto (sessions_from_rows).
    Una sola consulta.

    Devuelve None sin al menos 2 semanas con datos, o:
      pct: cambio del índice en las últimas 4 semanas (o desde el inicio si
           hay menos historial), weeks: semanas que abarca ese cambio,
      series: [(lunes, índice)] de todas las semanas,
      movers: [{exercise, pct}] ejercicios con dato antes y dentro de la
              ventana, de más subida a más bajada."""
    if rows is None:
        rows = history_rows(user_id)
    by_exercise = defaultdict(list)
    for workout, entry in rows:
        by_exercise[entry.exercise].append((workout, entry))

    weekly = {}  # ejercicio -> {lunes: mejor 1RM de esa semana}
    for exercise, ex_rows in by_exercise.items():
        per_week = {}
        for s in qualifying_sessions(sessions_from_rows(ex_rows)):
            wk = _week_start_local(s["timestamp"])
            per_week[wk] = max(per_week.get(wk, 0), s["best_1rm"])
        if per_week:
            weekly[exercise] = per_week
    if not weekly:
        return None

    first_week = min(min(w) for w in weekly.values())
    current_week = _week_start_local(datetime.now(timezone.utc))
    weeks = []
    wk = first_week
    while wk <= current_week:
        weeks.append(wk)
        wk += timedelta(days=7)
    # Hacen falta 2 semanas CON entrenos: contar la semana en curso vacía
    # pintaba una línea plana ("0 % en 1 semana") con un solo entreno.
    if len({w for per_week in weekly.values() for w in per_week}) < 2:
        return None

    lo, hi = STRENGTH_STEP_CAP
    last_known = {}
    index = 100.0
    series = []
    for wk in weeks:
        ratios = []
        for exercise, per_week in weekly.items():
            if wk in per_week:
                value = per_week[wk]
                if exercise in last_known and last_known[exercise] > 0:
                    ratios.append(min(hi, max(lo, value / last_known[exercise])))
                last_known[exercise] = value
        if ratios:
            index *= math.exp(sum(math.log(r) for r in ratios) / len(ratios))
        series.append((wk, index))

    span = min(STRENGTH_WINDOW_WEEKS, len(series) - 1)
    ref_week, ref_index = series[-1 - span]
    pct = 100 * (series[-1][1] / ref_index - 1)

    movers = []
    for exercise, per_week in weekly.items():
        before = [v for w, v in per_week.items() if w <= ref_week]
        after = [(w, v) for w, v in per_week.items() if w > ref_week]
        if before and after:
            ref_value = per_week[max(w for w in per_week if w <= ref_week)]
            latest = max(after)[1]
            if ref_value > 0:
                movers.append({"exercise": exercise, "pct": 100 * (latest / ref_value - 1)})
    movers.sort(key=lambda m: m["pct"], reverse=True)
    return {"pct": pct, "weeks": span, "series": series, "movers": movers}


# Cálculos sobre TODO el historial, memorizados mientras tus datos no cambien
# (app/datacache.py). Solo en vistas de lectura: tras escribir, la siguiente
# petición ya ve otra versión y recalcula.
class LightWorkout(NamedTuple):
    id: int
    timestamp: datetime
    user_id: int


class LightSet(NamedTuple):
    id: int
    workout_id: int
    exercise: str
    weight: float
    reps: int
    rir: Optional[int]
    rpe: Optional[int]
    set_type: Optional[str]
    completed: bool
    is_pr: bool


def history_rows(user_id):
    """[(entreno, serie)] de TODO el historial en orden cronológico, en filas
    ligeras de solo lectura (sin objetos del ORM, que era lo que más costaba)
    y leídas UNA vez para el perfil de fuerza, el índice y Progreso."""
    def load():
        result = db.session.execute(
            sa.select(Workout.id, Workout.timestamp, Workout.user_id, SetEntry.id.label("set_id"),
                      SetEntry.exercise, SetEntry.weight, SetEntry.reps, SetEntry.rir, SetEntry.rpe,
                      SetEntry.set_type, SetEntry.completed, SetEntry.is_pr)
            .join(SetEntry, SetEntry.workout_id == Workout.id)
            .where(Workout.user_id == user_id)
            .order_by(Workout.timestamp.asc(), SetEntry.id.asc())
        ).all()
        workouts, out = {}, []
        for r in result:
            w = workouts.get(r.id)
            if w is None:
                w = workouts[r.id] = LightWorkout(r.id, r.timestamp, r.user_id)
            out.append((w, LightSet(r.set_id, r.id, r.exercise, r.weight, r.reps, r.rir, r.rpe,
                                    r.set_type, r.completed, r.is_pr)))
        return out
    return datacache.cached("rows", user_id, load)


def cached_profile(user):
    return datacache.cached("profile", user.id, lambda: standards.strength_profile(user, rows=history_rows(user.id)))


def _global_tier(user):
    """Rango global de fuerza (0-8) o None; para ajustar el ritmo de peso."""
    rank = cached_profile(user)["global_rank"]
    return rank["tier"] if rank else None


def cached_strength(user_id):
    return datacache.cached("strength", user_id, lambda: strength_progress(user_id))


def cached_overview(user_id, threshold):
    return datacache.cached("overview", user_id, lambda: progress_overview(user_id, threshold), threshold)


def cached_volume(user_id):
    return datacache.cached("volume", user_id, lambda: volume_mod.weekly_volume(user_id))


def sparkline_points(values, width=100, height=28, pad=2):
    """Puntos "x,y" de un <polyline> SVG para una mini gráfica."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1
    step = (width - 2 * pad) / (len(values) - 1)
    return " ".join(
        f"{pad + i * step:.1f},{height - pad - (v - lo) / rng * (height - 2 * pad):.1f}"
        for i, v in enumerate(values)
    )


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
        qualifying = qualifying_sessions(session_list)
        if not qualifying:
            continue
        catalog = find_catalog_exercise(name)
        muscle_group = None
        if catalog and catalog.primary_muscles:
            for muscle in catalog.primary_muscles.split(", "):
                muscle_group = MUSCLE_GROUP_MAP.get(muscle)
                if muscle_group:
                    break
        recent = qualifying[-current_user.stagnation_threshold :]
        completed_sets = [st for sess in recent for st in sess["sets"] if st.completed]
        rirs = [st.rir for st in completed_sets if st.rir is not None]
        rpes = [st.rpe for st in completed_sets if st.rpe is not None]
        exercises.append(
            {
                "name": name.title(),
                "sessions": n_sessions,
                "best_1rm": round(max(s["best_1rm"] for s in qualifying), 1),
                "stagnation": stagnation,
                "last_trained": to_local(qualifying[-1]["timestamp"]).strftime("%d/%m/%Y"),
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
                "date": to_local(w.timestamp).strftime("%d/%m/%Y"),
                "note": w.note or "Entrenamiento",
                "rating": w.performance_rating,
                "comment": w.performance_comment,
                "volume": round(sum(s.weight * s.reps for s in sets)),
                "duration": w.duration_str(),
            }
        )

    streak = compute_smart_streak(current_user.id, workouts)
    return {
        "total_workouts": len(workouts),
        "streak": streak,
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
        f"Racha actual: {summary['streak']['days']} días entrenados en semanas seguidas cumpliendo "
        f"su mínimo de {summary['streak']['minimum']} días/semana "
        f"(esta semana lleva {summary['streak']['this_week']})",
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
            f"Peso corporal: de {first.weight}kg ({to_local(first.timestamp).strftime('%d/%m/%Y')}) a "
            f"{last.weight}kg ({to_local(last.timestamp).strftime('%d/%m/%Y')}), {delta:+}kg en "
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

    checkins = progression.recent_checkins(current_user.id, days=14)
    if checkins:
        lines.append("")
        lines.append(
            "Check-in de recuperación de los últimos 14 días (valoración SUBJETIVA AUTODECLARADA por el usuario, "
            "no medida; úsala como contexto, no como dato objetivo). Sueño y energía 1-5, agujetas 0-3:"
        )
        for c in checkins:
            lines.append(f"- {c.day.strftime('%d/%m')}: sueño {c.sleep}, energía {c.energy}, agujetas {c.soreness}")

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
            f"de un usuario de una app de gimnasio. Responde en {'inglés' if _english() else 'español'}, con recomendaciones "
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


LOCAL_TZ = ZoneInfo("Europe/Madrid")


def to_local(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def _english():
    """¿Se está mostrando la app en inglés? (formato de números y fechas)."""
    locale = get_locale()
    return locale is not None and locale.language == "en"


def fmt_num(value, decimals=1):
    """Número en formato español para mostrar: coma decimal, punto de miles
    y sin ceros sobrantes (82.5 -> "82,5", 100.0 -> "100", 1200 -> "1.200").
    Filtro Jinja `num`. Solo para texto: los <input> siguen usando punto."""
    if value is None:
        return "—"
    v = round(float(value), decimals)
    sign = "-" if v < 0 else ""
    v = abs(v)
    whole = int(v)
    thousands, point = (",", ".") if _english() else (".", ",")
    text = f"{whole:,}".replace(",", thousands)
    if decimals:
        frac = f"{v - whole:.{decimals}f}"[2:].rstrip("0")
        if frac:
            text += point + frac
    return sign + text


def relative_day(dt):
    """"hoy" / "ayer" / "hace 3 días" / "hace 2 semanas" / "12/08" (hora de
    Madrid). Filtro Jinja `relative_day`."""
    if dt is None:
        return "—"
    local = to_local(dt).date()
    days = (to_local(datetime.now(timezone.utc)).date() - local).days
    if days <= 0:
        return gettext("hoy")
    if days == 1:
        return gettext("ayer")
    if days < 14:
        return gettext("hace %(n)s días", n=days)
    if days < 60:
        return gettext("hace %(n)s semanas", n=days // 7)
    return local.strftime("%m/%d/%Y" if _english() else "%d/%m/%Y")


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


def _alias_user_id():
    """Usuario cuyos alias aplican en esta petición (None fuera de una
    petición autenticada: scripts, comandos)."""
    from flask import has_request_context

    if has_request_context() and current_user.is_authenticated:
        return current_user.id
    return None


def find_catalog_exercise(name, use_alias=True):
    """Ejercicio del catálogo cuyo nombre (inglés o español) coincide con
    `name` ignorando mayúsculas y acentos. Una sola consulta indexada sobre
    name_normalized/name_es_normalized (antes eran dos: un ILIKE exacto que
    esta ya cubre). Memorizada por petición en flask.g: una misma página
    preguntaba por el mismo ejercicio hasta 24 veces (imagen, mapa
    muscular...), y cada consulta es un viaje a Neon en producción.
    Cuidado: quien modifique el catálogo debe llamar a
    _clear_catalog_cache() (ver api_create_exercise y la traducción)."""
    if not name:
        return None
    target = _strip_accents(name.strip())
    cache = g.setdefault("_catalog_cache", {})
    if target not in cache:
        cache[target] = db.session.scalar(
            sa.select(Exercise)
            .where(sa.or_(Exercise.name_normalized == target, Exercise.name_es_normalized == target))
            .limit(1)
        )
    if cache[target] is not None or not use_alias:
        return cache[target]
    # Sin coincidencia exacta: ¿lo asignó el usuario a un ejercicio del
    # catálogo? (ExerciseAlias). Nunca para renombrar, solo para saber
    # músculos, imagen, etc.
    uid = _alias_user_id()
    if uid is None:
        return None
    aliases = g.setdefault("_alias_cache", {})
    if target not in aliases:
        aliases[target] = db.session.scalar(
            sa.select(Exercise)
            .join(ExerciseAlias, ExerciseAlias.exercise_id == Exercise.id)
            .where(ExerciseAlias.user_id == uid, ExerciseAlias.name == target)
        )
    return aliases[target]


def _clear_catalog_cache():
    g.pop("_catalog_cache", None)
    g.pop("_alias_cache", None)


def prefetch_catalog_exercises(names):
    """Rellena de golpe la caché de find_catalog_exercise() para varios
    nombres: UNA consulta en vez de una por ejercicio (la mayoría de los
    ejercicios propios no están en el catálogo y cada "no está" también
    costaba una consulta)."""
    cache = g.setdefault("_catalog_cache", {})
    targets = {_strip_accents(n.strip()) for n in names if n} - set(cache)
    if not targets:
        return
    for ex in db.session.scalars(
        sa.select(Exercise).where(
            sa.or_(Exercise.name_normalized.in_(targets), Exercise.name_es_normalized.in_(targets))
        )
    ):
        for key in (ex.name_normalized, ex.name_es_normalized):
            if key in targets and key not in cache:
                cache[key] = ex
    for t in targets:
        cache.setdefault(t, None)
    # Y los alias del usuario para lo que no está en el catálogo (otra consulta).
    uid = _alias_user_id()
    missing = {t for t in targets if cache[t] is None}
    if uid is not None and missing:
        aliases = g.setdefault("_alias_cache", {})
        for alias, ex in db.session.execute(
            sa.select(ExerciseAlias.name, Exercise)
            .join(Exercise, Exercise.id == ExerciseAlias.exercise_id)
            .where(ExerciseAlias.user_id == uid, ExerciseAlias.name.in_(missing))
        ):
            aliases[alias] = ex
        for t in missing:
            aliases.setdefault(t, None)


def catalog_display_name(exercise):
    """Nombre del ejercicio del catálogo en el idioma de la app: en inglés el
    original del dataset; en español el traducido si lo hay. Los dos casan
    con find_catalog_exercise, así que músculos, imagen y rango funcionan
    con cualquiera de ellos."""
    if _english():
        return exercise.name
    return exercise.name_es or exercise.name


def canonicalize_exercise_name(name):
    """Si `name` coincide (ignorando acentos/mayúsculas) con el catálogo, devuelve la
    forma canónica del catálogo en vez del texto tal cual lo escribió el usuario."""
    name = name.strip().lower()
    match = find_catalog_exercise(name, use_alias=False)
    if match:
        return catalog_display_name(match).strip().lower()
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
# Paleta "de firma" (un color distinto por grupo) que había antes del morado
# único -- restaurada a modo de comparación (a petición explícita), con la
# curva actual (suelo 15% + exponente 2) en vez de la curva vieja que traía,
# para no mezclar dos variables distintas en la comparación.
_MUSCLE_SIGNATURE_RGB = {
    "trapecios": (253, 253, 18),
    "hombros": (174, 18, 253),
    "pecho": (96, 253, 18),
    "biceps": (18, 174, 253),
    "antebrazos": (253, 96, 18),
    "cuello": (18, 253, 213),
    "dorsales": (57, 18, 253),
    "espalda_baja": (253, 135, 18),
    "triceps": (18, 253, 76),
    "abdomen": (253, 18, 253),
    "cuadriceps": (135, 253, 18),
    "aductores": (96, 18, 253),
    "gluteos": (18, 253, 174),
    "isquiotibiales": (253, 18, 96),
    "pantorrillas": (18, 135, 253),
}


def _interpolate_muscle_color(group, t):
    t = max(0.0, min(1.0, t))
    # t es relativo al músculo MÁS trabajado de la ventana, no a un umbral
    # absoluto -- y en una rutina bien repartida (push/pull/legs, no solo
    # "brazo") eso significa que la mayoría de grupos caen razonablemente
    # cerca del máximo, no solo el propio grupo estrella. Verificado con una
    # rutina de ejemplo de 3 días: con suelo+lineal, 8 de 10 grupos
    # entrenados quedaban por encima del 50% de mezcla -- de ahí la queja de
    # "parece que todo está fatigado". Cambiar el suelo no lo arregla (el
    # problema está en el tramo medio-alto, no en el bajo); hace falta una
    # curva más cóncava (exponente > 1) que separe más ese tramo. Suelo
    # pequeño (15%, solo para no confundir "casi nada" con "nada") + cuadrado
    # en el resto: t=0.15->~17%, t=0.4->~29%, t=0.6->~46%, t=0.85->~76%,
    # t=1->100% -- ahora el grupo estrella destaca claramente por encima de
    # los que solo reciben trabajo secundario.
    if t > 0:
        t = 0.15 + 0.85 * (t ** 2)
    target = _MUSCLE_SIGNATURE_RGB[group]
    r = round(_MUSCLE_NEUTRAL_RGB[0] + (target[0] - _MUSCLE_NEUTRAL_RGB[0]) * t)
    g = round(_MUSCLE_NEUTRAL_RGB[1] + (target[1] - _MUSCLE_NEUTRAL_RGB[1]) * t)
    b = round(_MUSCLE_NEUTRAL_RGB[2] + (target[2] - _MUSCLE_NEUTRAL_RGB[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


@functools.lru_cache(maxsize=4)
def muscle_svg_markup(sex):
    """Interior de los dos <svg> del mapa muscular (frente, espalda), ya
    escapado y memorizado: los ~160 trazos (~40 KB) nunca cambian -- los
    colores van aparte en el <style> de la plantilla por clase mm-<grupo>.
    Antes se regeneraban y escapaban en cada visita a Inicio."""
    parts = build_muscle_svg_parts(sex)
    out = {}
    for side in ("front", "back"):
        out[side] = Markup("".join(
            f'<path class="mm-{part["group"] or "neutral"}" d="{escape(d)}"/>'
            for part in parts[side]
            for d in part["paths"]
        ))
    return out


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
    prefetch_catalog_exercises({e.exercise for e in entries})
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
        if catalog.secondary_muscles:
            for muscle in catalog.secondary_muscles.split(", "):
                group = MUSCLE_GROUP_MAP.get(muscle)
                if group:
                    # Un músculo secundario recibe estímulo real pero no es el
                    # motor principal del movimiento -- se cuenta a una
                    # fracción del volumen (40%) en vez de a la par que los
                    # primarios, para no igualar "protagonista" con "asiste".
                    volumes[group] += stress * 0.4
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
