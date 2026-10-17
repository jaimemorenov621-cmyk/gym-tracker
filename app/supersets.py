"""Biseries (y triseries, circuitos): ejercicios que se hacen seguidos,
alternando series, y se descansa al terminar la ronda.

Se guardan como un nº de grupo por ejercicio: en las rutinas en
RoutineExercise.superset_group y en los entrenos en Workout.supersets (JSON
{ejercicio: grupo}, como exercise_order). Lo de aquí es puro (listas y
dicts) para poder usarlo con los dos y probarlo sin base de datos.

Reglas:
  - Un grupo necesita 2 o más ejercicios; uno solo no es biserie.
  - Los de un grupo se muestran SIEMPRE juntos, en el sitio del primero.
  - "Unir con el siguiente" junta un ejercicio con el que va detrás (si uno
    ya estaba en un grupo, el otro entra en él; si estaban en dos, se
    funden). "Separar" corta el grupo entre esos dos.
  - Los grupos se numeran 1, 2, 3... por orden de aparición (A, B, C...).
"""
import json


def normalize(order, groups):
    """(orden, grupos) limpios: grupos de 2+ ejercicios presentes en `order`,
    numerados 1..n por aparición, y sus miembros seguidos en el sitio del
    primero. `groups` es {clave: grupo}; las claves sin grupo no aparecen."""
    members = {}
    for key in order:
        gid = groups.get(key)
        if gid is not None:
            members.setdefault(gid, []).append(key)
    valid = {gid: keys for gid, keys in members.items() if len(keys) >= 2}
    new_order, new_groups, placed = [], {}, set()
    for key in order:
        if key in placed:
            continue
        gid = groups.get(key)
        block = valid.get(gid, [key])
        number = len({g for g in new_groups.values()}) + 1 if len(block) >= 2 else None
        for k in block:
            new_order.append(k)
            placed.add(k)
            if number is not None:
                new_groups[k] = number
    return new_order, new_groups


def linked_with_next(order, groups, key):
    """¿`key` y el que va detrás están en la misma biserie?"""
    i = order.index(key)
    return i + 1 < len(order) and groups.get(key) is not None and groups.get(key) == groups.get(order[i + 1])


def toggle_with_next(order, groups, key):
    """Une `key` con el siguiente o, si ya lo estaban, los separa.
    Devuelve (orden, grupos) normalizados. Sin siguiente, no cambia nada."""
    order, groups = normalize(order, groups)
    i = order.index(key)
    if i + 1 >= len(order):
        return order, groups
    nxt = order[i + 1]
    groups = dict(groups)
    if linked_with_next(order, groups, key):
        # Separar: los que van detrás de `key` en su grupo pasan a uno nuevo.
        gid = groups[key]
        fresh = max(groups.values()) + 1
        block = [k for k in order if groups.get(k) == gid]
        for k in block[block.index(nxt):]:
            groups[k] = fresh
    else:
        a, b = groups.get(key), groups.get(nxt)
        target = a if a is not None else (b if b is not None else max(groups.values(), default=0) + 1)
        for k in order:
            if k in (key, nxt) or (groups.get(k) is not None and groups.get(k) in (a, b)):
                groups[k] = target
    return normalize(order, groups)


def label(size):
    """Nombre según cuántos ejercicios tiene el grupo."""
    from flask_babel import gettext

    if size == 2:
        return gettext("Biserie")
    if size == 3:
        return gettext("Triserie")
    return gettext("Circuito")


def letter(gid):
    return chr(ord("A") + (gid - 1) % 26)


def display_info(order, groups):
    """{clave: {"gid", "letter", "label", "pos", "size", "first", "last",
    "linked_next"}} para pintar las tarjetas."""
    sizes = {}
    for key in order:
        if groups.get(key) is not None:
            sizes[groups[key]] = sizes.get(groups[key], 0) + 1
    info, seen = {}, {}
    for key in order:
        gid = groups.get(key)
        if gid is None:
            continue
        seen[gid] = seen.get(gid, 0) + 1
        info[key] = {
            "gid": gid, "letter": letter(gid), "label": label(sizes[gid]),
            "pos": seen[gid], "size": sizes[gid],
            "first": seen[gid] == 1, "last": seen[gid] == sizes[gid],
            "linked_next": linked_with_next(order, groups, key),
        }
    return info


# ------------------------------------------------------------- tiempos
DEFAULT_TRANSITION = 40     # s para cambiar de ejercicio dentro de la ronda
MAX_TRANSITION = 180
MAX_REST = 900


def group_timers(order, groups, timers):
    """{grupo: (transición, descanso)} con el primer valor puesto en
    cualquiera de sus ejercicios (None = sin elegir)."""
    out = {}
    for key in order:
        gid = groups.get(key)
        if gid is None:
            continue
        t, r = (timers.get(key) or (None, None))
        cur = out.get(gid, (None, None))
        out[gid] = (cur[0] if cur[0] is not None else t, cur[1] if cur[1] is not None else r)
    return out


def clean_seconds(value, maximum):
    """Entero 0..maximum, o None si no es un número."""
    try:
        return max(0, min(maximum, int(value)))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- entrenos
def load_timers(workout):
    """{ejercicio: [transición, descanso]} de un Workout."""
    try:
        data = json.loads(workout.superset_timers) if workout.superset_timers else {}
    except (ValueError, TypeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, list) and len(v) == 2} if isinstance(data, dict) else {}


def save_timers(workout, timers):
    workout.superset_timers = json.dumps(timers) if timers else None


def load(workout):
    """{ejercicio: grupo} de un Workout (vacío si no hay o está roto)."""
    try:
        data = json.loads(workout.supersets) if workout.supersets else {}
    except (ValueError, TypeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, int)} if isinstance(data, dict) else {}


def save(workout, groups):
    workout.supersets = json.dumps(groups) if groups else None


def rename(workout, old, new):
    """Tras cambiar el nombre de un ejercicio en el entreno. Si el nuevo ya
    estaba (fusión), conserva el grupo del viejo si lo tenía."""
    groups = load(workout)
    if old in groups:
        groups[new] = groups.pop(old)
        save(workout, groups)
    timers = load_timers(workout)
    if old in timers:
        timers[new] = timers.pop(old)
        save_timers(workout, timers)


def remove(workout, name):
    groups = load(workout)
    if name in groups:
        groups.pop(name)
        _, groups = normalize(list(groups), groups)
        save(workout, groups)
    timers = load_timers(workout)
    if name in timers:
        timers.pop(name)
        save_timers(workout, timers)
