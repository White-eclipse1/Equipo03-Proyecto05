# Plan del equipo — Proyecto 3

Entrega: **jueves 1 de octubre de 2026**. Arranque: **jueves 24 de septiembre**. Compuerta: si M1 (arranque), M2 (release aprobado de P2), M3 (particiones aisladas) o M4 (modelo recargable) fallan, la nota se topa en 60.

Todo cierra el **miércoles 30 (Control 3)**. El jueves 1 es exclusivamente revisión, feedback y corrección.

## Roles

| Persona | Rol | Fases | Puntos | Revisa sus PRs | Responsabilidad |
|---|---|---|---:|---|---|
| Diego | PM · datos · evaluación · entrega | F2, F3, F6, F7, F11 | 42 | Edith | PM del proyecto: dirige el kickoff de decisiones, custodia el test y vigila que la cadena release → recortes → split → run → checkpoint → test → S3 → predicción sea demostrable. Dueño del almacenamiento, los datos, la evaluación final y la publicación en S3; prepara la demo y pone el tag de entrega. |
| Edith | Líder de ML y MLOps | F1, F4, F5 | 32 | Andrés | Dueña del stack de entrenamiento: docker-compose con worker y MLflow, contratos, modelo, entrenador, barrido de corridas, selección del candidato y servicio de inferencia. |
| Andrés | Líder de portal y calidad | F8, F9, F10 | 26 | Diego | Dueño de las 5 páginas del portal, la CI, la prueba de extremo a extremo y el ensayo de arranque desde un clon limpio. |

Revisión en rotación: Diego → Edith → Andrés → Diego. Nadie aprueba su propio PR. Los puntos no equivalen a esfuerzo: la carga en horas es pareja (≈32 h cada uno).

## Cronograma

🟦 Diego · 🟩 Edith · 🟧 Andrés · `·` fin de semana (colchón)

| Fase | jue 24 | vie 25 | sáb 26 | dom 27 | lun 28 | mar 29 | mié 30 | jue 1 |
|---|---|---|---|---|---|---|---|---|
| F1 Kickoff, arranque del stack y contratos (Edith) | 🟩 |   | · | · |   |   |   |   |
| F2 Almacenamiento, release y recortes COCO (Diego) | 🟦 | 🟦 | · | · |   |   |   |   |
| F3 Manifiesto 70/20/10 sin fuga (Diego) |   | 🟦 | · | · | 🟦 |   |   |   |
| F4 Modelo, entrenador y servicio de inferencia (Edith) |   | 🟩 | · | · | 🟩 | 🟩 |   |   |
| F5 Experimentos MLflow y selección (Edith) |   |   | · | · | 🟩 | 🟩 |   |   |
| F6 Evaluación final en test (Diego) |   |   | · | · | 🟦 | 🟦 |   |   |
| F7 Paquete, tarjeta y publicación en S3 (Diego) |   |   | · | · |   | 🟦 | 🟦 |   |
| F8 Portal: Training y Experiments (Andrés) | 🟧 | 🟧 | · | · | 🟧 |   |   |   |
| F9 Portal: Evaluation, Models e Inference (Andrés) |   |   | · | · | 🟧 | 🟧 | 🟧 |   |
| F10 Pruebas, CI y ensayo de arranque (Andrés) | 🟧 | 🟧 | · | · | 🟧 | 🟧 | 🟧 |   |
| F11 Autoevaluación, demo y congelación (Diego) |   |   | · | · |   |   | 🟦 |   |

## Fases

| ID | Fase | Responsable | Fechas | Puntos | Depende de | Bloquea a | Archivo |
|---|---|---|---|---:|---|---|---|
| F1 | Kickoff, arranque del stack y contratos | Edith | 24 sep | 0 | — | F2–F10 | `docs/fases/F1-arranque-contratos.md` |
| F2 | Almacenamiento, release y recortes COCO | Diego | 24 sep → 25 sep | 9 | F1 (contratos y decisiones) | F3, F7 | `docs/fases/F2-release-recortes.md` |
| F3 | Manifiesto 70/20/10 sin fuga | Diego | 25 sep → 28 sep | 5 | F2 | F5, F6 | `docs/fases/F3-manifiesto.md` |
| F4 | Modelo, entrenador y servicio de inferencia | Edith | 25 sep → 29 sep | 18 | F1 | F5, F9 | `docs/fases/F4-modelo-entrenador.md` |
| F5 | Experimentos MLflow y selección | Edith | 28 sep → 29 sep | 14 | F3, F4 | F6, F7, F8 | `docs/fases/F5-experimentos-seleccion.md` |
| F6 | Evaluación final en test | Diego | 28 sep → 29 sep | 18 | F3, F5 (selección) | F7, F9 | `docs/fases/F6-evaluacion-test.md` |
| F7 | Paquete, tarjeta y publicación en S3 | Diego | 29 sep → 30 sep | 10 | F5, F6 | F9, F11 | `docs/fases/F7-paquete-s3.md` |
| F8 | Portal: Training y Experiments | Andrés | 24 sep → 28 sep | 7 | F1 (contratos) | F9 | `docs/fases/F8-portal-training-experiments.md` |
| F9 | Portal: Evaluation, Models e Inference | Andrés | 28 sep → 30 sep | 11 | F4, F6, F7 | F10 | `docs/fases/F9-portal-evaluation-models-inference.md` |
| F10 | Pruebas, CI y ensayo de arranque | Andrés | 24 sep → 30 sep | 8 | F1 (CI arranca el jueves 24) | F11 | `docs/fases/F10-pruebas-ci.md` |
| F11 | Autoevaluación, demo y congelación | Diego | 30 sep | 0 | F1–F10 | — | `docs/fases/F11-autoevaluacion-cierre.md` |

## Controles

- **Control 1 → jueves 24:** el stack arranca desde un clon limpio con portal, worker y MLflow persistente; contratos congelados (`manifest`, `training_config`, `selection.json`, `model_version`); CI corriendo con Ruff, pytest y build del frontend; las 5 rutas visibles en la navegación existente.
- **Control 2 → lunes 28 a mediodía:** clases fijadas con commit, manifiesto 70/20/10 congelado y versionado en DVC con intersecciones vacías demostradas, entrenador con early stopping registrando en MLflow. Arranca el barrido.
- **Control 3 → miércoles 30:** congelación total. Selección por validación con commit antes de la evaluación en test, modelo en S3, 5 páginas con datos reales, E2E en verde, autoevaluación completa con el prompt de la rúbrica (incluida la inyección de datos malos) y todo revertido antes de etiquetar.

## Git

**Nadie hace push directo a `main`; todo cambio entra por PR.** Nadie mergea su propio PR: hace falta la aprobación de otro de los tres, con una review real (no un "LGTM" vacío). Ramas por fase, no por persona: `feat/fase-N-*`.

Las reglas completas del equipo están en `AGENTS.md`.
