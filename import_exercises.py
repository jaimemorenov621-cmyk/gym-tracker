import json
import queue
import sys
import threading
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from deep_translator import GoogleTranslator
from app import app, db
from app.models import Exercise

JSON_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
IMAGE_BASE = "https://cdn.jsdelivr.net/gh/yuhonas/free-exercise-db@main/exercises/"
TRANSLATE_TIMEOUT = 10  # deep-translator's requests.get has no timeout of its own

translator = GoogleTranslator(source="en", target="es")


def translate(name):
    # Run in a throwaway daemon thread: deep-translator issues requests.get()
    # with no timeout, so a stalled connection would otherwise hang forever.
    result_queue = queue.Queue()

    def worker():
        try:
            result_queue.put(("ok", translator.translate(name)))
        except Exception as e:
            result_queue.put(("error", e))

    threading.Thread(target=worker, daemon=True).start()
    try:
        status, value = result_queue.get(timeout=TRANSLATE_TIMEOUT)
    except queue.Empty:
        print(f"  ⚠️ Timeout traduciendo '{name}', se omite por ahora.")
        return None
    if status == "error":
        print(f"  ⚠️ No se pudo traducir '{name}': {value}")
        return None
    return value


with app.app_context():
    print("Descargando catálogo de ejercicios...")
    with urllib.request.urlopen(JSON_URL) as response:
        data = json.loads(response.read().decode())

    print(f"{len(data)} ejercicios encontrados. Importando/traduciendo...")
    created = 0
    translated = 0
    for i, item in enumerate(data):
        existing = db.session.get(Exercise, item["id"])

        if existing:
            if not existing.name_es:
                existing.name_es = translate(item["name"])
                translated += 1
                time.sleep(0.1)
        else:
            image_url = None
            if item.get("images"):
                image_url = IMAGE_BASE + item["images"][0]

            name_es = translate(item["name"])
            time.sleep(0.1)

            exercise = Exercise(
                id=item["id"],
                name=item["name"],
                name_es=name_es,
                category=item.get("category"),
                primary_muscles=", ".join(item.get("primaryMuscles", [])),
                equipment=item.get("equipment"),
                image_url=image_url,
            )
            db.session.add(exercise)
            created += 1
            translated += 1

        if (i + 1) % 50 == 0:
            db.session.commit()
            print(f"  ... {i + 1}/{len(data)} procesados")

    db.session.commit()
    print(f"✅ {created} ejercicios nuevos importados, {translated} traducciones generadas.")
