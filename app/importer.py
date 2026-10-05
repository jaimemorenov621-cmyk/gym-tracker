"""Importar el historial de otras apps (CSV de Hevy y de Strong).

Flujo (rutas /importar en routes.py):
  1. parse_csv(): lee el CSV y lo convierte en entrenos con sus series.
     Se guarda como borrador (ImportDraft) para no tener que volver a subirlo.
  2. El usuario elige a qué ejercicio corresponde cada nombre: uno suyo o
     uno del catálogo (suggest_names() propone uno); nunca se crea uno nuevo
     con el nombre de la otra app. Lo que quede sin elegir no se importa.
  3. apply_import(): crea los entrenos (saltándose los que ya existen a la
     misma hora, así reimportar no duplica), las series, las notas de
     ejercicio que no tuviera, las medallas de récord y los logros.

Detalles de formato:
  - Hevy: fechas "19 ago 2026, 14:20" (mes en el idioma del móvil) o ISO;
    weight_kg o weight_lbs; RPE con medios puntos; set_type normal /
    warmup / failure / dropset.
  - Strong: "Date","Workout Name","Duration","Exercise Name","Set Order",
    "Weight","Reps",...,"RPE" (unidad la que tuviera la app: se elige al
    subir). Set Order "W" = calentamiento, "D" = dropset, "F" = fallo.
  - Las horas se interpretan en hora de Madrid, como el resto de la app.
  - El esfuerzo se guarda en la escala del usuario: RIR = 10 - RPE
    (redondeado) o RPE redondeado. Se pierde el medio punto.
  - Sin valoración: los entrenos importados quedan terminados por su hora
    de fin, sin nota de rendimiento (la app no se la inventa).
"""
import csv
import io
import json
import math
import re
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from flask_babel import gettext

from app import db
from app.models import ExerciseNote, SetEntry, Workout

MADRID = ZoneInfo("Europe/Madrid")
LB = 0.45359237
MAX_BYTES = 10 * 1024 * 1024
MONTHS = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "ago": 8, "aug": 8, "sep": 9, "sept": 9, "set": 9, "oct": 10, "out": 10, "nov": 11, "dic": 12, "dec": 12, "dez": 12,
}
_DATE_RE = re.compile(r"^\s*(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\.?\s+(\d{4}),?\s+(\d{1,2}):(\d{2})")
SET_TYPES = {"warmup": "calentamiento", "warm-up": "calentamiento", "w": "calentamiento",
             "failure": "fallo", "f": "fallo", "dropset": "dropset", "drop": "dropset", "d": "dropset"}


class ImportError_(ValueError):
    """Archivo que no se puede importar (mensaje para el usuario)."""


def parse_time(text):
    """Hora local (Madrid) del CSV -> datetime UTC sin zona, o None."""
    text = (text or "").strip()
    if not text:
        return None
    m = _DATE_RE.match(text)
    local = None
    if m:
        month = MONTHS.get(m.group(2).lower()[:4]) or MONTHS.get(m.group(2).lower()[:3])
        if month:
            local = datetime(int(m.group(3)), month, int(m.group(1)), int(m.group(4)), int(m.group(5)))
    if local is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M"):
            try:
                local = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
    if local is None:
        return None
    return local.replace(tzinfo=MADRID).astimezone(timezone.utc).replace(tzinfo=None)


def _num(text):
    text = (text or "").strip().replace(",", ".")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _duration(text):
    """Duración de Strong ("1h 5m", "45m", "3600") -> segundos."""
    text = (text or "").strip()
    if text.isdigit():
        return int(text)
    h = re.search(r"(\d+)\s*h", text)
    m = re.search(r"(\d+)\s*m", text)
    return (int(h.group(1)) * 3600 if h else 0) + (int(m.group(1)) * 60 if m else 0)


def parse_csv(raw, unit="kg"):
    """Bytes del CSV -> borrador {source, workouts: [...], exercises: {nombre: nº series}, notes}."""
    if len(raw) > MAX_BYTES:
        raise ImportError_(gettext("El archivo es demasiado grande (máximo 10 MB)."))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows:
        raise ImportError_(gettext("El archivo está vacío."))
    cols = {c.strip().lower(): c for c in rows[0].keys() if c}

    if "exercise_title" in cols and "start_time" in cols:
        source = "hevy"
        weight_col = cols.get("weight_kg") or cols.get("weight_lbs")
        factor = LB if (weight_col and weight_col.lower() == "weight_lbs") else 1.0

        def read(r):
            return {"key": r[cols["start_time"]], "title": r.get(cols.get("title", ""), ""),
                    "start": parse_time(r[cols["start_time"]]), "end": parse_time(r.get(cols.get("end_time", ""), "")),
                    "description": r.get(cols.get("description", ""), ""), "exercise": r[cols["exercise_title"]],
                    "notes": r.get(cols.get("exercise_notes", ""), ""), "set_type": r.get(cols.get("set_type", ""), ""),
                    "weight": (_num(r.get(weight_col, "")) or 0.0) * factor, "reps": _num(r.get(cols.get("reps", ""), "")),
                    "rpe": _num(r.get(cols.get("rpe", ""), ""))}
    elif "exercise name" in cols and "date" in cols:
        source = "strong"
        factor = LB if unit == "lb" else 1.0

        def read(r):
            start = parse_time(r[cols["date"]])
            secs = _duration(r.get(cols.get("duration", ""), ""))
            order = (r.get(cols.get("set order", ""), "") or "").strip().lower()
            return {"key": r[cols["date"]], "title": r.get(cols.get("workout name", ""), ""), "start": start,
                    "end": start + timedelta(seconds=secs) if start and secs else None,
                    "description": r.get(cols.get("workout notes", ""), ""), "exercise": r[cols["exercise name"]],
                    "notes": r.get(cols.get("notes", ""), ""), "set_type": order if order in SET_TYPES else "",
                    "weight": (_num(r.get(cols.get("weight", ""), "")) or 0.0) * factor,
                    "reps": _num(r.get(cols.get("reps", ""), "")), "rpe": _num(r.get(cols.get("rpe", ""), ""))}
    else:
        raise ImportError_(gettext("No reconozco el formato. Sube el CSV que exporta Hevy (Export Workouts) o Strong."))

    workouts = OrderedDict()
    exercises = Counter()
    notes = {}
    skipped = 0
    for r in rows:
        item = read(r)
        name = (item["exercise"] or "").strip()
        if not item["start"] or not name or not item["reps"] or item["reps"] <= 0:
            skipped += 1  # cardio por tiempo/distancia, filas vacías
            continue
        w = workouts.setdefault(item["key"], {
            "title": (item["title"] or "").strip()[:64], "start": item["start"].isoformat(),
            "end": item["end"].isoformat() if item["end"] and item["end"] > item["start"] else None,
            "description": (item["description"] or "").strip()[:255], "sets": []})
        w["sets"].append({"exercise": name, "weight": round(max(item["weight"], 0.0), 2), "reps": int(item["reps"]),
                          "rpe": item["rpe"], "set_type": SET_TYPES.get((item["set_type"] or "").strip().lower(), "normal")})
        exercises[name] += 1
        note = (item["notes"] or "").replace("\\n", "\n").strip()
        if note:
            notes[name] = note  # el CSV va de más antiguo a más reciente o al revés: vale cualquiera
    if not workouts:
        raise ImportError_(gettext("No he encontrado series con repeticiones en el archivo."))
    ordered = sorted(workouts.values(), key=lambda w: w["start"])
    return {"source": source, "workouts": ordered, "exercises": dict(exercises.most_common()),
            "notes": notes, "skipped_rows": skipped}


# ------------------------------------------------------------ nombres


def _key(name):
    import unicodedata
    plain = "".join(c for c in unicodedata.normalize("NFD", name.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", plain).strip()


# Palabras que no cambian el ejercicio ("press de banca (barra)" = "press de
# banca agarre medio"); todo lo demás (mancuerna, inclinado, cerrado, smith...)
# sí lo distingue, así que tiene que coincidir.
_FILLER = {"de", "la", "el", "los", "las", "con", "en", "a", "al", "del", "y", "the", "with", "on",
           "barra", "barbell", "agarre", "medio", "media", "grip", "medium", "normal", "standard"}


def _core(name):
    """Palabras que definen el ejercicio, sin acentos, relleno ni plurales."""
    # "Dominada (Con Peso Añadido)" = "dominadas": en la app el lastre ya va en el peso.
    plain = re.sub(r"\(?(con peso anadido|con lastre|weighted|with added weight)\)?", " ", _key(name))
    words = re.findall(r"[a-z0-9]+", plain)
    return frozenset(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in _FILLER)


def suggest_names(user_id, names):
    """Propuesta para cada nombre del CSV, SOLO entre ejercicios que ya
    existen: primero uno tuyo con las mismas palabras clave (sin mirar
    acentos, mayúsculas, plurales, "(Barra)", "agarre medio"...; si hay
    varios, el que más usas) y si no, uno del catálogo. Si no hay ninguno,
    "" (queda sin elegir y no se importa hasta que elijas uno): la
    importación nunca crea ejercicios nuevos con el nombre de la otra app.

    Devuelve (propuestas, [(nombre tuyo, series)], nombres válidos)."""
    from app.models import Exercise
    from app.routes import catalog_display_name

    own_counts = db.session.execute(
        sa.select(SetEntry.exercise, sa.func.count()).join(Workout, Workout.id == SetEntry.workout_id)
        .where(Workout.user_id == user_id).group_by(SetEntry.exercise)).all()
    own_by_core = {}
    for ex, n in sorted(own_counts, key=lambda r: -r[1]):
        own_by_core.setdefault(_core(ex), ex)  # el más usado primero
    catalog_by_core = {}
    valid = {ex for ex, _ in own_counts}
    for e in db.session.scalars(sa.select(Exercise)):
        display = catalog_display_name(e).strip().lower()
        valid.update(n.strip().lower() for n in (e.name, e.name_es) if n)
        for n in (catalog_display_name(e), e.name_es, e.name):  # el nombre que se ve, primero
            if n:
                catalog_by_core.setdefault(_core(n), display)
    out = {name: own_by_core.get(_core(name)) or catalog_by_core.get(_core(name)) or "" for name in names}
    return out, sorted(own_counts, key=lambda r: (-r[1], r[0])), valid


# ------------------------------------------------------------ importar
def _local_day(utc_naive):
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(MADRID).date()


def overlap(user_id, draft):
    """Cuántos entrenos del archivo caen en días en los que ya entrenaste en Gyre."""
    days = {_local_day(ts) for ts in db.session.scalars(sa.select(Workout.timestamp).where(Workout.user_id == user_id))}
    return sum(1 for w in draft["workouts"] if _local_day(datetime.fromisoformat(w["start"])) in days)


def _effort(rpe, scale):
    if rpe is None:
        return None, None
    rpe = min(max(rpe, 0.0), 10.0)
    if scale == "rir":
        return int(math.floor(10 - rpe + 0.5)), None
    return None, int(math.floor(rpe + 0.5))


def apply_import(user, draft, mapping, skip_same_day=True):
    """Crea los entrenos del borrador con los nombres elegidos (mapping:
    {nombre CSV: nombre en Gyre o "" para no importarlo}). Devuelve
    {"workouts", "sets", "duplicates"}. skip_same_day: no importar los días
    (hora de Madrid) en los que ya hay un entreno en Gyre, por si se apuntó en
    las dos apps a la vez."""
    from app import achievements, progression
    from app.routes import apply_pr_flags_for_session, get_exercise_sessions

    existing = db.session.scalars(sa.select(Workout.timestamp).where(Workout.user_id == user.id)).all()
    existing_minutes = {int(ts.timestamp() // 60) for ts in existing}
    existing_days = {_local_day(ts) for ts in existing}
    created_sets, workouts, duplicates, names_used = [], 0, 0, set()
    for item in draft["workouts"]:
        start = datetime.fromisoformat(item["start"])
        minute = int(start.timestamp() // 60)
        if any(m in existing_minutes for m in range(minute - 2, minute + 3)) or (
                skip_same_day and _local_day(start) in existing_days):
            duplicates += 1
            continue
        sets = [s for s in item["sets"] if (mapping.get(s["exercise"]) or "").strip()]
        if not sets:
            continue
        end = datetime.fromisoformat(item["end"]) if item.get("end") else start + timedelta(minutes=60)
        w = Workout(user_id=user.id, timestamp=start, ended_at=end, note=item["title"] or None,
                    performance_comment=item["description"] or None)
        db.session.add(w)
        db.session.flush()
        workouts += 1
        existing_minutes.add(minute)
        for s in sets:
            name = mapping[s["exercise"]].strip().lower()[:64]
            names_used.add(name)
            rir, rpe = _effort(s["rpe"], user.effort_scale)
            created_sets.append({"workout_id": w.id, "exercise": name, "weight": s["weight"], "reps": s["reps"],
                                 "rir": rir, "rpe": rpe, "set_type": s["set_type"], "completed": True, "is_pr": False})
    if created_sets:
        # De golpe (miles de series): la caché de XP se invalida a mano solo
        # para este usuario, en la misma transacción.
        db.session.execute(sa.insert(SetEntry).execution_options(xp_irrelevant=True), created_sets)
        progression._bump_users(db.session.connection(), {user.id})
    # Notas de ejercicio de la otra app: se AÑADEN debajo de las que ya
    # tuvieras (nunca se borra nada) y sin repetir líneas que ya estén.
    notes = {n.exercise: n for n in db.session.scalars(sa.select(ExerciseNote).where(ExerciseNote.user_id == user.id))}
    for csv_name, note in draft.get("notes", {}).items():
        name = (mapping.get(csv_name) or "").strip().lower()[:64]
        if not name or name not in names_used:
            continue
        current = notes.get(name)
        if current is None:
            current = notes[name] = ExerciseNote(user_id=user.id, exercise=name, notes="")
            db.session.add(current)
        lines = [line for line in (current.notes or "").split("\n") if line.strip()]
        new = [line for line in note.split("\n") if line.strip() and line.strip() not in {x.strip() for x in lines}]
        if new:
            current.notes = "\n".join(lines + new)[:1000]
    db.session.commit()

    for name in names_used:  # medallas de récord, con el mismo código que la app
        for session in get_exercise_sessions(name, user_id=user.id)[0]:
            apply_pr_flags_for_session(session)
    db.session.commit()
    achievements.evaluate(user)
    return {"workouts": workouts, "sets": len(created_sets), "duplicates": duplicates}


def draft_json(draft):
    return json.dumps(draft, ensure_ascii=False)
