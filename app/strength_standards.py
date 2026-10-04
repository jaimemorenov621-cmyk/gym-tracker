"""Estándares de fuerza: en qué nivel está cada levantamiento.

FUENTE (citada también en la app):
  Lon Kilgore, PhD, "Weightlifting Performance Standards", ExRx.net
  https://exrx.net/Testing/WeightLifting/StrengthStandards
  Tablas de adultos de 18 a 39 años, en libras (las originales; consultadas
  el 02/10/2026): .../BenchStandards, .../SquatStandards,
  .../DeadliftStandards, .../PressStandards

Qué son y qué no: estándares de rendimiento (1RM, sin equipo de ayuda salvo
cinturón) basados en ~70 años de clasificaciones de halterofilia y
powerlifting. La propia fuente avisa de que no son normas de población ni
están derivados por regresión. Niveles de la fuente:
  Untrained    -> Principiante: no ha entrenado el ejercicio, pero lo hace bien.
  Novice       -> Novato: entrena con regularidad desde hace unos meses.
  Intermediate -> Intermedio: entrena con regularidad hasta un par de años.
  Advanced     -> Avanzado: lleva varios años entrenando.
  Elite        -> Élite: compite en deportes de fuerza.

Cómo se aplican aquí (decisiones nuestras, documentadas en /progress):
  - Las tablas van por categoría de peso corporal (límite superior de cada
    categoría). Entre dos categorías se interpola linealmente. Por debajo de
    la primera se usa la primera; por encima de la última categoría con
    límite se usa la fila "+" (más de 319 lb ≈ 145 kg en hombres, de 198 lb
    ≈ 90 kg en mujeres). Nunca se extrapola.
  - Se compara con el 1RM ESTIMADO (estimated_1rm) de series reales de 10
    repeticiones efectivas o menos: más allá, la estimación pierde fiabilidad.
  - Edad: solo tenemos la tabla de 18-39 años (la app no guarda la edad).
  - "Nivel alcanzado" = el mejor nivel de cualquier sesión, cada una con el
    peso corporal registrado más cercano ANTERIOR a esa sesión (o el primero,
    si es como mucho 30 días posterior). Así pesarse hoy no cambia lo que ya
    alcanzaste, y no contradice logros ya desbloqueados.

DOTS (puntuación de powerlifting que corrige por peso corporal): fórmula de
Tim Konertz (BVDK, 2019). Coeficientes verificados en el código de
OpenPowerlifting (crates/coefficients/src/dots.rs).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import BodyWeightEntry, SetEntry, Workout

SOURCE_NAME = "Lon Kilgore, «Weightlifting Performance Standards» (ExRx.net), adultos de 18 a 39 años"
SOURCE_URL = "https://exrx.net/Testing/WeightLifting/StrengthStandards"

LEVELS = ["principiante", "novato", "intermedio", "avanzado", "elite"]
LEVEL_LABELS = {
    "principiante": "Principiante",
    "novato": "Novato",
    "intermedio": "Intermedio",
    "avanzado": "Avanzado",
    "elite": "Élite",
}
LEVEL_DESCRIPTIONS = {
    "principiante": "No ha entrenado el ejercicio, pero lo ejecuta bien.",
    "novato": "Entrena con regularidad desde hace unos meses.",
    "intermedio": "Entrena con regularidad desde hace hasta un par de años.",
    "avanzado": "Lleva varios años entrenando.",
    "elite": "Compite en deportes de fuerza.",
}

LIFTS = ["bench", "squat", "smith_squat", "deadlift", "rdl", "press", "row", "smith_row", "pullup", "pulldown"]
BIG_THREE = ["bench", "squat", "deadlift"]
# Básicos del rango global. Cada uno vale lo que la MEJOR de sus variantes
# (mismo patrón de movimiento, cada una comparada con su propia tabla): el
# tirón vertical, dominadas o jalón; la sentadilla, libre o en Smith (no
# todos los gimnasios tienen jaula); el peso muerto, convencional o rumano.
BASICS = ["bench", "squat", "deadlift", "press", "row", "vertical"]
VERTICAL = ("pullup", "pulldown")
BASIC_SOURCES = {
    "bench": ("bench",), "squat": ("squat", "smith_squat"), "deadlift": ("deadlift", "rdl"),
    "press": ("press",), "row": ("row", "smith_row"), "vertical": VERTICAL,
}
BASIC_LABELS = {
    "bench": "Press de banca", "squat": "Sentadilla (libre o en Smith)", "deadlift": "Peso muerto (convencional o rumano)",
    "press": "Press militar", "row": "Remo (con barra o en Smith)", "vertical": "Dominadas / jalón al pecho",
}
# Nota en la pestaña Rango para los levantamientos que comparten básico.
SHARED_NOTE = {
    "squat": "cuenta la mejor de sentadilla libre y en Smith",
    "smith_squat": "cuenta la mejor de sentadilla libre y en Smith",
    "deadlift": "cuenta el mejor de peso muerto y rumano",
    "rdl": "cuenta el mejor de peso muerto y rumano",
    "row": "cuenta el mejor de remo con barra y en Smith",
    "smith_row": "cuenta el mejor de remo con barra y en Smith",
    "pullup": "cuenta el mejor de dominadas y jalón",
    "pulldown": "cuenta el mejor de dominadas y jalón",
}
MIN_BASICS_FOR_GLOBAL = 3
LIFT_LABELS = {
    "bench": "Press de banca",
    "squat": "Sentadilla",
    "smith_squat": "Sentadilla en Smith",
    "deadlift": "Peso muerto",
    "rdl": "Peso muerto rumano",
    "press": "Press militar",
    "row": "Remo con barra",
    "smith_row": "Remo en Smith",
    "pullup": "Dominadas",
    "pulldown": "Jalón al pecho",
}
LIFT_RULES = {  # condición de la fuente para que el estándar aplique
    "bench": "La barra toca el pecho con una pausa breve y se extienden los codos del todo.",
    "squat": "Los muslos bajan por debajo de la paralela.",
    "smith_squat": "Sentadilla en máquina Smith (multipower).",
    "deadlift": "Rodillas, cadera y espalda alta se extienden del todo.",
    "rdl": "Peso muerto rumano con barra (piernas casi rectas, bisagra de cadera).",
    "press": "De pie, piernas rectas, sin echar el tronco atrás y extendiendo los codos.",
    "row": "Remo con barra inclinado hacia delante (bent over row).",
    "smith_row": "Remo inclinado en Smith. Tabla APROXIMADA: no hay una propia medida, se usa la del remo con barra.",
    "pullup": "Dominada completa; el peso que apuntes es el lastre (0 = solo tu peso).",
    "pulldown": "Jalón al pecho en polea; el peso es el de la máquina.",
}
# De qué tabla sale cada levantamiento.
KILGORE_LIFTS = ("bench", "squat", "deadlift", "press")
SL_LIFTS = ("smith_squat", "rdl", "row", "smith_row", "pullup", "pulldown")
# Sin tabla propia medida: se compara con la de otro levantamiento y la app
# lo marca como aproximado. Remo en Smith: StrengthLevel no tiene tabla y la
# de FitnessVolt está modelada (no medida) y sale más baja que la del remo
# con barra, lo que no cuadra; se usa la del remo con barra.
APPROX_TABLE = {"smith_row": "row"}
SL_SOURCE_NAME = "StrengthLevel (strengthlevel.com), percentiles de sus usuarios"
SL_SOURCE_URL = "https://strengthlevel.com/strength-standards"

# Tablas ORIGINALES en libras, tal cual la fuente (ExRx publica también una
# versión en kg, pero no es una conversión exacta: difiere hasta 4,4 kg y
# tiene alguna incoherencia, p. ej. peso muerto femenino de 44 kg). Se pasan
# a kg abajo sin redondear. Fila: (límite de la categoría en lb | None = la
# fila "+", umbrales de Principiante, Novato, Intermedio, Avanzado, Élite).
LB_PER_KG = 1 / 0.45359237
_MEN_LB = [114, 123, 132, 148, 165, 181, 198, 220, 242, 275, 319, None]
_WOMEN_LB = [97, 105, 114, 123, 132, 148, 165, 181, 198, None]
TABLES_LB = {
    ("hombre", "bench"): [
        (85, 110, 130, 180, 220), (90, 115, 140, 195, 240), (100, 125, 155, 210, 260),
        (110, 140, 170, 235, 290), (120, 150, 185, 255, 320), (130, 165, 200, 275, 345),
        (135, 175, 215, 290, 360), (140, 185, 225, 305, 380), (145, 190, 230, 315, 395),
        (150, 195, 240, 325, 405), (155, 200, 245, 335, 415), (160, 205, 250, 340, 425)],
    ("mujer", "bench"): [
        (50, 65, 75, 95, 115), (55, 70, 80, 100, 125), (60, 75, 85, 110, 135), (65, 80, 90, 115, 140),
        (70, 85, 95, 125, 150), (75, 90, 105, 135, 165), (80, 95, 115, 145, 185), (85, 110, 120, 160, 195),
        (90, 115, 130, 165, 205), (95, 120, 140, 175, 220)],
    ("hombre", "squat"): [
        (80, 145, 175, 240, 320), (85, 155, 190, 260, 345), (90, 170, 205, 280, 370),
        (100, 190, 230, 315, 410), (110, 205, 250, 340, 445), (120, 220, 270, 370, 480),
        (125, 230, 285, 390, 505), (130, 245, 300, 410, 530), (135, 255, 310, 425, 550),
        (140, 260, 320, 435, 570), (145, 270, 325, 445, 580), (150, 275, 330, 455, 595)],
    ("mujer", "squat"): [
        (40, 85, 100, 130, 165), (50, 90, 105, 140, 175), (55, 100, 115, 150, 190), (55, 105, 120, 160, 200),
        (60, 110, 130, 170, 210), (65, 120, 140, 185, 230), (70, 130, 150, 200, 255), (75, 140, 165, 215, 270),
        (80, 150, 175, 230, 290), (85, 160, 185, 240, 305)],
    ("hombre", "deadlift"): [
        (95, 180, 205, 300, 385), (105, 195, 220, 320, 415), (115, 210, 240, 340, 440),
        (125, 235, 270, 380, 480), (135, 255, 295, 410, 520), (150, 275, 315, 440, 550),
        (155, 290, 335, 460, 565), (165, 305, 350, 480, 585), (170, 320, 365, 490, 595),
        (175, 325, 375, 500, 600), (180, 335, 380, 505, 610), (185, 340, 390, 510, 615)],
    ("mujer", "deadlift"): [
        (55, 105, 120, 175, 230), (60, 115, 130, 190, 240), (65, 120, 140, 200, 255), (70, 130, 150, 210, 265),
        (75, 135, 160, 220, 275), (80, 150, 175, 240, 295), (90, 160, 190, 260, 320), (95, 175, 205, 275, 330),
        (100, 185, 215, 285, 350), (110, 195, 230, 300, 365)],
    ("hombre", "press"): [
        (55, 75, 90, 110, 130), (60, 80, 100, 115, 140), (65, 85, 105, 125, 150),
        (70, 95, 120, 140, 170), (75, 100, 130, 155, 190), (80, 110, 140, 165, 220),
        (85, 115, 145, 175, 235), (90, 120, 155, 185, 255), (95, 125, 160, 190, 265),
        (95, 130, 165, 195, 275), (100, 135, 170, 200, 280), (100, 140, 175, 205, 285)],
    ("mujer", "press"): [
        (30, 40, 50, 65, 85), (35, 45, 55, 70, 90), (35, 50, 60, 75, 100), (40, 50, 60, 80, 105),
        (40, 55, 65, 85, 110), (45, 60, 70, 95, 120), (50, 65, 75, 105, 135), (50, 70, 80, 110, 140),
        (55, 75, 85, 115, 150), (60, 80, 95, 125, 160)],
}


def _to_kg(lb):
    return None if lb is None else lb / LB_PER_KG


# Las mismas tablas en kg: (límite de la categoría | None, 5 umbrales).
TABLES = {
    (sex, lift): [
        (_to_kg(limit), *(_to_kg(v) for v in row))
        for limit, row in zip(_MEN_LB if sex == "hombre" else _WOMEN_LB, rows)
    ]
    for (sex, lift), rows in TABLES_LB.items()
}
assert all(len(rows) == len(_MEN_LB if sex == "hombre" else _WOMEN_LB) for (sex, _), rows in TABLES_LB.items())

# StrengthLevel (consultado el 03/10/2026; sentadilla en Smith y rumano, el
# 04/10/2026; tablas en kg por peso corporal de 5 en 5). No hay estándares de Kilgore para remo, dominadas ni jalón, así
# que estos tres salen de otra fuente con otro método: percentiles de los
# levantamientos que registran sus usuarios (Principiante = más fuerte que el
# 5 %, Novato 20 %, Intermedio 50 %, Avanzado 80 %, Élite 95 %). Datos
# autodeclarados, no verificados; se dice en la app. Dominadas: LASTRE
# añadido en kg (negativo = asistida), como lo publica la fuente.
_SL_MEN_BW = list(range(50, 141, 5))
_SL_WOMEN_BW = list(range(40, 121, 5))
SL_TABLES = {
    ("hombre", "row"): [
        (23, 36, 52, 72, 94), (27, 41, 59, 80, 103), (31, 46, 65, 87, 111), (36, 51, 71, 94, 119),
        (40, 56, 77, 101, 127), (44, 61, 83, 107, 134), (48, 66, 88, 114, 141), (52, 71, 93, 120, 147),
        (56, 75, 99, 125, 154), (59, 79, 104, 131, 160), (63, 84, 108, 136, 166), (67, 88, 113, 142, 172),
        (70, 92, 118, 147, 178), (74, 96, 122, 152, 183), (77, 100, 127, 157, 188), (80, 103, 131, 161, 194),
        (84, 107, 135, 166, 199), (87, 111, 139, 170, 203), (90, 114, 143, 175, 208)],
    ("mujer", "row"): [
        (12, 21, 33, 48, 65), (14, 23, 36, 51, 69), (15, 25, 38, 54, 72), (17, 27, 41, 57, 75),
        (18, 29, 43, 59, 78), (19, 30, 44, 62, 80), (20, 32, 46, 64, 83), (22, 33, 48, 66, 85),
        (23, 35, 50, 68, 87), (24, 36, 51, 69, 89), (25, 37, 53, 71, 91), (26, 38, 54, 73, 93),
        (27, 40, 56, 74, 95), (28, 41, 57, 76, 97), (29, 42, 58, 78, 99), (29, 43, 60, 79, 100),
        (30, 44, 61, 80, 102)],
    ("hombre", "smith_squat"): [
        (27, 47, 73, 105, 141), (32, 53, 81, 115, 152), (37, 60, 89, 124, 163), (42, 66, 97, 133, 174),
        (47, 72, 104, 142, 183), (52, 78, 111, 150, 193), (57, 84, 118, 158, 202), (62, 90, 125, 166, 210),
        (66, 95, 131, 173, 219), (71, 101, 138, 180, 227), (75, 106, 144, 187, 234), (79, 111, 149, 194, 242),
        (83, 116, 155, 200, 249), (87, 120, 161, 207, 256), (91, 125, 166, 213, 263), (95, 130, 171, 219, 270),
        (99, 134, 176, 225, 276), (103, 138, 181, 230, 282), (107, 143, 186, 236, 288)],
    ("mujer", "smith_squat"): [
        (15, 29, 48, 73, 101), (17, 31, 52, 77, 106), (18, 34, 55, 81, 111), (20, 36, 58, 85, 115),
        (22, 38, 61, 88, 119), (23, 40, 63, 91, 122), (25, 42, 66, 94, 126), (26, 44, 68, 97, 129),
        (28, 46, 70, 99, 132), (29, 48, 72, 102, 135), (30, 49, 74, 104, 138), (32, 51, 76, 107, 140),
        (33, 52, 78, 109, 143), (34, 54, 80, 111, 145), (35, 55, 82, 113, 148), (36, 57, 83, 115, 150),
        (37, 58, 85, 117, 152)],
    ("hombre", "rdl"): [
        (32, 51, 76, 106, 140), (37, 58, 85, 117, 152), (43, 65, 93, 127, 163), (49, 72, 102, 136, 174),
        (54, 79, 110, 145, 184), (60, 85, 117, 154, 194), (65, 92, 125, 163, 203), (70, 98, 132, 171, 213),
        (75, 104, 139, 179, 221), (80, 110, 145, 186, 230), (85, 115, 152, 194, 238), (90, 121, 158, 201, 246),
        (95, 126, 164, 208, 254), (99, 132, 170, 214, 261), (104, 137, 176, 221, 268), (108, 142, 182, 227, 275),
        (112, 147, 188, 233, 282), (116, 151, 193, 240, 289), (121, 156, 198, 245, 295)],
    ("mujer", "rdl"): [
        (23, 37, 55, 77, 101), (25, 40, 58, 81, 105), (27, 42, 61, 84, 109), (29, 44, 64, 87, 113),
        (31, 47, 67, 90, 116), (32, 49, 69, 93, 119), (34, 51, 71, 96, 122), (36, 52, 73, 98, 125),
        (37, 54, 75, 100, 128), (38, 56, 77, 103, 130), (40, 57, 79, 105, 132), (41, 59, 81, 107, 135),
        (42, 60, 83, 109, 137), (43, 62, 84, 111, 139), (44, 63, 86, 112, 141), (45, 64, 87, 114, 143),
        (46, 65, 89, 116, 145)],
    ("hombre", "pulldown"): [
        (29, 43, 60, 79, 101), (32, 47, 64, 85, 107), (35, 50, 69, 90, 113), (39, 54, 73, 95, 118),
        (42, 57, 77, 99, 123), (44, 61, 81, 104, 128), (47, 64, 85, 108, 133), (50, 67, 88, 112, 137),
        (52, 70, 92, 116, 142), (55, 73, 95, 120, 146), (57, 76, 98, 123, 150), (60, 79, 101, 127, 154),
        (62, 81, 104, 130, 157), (64, 84, 107, 133, 161), (66, 86, 110, 136, 164), (68, 89, 112, 139, 167),
        (70, 91, 115, 142, 171), (72, 93, 118, 145, 174), (74, 95, 120, 148, 177)],
    ("mujer", "pulldown"): [
        (17, 26, 38, 51, 66), (19, 28, 40, 54, 69), (20, 30, 42, 56, 72), (22, 32, 44, 58, 74),
        (23, 33, 46, 60, 76), (24, 35, 47, 62, 79), (25, 36, 49, 64, 81), (26, 37, 51, 66, 83),
        (27, 38, 52, 68, 85), (28, 40, 53, 69, 86), (29, 41, 55, 71, 88), (30, 42, 56, 72, 90),
        (31, 43, 57, 74, 91), (32, 44, 58, 75, 93), (33, 45, 59, 76, 94), (34, 46, 61, 77, 95),
        (34, 47, 62, 79, 97)],
    ("hombre", "pullup"): [
        (-5, 7, 22, 39, 56), (-4, 9, 25, 42, 61), (-4, 11, 27, 45, 64), (-3, 12, 29, 48, 68),
        (-2, 13, 31, 50, 71), (-2, 14, 32, 52, 73), (-2, 14, 33, 54, 75), (-2, 15, 34, 56, 77),
        (-2, 15, 35, 57, 79), (-2, 15, 36, 58, 81), (-3, 15, 36, 59, 82), (-3, 15, 37, 60, 83),
        (-4, 15, 37, 60, 84), (-5, 15, 37, 60, 85), (-6, 14, 36, 61, 85), (-7, 13, 36, 61, 86),
        (-8, 13, 36, 61, 86), (-9, 12, 35, 60, 86), (-10, 11, 35, 60, 86)],
    ("mujer", "pullup"): [
        (-14, -5, 6, 17, 30), (-14, -5, 7, 19, 33), (-14, -4, 8, 21, 35), (-15, -4, 8, 22, 37),
        (-16, -4, 9, 23, 38), (-16, -5, 9, 24, 39), (-18, -5, 9, 24, 40), (-19, -6, 8, 24, 41),
        (-20, -7, 8, 24, 41), (-21, -8, 7, 24, 41), (-23, -9, 7, 24, 41), (-24, -10, 6, 23, 41),
        (-26, -12, 5, 22, 40), (-28, -13, 3, 21, 40), (-30, -15, 2, 20, 39), (-32, -17, 1, 19, 38),
        (-34, -18, -1, 18, 37)],
}
assert all(len(rows) == len(_SL_MEN_BW if sex == "hombre" else _SL_WOMEN_BW) for (sex, _), rows in SL_TABLES.items())

MAX_EFFECTIVE_REPS = 10
BW_AFTER_MAX_DAYS = 30
CURRENT_WINDOW_DAYS = 365


# ------------------------------------------------------------ detección
# Solo el levantamiento de la tabla, no sus variantes (otra carga, otro
# estándar). Es preferible no reconocer un nombre raro que contar mal.
_LIFT_WORDS = {
    "bench": ("press de banca", "press banca", "press en banca", "bench press", "banca plana"),
    "squat": ("sentadilla", "squat"),
    "deadlift": ("peso muerto", "deadlift"),
    "press": ("press militar", "military press", "overhead press", "press por encima de la cabeza"),
    "row": ("remo con barra", "remo barra", "remo inclinado con barra", "barbell row", "bent over row",
            "bent-over row", "remo pendlay", "pendlay row"),
    "pullup": ("dominada", "pull up", "pull-up", "pullup"),
    "pulldown": ("jalon al pecho", "jalon", "lat pulldown", "pulldown", "pull down"),
}
_COMMON_EXCLUDE = (
    "mancuerna", "dumbbell", "kettlebell", "pesa rusa", "smith", "multipower", "maquina", "machine",
    "banda", "band", "cadena", "chain", "landmine", "unilateral", "una pierna", "un brazo",
    "single", "one arm", "one-arm", "one leg",
    # Series que por definición no van al máximo: no son "ese levantamiento"
    # a efectos de nivel (p. ej. "press de banca ligero técnico").
    "ligero", "ligera", "tecnic", "light", "technique", "tempo", "calentamiento", "warm",
    "descarga", "deload", "activacion", "movilidad", "velocidad", "speed", "dinamic",
    "isometric", "parcial", "partial", "larsen", "pies arriba", "feet up",
)
_LIFT_EXCLUDE = {
    "bench": ("inclinad", "incline", "declinad", "decline", "agarre cerrado", "agarre estrecho", "close",
              "suelo", "floor", "tabla", "board", "pin", "spoto", "guillotina", "guillotine"),
    "squat": ("bulgara", "bulgarian", "hack", "goblet", "frontal", "front", "zercher", "overhead",
              "por encima", "split", "zancada", "lunge", "pistol", "sissy", "caja", "box", "banco",
              "bench", "salto", "jump", "peso corporal", "bodyweight", "sin peso", "prensa", "press",
              "sumo", "cinturon", "belt"),
    "deadlift": ("rumano", "romanian", "rigida", "stiff", "piernas rectas", "straight", "deficit",
                 "rack", "bloque", "block", "trap", "hexagonal", "parcial", "partial", "snatch",
                 "arranque"),
    "press": ("sentado", "seated", "arnold", "push press", "tras nuca", "behind", "nuca"),
    "row": ("polea", "cable", "barra t", "en t", "t-bar", "t bar", "seal", "menton", "upright", "invertido",
            "inverted", "australian"),
    "pullup": ("asistida", "assisted", "negativa", "negative", "invertida", "australian", "jalon",
               "supin", "chin up", "chin-up", "chinup"),  # las supinas tienen otra tabla
    "pulldown": ("brazos rectos", "straight arm", "straight-arm", "tras nuca", "behind", "pullover",
                 "estrech", "cerrad", "close", "supin", "neutr", "triangulo", "v-bar", "v bar"),
}


def _strip(s):
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


# Variantes con tabla propia (se miran antes que el levantamiento base, que
# las excluye): sentadilla en Smith y peso muerto rumano con barra.
_SMITH_WORDS = ("smith", "multipower")
_RDL_WORDS = ("peso muerto rumano", "rumano", "romanian", "rdl")
_ROW_WORDS = ("remo", "row")


def _variant_of(name):
    """"smith_squat"/"rdl"/"smith_row" si es esa variante, None si es una variante de
    ella que no vale (con mancuernas, a una pierna...), "" si no es ninguna."""
    if any(w in name for w in _LIFT_WORDS["squat"]) and any(w in name for w in _SMITH_WORDS):
        allowed = _SMITH_WORDS + ("maquina", "machine")
        excl = tuple(w for w in _COMMON_EXCLUDE if w not in allowed) + _LIFT_EXCLUDE["squat"]
        return None if any(w in name for w in excl) else "smith_squat"
    if any(w in name for w in _ROW_WORDS) and any(w in name for w in _SMITH_WORDS):
        allowed = _SMITH_WORDS + ("maquina", "machine")
        excl = tuple(w for w in _COMMON_EXCLUDE if w not in allowed) + _LIFT_EXCLUDE["row"] + ("alto", "high", "una mano")
        return None if any(w in name for w in excl) else "smith_row"
    if any(w in name for w in _RDL_WORDS):
        excl = _COMMON_EXCLUDE + ("deficit", "bloque", "block", "trap", "hexagonal", "parcial", "partial", "sumo")
        return None if any(w in name for w in excl) else "rdl"
    return ""


def lift_of(exercise_name):
    """Clave del levantamiento (ver LIFTS) si el nombre es ESE ejercicio, sin
    variantes con otra carga; None si no. "banca" a secas cuenta como
    banca, pero no como parte de otro nombre ("fondos en banca")."""
    name = _strip(exercise_name or "").strip()
    if name == "banca":
        return "bench"
    variant = _variant_of(name)
    if variant != "":
        return variant
    for lift in _LIFT_WORDS:  # las variantes ya se han mirado arriba
        if any(w in name for w in _LIFT_WORDS[lift]):
            common = tuple(w for w in _COMMON_EXCLUDE if not (lift == "pulldown" and w in ("maquina", "machine")))
            if any(w in name for w in common + _LIFT_EXCLUDE[lift]):
                return None
            return lift
    return None


# ------------------------------------------------------------ umbrales
def _sl_thresholds(sex, lift, body_weight):
    rows = SL_TABLES.get((sex, APPROX_TABLE.get(lift, lift)))
    if rows is None or not body_weight:
        return None
    bws = _SL_MEN_BW if sex == "hombre" else _SL_WOMEN_BW
    bw = min(max(body_weight, bws[0]), bws[-1])  # sin extrapolar
    for i in range(len(bws) - 1):
        if bws[i] <= bw <= bws[i + 1]:
            t = (bw - bws[i]) / (bws[i + 1] - bws[i])
            ths = [a + (b - a) * t for a, b in zip(rows[i], rows[i + 1])]
            break
    if lift == "pullup":  # lastre -> carga total (tu peso + lastre)
        ths = [body_weight + x for x in ths]
    return ths


def thresholds(sex, lift, body_weight):
    """Umbrales en kg (Principiante..Élite) para ese sexo, levantamiento y
    peso corporal. None si el sexo no es "hombre"/"mujer". En dominadas son
    de CARGA TOTAL (peso corporal + lastre)."""
    if lift in SL_LIFTS:
        return _sl_thresholds(sex, lift, body_weight)
    table = TABLES.get((sex, lift))
    if table is None or not body_weight:
        return None
    limited = [r for r in table if r[0] is not None]
    if body_weight > limited[-1][0]:
        return list(table[-1][1:])  # fila "+"
    if body_weight <= limited[0][0]:
        return list(limited[0][1:])
    for lo, hi in zip(limited, limited[1:]):
        if lo[0] <= body_weight <= hi[0]:
            t = (body_weight - lo[0]) / (hi[0] - lo[0])
            return [a + (b - a) * t for a, b in zip(lo[1:], hi[1:])]
    raise AssertionError("inalcanzable")  # pragma: no cover


def level_index(e1rm, ths):
    """-1 = por debajo de Principiante; 0..4 = Principiante..Élite."""
    idx = -1
    for i, threshold in enumerate(ths):
        if e1rm >= threshold:
            idx = i
    return idx


# ------------------------------------------------------------ rangos
# Rango = posición CONTINUA en la tabla, con tu forma actual (mejor 1RM
# estimado válido de los últimos 90 días y tu último peso): puede bajar si
# dejas de entrenar un levantamiento, como en un juego por temporadas.
# Puntuación: 0 = umbral de Principiante, 1 = Novato, 2 = Intermedio,
# 3 = Avanzado, 4 = Élite; por encima, tramos de la anchura Avanzado->Élite.
# Titán es el nivel de competición (Élite) y quien es Avanzado está a uno o
# dos rangos de la cima (antes Avanzado quedaba en Diamante, con 3 rangos
# por delante, y parecía que le faltaba mucho). Desde Novato, tramos de
# medio nivel para que haya progresión visible:
#   Hierro    < 0      por debajo de Principiante
#   Bronce    0-1      Principiante
#   Plata     1-1,5    Novato
#   Oro       1,5-2    Novato alto
#   Platino   2-2,5    Intermedio
#   Diamante  2,5-3    Intermedio alto
#   Esmeralda 3-3,5    Avanzado
#   Campeón   3,5-4    Avanzado alto (a las puertas de Élite)
#   Titán     4 o más  Élite: nivel de competición
# Cada rango (salvo Titán) tiene divisiones I < II < III, en tercios.
RANK_WINDOW_DAYS = 90
# Ranking entre amigos: todo lo apunta cada uno, así que una marca solo
# cuenta si es creíble: no salta más de un 20 % sobre tu mejor marca
# anterior (ni es de Élite en tu primera sesión de ese ejercicio), salvo que
# otra sesión posterior la confirme con al menos el 90 % de ese peso. En tu
# perfil cuentan todas; aquí solo cambia lo que se compara con otros.
CREDIBLE_JUMP = 1.2
CREDIBLE_CONFIRM = 0.9
RANKS = ["Hierro", "Bronce", "Plata", "Oro", "Platino", "Diamante", "Esmeralda", "Campeón", "Titán"]
RANK_KEYS = ["hierro", "bronce", "plata", "oro", "platino", "diamante", "esmeralda", "campeon", "titan"]
RANK_BOUNDS = [0, 1, 1.5, 2, 2.5, 3, 3.5, 4]  # dónde empieza cada rango a partir de Bronce
TOP_TIER = len(RANKS) - 1
RANK_RANGES = [
    "por debajo de Principiante",
    "Principiante",
    "Novato",
    "Novato alto",
    "Intermedio",
    "Intermedio alto",
    "Avanzado",
    "Avanzado alto (a las puertas de Élite)",
    "Élite: nivel de competición",
]
_ROMAN = {1: "I", 2: "II", 3: "III"}


def strength_score(e1rm, ths):
    """Puntuación continua: 0 = umbral de Principiante, 1 = Novato, ...,
    4 = Élite. Por debajo de Principiante, de -1 (0 kg) a 0. Por encima de
    Élite se sigue con la anchura del último tramo (Avanzado->Élite)."""
    if e1rm < ths[0]:
        return -1 + max(0.0, e1rm) / ths[0]
    for i in range(4):
        if e1rm < ths[i + 1]:
            return i + (e1rm - ths[i]) / (ths[i + 1] - ths[i])
    return 4 + (e1rm - ths[4]) / (ths[4] - ths[3])


def kg_for_score(score, ths):
    """Inversa de strength_score: 1RM estimado necesario para `score`."""
    if score < 0:
        return (score + 1) * ths[0]
    i = min(int(score), 4)
    if i >= 4:
        return ths[4] + (score - 4) * (ths[4] - ths[3])
    return ths[i] + (score - i) * (ths[i + 1] - ths[i])


def _tier_span(tier):
    """(inicio, fin) de la puntuación de un rango."""
    lo = -1 if tier == 0 else RANK_BOUNDS[tier - 1]
    hi = RANK_BOUNDS[tier] if tier < TOP_TIER else None
    return lo, hi


def rank_for(score):
    """Rango, división y progreso dentro de la división para `score`."""
    if score is None:
        return None
    import bisect

    tier = bisect.bisect_right(RANK_BOUNDS, score)
    if tier == TOP_TIER:
        return {"tier": tier, "key": RANK_KEYS[tier], "name": RANKS[tier], "division": None,
                "label": RANKS[tier], "pct": 100, "next_score": None, "file": RANK_KEYS[tier]}
    lo, hi = _tier_span(tier)
    width = (hi - lo) / 3
    within = min(max(score - lo, 0.0), hi - lo - 1e-9)
    division = int(within / width) + 1
    div_start = lo + (division - 1) * width
    return {
        "tier": tier,
        "key": RANK_KEYS[tier],
        "name": RANKS[tier],
        "division": division,
        "label": f"{RANKS[tier]} {_ROMAN[division]}",
        "pct": round(100 * (score - div_start) / width),
        "next_score": div_start + width,
        "file": f"{RANK_KEYS[tier]}-{division}",
    }


def next_rank_label(rank):
    if rank is None or rank["tier"] == TOP_TIER:
        return None
    if rank["division"] < 3:
        return f"{rank['name']} {_ROMAN[rank['division'] + 1]}"
    return RANKS[rank["tier"] + 1] + ("" if rank["tier"] + 1 == TOP_TIER else " I")


def level_label(idx):
    if idx is None:
        return None
    return "Por debajo de Principiante" if idx < 0 else LEVEL_LABELS[LEVELS[idx]]


# ------------------------------------------------------------ DOTS
_DOTS = {
    "hombre": ((-0.0000010930, 0.0007391293, -0.1918759221, 24.0900756, -307.75076), (40.0, 210.0)),
    "mujer": ((-0.0000010706, 0.0005158568, -0.1126655495, 13.6175032, -57.96288), (40.0, 150.0)),
}


def dots(total, body_weight, sex):
    if sex not in _DOTS or not body_weight or not total:
        return None
    (a, b, c, d, e), (lo, hi) = _DOTS[sex]
    x = min(max(body_weight, lo), hi)
    denominator = a * x ** 4 + b * x ** 3 + c * x ** 2 + d * x + e
    return total * 500.0 / denominator


# ------------------------------------------------------------ perfil
def _valid_e1rm(entry):
    """1RM estimado de la serie, o None si no vale para el estándar."""
    from app.routes import effective_reps, estimated_1rm, is_real_set

    if not is_real_set(entry) or (entry.set_type or "normal") == "calentamiento":
        return None
    if effective_reps(entry) > MAX_EFFECTIVE_REPS:
        return None
    return estimated_1rm(entry)


def _pullup_added_1rm(entry, body_weight):
    """Dominadas: el peso apuntado es el lastre (0 = solo tu peso). Devuelve
    el LASTRE equivalente a tu 1RM (carga total estimada menos tu peso), o
    None si la serie no vale."""
    from types import SimpleNamespace

    from app.routes import effective_reps, estimated_1rm

    if (not entry.completed or entry.reps <= 0 or entry.weight < 0 or body_weight is None
            or (entry.set_type or "normal") == "calentamiento"):
        return None
    if effective_reps(entry) > MAX_EFFECTIVE_REPS:
        return None
    total = SimpleNamespace(weight=body_weight + entry.weight, reps=entry.reps, rir=entry.rir, rpe=entry.rpe)
    return estimated_1rm(total) - body_weight


def _load(lift, value, body_weight):
    """Lo que se compara con la tabla: en dominadas, tu peso + el lastre."""
    if value is None:
        return None
    return value + body_weight if lift == "pullup" else value


def _body_weight_at(points, when):
    """Peso registrado más cercano anterior a `when`; si no hay, el primero
    siempre que sea como mucho BW_AFTER_MAX_DAYS días posterior.
    points: [(fecha UTC naive, kg)] ordenados por fecha."""
    before = None
    for ts, kg in points:
        if ts <= when:
            before = kg
        else:
            break
    if before is not None:
        return before
    if points and points[0][0] - when <= timedelta(days=BW_AFTER_MAX_DAYS):
        return points[0][1]
    return None


def _naive_utc(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def strength_profile(user, rows=None, weights=None, now=None):
    """Nivel por levantamiento, nivel global y DOTS.

    rows: [(Workout, SetEntry)] ya cargadas (compute_stats las reutiliza);
    si no, se consultan. weights: BodyWeightEntry del usuario.
    """
    sex = user.sex if user.sex in ("hombre", "mujer") else None
    if rows is None:
        rows = db.session.execute(
            sa.select(Workout, SetEntry)
            .join(SetEntry, SetEntry.workout_id == Workout.id)
            .where(Workout.user_id == user.id)
            .order_by(Workout.timestamp.asc())
        ).all()
    if weights is None:
        weights = db.session.scalars(
            sa.select(BodyWeightEntry)
            .where(BodyWeightEntry.user_id == user.id)
            .order_by(BodyWeightEntry.timestamp.asc())
        ).all()
    # Siempre en UTC naive, como Workout.timestamp.
    bw_points = sorted((_naive_utc(e.timestamp), e.weight) for e in weights)
    latest_bw = bw_points[-1][1] if bw_points else None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    # Mejor e1RM válido por sesión (entreno) y levantamiento; y mejor carga
    # real levantada (para los hitos de discos, cualquier nº de reps).
    sessions = defaultdict(dict)  # lift -> {workout_id: (timestamp, e1rm, entry)}
    by_name = defaultdict(list)    # nombre exacto del ejercicio -> [(timestamp, e1rm)]
    max_weight = defaultdict(float)
    from app.routes import is_real_set

    lift_cache = {}
    for w, s in rows:
        if s.exercise not in lift_cache:
            lift_cache[s.exercise] = lift_of(s.exercise)
        lift = lift_cache[s.exercise]
        if lift is None:
            continue
        if is_real_set(s) and (s.set_type or "normal") != "calentamiento":
            max_weight[lift] = max(max_weight[lift], s.weight)
        if lift == "pullup":
            e1rm = _pullup_added_1rm(s, _body_weight_at(bw_points, w.timestamp))
        else:
            e1rm = _valid_e1rm(s)
        if e1rm is None:
            continue
        by_name[s.exercise].append((w.timestamp, e1rm))
        prev = sessions[lift].get(w.id)
        if prev is None or e1rm > prev[1]:
            sessions[lift][w.id] = (w.timestamp, e1rm)

    lifts = {}
    for lift in LIFTS:
        info = {
            "lift": lift,
            "label": LIFT_LABELS[lift],
            "rule": LIFT_RULES[lift],
            "has_data": bool(sessions[lift]),
            "max_weight": max_weight[lift] or None,
            "reached": None,         # índice -1..4 (mejor de todas las sesiones)
            "reached_label": None,
            "reached_at": None,
            "reached_e1rm": None,
            "best_e1rm_all": max((e for ts, e in sessions[lift].values()), default=None),
            "best_e1rm": None,       # mejor e1RM válido de los últimos 12 meses
            "ratio": None,           # best_e1rm / último peso
            "next_label": None,
            "next_kg": None,         # umbral del siguiente nivel con tu peso actual
            "missing_kg": None,
            "meets_next_now": False,
            "bar_pct": None,
        }
        recent = [e for ts, e in sessions[lift].values() if now - ts <= timedelta(days=CURRENT_WINDOW_DAYS)]
        info["best_e1rm"] = max(recent) if recent else None
        if sex and bw_points:
            for ts, e1rm in sorted(sessions[lift].values()):
                bw = _body_weight_at(bw_points, ts)
                ths = thresholds(sex, lift, bw)
                if ths is None:
                    continue
                idx = level_index(_load(lift, e1rm, bw), ths)
                if info["reached"] is None or idx > info["reached"]:
                    info.update(reached=idx, reached_at=ts, reached_e1rm=e1rm)
            if info["reached"] is not None:
                info["reached_label"] = level_label(info["reached"])
                if info["reached"] < len(LEVELS) - 1:
                    nxt = info["reached"] + 1
                    ths_now = thresholds(sex, lift, latest_bw)
                    info["next_label"] = LEVEL_LABELS[LEVELS[nxt]]
                    info["next_kg"] = ths_now[nxt]
                    if info["best_e1rm"] is not None:
                        load_now = _load(lift, info["best_e1rm"], latest_bw)
                        info["missing_kg"] = max(0.0, ths_now[nxt] - load_now)
                        info["meets_next_now"] = load_now >= ths_now[nxt]
                        # Barra: del umbral del nivel actual (0 si aún no hay
                        # nivel) al del siguiente, con tu peso actual.
                        floor = ths_now[nxt - 1] if nxt > 0 else 0.0
                        span = ths_now[nxt] - floor
                        info["bar_pct"] = round(100 * min(1.0, max(0.0, (load_now - floor) / span))) if span > 0 else 100
        if info["best_e1rm"] is not None and latest_bw and lift != "pullup":
            info["ratio"] = info["best_e1rm"] / latest_bw

        # Rango actual (últimos 90 días, peso actual) y mejor rango histórico
        # (cada sesión con el peso de entonces, como el nivel alcanzado).
        info.update(rank=None, score=None, rank_peak=None, rank_next=None, rank_next_kg=None,
                    rank_missing_kg=None, rank_e1rm=None, rank_stale=False, ranking_score=None)
        if sex and bw_points:
            peak = None
            for ts, e1rm in sessions[lift].values():
                bw = _body_weight_at(bw_points, ts)
                ths = thresholds(sex, lift, bw)
                if ths is not None:
                    sc = strength_score(_load(lift, e1rm, bw), ths)
                    peak = sc if peak is None else max(peak, sc)
            info["rank_peak"] = rank_for(peak)
            window = [e for ts, e in sessions[lift].values() if now - ts <= timedelta(days=RANK_WINDOW_DAYS)]
            if window:
                ths_now = thresholds(sex, lift, latest_bw)
                best = max(window)
                load = _load(lift, best, latest_bw)
                info["score"] = strength_score(load, ths_now)
                info["rank"] = rank_for(info["score"])
                info["rank_e1rm"] = best  # en dominadas: lastre equivalente
                info["ranking_score"] = _credible_score(lift, sessions[lift].values(), now, latest_bw, ths_now)
                if info["rank"]["next_score"] is not None:
                    info["rank_next"] = next_rank_label(info["rank"])
                    target = kg_for_score(info["rank"]["next_score"], ths_now)
                    info["rank_missing_kg"] = max(0.0, target - load)
                    # Objetivo en la misma unidad que se apunta (lastre en dominadas).
                    info["rank_next_kg"] = target - latest_bw if lift == "pullup" else target
            elif sessions[lift]:
                info["rank_stale"] = True  # entrenado, pero no en los últimos 90 días
        lifts[lift] = info

    # Qué falta para poder dar niveles.
    missing = []
    if not sex:
        missing.append("sexo")
    if not bw_points:
        missing.append("peso corporal")
    missing_lifts = [LIFT_LABELS[l] for l in BIG_THREE if not lifts[l]["has_data"]]

    global_level = None
    if not missing and not missing_lifts and all(lifts[l]["reached"] is not None for l in BIG_THREE):
        global_level = min(lifts[l]["reached"] for l in BIG_THREE)

    dots_score = None
    if sex and latest_bw and all(lifts[l]["best_e1rm"] for l in BIG_THREE):
        total = sum(lifts[l]["best_e1rm"] for l in BIG_THREE)
        dots_score = dots(total, latest_bw, sex)

    # Rango global: MEDIA de los básicos entrenados en los últimos 90 días
    # (así cualquier mejora cuenta), con un mínimo de 3. El tirón vertical
    # vale lo que el mejor de dominadas y jalón. Para no esconder
    # desequilibrios, se avisa si un básico va un rango entero por detrás.
    def basic_score(basic):
        vals = [lifts[l]["score"] for l in BASIC_SOURCES[basic] if lifts[l]["score"] is not None]
        return max(vals) if vals else None

    scores = {b: basic_score(b) for b in BASICS}
    counted = {b: sc for b, sc in scores.items() if sc is not None}
    # Lo mismo con las marcas creíbles, para el ranking entre amigos.
    ranking_basics = {}
    for basic in BASICS:
        vals = [lifts[l]["ranking_score"] for l in BASIC_SOURCES[basic] if lifts[l]["ranking_score"] is not None]
        if vals:
            ranking_basics[basic] = max(vals)
    ranking_global = (sum(ranking_basics.values()) / len(ranking_basics)
                      if not missing and len(ranking_basics) >= MIN_BASICS_FOR_GLOBAL else None)
    rank_missing = [BASIC_LABELS[b] for b in BASICS if scores[b] is None]
    global_rank = lagging = None
    if not missing and len(counted) >= MIN_BASICS_FOR_GLOBAL:
        mean = sum(counted.values()) / len(counted)
        global_rank = rank_for(mean)
        weakest = min(counted, key=counted.get)
        if mean - counted[weakest] >= 1:
            lagging = BASIC_LABELS[weakest]

    # Rango de cada NOMBRE de ejercicio por separado (básicos personales):
    # "press banca" y "press de banca con pausa" pueden tener rangos distintos.
    exercise_ranks = {}
    if sex and latest_bw:
        for name, items in by_name.items():
            lift = lift_cache[name]
            window = [e for ts, e in items if now - ts <= timedelta(days=RANK_WINDOW_DAYS)]
            ths = thresholds(sex, lift, latest_bw)
            if window and ths:
                exercise_ranks[name] = rank_for(strength_score(_load(lift, max(window), latest_bw), ths))

    return {
        "global_rank": global_rank,
        "global_score": (sum(counted.values()) / len(counted)) if global_rank else None,
        "basic_scores": counted,
        "ranking": {"global": ranking_global, "basics": ranking_basics},
        "exercise_ranks": exercise_ranks,
        "rank_missing": rank_missing,
        "basics_counted": len(counted),
        "lagging": lagging,
        "sex": sex,
        "latest_bw": latest_bw,
        "lifts": lifts,
        "missing": missing,
        "missing_lifts": missing_lifts,
        "global": global_level,
        "global_label": level_label(global_level),
        "dots": dots_score,
    }


def _credible_score(lift, sessions, now, latest_bw, ths_now):
    """Puntuación del ranking: la mejor marca CREÍBLE de los últimos 90 días
    (ver CREDIBLE_JUMP). sessions: [(timestamp, e1rm)]."""
    ordered = sorted(sessions)
    later_max = [0.0] * len(ordered)
    best_after = 0.0
    for i in range(len(ordered) - 1, -1, -1):
        later_max[i] = best_after
        best_after = max(best_after, ordered[i][1])
    best, prev_best = None, None
    for i, (ts, e1rm) in enumerate(ordered):
        confirmed = later_max[i] >= CREDIBLE_CONFIRM * e1rm
        if prev_best is None:
            plausible = strength_score(_load(lift, e1rm, latest_bw), ths_now) <= 4
        else:
            plausible = e1rm <= CREDIBLE_JUMP * prev_best
        if (confirmed or plausible) and now - ts <= timedelta(days=RANK_WINDOW_DAYS):
            best = e1rm if best is None else max(best, e1rm)
        prev_best = e1rm if prev_best is None else max(prev_best, e1rm)
    return None if best is None else strength_score(_load(lift, best, latest_bw), ths_now)


def rank_key(rank):
    """Orden total de rangos: rango*3 + división (Titán, sin división, el mayor)."""
    return None if rank is None else rank["tier"] * 3 + (rank["division"] or 3)


def rank_notice(user, rank):
    """Qué animación de rango toca mostrar en Inicio, y la deja anotada:
    "intro" la primera vez que tiene rango, "up" al subir (también al
    recuperar un rango que había perdido); None si nada cambió o bajó (las
    bajadas no se anuncian con una animación, se ven en la pestaña Rango)."""
    from app import db
    from app.models import User

    key = rank_key(rank)
    if key is None:
        return None
    seen = user.rank_seen
    if seen == key:
        return None
    kind = "intro" if seen is None else ("up" if key > seen else None)
    db.session.execute(
        sa.update(User).where(User.id == user.id).values(rank_seen=key)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    return kind
