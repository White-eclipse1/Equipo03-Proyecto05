# F5 — Experimentos MLflow y selección

| Campo | Valor |
|---|---|
| Responsable | Edith (Líder de ML y MLOps) |
| Revisor de PRs | Andrés |
| Fechas | 28 sep → 29 sep de 2026 |
| Rama | `feat/fase-5-experimentos-seleccion` |
| Puntos de rúbrica | 14 (3.1, 3.2, 3.3) |
| Depende de | F3, F4 |
| Bloquea a | F6, F7, F8 |
| Control | Control 3 |

**Nota de calendario:** Barrido según el calendario medido en F4; selección con la métrica ya fijada en decisiones.md y commit de selection.json el martes antes de mediodía.

> Antes de empezar lee `AGENTS.md` (contexto y reglas) y `docs/contratos.md`. Trabaja los bloques en orden; cada bloque es al menos un PR.

## Bloque T13 — Barrido de ≥10 corridas válidas

**Objetivo:** Ejecutar al menos 10 corridas completas sobre el MISMO manifiesto congelado y la MISMA definición de clases, variando los 7 parámetros.

**Criterios de rúbrica:** 3.1

**Pasos**

1. Define en config/p3/sweep.yaml ≥12 combinaciones (margen por si alguna falla) donde optimizer, batch_size, max_epochs, learning_rate, image_size, hidden_layers y dropout aparecen cada uno con ≥2 valores. Ejemplo: optimizer {adam, sgd, adamw}, batch_size {32, 64}, max_epochs {15, 30}, lr {1e-3, 3e-4, 1e-2 para sgd}, image_size {128, 224}, hidden_layers {[256], [512,128]}, dropout {0.2, 0.5}.
2. Lanza las corridas por el worker (se pueden ejecutar de noche); ninguna corrida de un solo batch ni duplicada.
3. Al terminar, lista con mlflow.search_runs los run_id FINISHED con su mejor val_accuracy y guárdalo en docs/corridas.md.
4. NO mires ninguna métrica de test en este paso.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] ≥10 runs FINISHED con resultados distintos → [corridas.md](../corridas.md): 12 corridas FINISHED en `p3-clasificador`, val_acc de 0.9384 a 0.9966, todas con early stopping; las 2 interrumpidas por cortes de luz quedan como no válidas y se relanzaron
- [x] Cada uno de los 7 parámetros tiene ≥2 valores → [corridas.md](../corridas.md#comprobación-31): optimizer 3, batch_size 2, max_epochs 2, learning_rate 5, image_size 3, hidden_layers 3, dropout 3; `tests/test_sweep_config.py`
- [x] Todos con el mismo hash de manifiesto → tag `manifest_hash` = `45600f29…` en las 12 (el worker exige el manifiesto congelado); también `dvc_md5` `ca56420c…` y `crops_jsonl_sha256` `d3d61f35…`

**Entregables:** `config/p3/sweep.yaml`; `docs/corridas.md`

## Bloque T14 — Selección del candidato por validación

**Objetivo:** Elegir el modelo con una métrica de validación predeclarada, dejando evidencia fechada ANTES de evaluar en test.

**Criterios de rúbrica:** 3.3

**Pasos**

1. Implementa POST /api/p3/selection usando EXACTAMENTE la métrica y el desempate declarados en docs/decisiones.md (por defecto: mayor val_accuracy, desempate menor val_loss); toma el run ganador, escribe docs/selection.json con run_id, ruta del checkpoint, métrica, valor y timestamp, y etiqueta el run en MLflow (selected=true).
2. Haz commit de selection.json antes de que Diego ejecute T15.
3. Avisa a Diego en la tarjeta cuando esté listo.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] selection.json commiteado con fecha anterior a la evaluación → [`selection.json`](../selection.json) en `6bd9101` (2026-09-26 21:40 -06:00); todavía no existe ninguna evaluación en test (F6). `POST /api/p3/selection` responde 409 si se intenta elegir otra vez
- [x] El run seleccionado tiene la mejor val_accuracy de docs/corridas.md → r10 `9f9b62c2…` con 0.9966, empatada con r08; gana por menor val_loss (0.0243 vs 0.0435), como fija decisiones.md §4. Checkpoint `e4acca42…` verificado de forma independiente

**Entregables:** `docs/selection.json`; Endpoint de selección

## Definición de terminado

- [x] Todas las casillas de aceptación marcadas con evidencia real
- [ ] PRs fusionados con review de Andrés — #7 fusionado con review y aprobación de **Diego** (D-Lemus), no de Andrés; #12 (`GET /api/p3/runs` para Experiments) espera su review
- [x] CI en verde en `main` → run de CI sobre `35b4021` (merge de #7): success
- [x] Commits red → green visibles en el historial → T13 `1364329`→`23ef512`, T14 `a68e0f1`→`4cda351`, runs `5180361`→`d951df6`

## Registro de avance

| Fecha | Quién | Bloque | Qué se hizo / PR | Pendiente |
|---|---|---|---|---|
| 26 sep 2026 | Edith | T13 | Lanzador `scripts/launch_sweep.py` (red `1364329` → green `23ef512`); 12 corridas por el worker en la RTX 4060; dos cortes de luz interrumpieron r03 y r05, que quedaron `failed` por la recuperación de huérfanos y se relanzaron. `docs/corridas.md`, `reports/sweep/launched.json`, tag verificable del hash de recortes y snapshot de MLflow en DVC (`655be99`) | — |
| 26 sep 2026 | Edith | T14 | Regla de decisiones.md §4 en `p3.train.selection` y `POST/GET /api/p3/selection` (red `a68e0f1` → green `4cda351`); seleccionado r10 `9f9b62c2…` (val_acc 0.9966) y `docs/selection.json` commiteado (`6bd9101`) | Avisar a Diego para F6 |
