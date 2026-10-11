import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from app import app, db
from app.catalog_names import curated
from app.models import Exercise

JSON_URL = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json"
IMAGE_BASE = "https://cdn.jsdelivr.net/gh/yuhonas/free-exercise-db@main/exercises/"

# Nombres en español revisados a mano (app/data/exercise_names_es.json). Antes
# se traducían con Google Translate y salían nombres raros; un ejercicio que
# no esté en el archivo se queda sin nombre en español (se ve el inglés).
NAMES_ES = curated()


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
            if not existing.name_es and NAMES_ES.get(item["id"]):
                existing.name_es = NAMES_ES[item["id"]]
                translated += 1
        else:
            image_url = None
            if item.get("images"):
                image_url = IMAGE_BASE + item["images"][0]

            name_es = NAMES_ES.get(item["id"])

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
            translated += name_es is not None

        if (i + 1) % 50 == 0:
            db.session.commit()
            print(f"  ... {i + 1}/{len(data)} procesados")

    db.session.commit()
    print(f"✅ {created} ejercicios nuevos importados, {translated} nombres en español puestos.")
