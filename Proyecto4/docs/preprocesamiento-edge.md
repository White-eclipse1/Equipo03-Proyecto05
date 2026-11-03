# Preprocesamiento y entradas conocidas en el edge — VAL-07 (#19, criterios 2.2 y 6.2)

Comprueba que las diferencias entre el original y el INT8 **no vienen de un preprocesamiento incorrecto en el dispositivo**. Para eso corre **el mismo** [`edge/verificar_preprocesamiento.py`](../edge/verificar_preprocesamiento.py) en la Raspberry y en la laptop de VAL ("offline"), con las mismas entradas y los mismos modelos, y [`validacion/contrastar_edge.py`](../validacion/contrastar_edge.py) compara las dos corridas.

## Qué se comprueba

**1. Preprocesamiento contra valores calculados a mano.** El script verifica `modelo/preprocesar.py` en cada máquina con imágenes sintéticas, cuyos valores esperados se calculan en float32 sin depender de la otra máquina:

| Comprobación | Qué demuestra |
|---|---|
| `tensor.forma_tipo` | Entrada `[1, 3, 224, 224]`, float32, NCHW contiguo |
| `normalizacion.exacta` | Un color sólido (255, 128, 0) da, en los 224 × 224 píxeles, exactamente `(x/255 − media) / desviación`, con media `[0.485, 0.456, 0.406]` y desviación `[0.229, 0.224, 0.225]` de ImageNet. Prueba la escala a [0, 1] y el canal 0 = R |
| `rgb.orden_y_orientacion` | Una imagen roja a la izquierda y azul a la derecha conserva los colores y los lados: RGB (no BGR), sin espejo ni transposición |
| `resize.sin_recorte` | Una franja en el borde de una imagen de 400 × 100 sobrevive en la columna 0: se estira la imagen completa a 224 × 224 (`resize_to_square` del P3); no hay recorte central |
| `escala.cero_uno` | Un degradado 0..255 vuelve exactamente a [0, 1] al deshacer la normalización |
| `rgb.conversion` | Escala de grises y RGBA se convierten a RGB (el canal alfa se descarta) |

Las pruebas (`tests/test_preprocesamiento_edge.py`) confirman que estas comprobaciones **detectan** un preprocesamiento mal hecho: BGR, sin normalizar, con recorte central o en float64.

**2. Entradas conocidas**, verificadas por SHA-256 contra el índice versionado [`validacion/registros/entradas_edge.jsonl`](../validacion/registros/entradas_edge.jsonl):
- los **292 recortes `val`** del manifiesto del P3, con su clase real; sus predicciones offline son las de VAL-02;
- las **3 fotos de la cámara** de EDGE-03 (`cat`, `dog`, `person`).

Para cada entrada se registra el SHA-256 del tensor preprocesado, su forma y su tipo, y la clase y los logits de tres ejecuciones:

| Ejecución | Modelo | onnxruntime |
|---|---|---|
| `int8` | `model_int8.onnx` | Opciones por defecto, como `edge/inferencia.py` |
| `int8_referencia` | `model_int8.onnx` | `ORT_DISABLE_ALL`: el grafo QDQ paso a paso |
| `fp32` | `model_fp32.onnx` (original sin cuantizar) | Opciones por defecto |

**3. Contraste entre la Raspberry y la laptop** (`contrastar_edge.py`):
- **Lo que debe coincidir**, y si no coincide el contraste falla: las comprobaciones sintéticas en los dos lados, el mismo `preprocesar.py`, los mismos modelos y entradas, y el **tensor preprocesado idéntico bit a bit** en cada entrada.
- **Lo que se cuenta y se explica**, sin que sea una falla: las predicciones del edge contra las offline en cada ejecución, la diferencia máxima de logits y si en ARM el `int8` coincide con `int8_referencia`. Esto último pone a prueba la hipótesis de saturación de VAL-02.

## Pasos

### 1. Josué: preparar el paquete de entradas

Desde `Proyecto4/`, con el entorno de VAL y los datos del P3 (`--descargar` de VAL-02):

```bash
modelo/.venv/Scripts/python validacion/preparar_entradas_edge.py
modelo/.venv/Scripts/python edge/verificar_preprocesamiento.py --entradas validacion/entradas_edge --modelos modelo/artefactos/1.0.0-int8-e05.1 --maquina laptop
```

El primer comando genera `validacion/entradas_edge.zip` (69.5 MB, ignorado por Git) y el índice versionado. El segundo es la corrida offline, que queda en `evidencias/VAL-07/laptop/`. Josué le hace llegar el zip a Omar por un canal privado: directamente, o subiéndolo a S3 con un enlace temporal, como en VAL-05.

### 2. Omar: copiar a la Raspberry

Desde la laptop con el repositorio actualizado:

```bash
rsync -av Proyecto4/edge/verificar_preprocesamiento.py Proyecto4/edge/benchmark.py pi@<ip-de-la-raspberry>:/home/pi/edge01/app/
rsync -av Proyecto4/modelo/preprocesar.py pi@<ip-de-la-raspberry>:/home/pi/edge01/modelo/preprocesar.py
rsync -av entradas_edge.zip pi@<ip-de-la-raspberry>:/home/pi/edge01/
```

Los modelos INT8 y FP32 ya están en `/home/pi/edge01/modelo/` desde VAL-05.

### 3. Omar: correr en la Raspberry

```bash
cd "$HOME/edge01"
source .venv/bin/activate
sha256sum entradas_edge.zip
python -c "import zipfile; zipfile.ZipFile('entradas_edge.zip').extractall('.')"
python app/verificar_preprocesamiento.py
```

El hash del zip debe ser `8881813c3c1111f92c5076f3b9868e084237a39693d6bd6038d8a36221c6c085`.

La corrida tarda unos minutos. Debe mostrar `ok` en las 6 comprobaciones, avanzar de 50 en 50 hasta 295 entradas y escribir `evidencias/VAL-07/raspberry/resultados.csv` y `resultados.json`. Toma una captura de la Terminal. No hace llamadas de red.

### 4. Omar: devolver la evidencia

Devuelve, sin editarlos, `evidencias/VAL-07/raspberry/resultados.csv`, `resultados.json` y la captura (por ejemplo, en un zip). Josué los coloca en `Proyecto4/evidencias/VAL-07/raspberry/`.

### 5. Josué: contrastar

```bash
python validacion/contrastar_edge.py
```

Escribe `validacion/resultados/contraste_edge.json` y la tabla `validacion/resultados/entradas_conocidas.csv`, solo si el contraste pasa.

## Corrida offline (laptop de VAL)

En [`evidencias/VAL-07/laptop/`](../evidencias/VAL-07/laptop/): Python 3.13.15, onnxruntime 1.31.0, Ryzen 5 5625U. Las 6 comprobaciones sintéticas pasan. En `val`, `int8` acierta 288 de 292, `int8_referencia` 290 y `fp32` 291. Las predicciones de las tres ejecuciones son **idénticas, muestra por muestra**, a las de VAL-02 (`comparacion_val.csv`).

## Corrida en la Raspberry (16 oct de 2026)

Omar la ejecutó a las 18:31 (UTC−06:00) en la Raspberry Pi 4 Model B Rev 1.5 (1 GB), con Debian 13 aarch64, Python 3.13.5, onnxruntime 1.31.0, numpy 2.5.4 y Pillow 12.3.0. El código fue `verificar_preprocesamiento.py` `f08c314d…` y `preprocesar.py` `8fa139aa…`, los dos idénticos a los del repositorio. La evidencia está en [`evidencias/VAL-07/raspberry/`](../evidencias/VAL-07/raspberry/): llegó en `raspberry.zip` (SHA-256 `5210de49…`) y se copió sin editar. Ese zip no trae captura de la Terminal.

`python validacion/contrastar_edge.py` **pasa todas las comprobaciones**. El CI las repite en `tests/test_preprocesamiento_edge.py`. Resultados en [`contraste_edge.json`](../validacion/resultados/contraste_edge.json).

### Preprocesamiento: verificado

| Criterio de VAL-07 | Resultado en la Raspberry |
|---|---|
| RGB confirmado | `rgb.orden_y_orientacion` y `rgb.conversion`: ok |
| Resize 224×224 confirmado | `resize.sin_recorte` y `tensor.forma_tipo`: ok; los 295 tensores son `1x3x224x224` |
| Escala [0, 1] confirmada | `escala.cero_uno`: ok |
| Media y desviación de ImageNet | `normalizacion.exacta`: ok, bit a bit |
| Forma y tipo del tensor | `[1, 3, 224, 224]`, float32, NCHW, en las 295 entradas |
| Mismo preprocesamiento que offline | **295 de 295 tensores idénticos bit a bit** (SHA-256) entre la Raspberry y la laptop; también los tensores sintéticos |
| Orden de clases cat/dog/person | En `val`, cada clase se predice sobre todo como sí misma; las 3 fotos de la cámara dan la clase presentada |

**El preprocesamiento del dispositivo es exactamente el offline.** Ninguna diferencia entre el original y el INT8 puede venir de él.

### Predicciones: Raspberry contra laptop

| Ejecución | Aciertos en `val`, Raspberry | Aciertos en `val`, laptop | Iguales (de 295) | Máx. \|Δlogit\| |
|---|---:|---:|---:|---:|
| `fp32` (original sin cuantizar) | 291 / 292 | 291 / 292 | 295 | 6.0e-6 |
| `int8_referencia` (QDQ paso a paso) | 290 / 292 | 290 / 292 | 295 | 0.067 |
| **`int8`** (onnxruntime por defecto) | **290 / 292** | 288 / 292 | 291 | 6.7 |

**En la Raspberry, el INT8 coincide con la aritmética de referencia en las 295 entradas.** En la laptop coincide en 291. Las 4 diferencias son las muestras que la laptop cambia:

| Muestra | Real | Original (VAL-02) | `fp32` | `int8_referencia` | `int8` Raspberry | `int8` laptop |
|---|---|---|---|---|---|---|
| `0.1.3:a1647` | cat | cat | cat | cat | **cat** | person |
| `0.1.3:a448` | cat | cat | cat | cat | **cat** | person |
| `0.1.3:a554` | dog | dog | dog | dog | **dog** | person |
| `0.1.3:a322` | cat | dog | dog | dog | dog | cat |
| `0.1.3:a559` | dog | dog | dog | cat | cat | cat |

La tabla completa de entradas conocidas, con las 3 fotos de la cámara, las 5 muestras relevantes de VAL-04 y una correcta por clase, está en [`entradas_conocidas.csv`](../validacion/resultados/entradas_conocidas.csv).

### Diferencias explicadas

- **Entre el original y el FP32: ninguna en el dispositivo.** El FP32 de la Raspberry da las mismas predicciones que el de la laptop (diferencia máxima de 6e-6), y en VAL-02 el FP32 de la laptop coincidía con el original de PyTorch en las 292 muestras.
- **Entre el original y el INT8 en el dispositivo: una sola muestra**, `a559`. Es un caso límite en el que el original ya dudaba (`dog` 0.583 contra `cat` 0.416), y la referencia QDQ también la cambia. Es la pérdida propia de la cuantización: en el dispositivo, el INT8 acierta 290 de 292 contra 291 del original, una diferencia de 0.34 pp. `a322` es un error que ya tenía el original y que el INT8 repite en el dispositivo.
- **Entre el INT8 de la laptop y el del dispositivo: 4 muestras**, que dependen del runtime en x86. En la Raspberry, el kernel entero que usa onnxruntime por defecto da exactamente lo mismo que la referencia en las 295 entradas; en la laptop, no. Esto **respalda la hipótesis de VAL-02**: la diferencia de la laptop viene de cómo ejecuta el INT8 su CPU x86 sin VNNI, no del modelo ni del preprocesamiento. La prueba muestra *dónde* está la diferencia (el kernel de x86); que el mecanismo exacto sea la saturación sigue siendo la explicación más probable, sin demostración directa.

**Consecuencia para la calidad.** La cifra del dispositivo es 290 de 292, 0.34 pp por debajo del original: mejor que los 288 de la laptop que reportaron VAL-03, VAL-04 y VAL-06. Con esta corrida, VAL-08 regeneró esos tres con la predicción del edge ([`comparacion_edge.py`](../validacion/comparacion_edge.py) y `predicciones_formales.py --comparacion`).
