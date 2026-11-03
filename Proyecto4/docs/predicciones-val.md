# Predicciones por muestra en validación — VAL-03 (#13, criterio 1.3)

Archivo formal para que el evaluador recalcule la calidad del modelo original y del optimizado **sin confiar en una tabla resumida**. Tiene una fila por cada muestra `val` del manifiesto del Proyecto 3, unida a ese manifiesto por `sample_id`.

| Archivo | Qué es |
|---|---|
| [`validacion/resultados/predicciones_val.csv`](../validacion/resultados/predicciones_val.csv) | 292 filas, una por muestra |
| [`validacion/resultados/predicciones_val.json`](../validacion/resultados/predicciones_val.json) | Procedencia, exclusiones, resumen y verificación |
| [`validacion/resultados/manifiesto/manifest_val.jsonl`](../validacion/resultados/manifiesto/manifest_val.jsonl) | Las 292 líneas `val` del manifiesto `m-0.1.3-s42-1`, byte a byte y en su orden |
| [`validacion/resultados/manifiesto/manifest.meta.json`](../validacion/resultados/manifiesto/manifest.meta.json) | El meta del manifiesto, copia exacta: clases declaradas, conteos y exclusiones |

## Verificarlo (evaluador)

Desde `Proyecto4/`, con cualquier Python 3.11 o superior y **sin instalar nada**. No hacen falta modelos, torch ni credenciales:

```bash
python validacion/verificar_predicciones.py
```

[`verificar_predicciones.py`](../validacion/verificar_predicciones.py) une el CSV con el manifiesto por `sample_id` y debe terminar en `VERIFICADO`. Comprueba:

| Comprobación | Qué exige |
|---|---|
| `formato` | Columnas `sample_id`, `true_class`, `original_prediction`, `optimized_prediction`, `manifest_id`, `split` y `class_index` |
| `csv.sha256` | El CSV es el que registra el JSON |
| `manifiesto.vinculo` | El manifiesto usado es el del P3 (SHA-256 `45600f29…`, el de `Proyecto3/docs/selection.json`) o su extracto `val` registrado |
| `ids.duplicados` | Cero `sample_id` repetidos |
| `ids.union_con_manifiesto` | Las mismas muestras que `val`: cero faltantes sin justificar y cero sobrantes |
| `etiquetas` | `true_class`, `class_index`, `split` y `manifest_id` iguales a los del manifiesto |
| `clases` | Las clases declaradas (`cat`, `dog`, `person`) con los conteos del meta (67, 78 y 147), y predicciones solo dentro de esas clases |
| `resumen.recalculado` | Aciertos y acuerdo recalculados desde las filas, iguales a los declarados |

Quien tenga los datos del P3 (`dvc pull` o la copia en `s3://p4-capturas-474665692638/datos/p3/`) puede verificar contra el **manifiesto completo**:

```bash
python validacion/verificar_predicciones.py --manifiesto ../Proyecto3/data/manifests/m-0.1.3-s42-1/manifest.jsonl
```

En ese caso, además de comprobar su SHA-256, verifica que el extracto versionado sea exactamente su `val`, línea por línea.

## Columnas

| Columna | Contenido |
|---|---|
| `sample_id` | `crop_id` del manifiesto del P3 |
| `true_class` | `category_name` del manifiesto |
| `original_prediction` | Clase predicha por el `model.pt` 1.0.0 del P3 (PyTorch, preprocesamiento del P3) |
| `optimized_prediction` | Clase predicha por la variante `1.0.0-int8-e05.1` (onnxruntime, `modelo/preprocesar.py`) |
| `manifest_id`, `split`, `class_index` | Columnas del manifiesto, para la unión |
| `prob_original_<clase>`, `prob_optimized_<clase>` | Probabilidades (softmax) sin redondear |

## Resultado declarado (recalculable)

| | Valor |
|---|---:|
| Muestras | 292 |
| Aciertos del original | 291 |
| Aciertos del optimizado | 290 |
| Acuerdo entre original y optimizado | 291 |

Las métricas por clase y el análisis de errores corresponden a VAL-04 (#14).

**De dónde sale `optimized_prediction`.** Es el INT8 **ejecutado en la Raspberry Pi 4 de la demostración**, que es la cifra de la rúbrica. Corresponde a la columna `int8` de la corrida de VAL-07 en el dispositivo: onnxruntime 1.31.0 con sus optimizaciones por defecto, el mismo preprocesamiento bit a bit que offline. [`comparacion_edge.py`](../validacion/comparacion_edge.py) la une con el original de VAL-02 en [`comparacion_val_edge.csv`](../validacion/resultados/comparacion_val_edge.csv), y las probabilidades son el softmax de los logits registrados en el dispositivo. `original_prediction` es el `model.pt` en PyTorch: solo corre offline, pero en la Raspberry su exportación FP32 da las mismas 292 predicciones.

Antes (16 oct), este archivo usaba el INT8 de la laptop de VAL (AMD Ryzen 5 5625U, 288 aciertos). En el dispositivo el INT8 coincide con la aritmética de referencia del grafo en las 295 entradas de VAL-07 (ver [`preprocesamiento-edge.md`](preprocesamiento-edge.md)). La comparación de la laptop se conserva en [`comparacion_val.csv`](../validacion/resultados/comparacion_val.csv) (VAL-02).

## Exclusiones

**Ninguna muestra de `val` está excluida.** El JSON lo registra en `"exclusiones": []`. Si en el futuro se excluyera alguna, cada una debe ir ahí con su `sample_id` y su `motivo`; el verificador rechaza exclusiones sin motivo.

Antes de armar el manifiesto, el P3 dejó fuera las 661 anotaciones de `car` y `bicycle` (motivo `excluded_category`; ver `Proyecto3/docs/clases.md`). No son muestras de `val`: quedan registradas en `manifest.meta.json` y en `exclusiones_previas_al_manifiesto` del JSON.

## Regenerar

Desde `Proyecto4/`, con el entorno de VAL ([`comparacion-modelos.md`](comparacion-modelos.md#reproducir)) y el manifiesto del P3 en local:

```bash
modelo/.venv/Scripts/python validacion/comparacion_edge.py
modelo/.venv/Scripts/python validacion/predicciones_formales.py --comparacion validacion/resultados/comparacion_val_edge.csv
```

[`predicciones_formales.py`](../validacion/predicciones_formales.py) no vuelve a correr los modelos: une la comparación con el manifiesto. Antes de escribir:
- exige el SHA-256 del manifiesto y que el CSV de la comparación sea el que registra su JSON;
- corre la misma verificación con el manifiesto completo.

Si algo falla, no toca la evidencia existente. Dos corridas dan el mismo CSV (`08e07c06…`), el mismo extracto (`d307002a…`) y el mismo meta (`f1e832d4…`).
