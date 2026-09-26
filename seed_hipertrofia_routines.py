"""Crea las 4 rutinas del bloque de hipertrofia de 8 semanas (Torso A/B, Pierna A/B)
para un usuario ya existente, identificado por username. No requiere la contraseña
del usuario: es un script one-off (como import_exercises.py) que se ejecuta con
acceso directo a la base de datos configurada en DATABASE_URL/.flaskenv.

Los valores de series/reps/RIR reflejan la semana 1 de cada ciclo (el punto de
partida más seguro): la progresión semana a semana del bloque hay que ajustarla
a mano en la app, igual que ya se hace con los bloques de fuerza -- Routine no
modela periodización, solo la plantilla del día.

Uso:
    python seed_hipertrofia_routines.py Jaime_309
"""
import sys

from app import app, db
from app.models import User, Routine, RoutineExercise
from app.routes import canonicalize_exercise_name

AMRAP = "AMRAP (min. 5)"

# (nombre, sets, reps, rir)
DAYS = [
    ("Torso A", [
        ("press banca", 1, AMRAP, "3"),
        ("press banca", 3, "5", "3"),
        ("dominada lastrada / jalón al pecho", 1, AMRAP, "3"),
        ("dominada lastrada / jalón al pecho", 3, "5", "3"),
        ("curl bíceps con barra", 3, "8", "2"),
        ("extensión de tríceps en polea", 3, "8", "2"),
        ("press inclinado con mancuerna", 3, "10-12", "2"),
        ("face pull", 3, "12-20", "0-1"),
    ]),
    ("Torso B", [
        ("press militar", 1, AMRAP, "3"),
        ("remo en Smith", 3, "5", "3"),
        ("remo en Smith", 1, AMRAP, "3"),
        ("curl martillo (agarre neutro)", 3, "8", "2"),
        ("curl inclinado con mancuerna", 3, "8", "2"),
        ("elevación lateral", 3, "10-12", "2"),
        ("fondos en paralelas", 3, "10-12", "2"),
    ]),
    ("Pierna A", [
        ("sentadilla en máquina Smith", 1, AMRAP, "3"),
        ("sentadilla en máquina Smith", 3, "5", "3"),
        ("prensa de piernas (pies bajos y juntos)", 3, "10-12", "2"),
        ("extensión de cuádriceps", 3, "10-12", "2"),
        ("curl femoral", 3, "10-12", "2"),
        ("elevación de gemelo de pie", 3, "12-20", "0-1"),
    ]),
    ("Pierna B", [
        ("peso muerto rumano (RDL)", 3, "8", "3"),
        ("hiperextensión (énfasis de cadera)", 3, "10-12", "2"),
        ("curl femoral", 3, "12-20", "0-1"),
        ("crunch abdominal", 3, "12-20", "0-1"),
        ("elevación de gemelo", 3, "12-20", "0-1"),
    ]),
]

# Corrige el orden: en Torso B el AMRAP de remo debe ir antes del backoff.
DAYS[1][1][1], DAYS[1][1][2] = DAYS[1][1][2], DAYS[1][1][1]


def main(username):
    with app.app_context():
        user = db.session.scalar(db.select(User).filter_by(username=username))
        if user is None:
            print(f"No existe ningún usuario con username '{username}'.")
            return 1

        next_order = db.session.scalar(
            db.select(db.func.count()).select_from(Routine).filter_by(user_id=user.id)
        ) or 0

        for name, exercises in DAYS:
            routine = Routine(name=name, order_index=next_order, user_id=user.id)
            db.session.add(routine)
            db.session.flush()
            next_order += 1

            for i, (exercise, sets, reps, rir) in enumerate(exercises):
                db.session.add(RoutineExercise(
                    exercise=canonicalize_exercise_name(exercise),
                    target_sets=sets,
                    target_reps=reps,
                    rir=rir,
                    order_index=i,
                    routine_id=routine.id,
                ))
            print(f"Creada rutina '{name}' con {len(exercises)} ejercicios.")

        db.session.commit()
        print(f"Listo: 4 rutinas añadidas a la cuenta de '{username}'.")
        return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python seed_hipertrofia_routines.py <username>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
