"""Avisos por email de los mensajes de Contacto (Configuración → Contacto).

Render, en el plan gratuito, BLOQUEA el correo saliente por SMTP (puertos 25,
465 y 587, desde septiembre de 2025), así que el envío va por la API web de
Brevo (HTTPS, gratis hasta 300 correos al día). Variables de entorno:
  BREVO_API_KEY      clave de API de Brevo (brevo.com → SMTP y API → Claves API)
  MAIL_USERNAME      remitente: el Gmail de la app, verificado como remitente en Brevo
  MAIL_TO            a quién avisar (opcional; por defecto, MAIL_USERNAME)
Sin BREVO_API_KEY pero con MAIL_APP_PASSWORD se intenta por SMTP de Gmail
(solo funciona en planes de pago o en local). Sin nada, no se envía y los
mensajes se siguen viendo en /landing/stats.

El aviso lleva Reply-To con el email del usuario: al pulsar "Responder" en
Gmail, la respuesta le llega directamente a él. Se envía en segundo plano
para no retrasar la página. El resultado del último intento queda en
LAST_STATUS (se enseña en /landing/stats) y los fallos, en el log.
"""
import json
import os
import smtplib
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage

from app import app

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
BREVO_URL = "https://api.brevo.com/v3/smtp/email"
LAST_STATUS = {"at": None, "ok": None, "detail": ""}


def method():
    if not os.environ.get("MAIL_USERNAME"):
        return None
    if os.environ.get("BREVO_API_KEY"):
        return "brevo"
    if os.environ.get("MAIL_APP_PASSWORD"):
        return "smtp"
    return None


def enabled():
    return method() is not None


def build_contact_email(username, user_email, body, stats_url):
    sender = os.environ["MAIL_USERNAME"]
    msg = EmailMessage()
    msg["Subject"] = f"Gyre · mensaje de {username}"
    msg["From"] = f"Gyre <{sender}>"
    msg["To"] = os.environ.get("MAIL_TO") or sender
    msg["Reply-To"] = user_email
    msg.set_content(f"{body}\n\n—\nUsuario: {username} ({user_email})\nTodos los mensajes: {stats_url}\n"
                    "Responde a este correo y le llegará directamente al usuario.")
    return msg


def _record(ok, detail=""):
    LAST_STATUS.update(at=datetime.now(timezone.utc), ok=ok, detail=detail[:300])


def _send_brevo(msg):
    payload = {
        "sender": {"name": "Gyre", "email": os.environ["MAIL_USERNAME"]},
        "to": [{"email": msg["To"]}],
        "replyTo": {"email": msg["Reply-To"]},
        "subject": msg["Subject"],
        "textContent": msg.get_content(),
    }
    request = urllib.request.Request(
        BREVO_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"api-key": os.environ["BREVO_API_KEY"], "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status


def _send_smtp(msg):
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        # Google enseña la contraseña de aplicación en grupos con espacios.
        smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_APP_PASSWORD"].replace(" ", ""))
        smtp.send_message(msg)


def _send(msg, how):
    try:
        if how == "brevo":
            _send_brevo(msg)
        else:
            _send_smtp(msg)
        _record(True, how)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        _record(False, f"Brevo {exc.code}: {detail}")
        app.logger.error("Aviso de contacto por Brevo rechazado: %s %s", exc.code, detail)
    except Exception as exc:
        _record(False, f"{how}: {exc!r}")
        app.logger.exception("No se pudo enviar el aviso de contacto por email")


def notify_contact(username, user_email, body, stats_url):
    """Avisa del mensaje nuevo, en segundo plano. No hace nada sin configurar."""
    how = method()
    if how is None:
        return False
    threading.Thread(target=_send, args=(build_contact_email(username, user_email, body, stats_url), how),
                     daemon=True).start()
    return True
