# Calidad del original y del optimizado en validación — VAL-04 (#14, criterio 1.3)

Métricas formales del modelo original del P3 (`model.pt` 1.0.0) y de la variante `1.0.0-int8-e05.1` **ejecutada en la Raspberry Pi 4 de la demostración**. Se calculan **exclusivamente** desde el archivo de predicciones por muestra de VAL-03 ([`predicciones_val.csv`](../validacion/resultados/predicciones_val.csv)) y sobre la **misma validación**: las 292 muestras `val` del manifiesto `m-0.1.3-s42-1`.

| Evidencia | Contenido |
|---|---|
| [`validacion/resultados/metricas_val.json`](../validacion/resultados/metricas_val.json) | Métricas de los dos modelos, matrices de confusión, caída de accuracy, cambios por clase, errores relevantes y referencia del test del P3 (aparte) |
| [`validacion/resultados/metricas_val.csv`](../validacion/resultados/metricas_val.csv) | Tabla antes y después: cada métrica con el original, el optimizado y la diferencia en pp |

> **Todas las cifras son de validación (`val`).** Las del test del P3 aparecen solo en la [última sección](#cifras-del-test-del-p3-otra-partición), como referencia; no se comparan con estas.

## Resultado

| | Original | Optimizado (INT8 en la Raspberry) |
|---|---:|---:|
| Aciertos | 291 / 292 | 290 / 292 |
| Accuracy | 99.658 % | 99.315 % |
| F1 macro | 99.537 % | 99.075 % |

**Caída de accuracy: 25/73 pp = 0.3425 pp. Cumple el límite de 2 pp.** Se calcula con fracciones exactas, (291 − 290) / 292 × 100, y se compara con 2 sin redondear. El accuracy del original en `val` es idéntico al que registró el P3 para el modelo seleccionado (0.9965753424657534, `Proyecto3/docs/selection.json`).

**De dónde sale cada columna:**
- **Original:** `model.pt` en PyTorch, que solo corre offline (VAL-02). En la Raspberry su exportación FP32 da las mismas 292 predicciones (VAL-07).
- **Optimizado:** el INT8 tal como lo ejecuta onnxruntime 1.31.0, con sus opciones por defecto, en la Raspberry (VAL-07). Usa el mismo preprocesamiento, bit a bit, que offline.

## Antes y después por clase

| Clase | Support | Precisión orig. → opt. | Recall orig. → opt. | F1 orig. → opt. |
|---|---:|---|---|---|
| `cat` | 67 | 100.00 % → 98.51 % | 98.51 % → 98.51 % | 99.25 % → 98.51 % |
| `dog` | 78 | 98.73 % → 98.72 % | 100.00 % → 98.72 % | 99.36 % → 98.72 % |
| `person` | 147 | 100.00 % → 100.00 % | 100.00 % → 100.00 % | 100.00 % → 100.00 % |

Esta tabla está redondeada para leerla. Los valores exactos y las diferencias en pp están en `metricas_val.csv`.

Matrices de confusión (filas: clase real; columnas: predicha `cat`, `dog`, `person`):

| Real | Original | Optimizado |
|---|---|---|
| `cat` | 66, 1, 0 | 66, 1, 0 |
| `dog` | 0, 78, 0 | **1**, 77, 0 |
| `person` | 0, 0, 147 | 0, 0, 147 |

### Cambios por clase

La única diferencia entre los dos modelos es **una muestra de `dog` (`a559`) que el INT8 predice como `cat`**:
- **`dog`:** el recall baja 1.28 pp (de 78 a 77).
- **`cat`:** la precisión baja 1.49 pp, porque aparece un falso `cat`.
- **`person`:** sin cambios; precisión y recall de 100 % en los dos.

El otro error (`a322`) es de los dos modelos y no cambia.

## Errores relevantes

Son las 2 muestras en que algún modelo falla o en que los dos no coinciden. La última columna es contexto de VAL-07 y no interviene en ninguna métrica: es lo que predice el mismo INT8 en el dispositivo con la aritmética de referencia del grafo.

| Muestra | Real | Original (prob.) | Optimizado (prob.) | Tipo | Referencia QDQ |
|---|---|---|---|---|---|
| `0.1.3:a559` | dog | dog (0.583) | cat (0.4995) | regresión | cat |
| `0.1.3:a322` | cat | dog (0.891) | dog (0.845) | los dos fallan | dog |

Lectura:

- **`a559`: un empate exacto de la salida cuantizada.** El original ya dudaba en esta muestra (`dog` 0.584 contra `cat` 0.415). En el INT8 del dispositivo, los logits de `cat` y `dog` quedan **exactamente iguales** (2.2788479328155518), con probabilidad 0.4995 cada una. `argmax` desempata hacia el primer índice, `cat`. La aritmética de referencia da lo mismo, así que es un efecto de la cuantización y no del runtime. Es la pérdida propia de cuantizar a INT8: una muestra frontera cuyo margen desaparece.
- **`a322`: un error que ya tenía el original.** El original la clasifica como `dog` con 0.891 y el INT8 repite el error (0.845). No es una regresión.

## Comparación con la laptop (contexto)

Hasta el 16 de octubre, estas métricas usaban el INT8 ejecutado en la laptop de VAL (AMD Ryzen 5 5625U): 288 aciertos de 292 y una caída de 1.0274 pp, que también cumplía. Ese INT8 cambiaba otras 3 muestras (`a1647`, `a448` y `a554`) y corregía `a322`. En la Raspberry, en cambio, el INT8 coincide con la aritmética de referencia del grafo en las 295 entradas de VAL-07. Las diferencias de la laptop dependen del kernel entero de su CPU x86; ver [`comparacion-modelos.md`](comparacion-modelos.md) y [`preprocesamiento-edge.md`](preprocesamiento-edge.md). La cifra de la rúbrica es la del dispositivo. La comparación de la laptop se conserva en `comparacion_val.csv` (VAL-02).

## Recalcular

Desde `Proyecto4/`, con cualquier Python 3.11 o superior y sin dependencias:

```bash
python validacion/verificar_predicciones.py   # VAL-03: el archivo de predicciones es válido
python validacion/metricas.py                 # VAL-04: recalcula y reescribe metricas_val.*
```

[`metricas.py`](../validacion/metricas.py) funciona así:
- **Antes de calcular,** verifica el archivo de predicciones contra el manifiesto.
- **Al calcular,** usa fracciones exactas y solo convierte a decimal al escribir.
- **Antes de escribir,** contrasta los aciertos con los que declara VAL-03. Si algo no cuadra, no toca la evidencia.

Las métricas coinciden con scikit-learn (diferencias menores a 1e-12), tanto con las predicciones de la laptop como con las del dispositivo.

## Cifras del test del P3 (otra partición)

| Partición | Muestras | Modelo | Accuracy | F1 macro | Fuente |
|---|---:|---|---:|---:|---|
| **test** del P3 | 145 | solo el original | 97.93 % | 97.44 % | `Proyecto3/reports/evaluation/9f9b62c2…/metrics.json` |

**No es la validación de VAL-04 y no se compara con las cifras de arriba.** Es otra partición: el P3 evaluó en test solo el modelo seleccionado. El INT8 no se evalúa en test: el test del P3 no interviene en la conversión, la calibración ni esta comparación. En `metricas_val.json` estas cifras están aparte, en `referencia_test_p3`.
