# CLAUDE_HANDOFF.md — GymTracker

Traspaso de sesión, generado el 18/08/2026 (madrugada), al final de una sesión muy larga de Claude Code. Léase junto con `CLAUDE.md` (convenciones del proyecto) y `GYMTRACKER_HANDOFF_1.md` (traspaso anterior, contexto de fondo del proyecto/usuario — sigue siendo válido salvo donde este documento lo actualice).

## 1. Estado actual del proyecto

- **Producción**: `https://gym-tracker-uoex.onrender.com`, Render (plan gratuito). Repo en GitHub: `jaimemorenov621-cmyk/gym-tracker`, rama `main`.
- **Todo está pusheado**: `git status` limpio, `origin/main` al día con local (último commit `0a76acd`, pusheado justo antes de escribir este documento). Render tiene auto-deploy activado (`Start Command: flask db upgrade && gunicorn app:app` — las migraciones se aplican solas en cada deploy, no hace falta tocar producción a mano salvo scripts de datos como `import_exercises.py`/`fix_exercise_names.py`).
- **Deploy del último push**: recién lanzado al terminar esta sesión, no confirmado como "live" todavía — **verificar en el dashboard de Render o en la propia app** al retomar el trabajo.
- **Base de datos de producción (Render, gratuita)**: expiraba ~23/08/2026 salvo upgrade. Jaime confirmó que pagará el upgrade, pero no hay constancia de que ya se haya hecho — **confirmar si sigue viva y si se ha actualizado el plan** antes de asumir que los datos siguen ahí.
- **Local**: SQLite (`app.db`), migraciones aplicadas hasta el head `e9f4eebdde96`. Usuario real: `Jaime` (id 1). Hay también un usuario `smoketest_ai` (id 2) preexistente de origen desconocido, no tocado.

## 2. Funcionalidades implementadas en esta sesión (orden cronológico)

1. **Análisis de progreso con IA** (`gpt-5.6-luna` de OpenAI): nuevo modelo `AiAnalysis`, rutas `/ai/analysis` (ver) y `/ai/analyze` (generar, límite 1/semana aplicado en servidor), resumen construido a partir del historial real (`build_progress_summary()`).
2. **Normalización de nombres de ejercicio**: `find_catalog_exercise()` ahora ignora acentos; nuevos ejercicios se canonizan contra el catálogo al guardarse; script `fix_exercise_names.py` para corregir variantes ya existentes (dry-run por defecto).
3. **Ronda de mejoras rápidas**: temporizador de descanso por defecto 90s→2min, imágenes de ejercicio más grandes, búsqueda de ejercicios por palabras sueltas (antes exigía coincidencia exacta), limpieza de series vacías al finalizar entrenamiento, animación de tick/celebración al terminar entreno o superar récord.
4. **Bloqueos de integridad de datos**: no se puede marcar el tick de una serie con 0 repeticiones; no se puede finalizar un entrenamiento sin ninguna serie con repeticiones.
5. **Imágenes del catálogo migradas a `cdn.jsdelivr.net`** (antes `raw.githubusercontent.com`, que empezó a devolver 429 Too Many Requests en producción).
6. **Icono genérico SVG** (mancuerna, morado de marca) para ejercicios sin coincidencia en el catálogo; tick y fila de serie más visuales (escala/sombra en el tick, tinte morado tenue en la fila completada).
7. **Efecto de brillo (light sweep)** al marcar una serie como completada — barrido de izquierda a derecha, una sola vez, respeta `prefers-reduced-motion`.
8. **Rediseño del panel "Mis entrenamientos"**: de bloques sueltos (`stats-row` + calendario en `.card`) a un único `.dashboard-panel` cohesionado.
9. **Columna "ANTERIOR"** en la tabla de series de cada ejercicio — una sola consulta para todo el entrenamiento (`get_previous_sets_map()`), sin N+1.
10. **Perfil de usuario**: `sex`, `height_cm`, `training_goal` — gestionables desde Configuración.
11. **Registro de peso corporal**: modelo `BodyWeightEntry`, ruta `/weight` con formulario + gráfica (Chart.js).
12. **% de cambio de fuerza**: `compute_strength_change()`, mostrado en el panel de resumen.
13. **Peso corporal en el panel de resumen**: cuarta métrica.
14. **Mapa muscular con intensidad real**: dos siluetas (frontal + posterior) coloreadas por grupo muscular según entrenamiento reciente, con silueta que varía según `sex`.

## 3. Archivos modificados y por qué

- **`app/models.py`**: `AiAnalysis`, `BodyWeightEntry` (modelos nuevos); `SetEntry.completed`; `User.sex`/`height_cm`/`training_goal`.
- **`app/routes.py`**: el archivo que más ha crecido. Nuevas rutas (`/ai/analysis`, `/ai/analyze`, `/weight`); nuevos helpers reutilizables — `get_exercise_sessions()` (extraído de `exercise_progress()`), `get_previous_sets_map()`, `compute_streak()` (extraído de `index()`), `compute_strength_change()`, `compute_muscle_intensity()`, `_effort_factor()`, `find_catalog_exercise()` con fallback sin acentos, `canonicalize_exercise_name()`, `get_rest_seconds()`. Validaciones añadidas en `api_update_set()` y `finish_workout()`.
- **`app/forms.py`**: `WeightForm`; `SettingsForm` ampliado con sexo/altura/objetivo.
- **`app/templates/index.html`**: reescrito casi entero — panel de resumen unificado con 4 métricas + mapa muscular (2 SVGs por sexo) + calendario.
- **`app/templates/workout_detail.html`**: columna ANTERIOR, tick/fila con animaciones (`.just-checked`, `.set-row-sweep`), icono genérico de ejercicio.
- **`app/templates/settings.html`**, **`app/templates/weight.html`** (nueva), **`app/templates/ai_analysis.html`** (nueva), **`app/templates/base.html`** (nav: enlaces "IA" y "Peso").
- **`app/static/style.css`**: `.dashboard-panel`/`.dash-*`, `.mm-*` (mapa muscular), `.set-check-btn`/`.set-row-done`/`.set-row-sweep`, primera `@media` query del proyecto.
- **`import_exercises.py`**: `IMAGE_BASE` cambiado a jsdelivr.
- **`fix_exercise_names.py`** (nuevo): script de limpieza de variantes de nombre de ejercicio.
- **`requirements.txt`**: añadido `openai` (y sus dependencias transitivas, vía `pip freeze` completo).
- **9 migraciones nuevas** (ver sección 9).
- **`GYMTRACKER_HANDOFF_1.md`**: Jaime añadió a mano una nota sobre el objetivo comercial a medio plazo (no tocado por Claude, solo comiteado en un commit aparte a petición suya).

## 4. Commits de esta sesión (más reciente arriba)

```
0a76acd Mapa muscular con intensidad real (frente + espalda, por sexo)
c5a38c1 Muestra el último peso registrado en el panel de resumen
0d72f1a % de cambio de fuerza en el panel de resumen
f3d04e4 Registro de peso corporal con gráfica
c3fb3f0 Perfil: sexo, altura y objetivo
44a019e Columna "ANTERIOR" en la tabla de series
0cc04c0 Rediseña "Mis entrenamientos" como panel de resumen unificado
372c3bc Actualiza la visión del proyecto: objetivo comercial a medio plazo (edición manual de Jaime)
5c56edb Efecto de brillo al completar una serie
1af6872 Icono genérico para ejercicios sin catálogo, tick y fila más visuales
4442391 Sirve las imágenes de ejercicios desde jsdelivr en vez de raw.githubusercontent.com
99b7edd No permitir confirmar series ni finalizar entrenamientos vacíos
3140172 Ronda de mejoras rápidas: temporizador, imágenes, búsqueda, limpieza y celebraciones
3a191cb Normaliza nombres de ejercicio ignorando tildes al guardarlos
7d253a2 Añade análisis de progreso con IA (GPT-5.6 Luna)
789a02a Botón de confirmación por serie que dispara el temporizador de descanso
a14d76f Catálogo de ejercicios con imágenes y traducción, temporizador de descanso y ended_at
```
Todos pusheados a `origin/main`. `git log` para ver diffs completos si hace falta detalle línea a línea.

## 5. Backlog pendiente

**Sin ambigüedad de diseño, listo para retomar cuando Jaime quiera:**
- Nada — los ítems de esta categoría (columna ANTERIOR, perfil, peso corporal, %fuerza, peso en panel, mapa muscular) se completaron todos esta noche.

**Necesita conversación de diseño con Jaime antes de tocar código:**
- **Racha inteligente**: `compute_streak()` solo cuenta días consecutivos; Jaime quiere que respete su split real (entrenar 4 días/semana no debería limitar la racha a 2 como pasa hoy). Sin diseñar.
- **Análisis de IA más interactivo/visual**: hoy es texto plano en `ai_analysis.html`. Decisión de gusto, sin acordar.
- **Rediseño visual grande estilo Whoop** del resto de la app: el nuevo `.dashboard-panel` es el estilo de referencia (a Jaime le gustó mucho), pero el resto de la app no se ha tocado.
- **Cita del eslogan** ("Lo que no se mide..."): Jaime preguntó por atribuirla a Peter Drucker; se le avisó de que es casi con certeza una cita mal atribuida (sin fuente verificada). Pendiente de su decisión — no añadir la atribución sin que él lo confirme.

**Aparcado explícitamente (no retomar sin que lo pida):**
- Rutinas predefinidas para usuarios nuevos (0 usuarios externos reales hoy).
- Monetización / Play Store (misma razón; cuando se retome, recordar que cobrar por web con Stripe es más simple que la facturación de Google Play).

## 6. Decisiones de diseño ya tomadas — respetar sin volver a preguntar

- **Proveedor de IA**: `gpt-5.6-luna` (OpenAI), elegido tras comparar precio/calidad reales con Claude Haiku 4.5 (ninguno de los dos modelos existía en el conocimiento de Claude antes de la fecha de corte — se verificó con búsquedas web, no se asumió nada).
- **El sexo del usuario NO se envía a la IA** — decisión explícita de Jaime ("no guardar un dato personal porque sí"). Solo se usa para elegir la silueta del mapa muscular. Altura y objetivo sí van al prompt.
- **% de cambio de fuerza**: ponderado por nº de sesiones recientes (no media simple — Jaime dio un ejemplo concreto de por qué una media simple engaña), con techo/suelo [-50%, +100%] — Jaime dudó de esto y luego **reafirmó explícitamente que sí lo quiere**, no quitarlo.
- **Intensidad del mapa muscular usa `weight * reps * _effort_factor(entry)`, NO `effective_reps()`**: se detectó durante la implementación que `effective_reps()` (usada para estimar 1RM) va en la dirección contraria a la necesaria para "estrés muscular" — más RIR ahí significa más margen y por tanto una estimación de fuerza máxima más alta, pero para el mapa muscular una serie cerca del fallo (RIR bajo/RPE alto) debe contar como MÁS estímulo, no menos. `_effort_factor()` fue verificada con aserciones automáticas (RIR bajo > RIR alto, RPE alto > RPE bajo). **Esto es una desviación del plan que Jaime aprobó literalmente** (el plan decía reutilizar `effective_reps()`) — se le avisó explícitamente, pero no ha dado el visto bueno todavía a la fórmula concreta.
- **Imágenes de ejercicio**: siempre `cdn.jsdelivr.net/gh/yuhonas/free-exercise-db@main/exercises/...`, nunca `raw.githubusercontent.com` (rate-limited en producción).
- **Migraciones**: revisar siempre a mano el archivo autogenerado antes de `flask db upgrade` — ya hubo un caso real (antes de esta sesión) de un booleano mal generado para Postgres que funcionaba en SQLite local pero rompía producción.
- **Commits**: uno por funcionalidad lógica, nunca mezclar cambios de Claude con ediciones manuales de Jaime en el mismo commit (se le preguntó explícitamente y así lo prefiere).
- **Push**: Jaime confirma cada push explícitamente en sesiones normales — la excepción de "trabajar sin `git push`" de esta noche fue solo porque él estaba ausente, ya se hizo el push pendiente al empezar esta sesión de traspaso.

## 7. Decisiones pendientes de aprobación de Jaime

- **Diseño visual del mapa muscular**: construido sin las imágenes de referencia que Jaime tenía en mente (no se pudieron adjuntar en esa conversación). Es una interpretación propia razonada, no un diseño validado por él. **Enseñárselo en el navegador antes de considerarlo cerrado.**
- **Fórmula `_effort_factor()`** del mapa muscular (ver punto 6) — funcionalmente correcta y verificada, pero es una desviación del plan literal aprobado. Confirmar que le parece bien el enfoque.
- **Cita de Peter Drucker** en el eslogan de la home — sin decidir.

## 8. Problemas, errores y limitaciones encontrados

- **`raw.githubusercontent.com` daba 429 en producción** para las imágenes del catálogo — resuelto migrando a jsdelivr (commit `4442391`), incluye actualización retroactiva de las 873 URLs ya guardadas (local y producción).
- **Migración con booleano mal generado para Postgres** (antes de esta sesión, pero relevante como patrón): Alembic autogenera a veces `server_default=sa.text('0')` para un booleano, que funciona en SQLite pero rompe en Postgres (`server_default=sa.false()` es la forma correcta, portable). Revisar siempre las migraciones autogeneradas a mano.
- **`--no-reload` en el servidor de desarrollo local**: usado toda la sesión para evitar la confusión de procesos zombie del reloader de Werkzeug visto al principio de la sesión — pero implica que **hay que reiniciar manualmente el servidor tras cada cambio de código** para probarlo (se me olvidó una vez esta noche y perdí tiempo con un `UndefinedError` que en realidad era código no recargado, no un bug real).
- **El panel de pruebas ligero (Claude_Browser) tiene limitaciones reales de renderizado**: `getComputedStyle` en elementos `<tr>` a veces no refleja el `background-color` real (confirmado con pruebas en Chrome real que sí funciona correctamente — no es un bug de la app, es una limitación de esa herramienta de test concreta). Las pestañas en segundo plano (`document.hidden === true`) también pausan `setTimeout`/animaciones CSS, lo que puede dar falsos negativos al verificar temporizadores/animaciones — si algo parece no disparar un evento `animationend`, comprobar primero si la pestaña está en primer plano antes de asumir que es un bug real.
- **`ExerciseNote` huérfanas**: los scripts de limpieza de usuarios de prueba de esta sesión no siempre borraron `ExerciseNote` además de `set_entry`/`workout`/`user`, dejando alguna fila huérfana en local con un `user_id` que luego se reasignó a otro usuario de prueba por autoincremento de SQLite. Sin impacto real (solo local, solo entre usuarios de prueba), pero si aparece un `default_rest_seconds` inesperado en un test futuro, revisar `ExerciseNote` por `user_id` huérfano antes de asumir un bug.
- **La clase `class="card"`** usada en varias plantillas (`workout_detail.html`, `routines.html`, etc.) **no tiene ninguna definición en `style.css`** — no pinta nada, es una clase sin efecto. Detectado al rediseñar `index.html` (que ya no la usa). No se ha tocado en el resto de plantillas, es solo un hallazgo de paso.
- **`Exercise.primary_muscles`** (usado por el mapa muscular) solo existe para ejercicios que coinciden con el catálogo vía `find_catalog_exercise()` — ejercicios de texto libre sin match no aportan a ningún grupo muscular. Limitación de diseño conocida y aceptada.

## 9. Estado de las migraciones

Head local y (tras el próximo deploy) de producción: **`e9f4eebdde96`**.

Migraciones nuevas de esta sesión (todas ya aplicadas en local y comiteadas; se aplicarán solas en producción en el próximo deploy vía `flask db upgrade` del Start Command):
```
4b1a98fe2152  add_completed_to_set_entry
7faa7fed9150  add_ai_analysis
923d53e4ff89  add_sex_height_cm_training_goal_to_user
e9f4eebdde96  add_body_weight_entry
```
Todas revisadas a mano tras autogenerarse — sin sorpresas de tipos/defaults esta vez.

## 10. Cambios sin commit

**Ninguno.** `git status` limpio al terminar la sesión, todo comiteado y pusheado.

## 11. Tests / verificaciones realizadas

Sin suite de tests automatizada en el proyecto (según `CLAUDE.md`) — toda la verificación de esta sesión fue manual, con usuarios de prueba creados y **siempre eliminados después**, nunca tocando los datos reales de Jaime (usuario `Jaime`, id 1) salvo para visualizar (lectura) en un par de comprobaciones puntuales.

Metodología usada (más fiable que la automatización de navegador para este proyecto):
- **Peticiones HTTP directas con `curl`** (login con CSRF token real, POST a las rutas, `grep` sobre el HTML de respuesta) para verificar renderizado servidor — más rápido y fiable que un navegador automatizado para confirmar contenido.
- **Llamadas directas a las funciones Python** dentro de `app.test_request_context()` con `login_user()`, para verificar lógica de negocio sin pasar por HTTP.
- **Verificación numérica manual**: para `compute_strength_change()`, se sembraron datos con 1RM conocidos y se comprobó a mano que el resultado ponderado coincidía con el cálculo esperado (14.44% vs 18.33% de una media simple). Para `compute_muscle_intensity()`, se verificó el color interpolado byte a byte contra el cálculo RGB esperado.
- **Chrome real** (`mcp__claude-in-chrome__*`) para capturas visuales finales de cada funcionalidad — usado con cautela para no tocar la sesión real de Jaime (siempre `/logout` + login explícito con el usuario de prueba antes de cualquier verificación).

Todo lo implementado esta noche pasó su verificación correspondiente antes de comitearse (detalle en cada mensaje de commit).

## 12. Siguiente paso recomendado

1. **Confirmar que el último deploy (commit `0a76acd`) terminó bien en Render** y que la base de datos de producción sigue viva (revisar la fecha de expiración del plan gratuito).
2. **Probar en producción, con tu cuenta real**: el panel de resumen nuevo, el registro de peso, el % de fuerza, y sobre todo **el mapa muscular** — es la pieza que más necesita tu ojo antes de darla por buena.
3. Si el mapa muscular no coincide con lo que tenías en mente, esta vez sí seríamos capaces de adjuntar las imágenes de referencia en la nueva sesión para ajustarlo con precisión.
4. Decidir el siguiente ítem del backlog: probablemente **racha inteligente** (es la pieza "pendiente sin ambigüedad de diseño" más antigua) o continuar el rediseño visual grande usando `.dashboard-panel` como referencia de estilo — ambas necesitan conversación de diseño contigo antes de que Claude toque código.

## 13. Contexto adicional para no repreguntar cosas ya decididas

- Jaime es estudiante de ingeniería informática (primer año superado), sin experiencia previa en desarrollo web — GymTracker es su primer proyecto real, aprendiendo sobre la marcha. Explicar el porqué de las decisiones técnicas, no solo el qué (así ha funcionado bien toda la sesión).
- Prefiere que se le den recomendaciones objetivas con contras explícitos, no solo la opción más fácil de implementar (instrucción explícita en su `CLAUDE.md` global).
- Le gusta revisar y aprobar cada `git push` explícitamente — no asumir que "hecho localmente" implica luz verde para producción.
- Cuando pide "un plan grande para trabajar solo", espera que se elijan deliberadamente los ítems del backlog **sin ambigüedad de diseño** y se dejen fuera los que requieren su gusto/criterio — y que se le avise con claridad de cualquier desviación del plan aprobado, aunque sea una mejora (como pasó con `_effort_factor()`).
