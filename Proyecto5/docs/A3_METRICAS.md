# A3 — Métricas de detección

Tickets: #16 A3-01 y #17 A3-02. Entregable: E6.

## Objetivo

Medir la calidad de localización del detector sobre `p5-eval-v1`, de forma que cualquier persona pueda recalcular los números desde los datos primarios.

## Componentes

- src/p5/metrics/detection.py: IoU, emparejamiento, precision, recall y F1. Lógica pura.
- src/p5/metrics/\_\_main\_\_.py: comando de línea y evidencia.
- tests/test_metrics.py: casos a mano, incluidos los bordes.

## Reglas

Fijadas antes de medir:

| Regla | Valor |
|---|---|
| IoU para aceptar una pareja | ≥ 0.50 |
| Umbral de confianza | ≥ 0.50: es `umbral_alto` de la política. Una prueba exige que coincidan |
| Detector | YOLOX-Tiny, con su filtro inicial de 0.10 y NMS de 0.45 |
| Clases evaluadas | Las 8 clases obstáculo de la política |
| Cuadros | Todos los de `split: evaluacion`, incluidos los negativos |

**Emparejamiento**, por cuadro:

1. Las predicciones se ordenan de mayor a menor confianza.
2. Cada una toma la caja real libre de mayor IoU de su misma clase, si llega a 0.50.
3. Una caja real solo se usa una vez: una predicción duplicada es FP, y una caja real sin pareja es FN.
4. Una clase equivocada produce un FP y un FN.

**Fórmulas:** `precision = TP / (TP + FP)`, `recall = TP / (TP + FN)` y `F1 = 2TP / (2TP + FP + FN)`. Si un denominador es cero, el resultado es 0.

**Lo que no cuenta como FP:**
- Detecciones bajo el umbral. Se cuentan en `detecciones_bajo_umbral`.
- Detecciones de otras clases, como `refrigerator`. Se cuentan en `detecciones_de_otras_clases`.

**Cuadros con error:** siguen contando. Sin predicción, sus objetos anotados son FN, y quedan listados en `cuadros_con_error`. El comando termina con código 1, y la evidencia queda escrita.

## Uso

Desde Proyecto5, después de la preparación de A1-01_DETECTOR.md.

### PowerShell

```powershell
.venv\Scripts\python -m p5.metrics --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --output <carpeta-nueva>
```

### Linux

```bash
.venv/bin/python -m p5.metrics --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --output <carpeta-nueva>
```

## Recalcular desde los datos primarios

No necesita el detector ni los pesos: parte de las predicciones guardadas.

### PowerShell

```powershell
.venv\Scripts\python -m p5.metrics --dataset data/p5-eval-v1 --predictions <carpeta>\predicciones.jsonl --output <carpeta-nueva>
```

### Linux

```bash
.venv/bin/python -m p5.metrics --dataset data/p5-eval-v1 --predictions <carpeta>/predicciones.jsonl --output <carpeta-nueva>
```

## Archivos

| Archivo | Contenido |
|---|---|
| `predicciones.jsonl` | Dato primario: una línea por cuadro con todas las detecciones del detector, antes de aplicar el umbral |
| `resultados_por_cuadro.jsonl` | TP, FP y FN de cada cuadro, con las parejas, su IoU, y qué quedó sin pareja |
| `metricas.json` | Totales, resultados por clase, clases sin soporte y datos de la ejecución: commit, hashes y entorno |
| `metricas.csv` | La misma tabla de métricas, global y por clase |

## Verificación

Con `P5_DETECTOR_WEIGHTS` definida, las pruebas también corren el detector real.

### PowerShell

```powershell
$env:P5_DETECTOR_WEIGHTS = "models/yolox_tiny.onnx"
.venv\Scripts\python -m pytest tests\test_metrics.py
```

### Linux

```bash
export P5_DETECTOR_WEIGHTS=models/yolox_tiny.onnx
.venv/bin/python -m pytest tests/test_metrics.py
```
