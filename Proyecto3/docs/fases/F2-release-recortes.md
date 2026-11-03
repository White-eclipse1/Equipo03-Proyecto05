# F2 — Almacenamiento, release y recortes COCO

| Campo | Valor |
|---|---|
| Responsable | Diego (PM · datos · evaluación · entrega) |
| Revisor de PRs | Edith |
| Fechas | 24 sep → 25 sep de 2026 |
| Rama | `feat/fase-2-release-recortes` |
| Puntos de rúbrica | 9 (1.1, 1.2, M2 (compuerta)) |
| Depende de | F1 (contratos y decisiones) |
| Bloquea a | F3, F7 |
| Control | Control 2 |

**Nota de calendario:** El bucket propio y la copia de los datos de DVC van primero (jueves); las clases se fijan y se hace commit antes de cualquier corrida.

> Antes de empezar lee `AGENTS.md` (contexto y reglas) y `docs/contratos.md`. Trabaja los bloques en orden; cada bloque es al menos un PR.

## Bloque T31 — Almacenamiento propio en S3 (DVC, MLflow y modelos)

**Objetivo:** Tener, desde el inicio, un bucket del equipo con permisos listos para los datos de DVC, los artefactos de MLflow y los modelos publicados, sin depender del almacenamiento del equipo anterior.

**Criterios de rúbrica:** M2, 1.1, 1.3, 3.2, 5.2

**Pasos**

1. Crea (o confirma) un bucket de AWS S3 con versionado habilitado y prefijos dvc/, mlflow/ y models/.
2. Crea credenciales con el mínimo privilegio sobre ese bucket; guárdalas en .env y .dvc/config.local (ignorados por git) y en los Secrets de GitHub Actions si la CI las necesita. Nunca en el repo.
3. Copia los datos del release aprobado del P2: dvc pull desde el remoto original, dvc remote add -d p3storage s3://<bucket>/dvc, dvc push -r p3storage. Los hashes no cambian.
4. Verifica desde un clon limpio que dvc pull del release funciona solo con el remoto nuevo.
5. Apunta el artifact store de MLflow (T02) a s3://<bucket>/mlflow/ o confirma el volumen persistente elegido en decisiones.md.
6. Documenta bucket, prefijos, región y variables de entorno necesarias (solo nombres) en docs/almacenamiento.md.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] dvc pull del release funciona desde un clon limpio con el remoto propio — `dvc pull -r prod data/raw.dvc` sin datos ni caché previos: 2047 archivos del remote `prod` de la cuenta 750702272375, `dvc status` limpio ([almacenamiento.md](../almacenamiento.md#evidencia-t31))
- [x] Versionado del bucket habilitado — `head-object` devuelve `VersionId` sobre `0.1.3/dataset.tar.zst`; `aws_s3_bucket_versioning` en `Proyecto2/terraform/modules/s3/main.tf:20` ([almacenamiento.md](../almacenamiento.md#evidencia-t31))
- [x] gitleaks sin hallazgos tras el cambio — gitleaks v8.30.1 sobre todo el historial (159 commits): no leaks found ([almacenamiento.md](../almacenamiento.md#evidencia-t31))

**Entregables:** `docs/almacenamiento.md`; `.dvc/config actualizado (sin credenciales)`

## Bloque T05 — Selector de release DVC aprobado y consumo de COCO

**Objetivo:** Que P3 consuma de forma real y trazable un release aprobado del Proyecto 2, a través del servicio existente, y no una copia en data/.

**Criterios de rúbrica:** 1.1, M2, 6.1 (rechazo de gate fallido)

**Pasos**

1. Escribe primero pruebas: listar solo releases con quality gate aprobado; rechazar (HTTP 409 con mensaje claro) un release con gate fallido; conservar release_id, hash DVC y referencia al reporte de calidad.
2. Implementa GET /api/p3/releases?approved=true reutilizando el registro de releases del P2 (ver docs/inventario.md).
3. Implementa la carga del COCO e imágenes del release elegido mediante el servicio existente (dvc get/dvc api o el servicio del portal), nunca desde una ruta fija.
4. Agrega un script de comprobación que cambie de versión de release en entorno de prueba y muestre que los conteos cambian.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Con dos releases distintos los conteos de imágenes/anotaciones difieren — `tests/test_releases.py::test_cambiar_de_release_cambia_los_conteos` y `python scripts/demo_cambio_release.py` (9.0.0: 30 imágenes, 31 cajas, 28 válidas → 9.1.0: 20, 21, 18) en entorno de prueba; en S3 solo hay 0.1.2 y 0.1.3, con la misma huella
- [x] Un release con gate fallido no puede usarse — `ReleaseNotApprovedError` → HTTP 409 (`tests/test_releases.py::test_get_release_con_compuerta_fallida_responde_409`, `::test_release_con_compuerta_fallida_no_se_puede_usar`)
- [x] El release_id y hash quedan disponibles para el manifiesto — `p3.data.releases.Release` (`release_id`, `dataset_fingerprint`, `quality_report_fingerprint`, `archive_sha256`) y `GET /api/p3/releases/{release_id}`

**Entregables:** Endpoint de releases; Módulo de carga de release; Pruebas unitarias

## Bloque T06 — Selección y documentación de clases (antes de experimentar)

**Objetivo:** Fijar las clases incluidas y excluidas ANTES de cualquier experimento, con evidencia de conteos del release aprobado.

**Criterios de rúbrica:** 1.2 (≥2 clases con ≥300 originales), 3.1 (misma definición de clases)

**Pasos**

1. Escribe un script que cuente, por categoría del release aprobado, imágenes ORIGINALES distintas (no recortes) con al menos una caja válida.
2. Elige al menos 2 clases con ≥300 originales distintos cada una; documenta criterios de exclusión del resto (por conteo, ambigüedad, etc.).
3. Guarda la lista en config/p3/classes.yaml (id, nombre, conteo) y la justificación en docs/clases.md, con fecha y hash del release.
4. Haz commit antes de que exista cualquier corrida de entrenamiento: la fecha del commit es evidencia de que se decidió antes del test.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] classes.yaml y clases.md existen y citan el release — [`config/classes.yaml`](../../config/classes.yaml) y [`docs/clases.md`](../clases.md), release 0.1.3, huella `2200274d…`
- [x] Cada clase incluida tiene ≥300 originales distintos según el script — `scripts/count_classes.py --release 0.1.3`: cat 312, dog 348, person 441; protegido por `tests/test_classes_config.py`
- [x] Commit fechado antes de la primera corrida en MLflow — commit `219fed3` del 2026-09-25 21:45 (-06:00); la primera corrida del clasificador (experimento `p3-clasificador`, 14 corridas) empezó el 2026-09-26 19:55 (-06:00), según `mlflow_snapshot/mlflow.db`. La única corrida anterior (2026-09-24, experimento `f1-t02-persistencia`) es la prueba de persistencia del worker de F1 y no entrena el clasificador

**Entregables:** `config/p3/classes.yaml`; `docs/clases.md`; `scripts/p3/count_classes.py`

## Bloque T07 — Generador de recortes COCO con validación y exclusiones

**Objetivo:** Convertir cada caja COCO válida de las clases elegidas en un recorte etiquetado, trazable al original, rechazando cajas inválidas.

**Criterios de rúbrica:** 1.2

**Pasos**

1. Pruebas primero: caja con w o h <= 0 se rechaza; caja fuera de los límites de la imagen se rechaza (o se recorta al borde con regla documentada); imagen faltante se rechaza; categoría no incluida se excluye; cada exclusión queda registrada con motivo.
2. Implementa el recorte (Pillow) conservando image_id, annotation_id, category_id y bbox original; un original puede producir varios recortes.
3. Genera exclusions.csv con annotation_id, image_id y motivo.
4. Verifica manualmente 10 recortes al azar contra el COCO original y guarda la evidencia (ids + miniaturas) en docs/verificacion_recortes.md.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Una caja degenerada inyectada no aparece en el manifiesto — `tests/test_split.py::test_fixture_la_caja_degenerada_y_la_fuera_de_imagen_no_estan_en_el_manifiesto` (anotaciones 27, 30 y 31 del fixture fuera del manifiesto; cerrada en F3)
- [x] Cada recorte conserva los 4 identificadores de origen — `CropRecord` (`annotation_id`, `source_image_id`, `source_file_name`, categoría + bbox original); `scripts/verificar_recortes.py` (independiente del generador) lo comprobó en los 1459 recortes del 0.1.3, más revisión visual de 23 ([verificacion_recortes.md](../verificacion_recortes.md))
- [x] exclusions.csv con motivos — [`reports/crops/0.1.3/exclusions.csv`](../../reports/crops/0.1.3/exclusions.csv): 661 anotaciones, todas `excluded_category` (car y bicycle); ninguna caja de las clases incluidas es inválida

**Entregables:** `src/p3/data/crops.py`; `exclusions.csv`; Pruebas; `docs/verificacion_recortes.md`

## Definición de terminado

- [ ] Todas las casillas de aceptación marcadas con evidencia real
- [ ] PRs fusionados con review de Edith
- [ ] CI en verde en `main`
- [ ] Commits red → green visibles en el historial

## Registro de avance

| Fecha | Quién | Bloque | Qué se hizo / PR | Pendiente |
|---|---|---|---|---|
| 25 sep 2026 | Diego | T07a | Validación de cajas: `src/p3/data/crops.py` (`validate_annotations`, `read_image_sizes`) y `tests/test_crops_validation.py` (red `25e5490` → green `5374469`). Motivos del contrato; límites con el tamaño real del archivo. 11 mutaciones manuales (degenerada, bordes, faltante, categoría, etiqueta, ids, bbox) ponen la suite en rojo. | T07b: recorte con Pillow, `exclusions.csv`, `verificacion_recortes.md`; la casilla "caja degenerada no aparece en el manifiesto" se cierra con F3 |
| 25 sep 2026 | Diego | T31 | `docs/almacenamiento.md`: buckets de la cuenta 750702272375 (DVC, releases y `models/`), MLflow en volumen, permisos por Terraform y variables solo por nombre. | Evidencia con credenciales de Diego: `dvc pull -r prod` desde clon limpio, `get-bucket-versioning`, gitleaks |
| 25 sep 2026 | Diego | T05 | `src/p3/data/releases.py`, `api.py`, `settings.py` (red `c2cb87f` → green `675616b`); router montado en la app de P2; `scripts/demo_cambio_release.py`; contrato actualizado (`published_in`, `GET /releases/{id}`). 7 mutaciones (filtro, 409, SHA-256, huella, bucket) ponen la suite en rojo. | Leer el `0.1.3/dataset.tar.zst` real de S3 y comprobar la huella de P2 (`2200274d…`) con credenciales de Diego (se hace en T06) |
| 25 sep 2026 | Diego | T31 | Evidencia con el perfil de Diego: `dvc pull -r prod` sin caché previa (2047 archivos, `dvc status` limpio) y `VersionId` del release 0.1.3. `get-bucket-versioning` no está en la política de mínimo privilegio. | gitleaks |
| 25 sep 2026 | Diego | T06 | `src/p3/data/classes.py` (red `f5591c8` → green `578c6c0`), `scripts/count_classes.py` sobre el release real con SHA-256, huella de P2 y huella de DVC verificados; `config/classes.yaml` + `docs/clases.md` (red `085368e` → green `219fed3`): cat 312, dog 348, person 441; car y bicycle excluidas. 5 mutaciones ponen la suite en rojo. | Confirmar con Edith que no hay corridas en MLflow anteriores a `219fed3` |
| 25 sep 2026 | Diego | T31 | gitleaks v8.30.1 sobre el historial completo (159 commits): sin hallazgos. | — |
| 25 sep 2026 | Diego | T07b | `generate_crops`, `crop_box`, `write_exclusions_csv` (red `a4be2ef` → green `57a8b58`; prueba reforzada `2be6416` tras una mutación sobreviviente). Release 0.1.3: 1459 recortes (cat 329, dog 379, person 751), deterministas; `reports/crops/0.1.3/`; 1459/1459 verificados contra COCO y píxeles, 10/10 en revisión visual (`docs/verificacion_recortes.md`). | Casilla del manifiesto en F3 |
| 26 sep 2026 | Diego | T05/T06/T07 | Revisión de Edith en el PR #3. Rotación EXIF y tamaño distinto al COCO: red `388c1c7` → green `1142a35`; la revisión visual mostró que el intercambio de ejes era incorrecto → red `455927a` → green `a3d2e59` (escalado por eje desde el espacio del COCO). Verificación ya no circular (`9217fc1`, ajustada al modelo por eje en `fec9ced`): detecta 11 recortes malos de la versión anterior. `quality.json` del archivo debe decir `pass` (red `f5fcf28` → green `7182ec7`). `decided_at` en hora local. Regenerados: 1459 recortes, clases sin cambio (bicycle 239 → 240), 23/23 en revisión visual. | Respuesta a Edith en el PR |
| 1 oct 2026 | Diego | T05 | `GET /api/p3/releases` y `/{release_id}` agregan `trainable` y `blocked_reason` (sin `archive_sha256` → "no registra archive_sha256"; sin manifiesto congelado con seed 42 → "sin manifiesto congelado"). Búsqueda del congelado compartida con `/manifests` en `p3.data.frozen.frozen_for`. Red `08be044` → green (este PR); 7 mutaciones detectadas. Con el registro real solo 0.1.3 es entrenable. | Training (Andrés) usa los dos campos |
