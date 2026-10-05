"""Avisos por email de los mensajes de Contacto (Configuración → Contacto).

Se activa con variables de entorno (en Render):
  MAIL_USERNAME      la cuenta de Gmail de la app (p. ej. gyre.soporte@gmail.com)
  MAIL_APP_PASSWORD  una "contraseña de aplicación" de esa cuenta (no la normal)
  MAIL_TO            a quién avisar (opcional; por defecto, la misma cuenta)
Sin ellas no se envía nada y los mensajes se siguen viendo en /landing/stats.

El aviso lleva Reply-To con el email del usuario: al pulsar "Responder" en
Gmail, la respuesta le llega directamente a él. Se envía en segundo plano
para no retrasar la página; si falla, queda en el log (el mensaje ya está
guardado en la base de datos).
"""
import os
import smtplib
import threading
from email.message import EmailMessage

from app import app

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def enabled():
    return bool(os.environ.get("MAIL_USERNAME") and os.environ.get("MAIL_APP_PASSWORD"))


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


def _send(msg):
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_APP_PASSWORD"])
            smtp.send_message(msg)
    except Exception:
        app.logger.exception("No se pudo enviar el aviso de contacto por email")


def notify_contact(username, user_email, body, stats_url):
    """Avisa del mensaje nuevo, en segundo plano. No hace nada sin configurar."""
    if not enabled():
        return False
    threading.Thread(target=_send, args=(build_contact_email(username, user_email, body, stats_url),),
                     daemon=True).start()
    return True
