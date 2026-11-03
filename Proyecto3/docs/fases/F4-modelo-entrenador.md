# F4 — Modelo, entrenador y servicio de inferencia

| Campo | Valor |
|---|---|
| Responsable | Edith (Líder de ML y MLOps) |
| Revisor de PRs | Andrés |
| Fechas | 25 sep → 29 sep de 2026 |
| Rama | `feat/fase-4-modelo-entrenador` |
| Puntos de rúbrica | 18 (2.1–2.4, M4 (compuerta)) |
| Depende de | F1 |
| Bloquea a | F5, F9 |
| Control | Control 2 |

**Nota de calendario:** El viernes 25 se mide una corrida corta y se calendariza el barrido. Entrenador con early stopping listo el lunes 28 en la mañana; el servicio de inferencia se hace el martes mientras corre el barrido y se verifica con el objeto real de S3 el miércoles.

> Antes de empezar lee `AGENTS.md` (contexto y reglas) y `docs/contratos.md`. Trabaja los bloques en orden; cada bloque es al menos un PR.

## Bloque T09 — Dataset, DataLoader y transforms (aumentación solo en train)

**Objetivo:** Leer el manifiesto y construir DataLoaders con aumentación exclusiva de train y un preprocesamiento determinista compartido por val, test e inferencia.

**Criterios de rúbrica:** 2.3, M3

**Pasos**

1. Pruebas primero: val/test/inferencia usan exactamente la misma función de preprocesamiento; aplicar dos veces el transform de val a la misma imagen da el mismo tensor; el dataset de train nunca incluye ids de val/test.
2. Implementa src/p3/data/transforms.py con build_train_transform(cfg) y build_eval_transform(cfg) (resize a image_size, normalización ImageNet).
3. Implementa CropDataset que lee el manifiesto (esquema de docs/contratos.md) filtrando por split.
4. Implementa DataLoaders con generator y worker_init_fn sembrados para orden reproducible.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Mismo seed -> mismo orden de muestras (prueba) → `tests/test_dataset.py::test_misma_semilla_mismo_orden_de_muestras` (red `7538b71` → green `0ddeba3`)
- [x] Transform aleatorio solo en train (prueba) → `tests/test_dataset.py::test_la_aumentacion_aleatoria_solo_esta_en_train` y `::test_val_test_e_inferencia_comparten_el_mismo_preprocesamiento`; datos reales: 1022 / 292 / 145 recortes de `m-0.1.3-s42-1`

**Entregables:** `src/p3/data/transforms.py`; `src/p3/data/dataset.py`; Pruebas

## Bloque T10 — Modelo CNN configurable (ResNet18 + cabeza propia)

**Objetivo:** Construir el clasificador con cabeza adaptada a las clases y parámetros hidden_layers y dropout.

**Criterios de rúbrica:** 2.1

**Pasos**

1. Pruebas primero: la salida tiene tamaño = número de clases de classes.yaml; tras 3 pasos de optimizador los pesos de la cabeza cambian; el modelo se guarda y recarga con mapa de clases idéntico.
2. Implementa build_model(cfg, num_classes): backbone torchvision ResNet18 con pesos ImageNet (documenta origen y licencia) y cabeza MLP con hidden_layers y dropout configurables; documenta qué capas son entrenables.
3. Documenta en docs/modelo.md la arquitectura, el origen de pesos iniciales y la justificación.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Prueba de cambio de pesos pasa → `tests/test_model.py::test_tres_pasos_del_optimizador_cambian_los_pesos` (red `4590e71` → green `72b80aa`) y `tests/test_trainer.py::test_entrenar_cambia_los_pesos`
- [x] docs/modelo.md declara origen de pesos → [modelo.md](../modelo.md): `ResNet18_Weights.IMAGENET1K_V1` (`resnet18-f37072fd.pth`), todas las capas entrenables

**Entregables:** `src/p3/model/build.py`; `docs/modelo.md`

## Bloque T11 — Loop por minibatches, config validada y semillas

**Objetivo:** Entrenador por minibatches con configuración validada antes de crear el trabajo y todas las semillas registradas.

**Criterios de rúbrica:** 2.2, 2.3

**Pasos**

1. Pruebas primero: un valor inválido (batch_size=0, lr negativo, optimizador inexistente, dropout>=1) lanza error de validación con mensaje útil y NO crea trabajo; cada parámetro de la config cambia el comportamiento real (no se ignora).
2. Implementa TrainingConfig con Pydantic según contratos.md.
3. Implementa el loop: por época, por batch -> forward, loss, backward, optimizer.step(); calcula loss y accuracy de train y val por época.
4. Siembra random, numpy, torch (y cuda), DataLoader; registra versiones de librerías y torch.use_deterministic_algorithms donde sea posible, documentando lo no determinista.
5. Conecta el entrenador al worker de T02 para que un trabajo reporte progreso por época.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Config inválida rechazada por API con 422 → `tests/test_api.py::test_train_con_config_invalida_da_422_nombrando_el_campo_y_no_crea_trabajo`; en el stack real `batch_size: 0` responde 422 con `loc` `[body, train, config, batch_size]` y el conteo de `p3_training_jobs` no cambia (4 → 4)
- [x] Corrida corta con mismo seed reproduce orden de muestras → `tests/test_trainer.py::test_misma_semilla_misma_corrida` (mismo orden, misma historia y mismos pesos en CPU; red `e6f3947` → green `fff1b14`)

**Entregables:** `src/p3/train/config.py`; `src/p3/train/trainer.py`; Pruebas

## Bloque T32 — Medir una corrida corta y calendarizar el barrido

**Objetivo:** Saber con datos reales si las ≥10 corridas caben en el tiempo disponible antes de lanzarlas el lunes 28.

**Criterios de rúbrica:** 3.1 (riesgo: diez corridas sin presupuesto)

**Pasos**

1. Con el manifiesto provisional de Diego (o el fixture escalado si aún no existe), ejecuta una corrida corta por el worker: 2 épocas con image_size 128 y 224.
2. Mide segundos por época y memoria usada; estima la duración de cada combinación de config/p3/sweep.yaml con su max_epochs y el efecto esperado del early stopping.
3. Si el total estimado supera la ventana de la noche del lunes 28 al martes 29 a mediodía, ajusta: reduce image_size o max_epochs, paraleliza corridas o adelanta parte del barrido al fin de semana, sin romper la variación de los 7 parámetros.
4. Actualiza la decisión 7 (presupuesto de cómputo) en docs/decisiones.md con la medición real y el calendario de corridas.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Tiempo por época medido para al menos 2 tamaños de imagen → trabajos `2f9e2c93…` (224 px: 18 s y 13 s) y `494b7fdd…` (128 px: 11 s y 11 s) en la RTX 4060 ([decisiones.md §7](../decisiones.md#7-presupuesto-de-cómputo))
- [x] Calendario del barrido documentado y dentro de la ventana → [`config/sweep.yaml`](../../config/sweep.yaml) (12 corridas, protegido por `tests/test_sweep_config.py`): ≈ 70 min en el peor caso, lanzado el lun 28 después de mediodía

**Entregables:** `docs/decisiones.md (decisión 7)`; `config/p3/sweep.yaml ajustado si hace falta`

## Bloque T12 — Early stopping con restauración y registro completo en MLflow

**Objetivo:** Detener cuando la métrica de validación deja de mejorar, restaurar la mejor época y registrar todo en MLflow.

**Criterios de rúbrica:** 2.4, 3.2

**Pasos**

1. Pruebas primero: con una secuencia simulada de val_accuracy [0.5,0.6,0.7,0.65,0.64,0.63] y patience=3 se detiene en la época 6 y el checkpoint final es el de la época 3.
2. Implementa EarlyStopping(monitor, patience, min_delta, mode) que guarda el state_dict de la mejor época y lo restaura al terminar.
3. Registra por corrida en MLflow: parámetros efectivos, semilla, commit git, release DVC, hash del manifiesto, lista de clases, métricas por época (train/val loss y accuracy), época de parada, mejor época, curvas PNG y checkpoint como artefacto.
4. Rechaza iniciar si el manifiesto no está congelado o su hash no coincide con el esperado.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Prueba de secuencia controlada pasa → `tests/test_early_stopping.py::test_secuencia_controlada_para_en_la_6_y_se_queda_con_la_3` y `::test_el_entrenador_para_y_restaura_la_mejor_epoca` (pesos finales = los de la época 3; red `2081eac` → green `b28e37d`)
- [x] Un run en MLflow muestra todos los campos listados vía API (mlflow.search_runs) → run `fd690ca2846447a088b8e1fe588bd974` (experimento `p3-pruebas`, trabajo `625f5de1…`, RTX 4060) consultado con `MlflowClient.search_runs` en `http://localhost:5000`: `FINISHED`; 11 parámetros efectivos con semilla; tags `manifest_id`, `manifest_hash`, `release_id`, `release_hash`, `dvc_md5`, `classes`, `code_commit` (`250bedc`, árbol limpio), `job_id`, `pretrained_weights` y `env.*`; `val_accuracy` y demás métricas por época; `best_epoch` 7, `stopped_epoch` 10, `early_stopped` 1; artefactos `curves.png`, `history.json`, `environment.json` y `checkpoint/model.pt`. El checkpoint recargado en un proceso limpio da val_acc 0.9384 = época 7 (la época 10 tenía 0.7226). Manifiesto no congelado → 409 por API y fallo en el worker

**Entregables:** `src/p3/train/early_stopping.py`; Integración MLflow

## Bloque T24 — Servicio de inferencia (backend)

**Objetivo:** Endpoint que infiere con los pesos reales de la versión activa, con el mismo preprocesamiento de evaluación.

**Criterios de rúbrica:** 6.5, M4

**Pasos**

1. Pruebas primero: rechaza tipos no imagen y archivos > límite (p. ej. 10 MB) con 400/413; las probabilidades suman 1±1e-4; cambiar la versión activa cambia el modelo cargado (hash distinto).
2. Implementa POST /api/p3/inference: acepta imagen completa + bbox opcional para recortar, aplica build_eval_transform, devuelve clase, probabilidades por clase, versión de modelo y id de inferencia persistido.
3. Implementa POST /api/p3/inference/{id}/send-to-annotation que crea un elemento real en la cola de anotación existente del P1.
4. Carga SIEMPRE el paquete de la versión activa publicado en S3: descárgalo, verifica su SHA-256 contra el registro y cachéalo en memoria por versión. Nunca uses un checkpoint local del entrenamiento. Hasta que F7 publique (miércoles 30), pruébalo contra MinIO o un bucket de prueba; el miércoles verifica con el objeto real de S3.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Una predicción sobre una imagen de test coincide con predictions_test.csv → `scripts/verify_inference.py --profile p3-edith --predictions predictions_test.csv` (F6 PR #9, F7 PR #11) con el stack arriba, 28 sep: **145/145** recortes de test enviados por el portal (`POST :8000/api/p3/inference`) dan la misma clase y las mismas probabilidades (±1e-4) que `predictions_test.csv`
- [x] El modelo usado se descargó de S3 y su SHA-256 coincide con el registro → `scripts/verify_inference.py --profile p3-edith --predictions predictions_test.csv` (F6 PR #9, F7 PR #11) con el stack arriba, 28 sep: versión activa 1.0.0, `s3://dataset-quality-releases-750702272375/models/clasificador/1.0.0/model.pt` VersionId `VtRww5se97lomVTcKJUv6d9mYSL7TXOf`; SHA-256 descargado = registro = `selection.json` = `e4acca429ebf73d0e5a60fb0dda383a6a5322dccb1decf04b4e40ab9db989172`, y el portal devolvió ese mismo `model_sha256` en las 145 predicciones (lectura sin `s3:GetObjectVersion`: PR #13)
- [x] El elemento enviado aparece en la cola de anotación → con P1 levantado desde su README (`npm run up`, tras arreglar su imagen de MinIO) y el portal en `:8000`: la inferencia `1294c24f…` se envió con `POST /api/p3/inference/{id}/send-to-annotation` → 201 `image_id` 9; `GET :3000/api/images/9` la muestra `pending` y su archivo tiene el mismo SHA-256 que la foto enviada (`0bbe9272…`); las imágenes pendientes de P1 pasaron de 8 a 9; un segundo envío devuelve 200 con el mismo id, sin duplicar

**Entregables:** `src/p3/inference/service.py`; Endpoints; Pruebas

## Definición de terminado

- [x] Todas las casillas de aceptación marcadas con evidencia real
- [ ] PRs fusionados con review de Andrés — #5, #6, #7 y #8 fusionados, pero los revisó, aprobó y fusionó **Diego** (D-Lemus), no Andrés; #13 (lectura de S3) espera su review
- [x] CI en verde en `main` → run de CI sobre `4114c73` (merge de #8): success
- [x] Commits red → green visibles en el historial → T09 `7538b71`→`0ddeba3`, T10 `4590e71`→`72b80aa`, T11 `e6f3947`→`fff1b14`, T12 `2081eac`→`b28e37d` y `fb8e433`→`7d80897`, T24 `3bef15e`→`52d8e96`, `340ba4c`→`e67e563` y `3d7a4ff`→`a553e3f`

## Registro de avance

| Fecha | Quién | Bloque | Qué se hizo / PR | Pendiente |
|---|---|---|---|---|
| 26 sep 2026 | Edith | T09 | `src/p3/data/transforms.py` y `dataset.py`: preprocesamiento único para val/test/inferencia, aumentación solo en train, fuga revisada otra vez al construir, loader sembrado (red `7538b71` → green `0ddeba3`). Torch 2.14.0 y torchvision 0.29.0 en el extra `train`, lockfile generado en Linux (`8be9c15`) | — |
| 26 sep 2026 | Edith | T10 | `src/p3/model/build.py`: ResNet-18 IMAGENET1K_V1 con cabeza MLP configurable y checkpoint recargable con mapa de clases y preprocesamiento (red `4590e71` → green `72b80aa`); `docs/modelo.md` | — |
| 26 sep 2026 | Edith | T11 | `TrainingConfig` (contratos §3), loop por minibatches con semillas y registro del entorno, trabajo `train` en el worker con progreso por época (red `e6f3947` → green `fff1b14`; un batch final de 1 muestra se omite, `7fe6d93`). Worker con PyTorch, datos montados y GPU opcional (`9ce4ecf`) | MLflow y early stopping en T12 |
| 26 sep 2026 | Edith | T32 | Medición en la RTX 4060 (≈ 13 s/época, cuello de botella en la carga de imágenes), `config/sweep.yaml` con 12 corridas (red `19fb858` → green `8d88dd2`), decisión 7 cerrada (`72056a6`) | — |
| 26 sep 2026 | Edith | T12 | `EarlyStopping` con restauración de la mejor época (red `2081eac` → green `b28e37d`); `p3.train.tracking` registra todo en MLflow; `p3.data.frozen` exige el manifiesto congelado (409 en la API); `mlflow_run_id` en el trabajo y timestamps con microsegundos (red `fb8e433` → green `7d80897`); experimento `p3-pruebas` para corridas de humo (`73b42f8` → `84b1313`). Snapshot de MLflow restaurable desde DVC y commit del código en cada corrida (`250bedc`); decisión 5 actualizada | `dvc add mlflow_snapshot` + push tras el barrido de F5 |
| 27 sep 2026 | Edith | T24 | Servicio de inferencia: registro de versiones y descarga verificada por SHA-256 (red `3bef15e` → green `52d8e96`); API con cada inferencia guardada, envío a P1 y proxy del portal (red `340ba4c` → green `e67e563`); servicio `p3-inference` en el compose (`670c3f9`). Probado en el stack contra un paquete de prueba en MinIO: 200 con probabilidades que suman 1, recorte opcional, 415, 413 y 422 | Casillas que dependen de F6 (`predictions_test.csv`), F7 (`registry.json` en S3) y de levantar P1 |
| 27 sep 2026 | Edith | T24 | P1 arranca desde un clon limpio (imagen de MinIO y ruta del README) y la inferencia llega a su cola de anotación: imagen 9 `pending`, mismos bytes | Solo quedan las casillas de F6 y F7 |
| 28 sep 2026 | Edith | T24 | Con F6 y F7: `verify_inference.py` contra el S3 real y `predictions_test.csv`: 145/145 predicciones iguales y SHA-256 del modelo = registro = selección. Arreglo de lectura sin `s3:GetObjectVersion` (#13) | Review de Andrés en #13 |
| 30 sep 2026 | Edith | T24 | Hallazgo 1 del ensayo (#14): imagen de `p3-worker`/`p3-inference` con torch **CPU** por defecto (`TORCH_VARIANT=cpu`: mismas versiones del lockfile en su wheel `+cpu`, sin `nvidia-*`, `cuda-*` ni `triton`); `docker-compose.gpu.yml` pide `cuda` solo para el worker. Imagen de 9.57 GB a 1.99 GB. Con el stack en CPU (`P3_GPU=0`): `verify_inference.py` contra el S3 real, 145/145 predicciones iguales a `predictions_test.csv` y SHA-256 = registro = selección; trabajo `dummy` `succeeded` | Review |
