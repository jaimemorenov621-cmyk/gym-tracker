"""Actualiza el catálogo de traducciones de una vez:
extrae los textos (con todas las palabras clave que usa la app), actualiza
app/translations/en/.../messages.po, lista lo que falta por traducir y
compila el .mo (que se sube al repo: Render no compila).

Uso: python tools/i18n_update.py            (desde la raíz del repo)
Traducir lo listado en el .po y volver a ejecutarlo.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.i18n import EXTRACT_KEYWORDS  # noqa: E402


def pybabel(*args):
    exe = os.path.join(os.path.dirname(sys.executable), "pybabel")
    subprocess.run([exe, *args], cwd=ROOT, check=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # consola de Windows (cp1252)
    keywords = [arg for kw in EXTRACT_KEYWORDS for arg in ("-k", kw)]
    pybabel("extract", "-F", "babel.cfg", *keywords, "-o", "messages.pot", ".")
    pybabel("update", "-i", "messages.pot", "-d", "app/translations", "--ignore-obsolete")
    from babel.messages.pofile import read_po

    with open(os.path.join(ROOT, "app/translations/en/LC_MESSAGES/messages.po"), "rb") as f:
        catalog = read_po(f, locale="en")
    pending = [m for m in catalog if m.id and ("fuzzy" in m.flags or not all(
        m.string if isinstance(m.string, tuple) else (m.string,)))]
    for m in pending:
        print("SIN TRADUCIR" + (" (fuzzy)" if "fuzzy" in m.flags else "") + ":", m.id)
    pybabel("compile", "-d", "app/translations")
    print(f"{len(pending)} por traducir")


if __name__ == "__main__":
    main()
