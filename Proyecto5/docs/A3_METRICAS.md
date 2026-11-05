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

## Resultado vigente, con el filtro de mediana

Evidencia en [evidencias/a3-metricas-mediana3/](../evidencias/a3-metricas-mediana3/), medida una vez con el commit `39e72ad`, Python 3.12.16 y dependencias fijadas. El detector aplica el filtro de mediana 3×3 de [B1-03_DETECTOR.md](B1-03_DETECTOR.md). Son los mismos modelo, umbrales, datos y reglas.

| Cuadros | TP | FP | FN | Precision | Recall | F1 micro |
|---:|---:|---:|---:|---:|---:|---:|
| 128 | 83 | 1 | 8 | 0.9881 | 0.9121 | **0.9486** |

| Secuencia | Objetos | TP | FP | FN | Recall |
|---|---:|---:|---:|---:|---:|
| seq01 | 0 | 0 | 0 | 0 | Sin objetos |
| seq02 | 15 | 15 | 0 | 0 | 1.000 |
| seq03 | 12 | 12 | 0 | 0 | 1.000 |
| seq04 | 12 | 10 | 0 | 2 | 0.833 |
| seq05 | 30 | 29 | 0 | 1 | 0.967 |
| seq06 | 22 | 17 | 1 | 5 | 0.773 |

**Lo que muestra:** con el filtro, el detector pierde a menos personas: de 27 pasa a 8. Bajo los mismos criterios, `floor(12 × 0.9486) / 2` da 5.5 en el criterio 1.4.

**Comprobado:** un recálculo con un script aparte, que no importa `p5.metrics`, da los mismos TP, FP y FN por cuadro, por clase y en total. Ese script no está en el repositorio.

**Límites de esta cifra:**
- **Se miró la evaluación:** el filtro se eligió con `p5-ajuste-v1`, pero antes se revisaron los puntajes de `seq05` y `seq06` para diagnosticar la pérdida, y el conjunto ya se había visto al colocar a las personas.
- **Más detecciones de otras clases:** pasan de 85 a 95, sobre todo `skateboard`. No cuentan en esta métrica.
- **El `truck` falso de `seq06-0025`:** con 0.44 queda bajo el umbral de 0.50, así que no es un FP aquí, pero la política lo trata como detección débil y reduce la velocidad.
- **El par de `seq06-0028`:** su caja sigue justo por debajo de IoU 0.50, y es la observación abierta en #41.

## Resultado anterior, sin filtro

Se conserva sin cambios. Evidencia en `evidencias/a3-metricas-v1/`. Se midió con el commit `0cf6dd9`, que ya fijaba el umbral, y no se repitió con otro.

| Cuadros | TP | FP | FN | Precision | Recall | F1 micro |
|---:|---:|---:|---:|---:|---:|---:|
| 128 | 64 | 2 | 27 | 0.9697 | 0.7033 | **0.8153** |

Todo el soporte es de `person`, con 91 objetos, así que su fila coincide con la global. Las otras 7 clases no tienen soporte y dan 0 por regla: no son una medida del detector. Son 76 cuadros con objetos y 52 negativos, sin errores.

| Secuencia | Objetos | TP | FP | FN | Recall |
|---|---:|---:|---:|---:|---:|
| seq01 | 0 | 0 | 0 | 0 | Sin objetos |
| seq02 | 15 | 14 | 0 | 1 | 0.933 |
| seq03 | 12 | 8 | 1 | 4 | 0.667 |
| seq04 | 12 | 11 | 0 | 1 | 0.917 |
| seq05 | 30 | 20 | 0 | 10 | 0.667 |
| seq06 | 22 | 11 | 1 | 11 | 0.500 |

**Lo que muestra:** cuando el detector marca a una persona con 0.50 o más casi siempre acierta, pero pierde casi 3 de cada 10. El riesgo principal es no ver a alguien, no frenar de más.

Fuera del conteo quedaron 80 detecciones de las clases evaluadas bajo el umbral y 85 de otras clases, como `tv` (43) y `backpack` (14).

**Comprobado:**
- Un recálculo con un script aparte, que no importa `p5.metrics`, da los mismos TP, FP y FN.
- Recalcular con `--predictions` da archivos idénticos.
- Dos corridas del detector dan predicciones idénticas, byte a byte, en esta PC.

### Límites de esta medición

- **Elección del umbral:** 0.50 se tomó de la política antes de calcular este F1. Pero antes de congelar el dataset ya se habían visto detecciones de estas secuencias, y se usaron para decidir dónde colocar a las personas. Por eso **estas métricas no representan cualquier escena**. Ver "Tomas repetidas" en A2_DATASET.md.
- **Una sola clase real:** no mide `car`, `dog` ni las demás.
- **Muestra pequeña y correlacionada:** son 91 objetos en cuadros consecutivos, no 91 escenas independientes.
- **Etiquetas de una sola persona:** la [auditoría independiente de #29](A3-04_AUDITORIA.md) revisó visualmente 38 cuadros y reprodujo las cifras publicadas. Conserva observaciones de seguimiento y no certifica todos los bordes de las cajas; cajas ajustadas de otra forma podrían cambiar algunos pares cerca de IoU 0.50.
- **Entorno histórico:** medido en Windows con Python 3.13. La repetición con Python 3.12.16 y todas las dependencias fijadas reproduce exactamente las predicciones y métricas; ver [cierre F01](../evidencias/a3-metricas-python312/README.md). Esto no garantiza igualdad en cualquier plataforma.

### Repetición en el entorno soportado — A3-04-F01 (#40)

Seguimiento de [#29](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/29),
relacionado con #16 y #17. El 4 de noviembre de 2026 se ejecutó nuevamente el
evaluador existente con inferencia real en Python 3.12.16, ONNX Runtime 1.31.1,
NumPy 2.5.4 y OpenCV headless 5.0.0.93, verificando todas las versiones del lock.

La [nueva evidencia](../evidencias/a3-metricas-python312/README.md) conserva el
manifiesto, modelo y umbrales publicados. Resultados: 64 TP, 2 FP, 27 FN,
precision 0.9696969697, recall 0.7032967033 y F1 0.8152866242, sin errores.
Predicciones, resultados por cuadro y CSV son idénticos byte a byte a v1.
En `metricas.json` solo cambia el bloque de metadatos `ejecucion`.
La evidencia histórica permanece intacta y un recálculo independiente de los
128 cuadros no encuentra diferencias. No se calibró con evaluación.

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
