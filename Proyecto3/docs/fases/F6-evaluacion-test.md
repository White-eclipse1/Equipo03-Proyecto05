# F6 — Evaluación final en test

| Campo | Valor |
|---|---|
| Responsable | Diego (PM · datos · evaluación · entrega) |
| Revisor de PRs | Edith |
| Fechas | 28 sep → 29 sep de 2026 |
| Rama | `feat/fase-6-evaluacion-test` |
| Puntos de rúbrica | 18 (4.1–4.4) |
| Depende de | F3, F5 (selección) |
| Bloquea a | F7, F9 |
| Control | Control 3 |

**Nota de calendario:** Diego es el custodio del test. Se implementa el lunes con el fixture; se ejecuta UNA vez el martes, después de la selección.

> Antes de empezar lee `AGENTS.md` (contexto y reglas) y `docs/contratos.md`. Trabaja los bloques en orden; cada bloque es al menos un PR.

## Bloque T15 — Evaluación final en test congelado

**Objetivo:** Implementar (lunes, con el fixture) y ejecutar UNA vez (martes, tras T14) la evaluación del candidato elegido sobre el 10% de test.

**Criterios de rúbrica:** 4.1, 4.2, 4.3

**Pasos**

1. Pruebas primero: la evaluación se niega a correr si no existe docs/selection.json con run_id y checkpoint; matriz con filas=real y columnas=predicho, todas las clases, suma = total de test; accuracy = diagonal/total sin redondear; F1 macro y precision/recall/support por clase coinciden con sklearn.
2. Implementa evaluate.py: carga checkpoint y mapa de clases del run elegido, usa el preprocesamiento determinista compartido, infiere todos los crop_id de test.
3. Guarda predictions_test.csv (crop_id, clase_real, clase_predicha, probabilidades), la matriz y las métricas; regístralo todo como artefactos en el run de MLflow elegido junto con timestamp, hash del manifiesto y hash del checkpoint.
4. Ejecuta la evaluación final solo después de la selección; compara accuracy con 0.85 sin redondear.
5. Diego es el custodio del test (ver docs/decisiones.md): nadie más ejecuta inferencia ni calcula métricas sobre el test antes de este paso, y la evaluación final se corre una sola vez.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] La evaluación registra fecha posterior a selection.json — `metrics.json`: `evaluated_at` 2026-09-28T02:25:07Z (27 sep 20:25 -06:00) y `selection_commit` `6bd9101` del 26 sep 21:40; `scripts/final_evaluation.py` exige `selection.json` versionado y sin cambios antes de correr ([analisis_errores.md](../analisis_errores.md#protocolo-y-cronología-41))
- [x] Matriz recalculada desde predictions_test.csv coincide con MLflow — recalculada con código aparte: `[[30,2,0],[0,38,0],[0,1,74]]`, accuracy 142/145 = 0.9793103448275862, igual que `metrics.json`, que las métricas `test_*` de la corrida `9f9b62c2…` en MLflow (snapshot `723d7c5`) y que `GET /api/p3/evaluation`; `--audit` vuelve a predecir y da `audit_matches: true`
- [x] Métricas por clase disponibles — precisión, recall, F1 y support por clase en `metrics.json`, en MLflow (`test_precision_*`, `test_recall_*`, `test_f1_*`) y en la API

**Entregables:** `src/p3/eval/evaluate.py`; `predictions_test.csv`; Artefactos en MLflow

## Bloque T16 — Análisis de errores y baseline

**Objetivo:** Explicar la calidad real del clasificador más allá del accuracy.

**Criterios de rúbrica:** 4.4

**Pasos**

1. Calcula el baseline de clase mayoritaria sobre el MISMO test.
2. Identifica la clase más confundida (par real->predicho con más errores) y el recall por clase; indica si el 85% oculta bajo recall de alguna clase.
3. Genera errors.json con N aciertos y N errores del test (crop_id, ruta del recorte, real, predicho, probabilidad) para que la página Evaluation los muestre.
4. Documenta en docs/analisis_errores.md.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Baseline calculado y comparado — clase mayoritaria `person` en el mismo test: 75/145 = 0.5172 frente a 0.9793 ([analisis_errores.md](../analisis_errores.md#el-979--oculta-una-clase-débil-44))
- [x] Ejemplos provienen solo de test (verificable por crop_id en el manifiesto) — `errors.json` (3 errores y 12 aciertos) solo con `crop_id` de `test`; lo protege `tests/test_evaluate.py::test_errores_y_aciertos_de_ejemplo_solo_de_test`

**Entregables:** `errors.json`; `docs/analisis_errores.md`

## Definición de terminado

- [ ] Todas las casillas de aceptación marcadas con evidencia real
- [ ] PRs fusionados con review de Edith
- [ ] CI en verde en `main`
- [x] Commits red → green visibles en el historial — métricas `82055bd` → `91331b0`; protocolo `1df6ab8` → `f34d2e5`; procedencia `9a3ba00` → `c0ffbda`; API `9599957` → `d7a1144`

## Registro de avance

| Fecha | Quién | Bloque | Qué se hizo / PR | Pendiente |
|---|---|---|---|---|
| 27 sep 2026 | Diego | T15 | `src/p3/eval/metrics.py` y `evaluate.py` (una sola corrida, auditoría sin escritura), `scripts/final_evaluation.py`. **Evaluación única** de r10 (`3792f93`): accuracy **0.9793103448275862** (142/145) ≥ 0.85, F1 macro 0.9744. Recalculada de forma independiente; `--audit` idéntico. Registrada en MLflow (`scripts/log_evaluation_mlflow.py`) y snapshot nuevo en DVC (`723d7c5`). `GET /api/p3/evaluation` (+ `/predictions`, `/examples`) montado en P2 y probado contra el MLflow real. 17 mutaciones detectadas (7 en métricas, 10 en el protocolo). | — |
| 27 sep 2026 | Diego | T16 | `docs/analisis_errores.md`: baseline 0.5172, par más confundido cat → dog, recall mínimo 0.9375 (cat); 3 errores leídos a ojo (2 gatos oscuros sin rostro, 1 recorte de persona dominado por un perro). `errors.json` para la página Evaluation. | Limitaciones a la tarjeta del modelo (F7) |
| 29 sep 2026 | Diego | T15 | `GET /api/p3/evaluation` responde **503** con motivo si MLflow no responde o da un error distinto de 404 (antes 500); el 404 de un artefacto sigue siendo "sin evaluación". Red `d99978b` → green (este PR). | — |
| 2 oct 2026 | Diego | F12 (C1) | Backend de 6.3 y 4.4: `GET /api/p3/evaluation` suma `release_id`, `manifest_hash`, `checkpoint_sha256` y `selected_at`; nuevo `GET /api/p3/evaluation/crops/{crop_id}` (409 / 404 / 422 / 503) y montaje de `data/crops` en la app. Red `c139bd3` → green (este PR); 8 mutaciones detectadas. Con los datos reales, los 15 ejemplos de la galería devuelven su PNG y un recorte de train da 404. | UI de Andrés (F14) |
