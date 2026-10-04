"""Lista el texto en español de las plantillas que aún no pasa por _():
nodos de texto, literales dentro de {{ }} / {% %}, atributos visibles y
cadenas de los <script>. Heurístico: sirve para no dejarse nada al traducir.

Uso: python tools/i18n_leftovers.py [plantilla.html ...]
"""
import io
import os
import re
import sys

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "templates")
SKIP = {"landing_stats.html"}  # página interna
TAG = r"<[A-Za-z!/](?:\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}|[^>{]|\{)*>"
TOKEN = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}|<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->|" + TAG + ")", re.S)
LETTER = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ¿¡]")
SPANISHY = re.compile(r"[áéíóúñ¿¡ÁÉÍÓÚÑ]|\b(de|la|el|en|los|las|tu|tus|con|por|para|sin|del|una|un|que|días?|semana|serie|series|entreno|rango|nivel|peso)\b", re.I)
LITERAL = re.compile(r"""(?<![\w.])(?<!_\()(?<!gettext\()(['"])((?:(?!\1).)*?)\1""")
ATTR = re.compile(r'\b(placeholder|aria-label|title|alt|data-label)="([^"]*)"')
CODEISH = re.compile(r"^[\w\-./#:%?=&]*$")
# Textos que no se traducen (unidades, siglas, la marca, símbolos).
NEUTRAL = re.compile(r"^[\s\d.,:;·×+\-–—()%/*✓▲▼←→]*(kg|XP|RIR|RPE|1RM|h|min|s|m|Gyre|N|C|F|D|I|II|III|e1RM|DOTS)?[\s\d.,:;·×+\-–—()%/*✓▲▼←→]*$")


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def scan(path):
    src = io.open(path, encoding="utf-8").read()
    found = []
    pos = 0
    for i, part in enumerate(TOKEN.split(src)):
        start = pos
        pos += len(part)
        if i % 2 == 0:
            t = part.strip()
            if t and LETTER.search(t) and not NEUTRAL.match(t):
                found.append((line_of(src, start), "texto", t[:90]))
            continue
        if part.startswith("{#") or part.startswith("<!--") or part.startswith("<style"):
            continue
        if part.startswith("<script"):
            for m in re.finditer(r"""(['"`])((?:(?!\1).)*?)\1""", part):
                s = m.group(2)
                if " " in s and SPANISHY.search(s) and "{{" not in s and "_(" not in part[max(0, m.start() - 3):m.start()]:
                    found.append((line_of(src, start + m.start()), "script", s[:90]))
            continue
        if part.startswith("{{") or part.startswith("{%"):
            for m in LITERAL.finditer(part):
                s = m.group(2)
                before = part[:m.start()]
                if before.rstrip().endswith(("_(", "gettext(", "ngettext(")) or re.search(r"_\(\s*$", before):
                    continue
                if s and not CODEISH.match(s) and LETTER.search(s) and SPANISHY.search(s):
                    found.append((line_of(src, start + m.start()), "jinja", s[:90]))
            continue
        for m in ATTR.finditer(part):
            s = m.group(2)
            if s and "_(" not in s and LETTER.search(s) and SPANISHY.search(s.split("{{")[0] + s.split("}}")[-1]):
                found.append((line_of(src, start + m.start()), "atributo", s[:90]))
    return found


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(f for f in os.listdir(TPL) if f.endswith(".html") and f not in SKIP)
    total = 0
    for f in files:
        items = scan(os.path.join(TPL, f))
        total += len(items)
        if items:
            print(f"\n## {f} ({len(items)})")
            for line, kind, s in items:
                print(f"  {line:4d} {kind:8s} {s}")
    print(f"\nTOTAL {total}")
