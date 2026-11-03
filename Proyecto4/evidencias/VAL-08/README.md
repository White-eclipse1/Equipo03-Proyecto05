# Paquete de evidencia: calidad y recursos — VAL-08 (#24)

Archivos para que el evaluador **recalcule** calidad y recursos sin depender de capturas de pantalla (criterios 1.1–1.3, 3.1–3.3 y 6.2). Todo se recalcula **solo con esta carpeta** y Python 3.11 o superior, sin instalar nada:

```bash
python recalcular.py
```

[`recalcular.py`](recalcular.py) verifica cada archivo contra [`SHA256SUMS.txt`](SHA256SUMS.txt). Reconstruye las predicciones por muestra desde los datos primarios, las une con el manifiesto y recalcula accuracy, F1, la caída en pp, la reducción de tamaño y p50/p95 desde los tiempos crudos. Termina en `VERIFICADO` si todo coincide con lo declarado.

## Resumen

| | Original | Optimizado | Cambio |
|---|---:|---:|---:|
| Modelo | `model.pt` 1.0.0 (P3) | `model_int8.onnx` `1.0.0-int8-e05.1` | |
| Tamaño | 44,783,563 B | 11,295,280 B | **−74.78 %** |
| Accuracy en `val` (292) | 99.658 % | 99.315 % | **−0.3425 pp** (25/73; cumple ≤ 2 pp) |
| F1 macro en `val` | 99.537 % | 99.075 % | |
| Latencia p50 en la Raspberry | 190.11 ms | 113.51 ms | **−40.29 %** |
| Latencia p95 en la Raspberry | 191.52 ms | 114.34 ms | **−40.30 %** |

F1 por clase en `val`:

| Clase | Original | Optimizado |
|---|---:|---:|
| `cat` | 99.25 % (support 67) | 98.51 % (support 67) |
| `dog` | 99.36 % (support 78) | 98.72 % (support 78) |
| `person` | 100.00 % (support 147) | 100.00 % (support 147) |

El optimizado es el INT8 **ejecutado en la Raspberry Pi 4 de la demostración** (VAL-07), con el mismo preprocesamiento bit a bit que offline. Las latencias comparan el INT8 con el original exportado a ONNX FP32 **en el mismo dispositivo**, el mismo runtime y las mismas imágenes; no se usan tiempos de laptop.

## Dónde está cada cosa

| Criterio de VAL-08 | Archivo (campo) |
|---|---|
| Identificación del modelo original y del optimizado; hashes SHA-256 | [`modelo/ficha_modelos.json`](modelo/ficha_modelos.json) (`original`, `optimizado`, `fp32_onnx`); [`modelo/registro_conversion.json`](modelo/registro_conversion.json) (`entrada`, `salidas`); [`modelo/linaje_verificacion.json`](modelo/linaje_verificacion.json) (VAL-01: 20 comprobaciones, incluidos los binarios en S3) |
| Referencia al manifiesto de validación | [`validacion/manifest_val.jsonl`](validacion/manifest_val.jsonl) (las 292 líneas `val`, byte a byte) y [`validacion/manifest.meta.json`](validacion/manifest.meta.json): `m-0.1.3-s42-1`, SHA-256 del manifiesto completo `45600f29…` |
| Predicciones por muestra | [`validacion/predicciones_val.csv`](validacion/predicciones_val.csv) (`sample_id`, `true_class`, `original_prediction`, `optimized_prediction`, probabilidades). Datos primarios en [`validacion/primarios/`](validacion/primarios/): probabilidades del original (VAL-02) y logits del INT8 en la Raspberry (VAL-07) |
| Accuracy y F1 macro de los dos; F1 y support por clase; caída en pp | [`validacion/metricas_val.json`](validacion/metricas_val.json) (`modelos`, `caida_accuracy`) y [`validacion/metricas_val.csv`](validacion/metricas_val.csv) |
| Tamaño original, tamaño optimizado y reducción | [`modelo/ficha_modelos.json`](modelo/ficha_modelos.json) (`bytes`, `reduccion_tamano_pct`); [`benchmark/recursos_edge.json`](benchmark/recursos_edge.json) (`tamanos`, contrastados en tres fuentes) |
| Archivo crudo con más de 100 tiempos y calentamientos identificados | [`benchmark/tiempos.csv`](benchmark/tiempos.csv): una fila por repetición, `fase` = `calentamiento` o `medicion`; 10 + 200 por modelo |
| p50 y p95 | [`benchmark/recursos_edge.json`](benchmark/recursos_edge.json) (`latencia_edge`, `metodo_percentil`: interpolación lineal, tipo 7) |
| Hardware, runtime y condiciones | [`benchmark/benchmark.json`](benchmark/benchmark.json) (`hardware`, `runtime`, `condiciones_inicio`/`fin`, `modelos.*.sesion`); preprocesamiento verificado en el edge: [`validacion/contraste_edge.json`](validacion/contraste_edge.json) |
| Interpretación del intercambio | [abajo](#intercambio-entre-recursos-y-calidad) |

## Condiciones de medición

- **Dispositivo:** Raspberry Pi 4 Model B Rev 1.5, 4 núcleos, 927380 kB de RAM, Debian GNU/Linux 13 (trixie), kernel `6.18.50+rpt-rpi-v8`, aarch64.
- **Runtime:** Python 3.13.5, onnxruntime 1.31.0 (`CPUExecutionProvider`, opciones por defecto), numpy 2.5.4, Pillow 12.3.0.
- **Entrada:** float32 `[1, 3, 224, 224]`, RGB normalizado con la media y la desviación de ImageNet; precisión INT8 (QDQ estático, pesos INT8 por canal, activaciones UINT8) contra FP32.
- **Qué mide cada repetición:** decodificar el JPEG, preprocesar, inferir y aplicar softmax. Queda fuera la captura, la carga del modelo y el envío a AWS, porque el benchmark no hace llamadas de red.
- **Estado del dispositivo:** temperatura de 49.2 °C al inicio y 75.0 °C al final, y `vcgencmd get_throttled` = `throttled=0x0`, sin limitación.
- **Preprocesamiento en el edge:** 295/295 tensores preprocesados identicos (SHA-256); distintos: [].

## Intercambio entre recursos y calidad

La cuantización a INT8 reduce el modelo **74.8 %** (3.96 veces menor) y su latencia en la Raspberry **40.3 %** en p50 y p95. La medición INT8 más lenta es más rápida que la FP32 más rápida, así que la diferencia no está dentro de la variabilidad. La memoria pico baja 37.9 %.

A cambio, la accuracy en `val` baja **0.34 pp**: una sola muestra de 292 (`a559`). Es una muestra frontera en la que el original ya dudaba, y el INT8 empata exactamente `cat` y `dog`. `person` conserva precisión y recall de 100 %. La caída cumple el límite de 2 pp con un margen de 1.66 pp.

En una Raspberry Pi 4 de 1 GB, el INT8 deja más memoria libre para la captura y el envío y clasifica unas 8.8 fotos por segundo, contra 5.3 del original. El costo en calidad es de una muestra.

## Procedencia

El paquete lo genera [`validacion/paquete_val08.py`](../../validacion/paquete_val08.py) a partir de la evidencia de VAL-01 a VAL-07, y solo lo escribe si `recalcular.py` da VERIFICADO. El análisis completo está en `docs/`: [`linaje-modelo.md`](../../docs/linaje-modelo.md), [`predicciones-val.md`](../../docs/predicciones-val.md), [`metricas-val.md`](../../docs/metricas-val.md), [`benchmark-edge.md`](../../docs/benchmark-edge.md), [`recursos-edge.md`](../../docs/recursos-edge.md) y [`preprocesamiento-edge.md`](../../docs/preprocesamiento-edge.md).
