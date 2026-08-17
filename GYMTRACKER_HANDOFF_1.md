# GymTracker — Documento de traspaso para Claude Code

> Este documento resume el estado real del proyecto tal y como quedó al final de una sesión de desarrollo asistido por chat. Todo lo marcado como "✅ Implementado" ha sido escrito y, salvo que se indique lo contrario, probado por el usuario en local y/o en producción. Todo lo marcado como "⏳ Pendiente" **no existe en el código todavía**. No se ha inventado ninguna funcionalidad no mencionada explícitamente en el desarrollo.

---

## 1. Visión del proyecto

GymTracker es una aplicación web de seguimiento de entrenamientos de gimnasio, construida por el usuario (estudiante de ingeniería informática, primer año superado, sin experiencia previa en desarrollo web) como proyecto de aprendizaje práctico tras completar CS50P y el Flask Mega-Tutorial de Miguel Grinber.
Aunque comenzó como un proyecto de aprendizaje, el objetivo a medio plazo es convertir GymTracker en un producto real y comercial, conseguir usuarios y generar ingresos mediante un modelo de monetización sostenible.

**Contexto de producto importante:** este proyecto nació de una idea más amplia ("aplicación para optimizarte a ti mismo", con módulos futuros de sueño, nutrición, finanzas, estudio, etc. — concepto interno llamado "LifeOS"). Esa idea fue **explícitamente descartada como prematura** (over-engineering) en favor de una V1 minimalista: **solo entrenamiento**, usada a diario por el propio usuario, que se expande únicamente si demuestra valor real de uso. **No sugieras expandir a otros dominios de vida (sueño, nutrición, etc.) a menos que el usuario lo pida explícitamente.**

El objetivo declarado del usuario es que la app le resulte más útil que aplicaciones comerciales como Hevy (que ha usado 3 años), y eventualmente explorar si tiene potencial como producto para otros usuarios — pero la monetización se ha descartado deliberadamente como prioridad actual (ver sección 7).

Eslogan de la app (solo debe aparecer en la página de inicio, como subtítulo, no globalmente): **"Lo que no se mide, no se puede mejorar."**

---

## 2. Stack técnico

- **Backend:** Flask, Flask-SQLAlchemy, Flask-Migrate (Alembic), Flask-Login, Flask-WTF
- **Frontend:** Jinja2, CSS propio (`app/static/style.css`), JavaScript vanilla con `fetch` (sin frameworks), SortableJS vía CDN (drag & drop), Chart.js vía CDN (gráficas)
- **Base de datos:** SQLite en desarrollo local, **PostgreSQL en producción** (Render, `psycopg2-binary` instalado)
- **Despliegue:** Render.com
  - Repo GitHub: `jaimemorenov621-cmyk/gym-tracker`
  - URL producción: `https://gym-tracker-uoex.onrender.com`
  - Base de datos: `gym-tracker-db` (Render Postgres, plan gratuito)
  - **Start Command (crítico):** `flask db upgrade && gunicorn app:app` — las migraciones deben ejecutarse antes de arrancar gunicorn en cada deploy
- **Estructura del proyecto:**
```
gym_tracker/
  app/
    __init__.py
    models.py
    forms.py
    routes.py
    static/
      style.css
    templates/
      base.html, index.html, login.html, register.html,
      new_workout.html, workout_detail.html, finish_workout.html,
      exercise_progress.html, exercise_notes.html, settings.html,
      routines.html, new_routine.html, routine_detail.html
  migrations/
  config.py
  gymtracker.py
  import_exercises.py   (script de importación de catálogo, ejecución manual única)
  requirements.txt
  .flaskenv
```

---

## 3. Funcionalidades implementadas ✅

### 3.1 Autenticación
- Registro, login, logout (patrón estándar Flask-Login, reutilizado de un proyecto anterior del usuario)

### 3.2 Entrenamientos (Workout)
- Crear entrenamiento (`/workout/new`), con nota/nombre opcional
- **Solo un entrenamiento activo a la vez**: se bloquea crear uno nuevo o iniciar una rutina si ya existe un `Workout` del usuario con `performance_rating IS NULL` y `timestamp` dentro de las últimas 6 horas; redirige al entrenamiento en curso con un mensaje flash
- Finalizar entrenamiento (`/workout/<id>/finish`): formulario con valoración de rendimiento 1-10 (escala redefinida para que el 10 sea alcanzable en una buena sesión normal, no "la mejor sesión de tu vida") + comentario de texto libre opcional
- Al finalizar se guarda `Workout.ended_at` (usado para calcular duración real)
- Eliminar entrenamiento (con confirmación JS)
- Duración de sesión:
  - **En vivo** mientras el entrenamiento está activo (`ended_at` es `None`): cronómetro JS en el header, actualizado cada segundo, formato `Xh Ymin Zs`
  - **Fija** una vez finalizado: se calcula con `Workout.duration_str()` a partir de `ended_at - timestamp`
  - Importante: el cronómetro en vivo **no debe ejecutarse** al revisar un entrenamiento antiguo ya finalizado (bug corregido explícitamente)

### 3.3 Series (SetEntry) — interfaz tipo Hevy
- Tabla editable en línea por ejercicio (no formulario clásico): columnas `# | Kg | Reps | RIR/RPE | Tipo | 🗑️`
- Añadir serie: botón "+ Agregar serie" que copia automáticamente los valores de la última serie del mismo ejercicio como punto de partida, vía `fetch` a `POST /workout/<id>/set`
- Editar celda: cualquier campo (peso, reps, esfuerzo, tipo) se edita haciendo clic directamente y se guarda vía `fetch PUT /set/<id>` al perder el foco (`onchange`)
- Eliminar serie: `fetch POST /set/<id>/delete`
- Campo `set_type`: `normal | calentamiento | fallo | dropset`
- Añadir ejercicio nuevo a la sesión: formulario con nombre libre (ahora con autocompletado del catálogo, ver 3.8)

### 3.4 Esfuerzo percibido (RIR/RPE)
- **Es una preferencia por usuario**, no por entrenamiento ni por serie (`User.effort_scale`: `'rir' | 'rpe' | 'none'`), configurable en `/settings`
- `SetEntry` guarda `rir` y `rpe` como enteros opcionales; solo uno se rellena según la escala activa en el momento de crear la serie
- Si el usuario cambia de escala con el tiempo, el histórico queda mixto (algunas series con RIR, otras con RPE) — el código de análisis lee el campo que esté relleno en cada serie individual, no depende de la configuración actual del usuario
- Equivalencia usada: **RPE = 10 − RIR**
- ⚠️ Bug conocido y corregido: WTForms `DataRequired()` rechaza el valor `0` como si estuviera vacío (Python trata `0` como falsy). Los campos numéricos donde 0 es válido (como RIR) deben usar `InputRequired()`, no `DataRequired()`

### 3.5 Notas técnicas por ejercicio (ExerciseNote)
- Un registro por combinación `(user_id, exercise)` (restricción única en BD)
- Notas de texto libre (una línea = un punto en la lista renderizada)
- **Se muestran siempre visibles**, sin necesidad de clicar ningún enlace, debajo del nombre de cada ejercicio ya registrado en la sesión actual (requisito explícito del usuario, inspirado en cómo Hevy las muestra)
- También incluyen el tiempo de descanso predeterminado del ejercicio (ver 3.6)
- Editables desde `/exercise/<name>/notes`, accesible desde cualquier pantalla donde aparezca el ejercicio (entrenamiento actual, rutinas, página de progreso)

### 3.6 Temporizador de descanso
- Cada `ExerciseNote` tiene `default_rest_seconds` (entero opcional)
- Widget flotante (`.rest-toast`, esquina inferior derecha) definido **una sola vez en `base.html`** (no en cada plantilla) para que persista visualmente al navegar entre páginas
- **Persiste entre páginas mediante `localStorage`** (`restEndTime`, `restExercise`) — si el usuario navega a otra página mientras el descanso corre, sigue contando
- Se **autoinicia** automáticamente tras añadir una serie (con el tiempo predeterminado de ese ejercicio, o 90s si no hay ninguno guardado)
- Si se añade otra serie mientras el temporizador anterior sigue corriendo, se **reemplaza** por el nuevo (no se acumulan)
- Botones +15s / −15s para ajustar sobre la marcha (funcionan tanto si el temporizador está corriendo como si aún no se ha iniciado)
- Al llegar a 0: pitido generado con Web Audio API (sin archivos de audio externos), notificación del navegador si hay permiso concedido, si no `alert()` de respaldo; **el widget desaparece automáticamente**
- Se oculta/limpia por completo si no hay un entrenamiento activo (`active_workout` es `None` vía el `context_processor`) — así no queda "fantasma" corriendo tras finalizar un entrenamiento
- Minimalista: **no** tiene inputs de minutos/segundos visibles permanentemente (se quitaron a petición explícita del usuario para reducir el tamaño del widget)
- Guarda automáticamente el tiempo usado como nuevo predeterminado para ese ejercicio (`fetch POST /exercise/<name>/rest_default`)

### 3.7 Detección de estancamiento y progresión
- Ruta `/exercise/<name>`: histórico completo de un ejercicio, ordenado cronológicamente
- **1RM estimado** por sesión: fórmula de Epley (`peso × (1 + reps_efectivas / 30)`), usando **"repeticiones efectivas"** = reps reales + RIR (o + (10 − RPE) si la escala es RPE) — esto evita que el sistema marque estancamiento falso cuando el peso/reps se mantienen pero el esfuerzo percibido mejora
- Se toma la serie de mayor 1RM estimado de cada sesión (no la primera, no una media)
- **Definición de estancamiento** (ya corregida tras un primer intento fallido que el propio usuario identificó como erróneo para datos con ruido): *"ninguna de las últimas N sesiones ha superado el récord histórico de 1RM estimado"*, donde N = `User.stagnation_threshold` (configurable en `/settings`, rango 1-20, por defecto 3). Se sustituyó una lógica anterior basada en "3 sesiones consecutivas sin mejorar en orden estricto", que fallaba con progresiones no lineales
- Se marca `is_pr` (récord personal) por sesión y se resalta con 🏆
- Gráfica Chart.js del 1RM a lo largo del tiempo, con puntos coloreados: verde = récord, rojo = parte de la racha de estancamiento, azul = normal
- Avisos visuales de "posible estancamiento" (rojo) y "¡nuevo récord!" (verde)

### 3.8 Catálogo de ejercicios con imágenes ⚠️ RECIÉN IMPLEMENTADO, NO CONFIRMADO POR EL USUARIO TODAVÍA
Esta es la **última funcionalidad entregada antes de este documento de traspaso**. El código fue escrito pero el usuario **no ha confirmado que funcione** — es el primer punto a verificar al retomar.

- Fuente de datos: **free-exercise-db** (https://github.com/yuhonas/free-exercise-db), dataset de dominio público (licencia Unlicense), 800+ ejercicios con imágenes reales, verificado como legítimo para uso sin restricciones
  - JSON combinado: `https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json`
  - Imágenes: `https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/{ID}/0.jpg`
- Nuevo modelo `Exercise` (id, name, category, primary_muscles, equipment, image_url)
- Script `import_exercises.py` en la raíz, ejecución manual única (`python import_exercises.py`), idempotente (salta ejercicios ya existentes)
- **Decisión de diseño deliberada:** el catálogo es una **capa de apoyo**, no sustituye el campo de texto libre `exercise` (string, en minúsculas) que ya usan `SetEntry`, `RoutineExercise` y `ExerciseNote`. Se decidió así para no arriesgar una migración de datos reales ya existentes del usuario. El catálogo aporta:
  - Autocompletado con imagen al escribir el nombre de un ejercicio nuevo (`GET /api/exercises/search?q=...`, JS con debounce de 250ms)
  - Función `get_exercise_image(name)` (registrada como global de Jinja) que busca coincidencia case-insensitive en el catálogo y devuelve la URL de imagen si existe, usada en `workout_detail.html` (junto al nombre de cada ejercicio) y `exercise_progress.html` (cabecera)

### 3.9 Rutinas (Routine / RoutineExercise)
- CRUD completo de rutinas: crear (`/routines/new`), listar (`/routines`, con nombre de ejercicios y fecha de última vez usada), ver detalle (`/routines/<id>`)
- Añadir ejercicios a una rutina con series/reps objetivo (`target_sets`, `target_reps` como texto tipo "8-10")
- **Reordenar ejercicios de una rutina arrastrando** (SortableJS + `fetch POST /routines/<id>/reorder`) — se descartó una implementación anterior con botones ⬆️⬇️ por ser menos usable, esa ruta (`move_routine_exercise`) fue eliminada del código
- Eliminar ejercicio individual de una rutina (icono de papelera, sin fondo rojo sólido)
- Eliminar rutina completa (con confirmación); al eliminar, los `Workout` que la referencian quedan con `routine_id = NULL` (no se borran los entrenamientos históricos)
- **Iniciar rutina** (`POST /routines/<id>/start`): crea un `Workout` nuevo con `routine_id` enlazado y `note` = nombre de la rutina; respeta la regla de "un entrenamiento activo a la vez"
- Dentro de `workout_detail`, si el entrenamiento viene de una rutina, se muestra un panel "Plan de la rutina" con cada ejercicio objetivo y contador `hecho/objetivo` de series
- **Guardar un entrenamiento ya realizado como rutina nueva** (`POST /workout/<id>/save_as_routine`), acción manual desde el menú de tres puntos — deliberadamente **no automático**, para que no se creen rutinas sin que el usuario lo pida

### 3.10 Página de inicio (`/index`)
- Entrenamientos agrupados por semana ISO (`isocalendar()`), con etiqueta de rango de fechas por grupo
- Cada tarjeta de entrenamiento muestra: fecha/hora, nombre, primeros nombres de ejercicios realizados, número de series, volumen total (Σ peso×reps), duración (si ya finalizado)
- Estadísticas: total de entrenamientos, racha actual (ver limitación conocida en sección 5)
- Calendario visual de los últimos 3 meses: cuadrícula de días, verde si se entrenó ese día, con el número del día visible dentro de cada casilla, desplazable horizontalmente en pantallas pequeñas

### 3.11 Diseño visual (rediseño ya bastante avanzado)
- Paleta principal morada (`#7c4dff` / `#536dfe`, degradados)
- **Ningún elemento clicable debe verse como enlace subrayado clásico** — todo son botones (`.btn`, `.btn-outline`) o "chips" (`.set-tag`, `.rest-badge`) — requisito explícito y repetido del usuario
- Verde (`.btn-finish`) reservado **únicamente** para "Guardar y finalizar" — se probó también en "Iniciar entrenamiento" pero el usuario pidió revertirlo por no encajar con el resto de la paleta; "Iniciar" (tanto en rutinas como en detalle de rutina) usa `.btn` (morado)
- Acciones destructivas: nunca rojo sólido — icono de papelera sin fondo (`.btn-icon`) para acciones menores, borde rojo con fondo blanco (`.btn-danger-outline`) para acciones importantes como "Eliminar rutina"/"Eliminar entrenamiento"
- Acciones secundarias/poco frecuentes (guardar como rutina, eliminar entrenamiento) agrupadas en un menú de tres puntos (`.action-menu`) para no competir visualmente con la acción principal
- Datos cortos (fechas, horas, RIR/RPE, descanso, rendimiento) mostrados como chips (`.set-tag`), nunca como texto plano — regla general a aplicar en cualquier plantilla nueva o revisada
- Notas técnicas y comentarios largos sí pueden ir en texto/`<p>`, la regla de "todo chip" aplica a datos cortos, no a texto libre extenso
- **Se pausó deliberadamente el trabajo estético** a petición del usuario para priorizar funcionalidad — ver sección 6

---

## 4. Funcionalidades pendientes ⏳ (nada de esto existe en el código)

En orden de prioridad declarada por el usuario en la última parte de la conversación:

1. **Integración de IA** (prioridad alta, próximo paso natural): analizar histórico de entrenamientos y dar recomendaciones. No hay ningún código, dependencia, ni diseño técnico decidido todavía — ni siquiera se ha elegido proveedor (OpenAI/Anthropic/otro) ni modelo de coste
2. **Bi/triseries** (superseries): el usuario explícitamente dijo que "no le importa mucho" esta funcionalidad — deprioritizada frente a IA y catálogo de ejercicios. No hay ningún modelo ni campo en BD para esto
3. **Racha inteligente**: ajustar el cálculo de racha para que tenga en cuenta el plan/split real del usuario (p.ej. entrenar 4 días/semana no debería limitar la racha máxima a 2 días como ocurre ahora con el cálculo actual de días consecutivos). El usuario planteó el problema pero **no se decidió ningún diseño concreto** — queda abierto qué significa "racha" en este nuevo esquema (¿semanas cumpliendo objetivo? ¿sesiones sin saltarse más de N días?)
4. **Columna "ANTERIOR"** en la tabla editable de series (mostrar la marca de la sesión pasada junto a cada fila, como hace Hevy) — explícitamente deferred por complejidad/valor no prioritario
5. **Infraestructura de suscripción/monetización**: el usuario propuso que la IA sea una función de pago. Se le aconsejó explícitamente **no construir esto todavía** (0 usuarios externos reales) y esperar a tener usuarios reales antes de montar Stripe/gestión de planes — en su lugar, limitar el uso de IA con un tope simple (ej. "1 análisis por semana") mientras sea de uso personal
6. **Publicación en Play Store**: se discutió en términos generales (coste de cuenta de desarrollador ~25$ único, necesidad de empaquetar como TWA) pero no se ha empezado ningún trabajo técnico

---

## 5. Problemas conocidos / cosas a verificar al retomar

- ⚠️ **Verificar primero que el catálogo de ejercicios (sección 3.8) funciona de verdad** — es lo último que se implementó y no se confirmó con el usuario. Revisar: migración aplicada, `import_exercises.py` ejecutado con éxito, endpoint de búsqueda responde, autocompletado JS funciona, imágenes se muestran
- **Base de datos local (SQLite) fue borrada por completo al menos una vez** durante el desarrollo (comando `Remove-Item app.db` para resolver un conflicto de migración `NOT NULL`). Cualquier dato de prueba anterior a ese punto ya no existe en local. **La base de datos de producción (Render PostgreSQL) es independiente y no se vio afectada** — contiene datos reales de uso desde el móvil
- ⏰ **La base de datos PostgreSQL de Render (plan gratuito) tiene fecha de caducidad** (creada aprox. 23/07/2026, ~30 días de vida en el plan gratuito antes de requerir upgrade de pago o perderse). El usuario tiene un recordatorio de calendario para el 22/08/2026. **Al retomar el proyecto, comprobar el estado de la base de datos de producción antes de asumir que los datos siguen ahí**
- `app/static/style.css` tiene un par de bloques de reglas CSS duplicados de forma inofensiva (`select.cell-input` y `.btn-finish` aparecen definidos dos veces de forma idéntica/similar) — no rompe nada, pero es limpieza pendiente
- **Patrones de bugs recurrentes durante el desarrollo, útiles para no repetirlos:**
  - Migraciones Alembic sobre SQLite necesitan **nombre explícito** en cualquier `ForeignKey` que se añada a una tabla ya existente (`sa.ForeignKey("tabla.id", name="fk_explicito")`), si no, falla con `Constraint must have a name` al usar `batch_alter_table`
  - Al añadir una migración que crea tablas nuevas **y** una FK hacia ellas desde una tabla existente, el **orden importa en PostgreSQL** aunque no diera problema en SQLite local — las tablas referenciadas deben crearse antes del `ALTER TABLE` que añade la FK. Un despliegue en Render falló por este motivo con datos que en local "parecían" funcionar porque las tablas ya existían de un intento fallido anterior
  - Relaciones `WriteOnlyMapped` de SQLAlchemy necesitan `passive_deletes=True` explícito para poder borrar el padre sin recorrer toda la colección — si no, error `InvalidRequestError: ... full iteration is not permitted`
  - WTForms `DataRequired()` rechaza `0` como si estuviera vacío en campos numéricos — usar `InputRequired()` cuando 0 es un valor válido
  - Bloques de JavaScript duplicados por error al iterar sobre el widget del temporizador (pegados dos veces en `base.html`) causaron errores silenciosos de `let` redeclarado que rompían **todos** los scripts posteriores de la página — revisar que no haya duplicados si algo dependiente de JS deja de funcionar sin motivo aparente
  - PowerShell con `>` para redirigir salida a `requirements.txt` genera archivos con BOM/UTF-16 que rompen herramientas que esperan UTF-8 — usar siempre `Out-File -Encoding utf8`

---

## 6. Preferencias explícitas del usuario a respetar

- Prioriza **crítica honesta y objetiva** sobre validación — quiere que se le señalen errores de diseño o malas ideas directamente, no que se le siga la corriente
- **Ningún elemento interactivo debe parecer un enlace de texto subrayado** — todo botones o chips visuales
- **Nunca texto plano para datos cortos** (fechas, horas, contadores, RIR/RPE) — siempre como chip/badge con fondo de color
- **Nunca botones rojos sólidos** para acciones destructivas — prefiere iconos de papelera sin relleno o botones con borde rojo sobre fondo blanco
- Prefiere widgets flotantes con estilo propio consistente con la app antes que diálogos nativos del navegador cuando es viable (excepción aceptada: `confirm()`/`alert()` nativos para confirmaciones puntuales, sí se usan)
- **En este momento, prioriza estructura y funcionalidad sobre estética** — pausar mejoras visuales no solicitadas explícitamente hasta nuevo aviso
- Cuando se propone código, prefiere el archivo completo a reemplazar, o instrucciones muy precisas de "busca esto / sustitúyelo por esto" — ha tenido bastantes bugs por fragmentos de código mal ubicados o mezclados entre versiones distintas de un archivo

---

## 7. Siguiente paso acordado

En el momento de este traspaso, el usuario confirmó explícitamente que el siguiente bloque de trabajo es la **integración de IA** como funcionalidad de análisis del entrenamiento — una vez verificado que el catálogo de ejercicios (sección 3.8) funciona correctamente. No se ha empezado ningún diseño técnico de esta funcionalidad todavía: ni elección de proveedor, ni esquema de prompt, ni límites de uso, ni interfaz. Es terreno completamente abierto para la siguiente sesión de trabajo.
