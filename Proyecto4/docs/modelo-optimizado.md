# Modelo optimizado para el edge: `1.0.0-int8-e05.1`

Variante ONNX INT8 del modelo publicado **1.0.0 del Proyecto 3**, generada por este equipo con [`modelo/convertir.py`](../modelo/convertir.py) y [`modelo/conversion.yaml`](../modelo/conversion.yaml). Es el archivo que carga el dispositivo (EDGE-03) y el que se compara en calidad y recursos (VAL).

## Origen

| Dato | Valor |
|---|---|
| Modelo del P3 | versión `1.0.0`, run de MLflow `9f9b62c202f0446a8a4b411a10321eff` (`Proyecto3/docs/selection.json`) |
| Pesos originales | `model.pt`, 44 783 563 bytes, SHA-256 `e4acca429ebf73d0e5a60fb0dda383a6a5322dccb1decf04b4e40ab9db989172` |
| Arquitectura | ResNet-18, cabeza `Dropout(0.5) → Linear(512, 3)` (leída del checkpoint) |
| Clases (orden de salida) | 0 `cat`, 1 `dog`, 2 `person` |

`convertir.py` exige ese SHA-256 y carga el checkpoint con `load_checkpoint` del propio P3. Arquitectura, clases y preprocesamiento salen del checkpoint, no se redefinen.

## Variante

| Dato | Valor |
|---|---|
| Versión | `1.0.0-int8-e05.1` |
| Formato | ONNX opset 18 |
| Técnica | Cuantización estática post-entrenamiento con onnxruntime: formato QDQ, pesos INT8 por canal, activaciones UINT8 (U8S8), calibración MinMax |
| Calibración | 300 recortes **solo de train** del manifiesto `m-0.1.3-s42-1` (62 cat, 86 dog, 152 person, semilla 42). IDs en [`registros/calibracion_ids.jsonl`](../modelo/registros/calibracion_ids.jsonl). Validación y test no intervienen |
| Entrada | `entrada`, float32 `[1, 3, 224, 224]`, NCHW, RGB normalizado. La cuantización de la entrada está dentro del grafo: el dispositivo manda float32 |
| Salida | `logits` `[1, 3]`; confianza = softmax |
| Preprocesamiento en el edge | [`modelo/preprocesar.py`](../modelo/preprocesar.py): numpy + Pillow, sin PyTorch. Estira a 224×224 (bilineal), escala a [0, 1] y normaliza con la media y desviación de ImageNet |

### Archivos

| Archivo | Bytes | SHA-256 |
|---|---:|---|
| `model.pt` (original P3) | 44 783 563 | `e4acca429ebf73d0e5a60fb0dda383a6a5322dccb1decf04b4e40ab9db989172` |
| `model_fp32.onnx` (exportación sin optimizar, referencia) | 44 702 717 | `6b640343a5862ad546d074e0b2a7701d5da61d65552f18555d1b4dccf30506c1` |
| **`model_int8.onnx` (variante del edge)** | **11 295 280** | **`ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12`** |

Publicados en `s3://p4-capturas-474665692638/modelos/` (cuenta `474665692638`, `us-east-1`), cada uno con su SHA-256 en los metadatos del objeto:

- `clasificador-p3/1.0.0/model.pt`
- `clasificador-edge/1.0.0-int8-e05.1/`: `model_int8.onnx`, `model_fp32.onnx`, `model_package.json`, `registro_conversion.json`, `calibracion_ids.jsonl`

El registro completo, con entrada, salidas, SHA-256, operadores, versiones y configuración, está en [`modelo/registros/registro_conversion.json`](../modelo/registros/registro_conversion.json).

En el receptor, esta versión se acepta con:

```
P4_MODELOS_ACEPTADOS=1.0.0-int8-e05.1=ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12
```

## Efecto de la técnica (laptop x86, 14 oct)

- **Tamaño:** 44 783 563 → 11 295 280 bytes, **74.78 % menos** que el original.
- **Grafo:** los 20 `Conv` y el `Gemm` guardan sus pesos en 42 inicializadores INT8, con sesgos INT32. Se agregan 33 `QuantizeLinear` y 75 `DequantizeLinear`.
- **Exportación fiel:** diferencia máxima de logits entre ONNX FP32 y PyTorch de 1.3e-05 sobre las 292 muestras de validación.
- **Verificación rápida de calidad (validación del P3, 292 muestras):**

  | Modelo | Preprocesamiento | Accuracy |
  |---|---|---:|
  | Original (PyTorch) | torchvision | 0.9966 |
  | ONNX FP32 | `preprocesar.py` | 0.9966 |
  | ONNX INT8 | `preprocesar.py` | 0.9932 |

  El INT8 coincide con el original en el 99.66 % de las muestras; la caída de accuracy es de 0.34 puntos. La comparación formal por muestra, con F1 y análisis de errores, es de VAL-03 y VAL-04.
- **Latencia:** no se reporta aquí. Se mide en el dispositivo físico (VAL-05); la laptop no cuenta para la rúbrica.

## Reproducir

Desde `Proyecto4/`, con `model.pt` y los recortes del P3 en local (`dvc pull` en `Proyecto3/`):

```bash
python -m venv modelo/.venv
modelo/.venv/Scripts/pip install -r modelo/requirements-conversion.lock.txt --extra-index-url https://download.pytorch.org/whl/cpu
modelo/.venv/Scripts/python modelo/convertir.py
```

Dos corridas seguidas dieron los mismos SHA-256 de `model_fp32.onnx`, `model_int8.onnx`, `model_package.json` y `calibracion_ids.jsonl`.
