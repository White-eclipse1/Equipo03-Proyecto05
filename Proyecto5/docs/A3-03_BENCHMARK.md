# A3-03 — Benchmark del recorrido en CPU

Ticket: #18. Entregable: E7.

## Objetivo

Medir de forma reproducible cuánto tarda el sistema en convertir una imagen en un comando, y cuánto aporta cada etapa.

## Componentes

- src/p5/benchmark/timing.py: cronómetros por etapa, corridas y resumen.
- src/p5/benchmark/\_\_main\_\_.py: comando de línea, condiciones de la medición y exportación.
- tests/test_benchmark.py: comportamiento y errores, con una sesión simulada.
- tests/test_benchmark_real_weights.py: pesos e imágenes reales.
- tests/test_benchmark_evidence.py: coherencia de la evidencia versionada.
- evidencias/A3-03-mediana3/: medición oficial, con el filtro de mediana y los tiempos crudos.
- evidencias/A3-03/ y evidencias/A3-03-programas-abiertos/: mediciones anteriores, sin filtro y en otro equipo.

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

1. Comprueba que la carpeta de salida no exista, el SHA-256 de los pesos y el paquete completo con `validate_package`, incluidas sus imágenes.
2. Carga la sesión con las opciones por defecto de ONNX Runtime, igual que la aplicación.
3. Ejecuta los calentamientos: al menos 10 válidos, marcados `calentamiento` y excluidos de las cifras.
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
- `--policy-config`: config/politica.yaml por defecto.

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
- **`codigo.cambios_sin_commit`:** debe ser `false` en una medición oficial. Considera los archivos versionados y el código nuevo de src/.
- **`salida_fisica`:** `false`, porque el adaptador es virtual.
- **`resumen`:** conteos, y `p50`, `p95`, `maximo`, `minimo` y `media` por etapa.
- **`tiempos`:** nombre, SHA-256 y número de filas de tiempos.csv.

Las cifras solo usan mediciones válidas, y se pueden recalcular desde tiempos.csv. El percentil usa interpolación lineal, la opción por defecto de `numpy.percentile`, igual que las métricas del Proyecto 4.

Ninguno de los dos archivos incluye el nombre del equipo, el usuario ni rutas locales.

## Errores

Una corrida con un error del recorrido, o con una excepción inesperada, queda con `valido: False` y su mensaje en `error`. No entra en las cifras, y la medición continúa.

Códigos de salida:

- **0:** hay al menos 10 calentamientos y 100 mediciones válidos, con datos en todas las etapas.
- **1 con resultados:** no se cumplen esos mínimos. Los archivos se conservan como evidencia.
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

## Resultados

Medición oficial en [evidencias/A3-03-mediana3/](../evidencias/A3-03-mediana3/), desde el commit `39e72ad` sin cambios, con el filtro de mediana 3×3 de [B1-03_DETECTOR.md](B1-03_DETECTOR.md): 10 calentamientos y 200 de 200 mediciones válidas.

**No se compara con la medición anterior para medir el efecto del filtro:** se hizo en otro equipo. El filtro corre dentro de `ms_preprocesamiento`.

| Condición | Valor |
|---|---|
| CPU | Intel Core i9-12900H, 20 núcleos lógicos, 16 GB de RAM |
| Sistema | Windows 11, x86-64. No se registró el estado de energía ni qué otros programas seguían abiertos |
| Runtime | Python 3.12.16, onnxruntime 1.31.1 con solo CPUExecutionProvider, opciones por defecto |
| Detector | YOLOX-Tiny, 20 219 662 bytes, SHA-256 `427cc366…b0f7`, filtro de mediana 3×3 |
| Imágenes | p5-eval-v1, 400x296 |
| Carga del modelo | 86 ms, fuera de las cifras |

| Columna | p50 (ms) | p95 (ms) | Máximo (ms) |
|---|---:|---:|---:|
| `ms_total` | 27.22 | 30.37 | 33.69 |
| `ms_lectura` | 1.22 | 1.79 | 2.19 |
| `ms_preprocesamiento` | 1.38 | 1.85 | 2.42 |
| `ms_inferencia` | 19.99 | 21.96 | 25.47 |
| `ms_posprocesamiento` | 3.83 | 5.30 | 5.86 |
| `ms_politica` | 0.14 | 0.19 | 0.27 |
| `ms_control` | 0.02 | 0.02 | 0.05 |

### Contraste con los plazos

| Plazo | Valor | Comparación | Resultado |
|---|---:|---|---|
| Vigencia del comando (`vigencia_comando_ms`) | 500 ms | p95 total 30.37 ms y máximo total 33.69 ms | El cómputo cabe |
| Periodo declarado en la política, a 10 FPS | 100 ms | p95 de inferencia 21.96 ms; p95 total 30.37 ms y máximo total 33.69 ms | El cómputo cabe en este equipo |
| Ritmo de captura de p5-eval-v1 | 122 huecos, de 500 a 2843 ms, mediana 525 ms | Vigencia de 500 ms: la superan 120 de 122 huecos, y los otros 2 miden justo 500 ms | A este ritmo de captura, el comando vence antes del siguiente cuadro |

La regla de [politica.md](../../Proyecto3/docs/politica.md) pide subir `vigencia_comando_ms` o bajar los FPS si el p95 de inferencia supera el periodo de entrada. Al ritmo de captura de p5-eval-v1 eso no ocurre: 21.96 ms contra al menos 500 ms. En el laptop de la medición anterior, sin filtro, el p95 de inferencia fue de 95.40 ms: el margen depende del equipo.

**La última fila describe cómo se capturó el dataset, no lo que entrega la cámara.** El mínimo de 500 ms lo impuso `--interval-ms` al grabar, y el ritmo real de `/stream` todavía no se ha medido. Solo dice qué pasaría a ese ritmo: cuando #5 aplique la vigencia, cada comando de movimiento vencería antes del siguiente cuadro, y el carro se detendría entre cuadros.

Lo que sí sale de esta medición es que, a ese ritmo, el cómputo no es lo que limita: en este equipo, el p95 total permite unos 32 cuadros por segundo, y el peor total observado, unos 29. **Hay que medir el ritmo real de `/stream` antes de decidir si cambia la vigencia.**

### Medición anterior, sin filtro

El p50 por cada 50 mediciones de la oficial fue de 27.0, 27.2, 27.0 y 28.4 ms. Las corridas anteriores son de otro laptop, sin filtro, y se conservan porque ahí el tiempo cambió bastante, con el mismo código y las mismas imágenes.

| Corrida | Condiciones | p50 total (ms) | p95 total (ms) | Máximo (ms) |
|---|---|---:|---:|---:|
| A3-03-programas-abiertos | Otros programas abiertos, justo después de instalar el paquete | 51.20 | 92.02 | 173.26 |
| A3-03, oficial hasta el filtro | Binding of Isaac, Steam, Epic Games Launcher y ProtonVPN cerrados | 62.86 | 107.88 | 139.22 |

Esa corrida se eligió antes de conocer su resultado, para no quedarse con la cifra más favorable. Cerrar esos programas no mejoró los tiempos, así que no explican la variación. Docker Desktop y el navegador seguían abiertos en la oficial.

Hubo dos corridas más sin registros versionados, así que no se usan como evidencia.

### Variación dentro de cada corrida

Las corridas también cambian mientras miden, y el p50 global mezcla esos momentos. p50 total, en milisegundos, por cada 50 mediciones:

| Corrida | 1.ª | 2.ª | 3.ª | 4.ª |
|---|---:|---:|---:|---:|
| A3-03 | 54.4 | 54.8 | 67.2 | 75.6 |
| A3-03-programas-abiertos | 58.8 | 61.8 | 46.8 | 46.4 |

La causa no quedó demostrada. Un límite de temperatura o potencia del laptop es una explicación posible, pero benchmark.json no registra esos datos. En la revisión del PR se reportó una corrida en otra PC con p50 18.66 ms, p95 20.59 ms y máximo 21.61 ms, sin esta dispersión. Eso apunta al equipo, aunque no lo demuestra, y esa corrida no está en el repositorio.

Estas cifras describen esos equipos en esas corridas: no son un valor estable del sistema.

## Límites conocidos

- **Condiciones del equipo:** benchmark.json no registra la carga del sistema, la temperatura, la frecuencia ni si el equipo está conectado a la corriente.
- **Hardware:** se midió en un laptop. Si la demostración corre en otro equipo, como la Raspberry del Proyecto 4, hay que repetir ahí la medición.
- **Tiempo del sistema completo:** no incluye la captura de la cámara ni el envío al carro. `ms_total` es el tiempo local.
- **Código medido:** la medición oficial ya incluye #5 y #6. Si cambian el recorrido o el adaptador, hay que repetirla.
- **Cambios en la política:** si `politica.yaml` cambia, la medición oficial queda con un `config_sha256` anterior y conviene repetirla. Si cambia `vigencia_comando_ms`, una prueba falla hasta actualizar este documento.
- **Commit de la evidencia:** la medición oficial cita `39e72ad`, así que su PR debe fusionarse con merge commit. Las mediciones anteriores citan `dacaa56`; en esos archivos no existen `calentamientos_validos` ni `filtro_mediana`.
- **Política:** las decisiones no se evalúan aquí; eso es de B3-02 (#8).
