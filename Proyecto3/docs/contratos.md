# Contratos entre módulos — Proyecto 3

Esquemas congelados que permiten que datos (Diego), entrenamiento (Edith) y portal (Andrés) avancen en paralelo. **Cualquier cambio de forma** (agregar, quitar o renombrar un campo, cambiar un rango o un código de respuesta) va explícito en el PR y se avisa al equipo (regla 11 de `AGENTS.md`).

Estado de cada pieza: **implementado** (existe en `main` con pruebas) o **contrato** (lo implementa la fase indicada).

## 0. Convenciones

- JSON en UTF-8 con finales de línea LF. Fechas en ISO 8601 UTC (`2026-09-24T22:29:34Z`).
- **Hash canónico:** SHA-256 del JSON serializado con claves ordenadas y sin espacios (`json.dumps(obj, sort_keys=True, separators=(",", ":"))`). Para el manifiesto, de sus filas ordenadas por `crop_id`, una por línea, cada línea terminada en `\n`.
- Toda la validación de entrada usa Pydantic v2 con `extra="forbid"`. Un error responde **422** con el formato de FastAPI, que nombra el campo en `loc`:

  ```json
  {"detail": [{"type": "less_than_equal", "loc": ["body", "config", "dropout"], "msg": "Input should be less than or equal to 0.9", "input": 1.5}]}
  ```

- Los demás errores responden `{"detail": "<mensaje en español>"}` con el código indicado en cada endpoint.
- Rutas bajo `/api/p3/`, servidas por la app de Proyecto2 (`http://localhost:8000`).
- Los valores de los ejemplos son ilustrativos, salvo los hashes del release 0.1.3 y los ids del fixture.

## 1. Mapa de clases

Fijado en [decisiones.md §2](decisiones.md#2-clases-incluidas-y-exclusiones). El `class_index` es el orden alfabético del nombre y es el índice de la salida del modelo:

| `class_index` | `category_name` | `category_id` (COCO del release) |
|---:|---|---:|
| 0 | cat | 4 |
| 1 | dog | 3 |
| 2 | person | 2 |

## 2. Manifiesto de recortes 70/20/10 — contrato (F2, F3)

Un manifiesto se deriva de **un** release aprobado y no se sobrescribe: cada generación produce un `manifest_id` nuevo. Se guarda como dos archivos versionados con DVC:

### `manifest.jsonl`: una fila por recorte

| Campo | Tipo | Regla |
|---|---|---|
| `crop_id` | string | `"<release_id>:a<annotation_id>"`, p. ej. `"0.1.3:a1234"`. Único y estable entre generaciones. |
| `source_image_id` | int | `id` de la imagen en el COCO del release |
| `source_file_name` | string | `file_name` de la imagen en el COCO |
| `annotation_id` | int | `id` de la anotación de la que sale el recorte |
| `category_id` | int | categoría COCO de la caja |
| `category_name` | string | nombre de la categoría |
| `class_index` | int | según la sección 1 |
| `bbox_xywh` | [float, float, float, float] | caja **original** del COCO, en píxeles, sin redondear |
| `dup_group_id` | string | `"g<menor image_id del grupo>"`; grupos por pHash con distancia ≤ `duplicates.phash_hamming_distance` de `Proyecto2/quality.yaml` (5), con el mismo criterio que `dataset_quality.analyzers.duplicates.duplicate_groups` de P2. Una imagen sin duplicados forma su propio grupo. |
| `split` | `"train"` \| `"val"` \| `"test"` | la unidad que se asigna es el **grupo de duplicados**: todos sus recortes van a la misma partición |
| `release_id` | string | versión del release, p. ej. `"0.1.3"` |
| `release_hash` | string | `dataset_fingerprint` del release |

```json
{"annotation_id":1234,"bbox_xywh":[461.0,346.0,300.0,200.0],"category_id":3,"category_name":"dog","class_index":1,"crop_id":"0.1.3:a1234","dup_group_id":"g1187","release_hash":"2200274dc6bbe6d0bc516e0136ae68651c0040bc6cab64a871794924fa39aa84","release_id":"0.1.3","source_file_name":"img_auto_1187.jpg","source_image_id":1187,"split":"train"}
```

### `manifest.meta.json`: procedencia y conteos

```json
{
  "schema_version": 1,
  "manifest_id": "m-0.1.3-s42-1",
  "manifest_hash": "<sha256 canónico de manifest.jsonl>",
  "created_at": "2026-09-25T18:00:00Z",
  "code_commit": "<git rev-parse HEAD>",
  "release": {
    "release_id": "0.1.3",
    "dataset_fingerprint": "2200274dc6bbe6d0bc516e0136ae68651c0040bc6cab64a871794924fa39aa84",
    "quality_status": "pass",
    "quality_report_fingerprint": "4d6e64aa13c6f66b15801811c4bb84ebc265b07f538ae27982f79628b170631a",
    "archive_sha256": "787742988af1df41d9a58573b81b5c9b4fe7ab24a647b25f2e71d3eb323838b5",
    "p2_splits_fingerprint": "9a87e0de3fb3069f06686065f149d64787593c04d90265a3e0f667a170d66279",
    "dvc_pointer": {"path": "Proyecto2/data/raw.dvc", "md5": "ca56420c9992f8b75fdb10f2ece81704.dir", "nfiles": 2046, "size": 634490876}
  },
  "seed": 42,
  "ratios": {"train": 0.7, "val": 0.2, "test": 0.1},
  "tolerance_pp": 5,
  "classes": [
    {"class_index": 0, "category_id": 4, "category_name": "cat"},
    {"class_index": 1, "category_id": 3, "category_name": "dog"},
    {"class_index": 2, "category_id": 2, "category_name": "person"}
  ],
  "excluded_categories": [{"category_id": 1, "category_name": "car"}, {"category_id": 5, "category_name": "bicycle"}],
  "exclusions": [
    {"annotation_id": 77, "source_image_id": 40, "reason": "degenerate_bbox"},
    {"annotation_id": 91, "source_image_id": 52, "reason": "bbox_out_of_bounds"},
    {"annotation_id": 12, "source_image_id": 9, "reason": "missing_image"},
    {"annotation_id": 5, "source_image_id": 3, "reason": "excluded_category"}
  ],
  "counts": {
    "crops": {"train": {"cat": 0, "dog": 0, "person": 0}, "val": {"cat": 0, "dog": 0, "person": 0}, "test": {"cat": 0, "dog": 0, "person": 0}},
    "originals": {"train": {"cat": 0, "dog": 0, "person": 0}, "val": {"cat": 0, "dog": 0, "person": 0}, "test": {"cat": 0, "dog": 0, "person": 0}}
  }
}
```

`reason` ∈ `degenerate_bbox` (ancho o alto ≤ 0), `bbox_out_of_bounds` (la caja sale de la imagen, en coordenadas del COCO), `missing_image` (el archivo no existe o no se puede abrir), `excluded_category`, `size_mismatch` (la proporción del archivo difiere más de 10 % de la del COCO).

**Coordenadas de las cajas (cambio F2, revisión del PR #3).** Las cajas se dibujaron en P1 sobre la foto que mostraba el navegador: con la rotación EXIF aplicada y con el `width`/`height` del COCO. Por eso:

- los límites se revisan contra el tamaño del COCO; si la foto gira por EXIF (orientación 5–8) y el COCO guarda el tamaño de la cabecera sin girar, ese tamaño se intercambia;
- para recortar, la foto se abre con la rotación EXIF aplicada y la caja se escala por eje al tamaño real del archivo (`pixel_scale` en `crops.jsonl`);
- `bbox_xywh` del manifiesto sigue siendo la caja **original del COCO**, sin escalar.

Nuevo motivo `size_mismatch` (aditivo). En el release 0.1.3 ninguna caja lo usa: la mayor deformación es de 5.7 % (imagen 8).

### Invariantes (las prueba F3)

1. Ningún `source_image_id` ni `dup_group_id` aparece en dos particiones.
2. La proporción de recortes por partición queda a ±5 puntos porcentuales de 70/20/10.
3. Cada clase tiene al menos un recorte en `val` y en `test`.
4. Misma semilla y mismo release → mismos `crop_id` en cada partición y mismo `manifest_hash`.
5. La aumentación nunca produce filas: se aplica en memoria y solo a `train`.

## 3. `TrainingConfig` — contrato (F4)

Todos los campos son obligatorios, salvo los que tienen valor por defecto. Un valor fuera de rango se rechaza con 422 **antes** de crear el trabajo, por API y por portal (criterio 2.2).

| Campo | Tipo | Rango válido | Por defecto |
|---|---|---|---|
| `optimizer` | string | `sgd` \| `adam` \| `adamw` | — |
| `batch_size` | int | 1 – 256 | — |
| `max_epochs` | int | 1 – 200 | — |
| `learning_rate` | float | > 0 y ≤ 1 | — |
| `image_size` | int | 32 – 512, múltiplo de 32 | — |
| `hidden_layers` | list[int] | 0 a 4 elementos, cada uno 8 – 4096 (`[]` = capa lineal directa) | — |
| `dropout` | float | 0 – 0.9 | — |
| `seed` | int | 0 – 2³²−1 | 42 |
| `patience` | int | 1 – 50 | 5 |
| `min_delta` | float | 0 – 0.1 | 0.001 |
| `monitor_metric` | string | `val_accuracy` \| `val_loss` | `val_accuracy` |

```json
{"optimizer": "adamw", "batch_size": 32, "max_epochs": 30, "learning_rate": 0.0003, "image_size": 224, "hidden_layers": [256], "dropout": 0.3, "seed": 42, "patience": 5, "min_delta": 0.001, "monitor_metric": "val_accuracy"}
```

## 4. API REST

| Método y ruta | Responde | Estado |
|---|---|---|
| `GET /api/p3/releases?approved=true` | releases de P2 | **implementado** (F2 T05) |
| `GET /api/p3/releases/{release_id}` | procedencia de un release aprobado | **implementado** (F2 T05) |
| `POST /api/p3/manifests` | manifiesto congelado de un release y una semilla | **implementado** (F3) |
| `GET /api/p3/manifests/{manifest_id}` | meta de un manifiesto | **implementado** (F3) |
| `POST /api/p3/training/jobs` | encola un trabajo | **implementado** para `kind: "dummy"` (T02); `kind: "train"` en F4 |
| `GET /api/p3/training/jobs/{job_id}` | estado, progreso, logs y error | **implementado** (T02); `mlflow_run_id` en F4 |
| `GET /api/p3/runs` | corridas de MLflow | **implementado** (F5) |
| `GET /api/p3/runs/{run_id}` | una corrida con curvas | **implementado** (F5) |
| `POST /api/p3/selection` | fija el candidato | contrato (F5) |
| `GET /api/p3/evaluation` | evaluación final en test | **implementado** (F6) |
| `GET /api/p3/evaluation/predictions` | `predictions_test.csv` por muestra | **implementado** (F6) |
| `GET /api/p3/evaluation/examples` | aciertos y errores de test (`errors.json`) | **implementado** (F6) |
| `GET /api/p3/evaluation/crops/{crop_id}` | PNG de un recorte del test elegido | **implementado** (F12, contrato C1) |
| `GET /api/p3/models` | versiones de modelo | **implementado** (F7) |
| `GET /api/p3/models/{version}/card` | tarjeta de una versión | **implementado** (F7) |
| `POST /api/p3/models/{version}/activate` | elige la versión para inferencia | **implementado** (F7) |
| `GET /api/p3/models/{version}/download` | descarga el `model.pt` publicado (C2) | **implementado** (F13) |
| `POST /api/p3/inference` | predice una imagen | **implementado** (F4 T24); página en F9 |
| `POST /api/p3/inference/{inference_id}/send-to-annotation` | crea el elemento en la cola de anotación | **implementado** (F4 T24); página en F9 |

### `GET /api/p3/releases?approved=true`

Lee `Proyecto2/reports/versions.json`. Con `approved=true` solo devuelve `quality_status: "pass"`.

```json
{"releases": [{"release_id": "0.1.3", "dataset_fingerprint": "2200274d…", "quality_status": "pass", "created_at": "2026-09-18T04:17:13Z", "counts": {"images": 2045, "annotations": 2120, "categories": 5}, "storage_uri": "s3://dataset-quality-releases-750702272375/0.1.3/dataset.tar.zst", "published_in": ["dev", "prod"], "trainable": true, "blocked_reason": null}]}
```

- **Cambio F2 T05 (aditivo):** campo `published_in`, con los remotes donde P2 publicó el release.
- `storage_uri` se arma con el bucket configurado (`P3_RELEASES_BUCKET`) si el release está en el remote `prod` (`P3_RELEASES_REMOTE`); si no, es `null`: el release solo existe en el MinIO local de quien lo generó y no se recupera desde un clon limpio. No se usa la URI que guarda P2, porque la del 0.1.3 apunta al bucket de la cuenta anterior ([decisiones.md §1](decisiones.md#1-release-dvc-de-origen)). El registro de P2 es la fuente de verdad: el archivo del 0.1.2 existe en el bucket del equipo, pero `versions.json` no registra esa publicación en `prod`, así que su `storage_uri` sale `null` (observación de la revisión del PR #3; el release elegido es el 0.1.3).
- Sin `approved` (o con `approved=false`) devuelve todos, incluidos los de compuerta fallida.
- **Cambio aditivo (1 oct):** `trainable` (bool) y `blocked_reason` (string o `null`) por release, para que Training deshabilite los que no se pueden entrenar y muestre el motivo. Las reglas se aplican en este orden:
  1. sin `archive_sha256` → `false`, `"no registra archive_sha256"` (su archivo no se puede verificar);
  2. sin ningún manifiesto congelado en `p3.data.frozen` → `false`, `"sin manifiesto congelado"` (el worker lo rechazaría);
  3. si no → `true`, `null`.

  Con el registro actual: 0.1.1 `"no registra archive_sha256"`; 0.1.2, 0.1.4 y 0.1.5 `"sin manifiesto congelado"`; **0.1.3 `true`**. Congelar un manifiesto nuevo (por PR) habilita su release sin tocar esta API. `GET /api/p3/releases/{release_id}` trae los mismos dos campos.
- **Cambio aditivo (F12, 1.1):** `manifests`, la lista de manifiestos congelados con los que se puede entrenar el release (vacía si no es entrenable), con el del barrido primero: `[{"manifest_id": "m-0.1.3-s42-1", "seed": 42, "sweep": true}, {"manifest_id": "m-0.1.3-s7-1", "seed": 7, "sweep": false}]`. Training la usa como selector de manifiesto y genera el elegido con `POST /api/p3/manifests` y su `seed`. Antes la regla 2 pedía un congelado con seed 42; ahora basta cualquiera.

### `GET /api/p3/releases/{release_id}` (nuevo en F2 T05)

Procedencia de un release para la vista de Training. **200** con los campos de la lista más `quality_report_fingerprint` y `archive_sha256`; **409** si la compuerta no pasó (`{"detail": "El release 0.1.0 no paso la compuerta de calidad (quality_status=fail); …"}`); **404** si no existe. `POST /api/p3/manifests` (F3) usa la misma regla.

Leer el COCO del release (`p3.data.releases.open_release_archive`) exige que el SHA-256 del `dataset.tar.zst` sea el `archive_sha256` registrado y que la huella de P2 del COCO sea el `dataset_fingerprint`; si no, `ReleaseIntegrityError`.

### `POST /api/p3/manifests`

```json
// request
{"release_id": "0.1.3", "seed": 42}
// 201
{"manifest_id": "m-0.1.3-s42-1", "manifest_hash": "…", "counts": {"…": "igual que manifest.meta.json"}}
```

- **409** si el release no tiene `quality_status: "pass"`.
- **404** si el release no existe.
- **Implementado (F3):** no genera un manifiesto nuevo. El worker solo entrena con los congelados (`p3.data.frozen`), así que devuelve el congelado de ese release y esa semilla (`m-<release>-s<seed>-<n>`) después de comprobar que el SHA-256 de `manifest.jsonl` es el congelado y que el meta dice el mismo release y seed. Es idempotente y no escribe nada. Generar uno nuevo es `scripts/generate_manifest.py` (reproducible byte a byte) y congelarlo entra por PR.
- **409** también si no hay congelado para ese release y esa semilla, o si los bytes en disco no son los congelados.
- **503** si el congelado no está descargado (`dvc pull data/manifests/<id>.dvc`).
- En Docker la app lee `Proyecto3/data/manifests` montado en solo lectura (`P3_MANIFESTS_DIR=/opt/p3/manifests`).

### `GET /api/p3/manifests/{manifest_id}`

**200** con el contenido de `manifest.meta.json`, o **404**.

### `POST /api/p3/training/jobs`

**Regla del barrido (F12):** con `experiment: "p3-clasificador"` solo se acepta el manifiesto del barrido (`p3.data.frozen.SWEEP_MANIFEST`, `m-0.1.3-s42-1`); otro manifiesto congelado responde **409** y pide `p3-pruebas`. Así las 12 corridas de `/api/p3/runs` y la selección no se mezclan con corridas de otro split.

```json
// request (F4)
{"kind": "train", "manifest_id": "m-0.1.3-s42-1", "config": {"…": "TrainingConfig"}}
// request (T02, disponible hoy)
{"kind": "dummy", "config": {"steps": 5, "seconds": 1, "fail": false}}
// 202
{"job_id": "02b40a98db684455b93dce8c89c107ee", "status": "queued"}
```

- **422** si `kind`, `config` o un campo extra no son válidos.
- **409** (F4) si el manifiesto no existe, su release no está aprobado o su test se mezcla con train o val.

### `GET /api/p3/training/jobs/{job_id}`

```json
{
  "job_id": "02b40a98db684455b93dce8c89c107ee",
  "kind": "dummy",
  "status": "succeeded",
  "progress": 1.0,
  "config": {"steps": 4, "seconds": 2},
  "logs": ["2026-09-25T04:54:54+00:00 encolado (dummy)", "…", "2026-09-25T04:55:03+00:00 terminado"],
  "error": null,
  "worker_id": "bd1a1827e2a6",
  "created_at": "2026-09-25T04:54:54",
  "started_at": "2026-09-25T04:54:55",
  "finished_at": "2026-09-25T04:55:03"
}
```

- `status` ∈ `queued`, `running`, `succeeded`, `failed`.
- En F4 se agrega `mlflow_run_id` (string o `null`).
- **404** si el trabajo no existe.

### `GET /api/p3/runs` y `GET /api/p3/runs/{run_id}`

`GET /api/p3/runs` acepta `?manifest_id=&status=FINISHED&order_by=val_accuracy&desc=true`.

```json
{"runs": [{"run_id": "01b222d3…", "status": "FINISHED", "manifest_id": "m-0.1.3-s42-1", "params": {"…": "TrainingConfig efectiva"}, "best_epoch": 12, "stopped_epoch": 17, "best_val_accuracy": 0.9, "best_val_loss": 0.31, "commit": "…", "start_time": "…", "end_time": "…"}]}
```

`GET /api/p3/runs/{run_id}` devuelve lo mismo más `history` (por época: `train_loss`, `train_accuracy`, `val_loss`, `val_accuracy`) y `artifacts` (rutas de curvas y checkpoint). **404** si el run no existe o no es del experimento `p3-clasificador`.

**503** en `/runs`, `/runs/{run_id}` y `/selection` (GET y POST) si MLflow no responde o responde un error distinto de 400/404, con el motivo y qué revisar (`P3_MLFLOW_URL`); nunca 500.

Si MLflow todavía no tiene el experimento `p3-clasificador` (clon limpio sin `dvc pull` de `mlflow_snapshot.dvc`), `GET /api/p3/runs` devuelve `{"runs": []}`, `/runs/{run_id}` **404**, `GET /api/p3/selection` **404** y `GET /api/p3/evaluation` **409**; nunca 500.

**Cambio aditivo (F5):** cada corrida trae también `experiment_id` (para armar el enlace a MLflow, `/#/experiments/<experiment_id>/runs/<run_id>`) y `selected` (`true` en el candidato de `selection.json`). `order_by` acepta `val_accuracy`, `val_loss`, `start_time` y `end_time`; `artifacts` trae las URI `mlflow-artifacts:/…` de `checkpoint`, `curves`, `history` y `environment`. Nunca hay métricas de test.

### `POST /api/p3/selection`

Aplica la regla de [decisiones.md §4](decisiones.md#4-métrica-de-selección-del-candidato) y escribe `selection.json` (sección 5).

- Request: `{"manifest_id": "m-0.1.3-s42-1"}`.
- **201** con el contenido de `selection.json`.
- **409** si hay menos de 10 corridas `FINISHED` sobre ese manifiesto, o si ya existe una selección para él.

### `GET /api/p3/evaluation`

Lee de MLflow la corrida `selected=true` y sus artefactos `evaluation/` (los registra `scripts/log_evaluation_mlflow.py`), para que portal, API y MLflow muestren las mismas cifras.

- **409** `{"detail": "La selección del modelo no está cerrada"}` mientras ninguna corrida esté seleccionada. El test no se revela antes (criterio 6.3).
- **404** si la corrida seleccionada todavía no tiene la evaluación final.
- **503** si MLflow no responde o responde un error distinto de 404 (nunca 500).
- **200**:

```json
{"run_id": "9f9b62c2…", "manifest_id": "m-0.1.3-s42-1", "test_size": 145, "accuracy": 0.9793103448275862, "passes_threshold": true, "threshold": 0.85, "f1_macro": 0.9743519475145314, "per_class": [{"class": "cat", "precision": 1.0, "recall": 0.9375, "f1": 0.9677, "support": 32}], "confusion_matrix": {"labels": ["cat", "dog", "person"], "rows_true_cols_pred": [[30, 2, 0], [0, 38, 0], [0, 1, 74]]}, "majority_baseline": 0.5172413793103449, "majority_class": "person", "most_confused": {"true": "cat", "predicted": "dog", "count": 2}, "evaluated_at": "2026-09-28T02:25:07Z", "predictions_uri": "/api/p3/evaluation/predictions", "examples_uri": "/api/p3/evaluation/examples"}
```

**Cambio aditivo (F12, contrato C1):** la respuesta suma la procedencia de las cifras (6.3): `release_id` (tag de la corrida), `manifest_hash` (de `metrics.json`), `checkpoint_sha256` y `selected_at` (de la selección guardada en la corrida). Con los datos reales: `"release_id": "0.1.3"`, `"manifest_hash": "45600f29…"`, `"checkpoint_sha256": "e4acca42…"`, `"selected_at": "2026-09-27T03:39:45Z"`.

### `GET /api/p3/evaluation/crops/{crop_id}` (F12, contrato C1)

El PNG de un recorte del **test del manifiesto de la corrida elegida**, para las miniaturas de la galería de Evaluation (4.4). `crop_id` es `<release_id>:a<annotation_id>` (por ejemplo `0.1.3:a1574`), igual que en `errors.json` y `predictions_test.csv`.

- **200** `image/png`.
- **409** `{"detail": "La selección del modelo no está cerrada"}` antes de cerrar la selección, como el resto de la evaluación.
- **404** si el recorte no es del test de ese manifiesto (de train o val, o de otro manifiesto).
- **422** si el id no tiene la forma de un recorte (impide salir de la carpeta).
- **503** con el comando que falta si el manifiesto no está descargado (`dvc pull`) o faltan los recortes (`scripts/generate_crops.py`).

Lee `manifest.jsonl` (`P3_MANIFESTS_DIR`), verifica que sea el congelado (**409** si sus bytes no coinciden), y lee `crops.jsonl` con los PNG (`P3_CROPS_DIR`). En Docker la app monta `Proyecto3/data` en solo lectura en `/opt/p3/data`, como el worker.

- **Cambios F6 (aditivos):** `f1` en `per_class`, `passes_threshold`, `threshold`, `majority_class`, `most_confused`, `evaluated_at` y `examples_uri`. `predictions_uri` apunta a `GET /api/p3/evaluation/predictions`, que devuelve el CSV de abajo (`text/csv`), no un `predictions.jsonl`.
- `GET /api/p3/evaluation/examples`: `{"correct": [...], "errors": [...]}`. Cada ejemplo trae `crop_id`, `crop_path` (relativo a `data/crops/<release>/`), `true`, `predicted` y `probability`; todos son de `test`.

### `predictions_test.csv` (F6) — cambio aditivo de F4 T24

Una fila por recorte de test, en el orden del manifiesto, con estas columnas (`scripts/verify_inference.py` las usa para comparar el portal con la evaluación):

```text
crop_id,clase_real,clase_predicha,prob_cat,prob_dog,prob_person
0.1.3:a1234,dog,dog,0.0213,0.9701,0.0086
```

Las probabilidades salen del mismo `build_eval_transform` y del checkpoint de `selection.json`, y suman 1.

### `GET /api/p3/models` y `POST /api/p3/models/{version}/activate`

```json
{"active_version": "1.0.0", "models": [{"version": "1.0.0", "run_id": "…", "manifest_id": "…", "release_id": "0.1.3", "s3": {"uri": "s3://…/models/clasificador/1.0.0/model.pt", "version_id": "…", "sha256": "…", "exists": true}, "card_uri": "…/MODEL_CARD.md"}]}
```

Viven en el servicio `p3-inference` (el que tiene el perfil de AWS); la app de P2 los reenvía (`p3.registry.proxy`), igual que la inferencia.

- `GET /api/p3/models`: versiones de `registry.json`; `s3.exists` sale de `head-object`, no del registro. **Aditivo (F7):** `active` por versión.
- `GET /api/p3/models/{version}/card`: la `MODEL_CARD.md` (`text/markdown`); **404** si la versión no está publicada.
- **503** en los tres endpoints de modelos si S3 no está disponible (sin credenciales, perfil de AWS inexistente, sin red o acceso denegado), con el motivo y qué configurar; nunca 500.
- `POST /api/p3/models/{version}/activate`: **200** con la misma forma que `GET /api/p3/models` (antes decía `{"active_version": …}`; ahora devuelve también la lista); **404** si la versión no está publicada; **409** si el objeto de S3 no existe o su SHA-256 no coincide; **422** si `version` no es semántica.
- `registry.json` lo escribe `p3.registry.publish` con, por versión, además de los campos de la sección 6: `release_id`, `card_key` y `files` (SHA-256 y `s3_version_id` de cada archivo del paquete).

### `GET /api/p3/models/{version}/download` (C2, F13: Edith → Andrés)

Descarga los pesos publicados de una versión para la acción «Descargar pesos» de Models (criterio 6.4). Lo atiende `p3-inference` y el portal lo reenvía conservando los encabezados.

- **200** `application/octet-stream` con los bytes de `model.pt` leídos de S3 (la versión registrada, como en la inferencia), solo si su SHA-256 es el del registro.
  - `Content-Disposition: attachment; filename="clasificador-<version>-model.pt"`
  - `X-Model-SHA256: <sha256 del registro>` (el mismo que muestra `GET /api/p3/models` en `s3.sha256`).
- **404** si la versión no está en `registry.json`.
- **409** si el objeto no existe en S3, su `VersionId` no es el registrado o su SHA-256 no coincide: nunca se sirve un archivo distinto del publicado.
- **422** si `version` no es semántica.
- **503** si S3 no está disponible, con el motivo y qué configurar (igual que los demás endpoints de modelos).

### `POST /api/p3/inference`

**Implementado (F4 T24).** Lo atiende el servicio `p3-inference` (el único con PyTorch); la app del portal le reenvía la petición.

- Request: `multipart/form-data` con `file` (JPEG o PNG de hasta 10 MB) y, opcionalmente, `bbox_xywh` como texto JSON `[x, y, ancho, alto]` en píxeles de la imagen tal como se ve (rotación EXIF aplicada), para recortar antes de predecir.
- Usa **la versión activa del registro** (sección 6): descarga su `model.pt` de S3, comprueba el SHA-256 registrado y aplica `build_eval_transform`, el mismo preprocesamiento de validación y prueba. Nunca usa un checkpoint local.
- Cada inferencia se guarda (tabla `p3_inferences`) con la imagen, la versión y el SHA-256 del modelo.
- Responde **200**:

```json
{"inference_id": "…", "model_version": "1.0.0", "model_sha256": "…", "run_id": "…", "predicted_class": "dog", "probabilities": {"cat": 0.05, "dog": 0.9, "person": 0.05}}
```

- Las probabilidades suman 1 (±1e-4).
- **415** si el tipo no es válido; **413** si el archivo pasa de 10 MB; **422** si `bbox_xywh` no es válido o no cabe en la imagen; **409** si no hay versión activa, su objeto no existe o su SHA-256 no coincide; **503** si el servicio no responde o si S3 no está disponible (sin credenciales, perfil de AWS inexistente, sin red o acceso denegado), con el motivo y qué configurar; nunca 500.

### `POST /api/p3/inference/{inference_id}/send-to-annotation`

**Implementado (F4 T24).** Sube la misma imagen de la inferencia a la cola de anotación de P1 (`POST {P3_ANNOTATION_URL}/api/images/upload`, campo `file`), que la crea en estado `pending`.

- **201** `{"annotation_queue_item": {"image_id": 91, "status": "pending"}}`.
- **200** con el mismo elemento si ya se había enviado: no se duplica.
- **404** si la inferencia no existe; **502** si P1 no responde o rechaza la imagen.
- **Cambio (F13):** el `detail` del 502 dice en español qué pasó y qué hacer: si P1 no responde, nombra la URL (`P3_ANNOTATION_URL`) y los comandos del README para levantarlo; si P1 respondió con error, incluye su código.

## 5. `selection.json` — contrato (F5)

Se commitea **antes** de correr la evaluación final (regla 8 de `AGENTS.md`).

```json
{
  "schema_version": 1,
  "selected_at": "2026-09-29T18:00:00Z",
  "manifest_id": "m-0.1.3-s42-1",
  "manifest_hash": "…",
  "rule": "max val_accuracy; desempate min val_loss; luego end_time mas temprano",
  "candidates": 10,
  "run_id": "…",
  "checkpoint_uri": "mlflow-artifacts:/…/checkpoints/best.pt",
  "checkpoint_sha256": "…",
  "best_epoch": 12,
  "val_accuracy": 0.9,
  "val_loss": 0.31
}
```

## 6. Versión de modelo — contrato (F7)

Carpeta `s3://dataset-quality-releases-750702272375/models/clasificador/<version>/` con `model.pt`, `class_map.json` (sección 1), `preprocessing.json`, `config.json` (TrainingConfig y arquitectura), `requirements.lock.txt`, `MODEL_CARD.md` y `model_version.json`:

```json
{
  "schema_version": 1,
  "version": "1.0.0",
  "architecture": "resnet18",
  "pretrained_weights": "torchvision ResNet18_Weights.IMAGENET1K_V1",
  "run_id": "…",
  "manifest_id": "m-0.1.3-s42-1",
  "release_id": "0.1.3",
  "selection_sha256": "<sha256 de selection.json>",
  "test_metrics": {"accuracy": 0.0, "f1_macro": 0.0},
  "preprocessing": {"image_size": 224, "resize": "resize_to_square", "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
  "files": {"model.pt": {"sha256": "…", "s3_version_id": "…"}},
  "created_at": "…"
}
```

La versión es semántica y propia del modelo; no se confunde con la versión del dataset (`release_id`).

### Registro de versiones (cambio de F4 T24, aditivo)

En la misma carpeta de modelos vive `s3://dataset-quality-releases-750702272375/models/clasificador/registry.json`. Lo escribe F7 al publicar y lo lee el servicio de inferencia en cada predicción, así que activar otra versión cambia el modelo sin reiniciar nada:

```json
{
  "schema_version": 1,
  "active_version": "1.0.0",
  "versions": [
    {"version": "1.0.0", "run_id": "9f9b62c2…", "manifest_id": "m-0.1.3-s42-1", "key": "models/clasificador/1.0.0/model.pt", "sha256": "<sha256 de model.pt>", "s3_version_id": "…"}
  ]
}
```

- `model.pt` es el checkpoint de `p3.model.build.save_checkpoint`: pesos, arquitectura, `class_names` y `preprocessing` (`resize_to_square`, ver `docs/modelo.md`).
- `active_version` debe estar en `versions`, o ser `null` si no hay ninguna activa. `POST /api/p3/models/{version}/activate` (F7) solo la cambia si el objeto existe y su SHA-256 coincide.

## 7. Fixture de pruebas — implementado

[`tests/fixtures/p3/`](../tests/fixtures/p3/) contiene un COCO de 3 clases (ids reales: 2 `person`, 3 `dog`, 4 `cat`) y 30 imágenes sintéticas de 128×96, donde cada clase es una figura distinta (elipse, rectángulo, triángulo). Tiene a propósito un caso de cada tipo:

| Caso | Dónde |
|---|---|
| Imagen con dos clases (dos recortes de un original) | imagen 28 |
| Casi duplicados (pHash a distancia 2; el resto a ≥ 22) | imágenes 25 y 26 |
| Imagen que falta en disco | imagen 27 |
| Caja degenerada (ancho 0) | imagen 29 |
| Caja fuera de la imagen | imagen 30 |

Recortes válidos: 10 `cat`, 9 `dog`, 9 `person`. `tests/test_fixture_p3.py` protege estas propiedades.
