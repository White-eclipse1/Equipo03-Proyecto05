# Comparación original contra INT8 — VAL-02 (#2, criterios 1.3 y 6.2)

Comparación reproducible, muestra por muestra, entre el modelo publicado 1.0.0 del Proyecto 3 y la variante del edge `1.0.0-int8-e05.1`. Se corre sobre **exactamente** las muestras `val` del manifiesto del P3 (`m-0.1.3-s42-1`, 292 recortes). La hace [`validacion/comparar_modelos.py`](../validacion/comparar_modelos.py), y la evidencia queda en [`validacion/resultados/`](../validacion/resultados/).

## Resultado (15 oct de 2026, laptop x86)

292 muestras de `val` (67 cat, 78 dog, 147 person), ninguna faltante, ningún ID duplicado. Los IDs y las etiquetas son los del manifiesto, en su orden, y los 300 IDs de calibración son de `train` según el manifiesto.

| Modelo | Aciertos | Accuracy | Acuerdo con el original |
|---|---:|---:|---:|
| `original` (PyTorch) | 291 / 292 | 0.99658 | — |
| `fp32` (ONNX) | 291 / 292 | 0.99658 | 292 / 292 |
| `int8_referencia` (QDQ sin fusionar) | 290 / 292 | 0.99315 | 291 / 292 |
| **`int8`** (onnxruntime por defecto, esta CPU) | **288 / 292** | **0.98630** | **287 / 292** |

Entorno: Python 3.13.15, torch 2.14.0+cpu, onnxruntime 1.31.0 y numpy 2.5.3 (idéntico a `modelo/requirements-conversion.lock.txt`). CPU: AMD Ryzen 5 5625U (Zen 3: AVX2, sin VNNI). Dos corridas seguidas dan el mismo CSV byte a byte (SHA-256 `e3be4f68…8240`).

Son números de la laptop. Las métricas por clase y el análisis de errores corresponden a VAL-04 (#14), y la medición que cuenta para la rúbrica se hace en el dispositivo (VAL-07, VAL-05).

### Hallazgo: el INT8 da resultados distintos según cómo lo ejecuta onnxruntime

**Lo medido.** Con el mismo `model_int8.onnx`, el mismo entorno y las mismas imágenes:
- con las optimizaciones por defecto de onnxruntime, que funden los pares QDQ en kernels enteros, hay **288** aciertos;
- con esas optimizaciones apagadas (`ORT_DISABLE_ALL`), hay **290**.

Las diferencias están en muestras que el original clasifica con mucha seguridad. Por ejemplo, `0.1.3:a448` es `cat` con probabilidad 0.9996 en el original, y el INT8 fusionado la convierte en `person` con 0.506. El registro de conversión, generado en otra máquina cuya CPU no conocemos, reporta 290/292.

**La hipótesis, sin confirmar.** La variante usa el formato U8S8 (activaciones UINT8 y pesos INT8), y la laptop de VAL es una CPU x86 sin VNNI (AMD Ryzen 5 5625U). onnxruntime documenta que, en esa combinación, las sumas intermedias de los kernels enteros pueden **saturar**. Eso explicaría la diferencia. Pero esta prueba no demuestra que sea la única causa: el kernel fusionado también redondea y recuantiza los resultados intermedios de otra forma que la ejecución QDQ paso a paso.

**Cómo confirmarla.** Correr este mismo CSV en el dispositivo (ARM, VAL-07) o en una CPU x86 con VNNI:
- si ahí `int8` coincide con `int8_referencia`, la hipótesis gana fuerza;
- si no coincide, hay otra causa que buscar.

> **Actualización (VAL-07, 16 oct).** En la Raspberry Pi 4 (aarch64), el mismo `model_int8.onnx` con onnxruntime por defecto **coincide con `int8_referencia` en las 295 entradas** de VAL-07 y acierta 290 de 292 en `val`. Los tensores preprocesados son idénticos bit a bit a los de la laptop. La hipótesis gana fuerza: las 4 diferencias de la laptop dependen del kernel entero en su CPU x86, y no del modelo ni del preprocesamiento. Detalle en [`preprocesamiento-edge.md`](preprocesamiento-edge.md#corrida-en-la-raspberry-16-oct-de-2026).

Mientras tanto, el CSV trae dos columnas del INT8 y la evidencia registra el nombre del CPU:

- **`int8`** (`optimized_prediction`): lo que ejecuta el runtime en la máquina que corre la comparación.
- **`int8_referencia`**: el mismo archivo con `ORT_DISABLE_ALL`. Cada `QuantizeLinear` y `DequantizeLinear` se ejecuta tal cual y la convolución se hace en float, sin kernels enteros fusionados. Es la cifra contra la que se contrasta el dispositivo.

El comentario de `modelo/conversion.yaml` afirmaba que las activaciones UINT8 "se comportan igual en x86 y en ARM", y ya se corrigió. Es solo un comentario: no cambia la técnica, la configuración que lee `convertir.py` ni el registro de conversión, y VAL-01 sigue pasando.

### Las tres cifras del INT8, y cuál cuenta

| Cifra | De dónde sale | Qué mide |
|---|---|---|
| 99.32 % (290/292) | `verificacion_rapida` de `modelo/registros/registro_conversion.json` | El runtime por defecto en la máquina donde se convirtió (CPU no registrada). Coincide con la referencia |
| 99.32 % (290/292) | columna `int8_referencia` de este CSV | La aritmética del grafo QDQ paso a paso, sin kernels enteros fusionados |
| 98.63 % (288/292) | columna `int8` (`optimized_prediction`) de este CSV | El runtime por defecto en la laptop de VAL (x86 sin VNNI) |

**Ninguna de las tres es la cifra de la rúbrica.** La que cuenta es la del runtime **en el dispositivo**. Cuando esté disponible, VAL-07 vuelve a generar este CSV en el edge, de modo que la columna `optimized_prediction` sea la del dispositivo. Esa corrida también pone a prueba la hipótesis de la saturación: si en ARM `int8` coincide con `int8_referencia`, la apoya. Mientras tanto, el CSV de la laptop sirve para VAL-03 y VAL-04, siempre citando la CPU.

## Qué se compara

| Columna | Archivo | Runtime y preprocesamiento |
|---|---|---|
| `original` | `model.pt` del P3 (`e4acca42…`) | PyTorch con `build_eval_transform` del P3: el modelo tal como se evaluó en el P3 |
| `fp32` | `model_fp32.onnx` (`6b640343…`) | onnxruntime CPU con [`modelo/preprocesar.py`](../modelo/preprocesar.py) |
| `int8` | `model_int8.onnx` (`ba89ee43…`) | onnxruntime CPU con optimizaciones por defecto y `preprocesar.py`, como corre en el dispositivo |
| `int8_referencia` | `model_int8.onnx` (`ba89ee43…`) | onnxruntime CPU con `ORT_DISABLE_ALL` y `preprocesar.py` |

La diferencia entre `original` e `int8` es la que ve el usuario. Las otras columnas separan sus causas:

- De `original` a `fp32` cambian el runtime y el preprocesamiento del edge. Aquí no cambia ninguna predicción.
- De `fp32` a `int8_referencia` actúa solo la cuantización.
- De `int8_referencia` a `int8` actúa solo el kernel entero de esa CPU.

## Qué garantiza antes y después de correr

1. **Insumos con hash exigido.** El SHA-256 del manifiesto (`45600f29…`, el de `selection.json` del P3), el de `crops.jsonl` (`d3d61f35…`) y el de los tres modelos se toman de `modelo/conversion.yaml` y del registro de conversión que verificó VAL-01. Si alguno no coincide, el comparador se detiene sin escribir nada.
2. **Cada imagen, verificada por hash y por su origen.** El P3 fija `crops.jsonl` por SHA-256, pero no guarda un hash por imagen. Por eso hay tres comprobaciones, cada una por un camino distinto:
   - **Inventario congelado.** [`validacion/inventario_recortes.py`](../validacion/inventario_recortes.py) generó [`validacion/registros/recortes_0.1.3.jsonl`](../validacion/registros/recortes_0.1.3.jsonl): SHA-256, bytes y `VersionId` en S3 de los 1 459 recortes (1 022 de train, 292 de val y 145 de test). El ETag de los 1 459 objetos coincide con el MD5 del archivo local. El comparador exige el SHA-256 del inventario (el de [`recortes_0.1.3.json`](../validacion/registros/recortes_0.1.3.json)) y el de cada PNG de `val`.
   - **Dimensiones.** Cada PNG debe medir lo que dice `crops.jsonl`, el archivo del P3.
   - **Huella de validación del P3.** El original, corrido sobre estas imágenes, debe reproducir el accuracy y el `val_loss` que el P3 registró en `selection.json` para el modelo seleccionado. Resultado: accuracy 0.9965753424657534, idéntico; `val_loss` 0.0242525 contra 0.0242535 del P3, una diferencia de 9.9e-7, dentro de la tolerancia de 1e-5 que cubre float32 por muestra contra por lotes. La pérdida es continua: se movería con cualquier imagen distinta de las que evaluó el P3.
3. **Mismas muestras y etiquetas.** El comparador toma las filas con `split == "val"` del manifiesto, en su orden. La clase real (`true_class`) es la `category_name` del manifiesto, y se exige que su `class_index` corresponda al orden `cat, dog, person` del modelo.
4. **Calibración solo con train, comprobada contra el manifiesto.** Cada uno de los 300 IDs de `modelo/registros/calibracion_ids.jsonl` debe ser `train` según el manifiesto del P3. Ninguno puede ser de `val` ni de `test`, ni estar fuera del manifiesto.
5. **CSV verificado al releerlo.** Después de escribirlo, el comparador vuelve a leer el CSV. Sus IDs deben ser exactamente los de `val`, sin duplicados y con las mismas etiquetas. Una muestra sin imagen se registra con su motivo y la comparación falla: no se aceptan faltantes.

## Evidencia

[`validacion/resultados/comparacion_val.csv`](../validacion/resultados/comparacion_val.csv): una fila por muestra.

| Columna | Contenido |
|---|---|
| `sample_id` | `crop_id` del manifiesto del P3 |
| `true_class` | clase real según el manifiesto |
| `original_prediction` | clase predicha por el modelo original |
| `optimized_prediction` | clase predicha por el INT8 (igual que `int8_prediction`) |
| `fp32_prediction`, `int8_prediction`, `int8_referencia_prediction` | clase predicha por cada ejecución ONNX |
| `prob_<columna>_<clase>` | probabilidad (softmax) sin redondear, para recalcular cualquier métrica |

[`validacion/resultados/comparacion_val.json`](../validacion/resultados/comparacion_val.json) contiene:
- la procedencia: hashes del manifiesto, de `crops.jsonl`, del inventario de recortes y de los modelos;
- la huella de validación del P3 (`huella_p3`);
- la comprobación de la calibración;
- la verificación del CSV (IDs, duplicados, faltantes y etiquetas) y su SHA-256;
- el entorno, con versiones y CPU;
- un resumen con aciertos y acuerdos.

## Reproducir

Desde `Proyecto4/`, con Python 3.13 (el lockfile fija `numpy==2.5.3`, que pide 3.12 o superior):

```bash
python -m venv modelo/.venv
modelo/.venv/Scripts/pip install -r validacion/requirements-validacion.lock.txt --extra-index-url https://download.pytorch.org/whl/cpu
modelo/.venv/Scripts/python validacion/comparar_modelos.py --descargar --profile <perfil-cuenta-p4>
```

[`validacion/requirements-validacion.lock.txt`](../validacion/requirements-validacion.lock.txt) es el lockfile de la conversión más boto3 y **awscrt**, con versiones fijas. awscrt hace falta si el perfil de AWS se configuró con `aws login`: botocore lo necesita para firmar con esas credenciales. Con llaves de acceso no se usa, pero se instala igual para que el entorno sea el mismo en cualquier caso.

`--descargar` baja de `s3://p4-capturas-474665692638/` lo que falte en local:
- los modelos, de `modelos/`;
- el manifiesto y los recortes del P3, de `datos/p3/`. Se guardan en `Proyecto3/data/manifests/m-0.1.3-s42-1/` y `Proyecto3/data/crops/0.1.3/`, las mismas rutas que usa `convertir.py`.

Después exige sus SHA-256 igual que con copias locales. En otra máquina x86 la columna `int8` puede cambiar según el CPU; las demás deben dar el mismo CSV.

Las pruebas (`python -m pytest tests/test_comparacion.py`) no necesitan torch ni pesos. Usan un manifiesto y recortes sintéticos para comprobar:
- la selección de `val`, el orden y las etiquetas;
- los duplicados y los faltantes;
- la calibración;
- las dimensiones y el hash de los recortes, y el inventario (incluido un ETag que no es el MD5);
- la huella de validación del P3;
- la exigencia de hashes.

El inventario se regenera solo si cambia la copia de los datos (`modelo/.venv/Scripts/python validacion/inventario_recortes.py --profile <perfil-cuenta-p4>`). Si los objetos de S3 no cambian, da el mismo `recortes_0.1.3.jsonl`.
