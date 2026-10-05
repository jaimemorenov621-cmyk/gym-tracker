"""Amigos, tarjeta de atleta y rankings entre amigos.

- Amistad: se pide con el código de amigo (o el enlace de invitación) y solo
  cuenta cuando el otro la acepta. Máximo MAX_FRIENDS.
- Tarjeta de atleta (AthleteCard): qué ven tus amigos. Todo sale de los datos
  de la app (rango, nivel, racha, constancia, récords y logros elegidos); el
  peso corporal va oculto por defecto. Nadie que no sea tu amigo la ve.
- Rankings: rango global y por básico con las puntuaciones "creíbles" de
  app/strength_standards.py (justas entre pesos y sexos distintos), y
  constancia (días entrenados en 4 semanas).
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask_babel import gettext

from app import db
from app.models import AthleteCard, Friendship, SetEntry, User, UserAchievement, Workout

MAX_FRIENDS = 50
MAX_FEATURED_LIFTS = 3
MAX_FEATURED_ACHIEVEMENTS = 6
CONSISTENCY_DAYS = 28
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I


# ------------------------------------------------------------ códigos
def friend_code(user):
    """Código de amigo del usuario (se crea la primera vez)."""
    if not user.friend_code:
        while True:
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
            if db.session.scalar(sa.select(User.id).where(User.friend_code == code)) is None:
                break
        user.friend_code = code
        db.session.commit()
    return user.friend_code


def user_by_code(code):
    code = (code or "").strip().upper().replace(" ", "").replace("-", "")
    return db.session.scalar(sa.select(User).where(User.friend_code == code)) if code else None


# ------------------------------------------------------------ amistades
def _pair(a_id, b_id):
    return db.session.scalar(sa.select(Friendship).where(
        sa.or_(sa.and_(Friendship.requester_id == a_id, Friendship.addressee_id == b_id),
               sa.and_(Friendship.requester_id == b_id, Friendship.addressee_id == a_id))))


def friend_ids(user_id):
    rows = db.session.execute(sa.select(Friendship.requester_id, Friendship.addressee_id).where(
        Friendship.status == "accepted",
        sa.or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id))).all()
    return [b if a == user_id else a for a, b in rows]


def are_friends(a_id, b_id):
    f = _pair(a_id, b_id)
    return f is not None and f.status == "accepted"


def send_request(user, other):
    """Pide amistad a `other`. Devuelve el mensaje para el usuario."""
    if other is None:
        return gettext("No hay nadie con ese código.")
    if other.id == user.id:
        return gettext("Ese es tu propio código.")
    existing = _pair(user.id, other.id)
    if existing is not None:
        if existing.status == "accepted":
            return gettext("%(name)s ya es tu amigo.", name=other.username)
        if existing.requester_id == user.id:
            return gettext("Ya le enviaste una solicitud a %(name)s.", name=other.username)
        return accept(user, existing.id)  # él ya te la había pedido: queda aceptada
    if len(friend_ids(user.id)) >= MAX_FRIENDS:
        return gettext("Has llegado al máximo de %(n)s amigos.", n=MAX_FRIENDS)
    db.session.add(Friendship(requester_id=user.id, addressee_id=other.id))
    db.session.commit()
    return gettext("Solicitud enviada a %(name)s. Cuando la acepte, os veréis en los rankings.", name=other.username)


def accept(user, friendship_id):
    f = db.session.get(Friendship, friendship_id)
    if f is None or f.addressee_id != user.id or f.status != "pending":
        return gettext("Esa solicitud ya no existe.")
    if len(friend_ids(user.id)) >= MAX_FRIENDS:
        return gettext("Has llegado al máximo de %(n)s amigos.", n=MAX_FRIENDS)
    f.status = "accepted"
    f.accepted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.commit()
    other = db.session.get(User, f.requester_id)
    return gettext("Ahora tú y %(name)s sois amigos.", name=other.username)


def remove(user, friendship_id):
    """Rechazar, cancelar o dejar de ser amigos (cualquiera de los dos)."""
    f = db.session.get(Friendship, friendship_id)
    if f is None or user.id not in (f.requester_id, f.addressee_id):
        return False
    db.session.delete(f)
    db.session.commit()
    return True


def requests_for(user_id):
    """(recibidas, enviadas) pendientes, con el otro usuario."""
    incoming = db.session.execute(sa.select(Friendship, User).join(User, User.id == Friendship.requester_id).where(
        Friendship.addressee_id == user_id, Friendship.status == "pending").order_by(Friendship.created_at)).all()
    outgoing = db.session.execute(sa.select(Friendship, User).join(User, User.id == Friendship.addressee_id).where(
        Friendship.requester_id == user_id, Friendship.status == "pending").order_by(Friendship.created_at)).all()
    return incoming, outgoing


def friends_with_links(user_id):
    """[(Friendship, User)] de amigos aceptados, por nombre."""
    rows = db.session.execute(sa.select(Friendship).where(
        Friendship.status == "accepted",
        sa.or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id))).scalars().all()
    out = []
    for f in rows:
        other = db.session.get(User, f.addressee_id if f.requester_id == user_id else f.requester_id)
        out.append((f, other))
    return sorted(out, key=lambda x: x[1].username.lower())


# ------------------------------------------------------------ tarjeta
def card_for(user_id):
    """Ajustes de la tarjeta (los de por defecto si nunca la editó; sin guardar)."""
    card = db.session.get(AthleteCard, user_id)
    if card is None:
        card = AthleteCard(user_id=user_id, in_rankings=True, show_rank=True, show_level=True, show_streak=True,
                           show_consistency=True, show_kg=True, show_bodyweight=False, show_progress=True,
                           featured_lifts="[]", featured_achievements="[]")
    return card


def featured(card):
    def load(raw):
        try:
            value = json.loads(raw or "[]")
            return [str(v) for v in value] if isinstance(value, list) else []
        except ValueError:
            return []
    return load(card.featured_lifts), load(card.featured_achievements)


def unlocked_codes(user_id):
    return list(db.session.scalars(
        sa.select(UserAchievement.code).where(UserAchievement.user_id == user_id).order_by(UserAchievement.unlocked_at.desc())))


def training_days(user_id, days=CONSISTENCY_DAYS):
    """Días distintos con un entreno terminado y alguna serie hecha, en los
    últimos `days` días (fecha local)."""
    from app.routes import to_local

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    stamps = db.session.scalars(
        sa.select(Workout.timestamp).where(
            Workout.user_id == user_id, Workout.performance_rating.is_not(None), Workout.timestamp >= since,
            sa.exists().where(SetEntry.workout_id == Workout.id, SetEntry.completed.is_(True), SetEntry.reps > 0))
    ).all()
    return len({to_local(ts).date() for ts in stamps})
