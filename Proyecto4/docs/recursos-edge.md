# Recursos y calidad: original contra optimizado — VAL-06 (#18, criterios 3.2 y 3.3)

Comparación auditable de tamaño, latencia en el edge, memoria y calidad entre el modelo original 1.0.0 del P3 y la variante `1.0.0-int8-e05.1`. La calcula [`validacion/recursos.py`](../validacion/recursos.py), que solo usa la biblioteca estándar, a partir de los **datos crudos**:
- los tiempos de la Raspberry ([`evidencias/VAL-05/tiempos.csv`](../evidencias/VAL-05/tiempos.csv), VAL-05);
- las métricas de validación de VAL-04;
- los tamaños de tres fuentes independientes.

| Evidencia | Contenido |
|---|---|
| [`validacion/resultados/recursos_edge.json`](../validacion/resultados/recursos_edge.json) | Tamaños por fuente, latencia por modelo y componente (p50, p95, mín., máx., media), comparación, memoria, calidad y método |
| [`validacion/resultados/recursos_edge.csv`](../validacion/resultados/recursos_edge.csv) | Tabla antes y después: cambio relativo (%) en recursos y absoluto (pp) en calidad |

## Antes y después

Original y optimizado medidos **en la misma Raspberry Pi 4 Model B** (1 GB, Cortex-A72, Debian 13 aarch64), con onnxruntime 1.31.0 `CPUExecutionProvider`. Usan el mismo runtime, el mismo preprocesamiento y las mismas imágenes en el mismo orden. Cada modelo tiene 200 mediciones válidas, sin los 10 calentamientos.

| | Original | Optimizado (INT8) | Cambio |
|---|---:|---:|---:|
| **Tamaño** (`model.pt` → `model_int8.onnx`) | 44 783 563 B (42.71 MiB) | 11 295 280 B (10.77 MiB) | **−74.78 %** (3.96 veces menor) |
| Tamaño en el mismo formato (`model_fp32.onnx` → INT8) | 44 702 717 B | 11 295 280 B | −74.73 % |
| **Latencia p50** (preprocesamiento + inferencia) | 190.11 ms | 113.51 ms | **−40.29 %** (1.67 veces más rápido) |
| **Latencia p95** | 191.52 ms | 114.34 ms | **−40.30 %** |
| Inferencia p50 (solo `sesion.run`) | 147.27 ms | 71.00 ms | −51.79 % |
| Preprocesamiento p50 (mismo código) | 42.61 ms | 42.30 ms | −0.73 % (sin cambio real) |
| Memoria pico del proceso | 184.2 MiB | 114.4 MiB | −37.86 % |
| Carga de la sesión (1 medición) | 311.6 ms | 152.0 ms | −51.2 % |
| Accuracy en `val` (VAL-04, INT8 en la Raspberry) | 99.658 % | 99.315 % | **−0.3425 pp** (cumple ≤ 2 pp) |
| F1 macro en `val` (VAL-04, INT8 en la Raspberry) | 99.537 % | 99.075 % | −0.4619 pp |

En la columna "Original", la latencia y la memoria corresponden al original exportado a ONNX FP32: los mismos pesos (VAL-01 verificó la paridad con PyTorch) en el mismo runtime que la variante, que es lo que exige el criterio 3.1. El tamaño se reporta de las dos formas: contra el `model.pt` publicado por el P3 y contra el FP32 en el mismo formato ONNX.

## Cómo se calcula (recalculable)

**Tamaños.** Se contrastan los bytes y el SHA-256 de cada archivo en tres fuentes:
- el registro de la conversión;
- el recálculo sobre los objetos de S3 de VAL-01;
- lo que leyó la propia Raspberry en VAL-05.

Si alguna fuente no coincide, el reporte no se escribe. Además, se recalcularon una vez sobre las copias locales, con el mismo resultado. La reducción se calcula con fracciones exactas: (44 783 563 − 11 295 280) / 44 783 563 × 100.

**Latencia.** Se calcula directamente de `tiempos.csv`, solo con las filas `fase == medicion` y `valido == True`: 200 por modelo, ninguna inválida. Los calentamientos quedan excluidos. El tiempo cubre decodificar el JPEG, preprocesar, inferir y aplicar softmax. **No incluye** la captura, la carga del modelo ni el envío a AWS, porque el benchmark no hace llamadas de red: no hay tiempo de AWS mezclado.

**Método de percentil: interpolación lineal** (Hyndman y Fan tipo 7). Para p en [0, 100], con los n valores ordenados x[0..n−1]:

```
h = (n − 1) · p / 100
percentil = x[⌊h⌋] + (h − ⌊h⌋) · (x[⌊h⌋+1] − x[⌊h⌋])
```

Con n = 200: p50 cae entre x[99] y x[100], a la mitad, y p95 entre x[189] y x[190], con peso 0.05. Es el método por defecto de `numpy.percentile` y el de `statistics.quantiles(method="inclusive")`. Al contrastarlo con los dos, los 12 percentiles (p50 y p95 de total, preprocesamiento e inferencia, para los dos modelos) coinciden con diferencias menores a 1e-9 ms.

```bash
python validacion/recursos.py   # verifica VAL-05 y regenera recursos_edge.*
```

## Mejoras medibles

1. **Tamaño: −74.78 %** (3.96 veces menor). Los pesos INT8 ocupan una cuarta parte que los FP32. Es verificable por hash en tres fuentes y vale aunque no se midiera la latencia.
2. **Latencia en el edge: −40.3 % en p50 y en p95** (1.67 veces más rápido). **No está dentro de la variabilidad:** la medición INT8 más lenta (118.09 ms) es más rápida que la FP32 más rápida (189.08 ms), así que las dos distribuciones no se solapan. Las mediciones son estables: el rango es de unos 6 ms por modelo, la mediana no cambia entre la primera y la segunda mitad, y no hubo *throttling* (ver [`benchmark-edge.md`](benchmark-edge.md)).
3. **Memoria pico: −37.9 %** (de 184 a 114 MiB). Es la memoria máxima de cada proceso, en una sola corrida: incluye Python y onnxruntime además del modelo. Es informativa; la rúbrica no exige memoria.

La aceleración se concentra en la inferencia (−51.8 %). El preprocesamiento (unos 42 ms: decodificar un JPEG de 1920 × 1080 y redimensionarlo) es el mismo código y no cambia. Por eso el total mejora menos que la inferencia sola: ese preprocesamiento es ahora el 37 % del tiempo del INT8.

**Qué no se compara.** No se usan tiempos de la laptop para calcular aceleración: las dos latencias son del mismo dispositivo. La calidad del optimizado también es la del dispositivo (VAL-07). La del original es la de PyTorch offline (VAL-02), y en la Raspberry su FP32 da las mismas 292 predicciones.

## Intercambio entre recursos y calidad

| Se gana | Se paga |
|---|---|
| Un modelo 3.96 veces más chico (−74.8 %) | −0.34 pp de accuracy en `val`: 1 acierto menos de 292 (291 → 290) |
| Inferencia 1.67 veces más rápida en la Raspberry (−40.3 % en p50 y p95) | −0.46 pp de F1 macro |
| 38 % menos memoria pico | |

**Relación entre la reducción de tamaño y la caída de accuracy.** Por cada punto porcentual de accuracy perdido, el modelo se reduce unos 218 puntos porcentuales de tamaño (74.78 / 0.3425) y la latencia, unos 118 (40.29 / 0.3425). La caída queda dentro del límite de 2 pp con un margen de 1.66 pp.

**Por qué compensa en este hardware.**
- La Raspberry de la demostración tiene **1 GB de RAM** (927 MB visibles). El INT8 deja libres unos 70 MiB más para la captura, el envío y el sistema.
- A 113.5 ms por foto, el edge clasifica unas **8.8 fotos por segundo**, contra unas 5.3 del original. Eso deja margen para capturar y enviar sin acumular retraso.
- El costo en calidad es pequeño y está explicado (VAL-04): una sola muestra (`a559`), en la que el original ya dudaba y en la que el INT8 empata exactamente `cat` y `dog`. `person` conserva precisión y recall de 100 %.

**Calidad y recursos, del mismo dispositivo.** La accuracy del optimizado (99.315 %) es la del INT8 ejecutado en la Raspberry, el mismo que se midió en latencia (VAL-07 y VAL-05). En la laptop de VAL, ese INT8 daba 98.630 % por cómo lo ejecuta su CPU x86 (ver [`metricas-val.md`](metricas-val.md#comparación-con-la-laptop-contexto)). Incluso con esa cifra, más desfavorable, la caída (1.03 pp) también cumplía el límite.
