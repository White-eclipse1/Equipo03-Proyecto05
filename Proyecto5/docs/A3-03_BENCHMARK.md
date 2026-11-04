# A3-03 — Benchmark del recorrido en CPU

Ticket: #18. Entregable: E7.

## Objetivo

Medir de forma reproducible cuánto tarda el sistema en convertir una imagen en un comando, y cuánto aporta cada etapa.

## Componentes

- src/p5/benchmark/timing.py: cronómetros por etapa, corridas y resumen.
- src/p5/benchmark/\_\_main\_\_.py: comando de línea, condiciones de la medición y exportación.
- tests/test_benchmark.py: comportamiento y errores, con una sesión simulada.
- tests/test_benchmark_real_weights.py: pesos e imágenes reales.

## Qué se mide

Cada corrida es una llamada a `Pipeline.process`, el mismo recorrido de B3-01. Los cronómetros envuelven los mismos objetos que usa la aplicación, así que no hay un camino aparte para medir.

| Columna | Etapa |
|---|---|
| `ms_total` | Toda la llamada a `Pipeline.process` |
| `ms_lectura` | Leer el archivo y decodificar el JPEG |
| `ms_preprocesamiento` | Redimensionar, rellenar y crear el tensor |
| `ms_inferencia` | Ejecutar el modelo en ONNX Runtime |
| `ms_posprocesamiento` | Decodificar la salida del modelo, aplicar el umbral y NMS |
| `ms_politica` | Validar el contrato y decidir |
| `ms_control` | Generar el comando en el adaptador virtual |

`ms_total` es algo mayor que la suma de las etapas, porque también incluye el código que las une.

**Qué queda fuera:** la carga del modelo, que se guarda aparte como `ms_carga`; la captura de la cámara; la escritura de resultados; y los motores. El benchmark no hace llamadas de red.

## Protocolo

1. Comprueba que la carpeta de salida no exista, y el SHA-256 de los pesos y de cada imagen del manifiesto.
2. Carga la sesión con las opciones por defecto de ONNX Runtime, igual que la aplicación.
3. Ejecuta los calentamientos: al menos 10, marcados `calentamiento` y excluidos de las cifras.
4. Ejecuta las mediciones: al menos 100, marcadas `medicion`. Por defecto son 200.

Las imágenes se recorren en el orden del manifiesto. Con 210 corridas y 128 cuadros, todos los cuadros entran en la medición. Al dar otra vuelta, los tiempos de captura se desplazan para que la política los siga aceptando.

## Preparación

La de [A1-01_DETECTOR.md](A1-01_DETECTOR.md). Para una medición oficial, conecta el equipo a la corriente, cierra los demás programas y corre desde un commit sin cambios.

## Uso

Desde Proyecto5. Usa una carpeta nueva en cada corrida.

### PowerShell

```powershell
.venv\Scripts\python -m p5.benchmark --manifest data\p5-eval-v1\manifiesto.jsonl --output resultados\benchmark
```

### Linux

```bash
.venv/bin/python -m p5.benchmark --manifest data/p5-eval-v1/manifiesto.jsonl --output resultados/benchmark
```

Opciones:

- `--calentamientos`: 10 por defecto. Menos de 10 se rechaza.
- `--repeticiones`: 200 por defecto. Menos de 100 se rechaza.
- `--weights`: models/yolox_tiny.onnx por defecto.
- `--policy-config`: ../Proyecto3/config/politica.yaml por defecto.

Al terminar imprime p50, p95 y máximo por etapa.

## Resultados que escribe

### tiempos.csv

Una fila por corrida, incluidos calentamientos y fallos, con los milisegundos de cada columna anterior y estos campos:

- `fase`: `calentamiento` o `medicion`.
- `indice`: posición en toda la corrida. `repeticion`: posición dentro de su fase.
- `sequence_id` y `frame_id`: el cuadro medido.
- `valido`, `accion` y `error`.

Una etapa que no llegó a ejecutarse queda vacía, no en cero.

### benchmark.json

- **Condiciones:** `hardware`, `runtime`, `detector`, `dataset`, `politica`, `codigo` y `medicion`.
- **`codigo.cambios_sin_commit`:** debe ser `false` en una medición oficial.
- **`salida_fisica`:** `false`, porque el adaptador es virtual.
- **`resumen`:** conteos, y `p50`, `p95`, `maximo`, `minimo` y `media` por etapa.
- **`tiempos`:** nombre, SHA-256 y número de filas de tiempos.csv.

Las cifras solo usan mediciones válidas, y se pueden recalcular desde tiempos.csv. El percentil usa interpolación lineal, la opción por defecto de `numpy.percentile`, igual que las métricas del Proyecto 4.

Ninguno de los dos archivos incluye el nombre del equipo, el usuario ni rutas locales.

## Errores

Una corrida con un error del recorrido, o con una excepción inesperada, queda con `valido: False` y su mensaje en `error`. No entra en las cifras, y la medición continúa.

Códigos de salida:

- **0:** se cumplen los mínimos de calentamientos y de mediciones válidas.
- **1 con resultados:** no hubo suficientes mediciones válidas. Los archivos se conservan como evidencia.
- **1 sin resultados:** falló el arranque (`benchmark_error stage=startup`), por ejemplo porque la carpeta ya existe o un SHA-256 no coincide.

## Verificación

Desde Proyecto5.

### PowerShell

```powershell
$env:P5_DETECTOR_WEIGHTS = "models/yolox_tiny.onnx"
.venv\Scripts\python -m pytest tests\test_benchmark.py tests\test_benchmark_real_weights.py
```

### Linux

```bash
export P5_DETECTOR_WEIGHTS=models/yolox_tiny.onnx
.venv/bin/python -m pytest tests/test_benchmark.py tests/test_benchmark_real_weights.py
```

## Límites conocidos

- **Condiciones del equipo:** no registra la carga del sistema, la temperatura ni si el equipo está conectado a la corriente.
- **Tiempo del sistema completo:** no incluye la captura de la cámara ni el envío al carro. `ms_total` es el tiempo local.
- **Regla de vigencia:** el adaptador todavía no aplica `valido_hasta_ms` (#5). Si #5 o #6 cambian el adaptador, `ms_control` puede cambiar.
- **Política:** las decisiones no se evalúan aquí; eso es de B3-02 (#8).
