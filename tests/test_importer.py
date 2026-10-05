"""Importar historial de Hevy y Strong (app/importer.py, /importar)."""
import io
import unittest
from datetime import datetime

from tests.dbcase import DbTestCase  # antes que `app`: fija la BD en memoria

import sqlalchemy as sa

from app import app, db, importer
from app.models import ExerciseNote, ImportDraft, SetEntry, User, Workout

HEVY = '''"title","start_time","end_time","description","exercise_title","superset_id","exercise_notes","set_index","set_type","weight_kg","reps","distance_km","duration_seconds","rpe"
"Cara A","19 ago 2026, 14:20","19 ago 2026, 15:35","Buena","Press de Banca (Barra)",,"-Codos\n-Pausa",0,"warmup",40,10,,,
"Cara A","19 ago 2026, 14:20","19 ago 2026, 15:35","Buena","Press de Banca (Barra)",,"-Codos\n-Pausa",1,"normal",80,5,,,8.5
"Cara A","19 ago 2026, 14:20","19 ago 2026, 15:35","Buena","Fondos",,"",0,"failure",,12,,,10
"Cara A","19 ago 2026, 14:20","19 ago 2026, 15:35","Buena","Cinta",,"",0,"normal",,,2.5,900,
"Pierna","22 Aug 2026, 10:05","22 Aug 2026, 11:00","","Sentadilla (Máquina Smith)",,"",0,"dropset",100,6,,,
'''
STRONG = '''Date;Workout Name;Duration;Exercise Name;Set Order;Weight;Reps;Distance;Seconds;Notes;Workout Notes;RPE
2025-03-01 09:30:00;Push;1h 5m;Bench Press (Barbell);W;95;10;0;0;;;
2025-03-01 09:30:00;Push;1h 5m;Bench Press (Barbell);1;185;5;0;0;;;8
'''


class ImporterTests(DbTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.make_user("importa")
        with app.app_context():
            w = Workout(user_id=self.uid, timestamp=datetime(2026, 8, 30, 16, 0), performance_rating=7)
            db.session.add(w)
            db.session.flush()
            db.session.add(SetEntry(workout_id=w.id, exercise="press de banca", weight=70, reps=5, completed=True))
            db.session.commit()

    def test_parse_hevy_spanish_and_english_dates(self):
        with app.test_request_context():
            d = importer.parse_csv(HEVY.encode("utf-8"))
        self.assertEqual(d["source"], "hevy")
        self.assertEqual(len(d["workouts"]), 2)
        first = d["workouts"][0]
        self.assertEqual(first["start"], "2026-08-19T12:20:00")  # 14:20 en Madrid (verano) = 12:20 UTC
        self.assertEqual([s["set_type"] for s in first["sets"]], ["calentamiento", "normal", "fallo"])  # sin la cinta
        self.assertEqual(d["notes"]["Press de Banca (Barra)"], "-Codos\n-Pausa")
        self.assertEqual(d["skipped_rows"], 1)

    def test_parse_strong_in_pounds(self):
        with app.test_request_context():
            d = importer.parse_csv(STRONG.encode("utf-8"), unit="lb")
        self.assertEqual(d["source"], "strong")
        sets = d["workouts"][0]["sets"]
        self.assertAlmostEqual(sets[1]["weight"], 83.91, places=2)
        self.assertEqual(sets[0]["set_type"], "calentamiento")
        self.assertEqual(d["workouts"][0]["end"], "2025-03-01T09:35:00")  # 08:30 UTC + 1 h 5 min

    def test_upload_review_and_import_without_duplicates(self):
        self.login(self.uid)
        r = self.client.post("/importar", data={"file": (io.BytesIO(HEVY.encode("utf-8")), "workout_data.csv"), "unit": "kg"},
                             content_type="multipart/form-data")
        self.assertIn("/importar/revisar", r.headers["Location"])
        html = self.client.get("/importar/revisar").get_data(as_text=True)
        self.assertIn('value="press de banca"', html)  # se une al ejercicio que ya tenía
        # "fondos" no existe ni en el catálogo ni entre tus ejercicios: no se crea ni se importa.
        form = {"map-0": "press de banca", "map-1": "fondos", "map-2": ""}  # la sentadilla, fuera
        self.client.post("/importar/revisar", data=form)
        with app.app_context():
            sets = db.session.scalars(sa.select(SetEntry).join(Workout).where(Workout.user_id == self.uid)).all()
            self.assertEqual(sorted(s.exercise for s in sets), ["press de banca", "press de banca", "press de banca"])
            user = db.session.get(User, self.uid)
            self.assertEqual(user.effort_scale, "rir")
            heavy = next(s for s in sets if s.weight == 80)
            self.assertEqual(heavy.rir, 2)  # RPE 8,5 -> RIR 1,5 -> 2
            note = db.session.scalar(sa.select(ExerciseNote).where(ExerciseNote.user_id == self.uid))
            self.assertEqual(note.notes, "-Codos\n-Pausa")
            self.assertIsNone(db.session.scalar(sa.select(ImportDraft)))
        # Reimportar el mismo archivo no duplica
        self.client.post("/importar", data={"file": (io.BytesIO(HEVY.encode("utf-8")), "w.csv")}, content_type="multipart/form-data")
        self.client.post("/importar/revisar", data=form)
        with app.app_context():
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Workout).where(Workout.user_id == self.uid)), 2)
        self.assertEqual(self.client.get("/progress").status_code, 200)

    def test_suggests_your_own_name_but_not_other_variants(self):
        with app.app_context():
            w = db.session.scalar(sa.select(Workout).where(Workout.user_id == self.uid))
            for name in ("press de banca agarre medio", "press de banca agarre cerrado", "dominadas"):
                db.session.add(SetEntry(workout_id=w.id, exercise=name, weight=60, reps=5, completed=True))
            db.session.commit()
            from app.models import Exercise
            db.session.add(Exercise(id="dips", name="Dips - Chest Version", name_es="Fondos", primary_muscles="chest",
                                    name_normalized="dips - chest version", name_es_normalized="fondos"))
            db.session.commit()
            m, _, valid = importer.suggest_names(self.uid, ["Press de Banca - Agarre Cerrado (Barra)", "Press de Banca Inclinado (Mancuerna)",
                                                            "Dominada (Con Peso Añadido)", "Fondos"])
        self.assertEqual(m["Press de Banca - Agarre Cerrado (Barra)"], "press de banca agarre cerrado")
        self.assertEqual(m["Press de Banca Inclinado (Mancuerna)"], "")  # ni tuyo ni del catálogo: sin elegir
        self.assertEqual(m["Dominada (Con Peso Añadido)"], "dominadas")
        self.assertEqual(m["Fondos"], "fondos")  # del catálogo
        self.assertIn("fondos", valid)
        self.assertNotIn("press de banca inclinado (mancuerna)", valid)

    def test_notes_are_added_below_yours_never_replaced(self):
        with app.app_context():
            db.session.add(ExerciseNote(user_id=self.uid, exercise="press de banca", notes="Mi nota\n-Codos"))
            db.session.commit()
        self.login(self.uid)
        self.client.post("/importar", data={"file": (io.BytesIO(HEVY.encode("utf-8")), "w.csv")}, content_type="multipart/form-data")
        self.client.post("/importar/revisar", data={"map-0": "press de banca", "map-1": "", "map-2": ""})
        with app.app_context():
            note = db.session.scalar(sa.select(ExerciseNote).where(ExerciseNote.user_id == self.uid))
            self.assertEqual(note.notes, "Mi nota\n-Codos\n-Pausa")  # "-Codos" no se repite

    def test_catalog_search_tells_your_saved_sets(self):
        from app.models import Exercise
        with app.app_context():
            db.session.add(Exercise(id="bp", name="Barbell Bench Press", name_es="Press de banca", primary_muscles="chest",
                                    name_normalized="barbell bench press", name_es_normalized="press de banca"))
            db.session.add(Exercise(id="ib", name="Incline Bench Press", name_es="Press de banca inclinado", primary_muscles="chest",
                                    name_normalized="incline bench press", name_es_normalized="press de banca inclinado"))
            db.session.commit()
        self.login(self.uid)
        items = {i["id"]: i for i in self.client.get("/api/exercises/search?q=banca&with_sets=1").get_json()}
        self.assertEqual((items["bp"]["sets"], items["bp"]["value"]), (1, "press de banca"))  # la serie del setUp
        self.assertEqual((items["ib"]["sets"], items["ib"]["value"]), (0, "press de banca inclinado"))
        self.assertNotIn("sets", self.client.get("/api/exercises/search?q=banca").get_json()[0])

    def test_catalog_search_ignores_accents_and_plurals_and_filters_by_muscle(self):
        from app.models import Exercise
        with app.app_context():
            for i, (en, es, m) in enumerate([("Wide-Grip Lat Pulldown", "Jalón al pecho agarre ancho", "lats"),
                                            ("Lat Pulldown", "Jalón al pecho", "lats"),
                                            ("Triceps Pushdown", "Extensión de tríceps en polea", "triceps"),
                                            ("Chin-Up", "Dominada supina", "lats")]):
                db.session.add(Exercise(id=f"e{i}", name=en, name_es=es, primary_muscles=m))
            db.session.commit()
        self.login(self.uid)
        names = lambda q: [i["name"] for i in self.client.get("/api/exercises/search?q=" + q).get_json()]
        self.assertEqual(names("jalones al pecho")[0], "Jalón al pecho")  # sin tilde, plural y "al"; el más corto primero
        self.assertEqual(names("extensiones triceps"), ["Extensión de tríceps en polea"])
        self.assertEqual(names("Dominadas"), ["Dominada supina"])
        self.assertEqual(names("jalon cable"), ["Jalón al pecho", "Jalón al pecho agarre ancho"])  # ninguno dice "cable": los de "jalon"
        lats = [i["name"] for i in self.client.get("/api/exercises/search?muscle=lats").get_json()]
        self.assertEqual(sorted(lats), ["Dominada supina", "Jalón al pecho", "Jalón al pecho agarre ancho"])
        both = [i["name"] for i in self.client.get("/api/exercises/search?muscle=lats&q=jalon").get_json()]
        self.assertEqual(both, ["Jalón al pecho", "Jalón al pecho agarre ancho"])  # músculo y texto a la vez

    def test_guess_muscle_from_the_name(self):
        self.assertEqual(importer.guess_muscle("Triceps Pressdown"), "triceps")
        self.assertEqual(importer.guess_muscle("Curl de Pierna Sentado"), "hamstrings")
        self.assertEqual(importer.guess_muscle("Curl de Bíceps (Mancuerna)"), "biceps")
        self.assertEqual(importer.guess_muscle("Peso Muerto Rumano (Barra)"), "hamstrings")
        self.assertEqual(importer.guess_muscle("Vuelos Posteriores (Cable)"), "shoulders")
        self.assertIsNone(importer.guess_muscle("Burpees"))

    def test_unknown_file(self):
        self.login(self.uid)
        r = self.client.post("/importar", data={"file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("No reconozco el formato", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
