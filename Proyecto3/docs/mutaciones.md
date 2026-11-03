# Pruebas de mutación — Proyecto 3 (F10 T26)

Las mutaciones prueban que la suite **detecta defectos**, no solo que calcula
sobre datos sanos (criterios 7.1 y 7.2). Cada mutación es un cambio manual y
temporal en el código de producción; se corre `pytest`, se confirma que la suite
**falla**, y se **revierte** de inmediato con `git checkout --`. Nunca se commitea
el código mutado: la evidencia es esta tabla.

Todas se ejecutan en `Proyecto3/` con el entorno del lockfile
(`pip install -r requirements.lock.txt`).

## M-A · Un grupo de casi duplicados se parte entre train y test

**Defecto inyectado.** En `src/p3/data/split.py`, `dup_group_ids` deja de honrar
los grupos de casi duplicados (pHash de P2) y devuelve un grupo propio por imagen:

```diff
-    return {image_id: assigned.get(image_id, f"g{image_id}") for image_id in sorted(image_ids)}
+    return {image_id: f"g{image_id}" for image_id in sorted(image_ids)}
```

Con esto dos imágenes casi idénticas pueden caer en particiones distintas: la
fuga que el criterio 3.3/M3 prohíbe.

**La suite lo detecta** (`pytest tests/test_split.py`):

```
FAILED tests/test_split.py::test_dup_group_id_es_g_mas_el_menor_image_id
FAILED tests/test_split.py::test_los_casi_duplicados_viajan_juntos
FAILED tests/test_split.py::test_muchos_pares_de_casi_duplicados_nunca_se_separan
```

Revertido con `git checkout -- src/p3/data/split.py` → 24/24 en verde.

## M-B · La red de seguridad `check_manifest` deja de ver la fuga

**Defecto inyectado.** En `check_manifest`, la comprobación de aislamiento solo
mira `crop_id` y ya no `source_image_id` ni `dup_group_id`:

```diff
-    for field in ("crop_id", "source_image_id", "dup_group_id"):
+    for field in ("crop_id",):
```

Un manifiesto con el mismo original (distinto `crop_id`) en dos particiones ya no
se reporta: el verificador que correría el evaluador quedaría ciego a la fuga.

**La suite lo detecta** (`pytest tests/test_split.py`):

```
FAILED tests/test_split.py::test_check_manifest_detecta_un_original_en_dos_particiones
```

Revertido con `git checkout -- src/p3/data/split.py` → suite en verde.

## M-C · El dataset deja de vigilar `dup_group_id` (sobrevivia)

**Defecto inyectado.** En `src/p3/data/dataset.py` la red de seguridad del
entrenamiento deja de revisar los grupos de casi duplicados:

```diff
-LEAKAGE_FIELDS = ("crop_id", "source_image_id", "dup_group_id")
+LEAKAGE_FIELDS = ("crop_id", "source_image_id")
```

**Antes de F13 sobrevivia:** `test_una_fuga_entre_particiones_se_rechaza` solo
probaba una fuga por `source_image_id` y toda la suite seguia en verde.

**Ahora la suite lo detecta.** La prueba esta parametrizada sobre los tres
identificadores, con la lista fija en la prueba (no `dataset.LEAKAGE_FIELDS`, que
desapareceria junto con el campo quitado). Cada caso agrega una fila en otra
particion que comparte **solo** ese identificador:

```
FAILED tests/test_dataset.py::test_una_fuga_entre_particiones_se_rechaza[dup_group_id]
```

Quitar `crop_id` o `source_image_id` hace fallar su propio caso del mismo modo.

## Bateria A–P (F13, 2 oct 2026)

Dieciseis mutaciones sobre las reglas criticas de la rubrica, cada una aplicada,
probada y restaurada por un script (`try/finally`, sin commitear codigo mutado),
sobre `main` + F13. **16/16 detectadas.**

| | Defecto inyectado | Archivo | Prueba que falla (una de ellas) |
|---|---|---|---|
| A | Repartir ignorando los grupos de casi duplicados | `data/split.py` | `test_split.py::test_los_casi_duplicados_viajan_juntos` |
| B | `check_manifest` solo vigila `crop_id` | `data/split.py` | `test_split.py::test_check_manifest_detecta_un_original_en_dos_particiones` |
| C | Aumentacion aleatoria en el preprocesamiento de evaluacion | `data/transforms.py` | `test_dataset.py::test_el_transform_de_evaluacion_no_tiene_operaciones_aleatorias` (nueva en F13) |
| D | Early stopping sin restaurar la mejor epoca | `train/trainer.py` | `test_early_stopping.py::test_el_entrenador_para_y_restaura_la_mejor_epoca` |
| E | Matriz de confusion transpuesta | `eval/metrics.py` | `test_metrics.py::test_matriz_con_filas_reales_y_columnas_predichas` |
| F | Accuracy redondeado a 2 decimales | `eval/metrics.py` | `test_metrics.py::test_accuracy_exacta_sin_redondear` |
| G | Caja degenerada (ancho o alto <= 0) aceptada | `data/crops.py` | `test_classes.py::test_en_el_fixture_solo_cuentan_las_cajas_validas` |
| H | Early stopping ignora `min_delta` | `train/early_stopping.py` | `test_early_stopping.py::test_min_delta_exige_una_mejora_real` |
| I | El dataset deja de vigilar `dup_group_id` (M-C) | `data/dataset.py` | `test_dataset.py::test_una_fuga_entre_particiones_se_rechaza[dup_group_id]` (nueva en F13) |
| J | La seleccion elige la menor `val_accuracy` | `train/selection.py` | `test_selection.py::test_gana_la_mayor_val_accuracy` |
| K | La seleccion cuenta corridas que no terminaron | `train/selection.py` | `test_selection.py::test_solo_cuentan_finished_del_manifiesto_congelado` |
| L | La inferencia no verifica el SHA-256 del modelo | `inference/service.py` | `test_inference.py::test_un_sha256_distinto_al_registro_se_rechaza` |
| M | La inferencia usa el transform de train | `inference/service.py` | `test_inference.py::test_usa_los_pesos_descargados_y_no_reglas_fijas` |
| N | Umbral de clases baja de 300 a 200 originales | `data/classes.py` | `test_classes.py::test_incluye_desde_300_y_excluye_299_con_motivo` |
| O | Evaluation revela el test sin seleccion cerrada | `eval/api.py` | `test_evaluation_api.py::test_sin_seleccion_cerrada_responde_409_sin_revelar_el_test` |
| P | No se verifica el SHA-256 del manifiesto congelado | `data/frozen.py` | `test_frozen_manifest.py::test_un_manifiesto_editado_se_rechaza` |

C solo la detectaba una prueba indirecta (la auditoria de `test_evaluate.py`), y
la de determinismo comparaba dos semillas: un flip con probabilidad 0.5 pasaba la
mitad de las veces. F13 agrega una revision estructural (ninguna operacion
`Random*` ni `ColorJitter` en `build_eval_transform`) y prueba ocho semillas.

## Nota

T26 pide "permitir un grupo duplicado en train y test **o** alterar una predicción
en la matriz": M-A cubre la primera opción (con M-B como refuerzo de la red de
seguridad). Con F4–F7 ya en `main`, el flujo completo se ejerce de punta a punta
en [`tests/test_e2e.py`](../tests/test_e2e.py) (`test_e2e_flujo_completo`): una
mutación adicional sobre la matriz de confusión de F6 (p. ej. en
`p3/eval/metrics.py`) es una extensión natural para endurecer 7.1 más adelante.
