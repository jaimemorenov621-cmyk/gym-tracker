"""Registro de errores del servidor, visible para el admin en /landing/stats.

Sin acceso a los registros de Render, un "Internal Server Error" no dejaba
rastro que se pudiera ver desde la app. Cada excepción no controlada de una
petición se guarda (método, ruta, usuario, traza) y se conservan las 50 más
recientes. Se escribe con una conexión propia: la sesión de la petición que
falló puede haber quedado inservible.
"""
import traceback

import sqlalchemy as sa
from flask import got_request_exception, request
from flask_login import current_user

from app import app, db
from app.models import ErrorLog

KEEP = 50


def _record(sender, exception, **extra):
    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
    except Exception:
        user_id = None
    try:
        with db.engine.begin() as conn:
            conn.execute(sa.insert(ErrorLog).values(
                method=request.method[:8],
                path=request.path[:255],
                user_id=user_id,
                error=f"{type(exception).__name__}: {exception}"[:255],
                traceback="".join(traceback.format_exception(exception))[-20000:],
            ))
            cutoff = conn.execute(
                sa.select(ErrorLog.id).order_by(ErrorLog.id.desc()).offset(KEEP - 1).limit(1)
            ).scalar()
            if cutoff is not None:
                conn.execute(sa.delete(ErrorLog).where(ErrorLog.id < cutoff))
    except Exception:  # registrar el error nunca debe causar otro
        app.logger.exception("No se pudo guardar el error en ErrorLog")


got_request_exception.connect(_record, app)


def recent(limit=10):
    return db.session.scalars(sa.select(ErrorLog).order_by(ErrorLog.id.desc()).limit(limit)).all()
