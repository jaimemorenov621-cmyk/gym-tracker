"""Idioma de la app (Flask-Babel).

Orden: 1) el que el usuario eligió en Ajustes (User.language); 2) sin
sesión, la cookie "lang"; 3) el idioma del navegador/móvil
(Accept-Language); 4) español.

Mientras I18N_ENABLED no esté activo (config), todo va en español: la
traducción se sube por partes y no debe verse a medias.

Textos nuevos: envolverlos en _() / ngettext() (plantillas y Python) o
lazy_gettext() si se definen al importar un módulo. Después:
    pybabel extract -F babel.cfg -k _l -k N_ -k lazy_pgettext:1c,2 -k _lp:1c,2 -o messages.pot .
    pybabel update -i messages.pot -d app/translations
    (traducir en app/translations/en/LC_MESSAGES/messages.po)
    pybabel compile -d app/translations
"""
from flask import current_app, has_request_context, request
from flask_babel import get_locale, gettext
from flask_login import current_user

LANGUAGES = {"es": "Español", "en": "English"}
DEFAULT = "es"


def enabled():
    return bool(current_app.config.get("I18N_ENABLED"))


def select_locale():
    if not enabled() or not has_request_context():
        return DEFAULT
    try:
        if current_user.is_authenticated and current_user.language in LANGUAGES:
            return current_user.language
    except Exception:  # sin usuario cargable (p. ej. errores tempranos)
        pass
    cookie = request.cookies.get("lang")
    if cookie in LANGUAGES:
        return cookie
    return request.accept_languages.best_match(list(LANGUAGES)) or DEFAULT


def N_(text):
    """Marca un texto para extraerlo sin traducirlo aquí (se traduce luego)."""
    return text


# Textos de los .js de app/static: base.html inyecta su traducción en
# window.GYRE_T y los scripts usan T('texto original', ...). Un texto nuevo en
# un .js hay que añadirlo aquí. Los {nombre} se sustituyen en el propio JS.
JS_STRINGS = [
    N_("Hombros"),
    N_("Cuello"),
    N_("Pecho"),
    N_("Abdomen"),
    N_("Bíceps"),
    N_("Tríceps"),
    N_("Antebrazos"),
    N_("Cuádriceps"),
    N_("Aductores"),
    N_("Abductores"),
    N_("Glúteos"),
    N_("Isquiotibiales"),
    N_("Dorsales"),
    N_("Espalda media"),
    N_("Espalda baja"),
    N_("Trapecios"),
    N_("Pantorrillas"),
    N_("Marcar como favorito"),
    N_("Sin resultados en el catálogo."),
    N_("+ Crear ejercicio nuevo"),
    N_("¿Es alguno de estos?"),
    N_("Ninguno, crear nuevo"),
    N_("Nombre del ejercicio"),
    N_("Músculos primarios (los que más trabajan)"),
    N_("Músculos secundarios (opcional)"),
    N_("Categoría (opcional)"),
    N_("Equipo (opcional)"),
    N_("Crear y usar"),
    N_("El nombre es obligatorio."),
    N_("Elige al menos un músculo primario."),
    N_("No se pudo crear el ejercicio."),
    N_("No se pudo reemplazar el ejercicio."),
    N_("Añadiendo {name}…"),
    N_("Escribe al menos 2 letras para buscar."),
    N_("Favoritos"),
    N_("Elige un ejercicio del catálogo primero."),
    N_("¡Has subido de rango!"),
    N_("Acabas de conseguirlo con este récord. Sigue así."),
    N_("Ver mi rango"),
    N_("Seguir entrenando"),
    N_("NV"),
    N_("Subida de nivel"),
    N_("Faltan {xp} XP para el nivel {level}"),
    N_("¡NIVEL {n}!"),
    N_("NUEVO RÉCORD PERSONAL"),
    N_("MI ENTRENO DE HOY"),
    N_("1RM estimado · {kg} kg"),
    N_("+{kg} kg sobre tu mejor marca"),
    N_("Registra tus entrenos gratis con Gyre"),
    N_("Comparte tu récord"),
    N_("Cerrar"),
    N_("Preparando tarjeta…"),
    N_("Diseño de la tarjeta"),
    N_("Compartir"),
    N_("Descargar"),
    N_("Perfecta para historias de Instagram o el estado de WhatsApp."),
    N_("Tarjeta de récord de {name}"),
    N_("No se pudo preparar la tarjeta."),
    N_("¡Nuevo récord!"),
    N_("🏅 Nuevo récord en {name}: {kg} kg × {reps} (1RM est. {e1rm} kg). Lo apunto todo con Gyre 👉 {url}"),
]


def js_translations():
    """{texto original: traducción} para el idioma actual (vacío en español)."""
    locale = get_locale()
    if locale is None or locale.language == DEFAULT:
        return {}
    return {text: gettext(text) for text in JS_STRINGS}
