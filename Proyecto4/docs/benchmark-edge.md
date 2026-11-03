# Benchmark de latencia en la Raspberry — VAL-05 (#17, criterios 3.1 y 3.2)

Medición de la latencia real de la variante optimizada **en la misma Raspberry Pi 4 de la demostración** y, en condiciones equivalentes, del modelo original. El script es [`edge/benchmark.py`](../edge/benchmark.py); la evidencia queda en `evidencias/VAL-05/`. p50/p95 y la comparación se calculan en VAL-06 (#18).

## Qué se mide

| | Detalle |
|---|---|
| Dispositivo | Raspberry Pi 4 Model B (EDGE-01): aarch64, Debian 13, Python 3.13 |
| Runtime | onnxruntime con `CPUExecutionProvider` y las opciones por defecto, igual que `edge/inferencia.py` |
| Variante optimizada | `model_int8.onnx`, `1.0.0-int8-e05.1`, SHA-256 `ba89ee43…2a12`. INT8: QDQ estático, pesos INT8 por canal, activaciones UINT8 |
| Original | `model_fp32.onnx`, SHA-256 `6b640343…06c1`: el `model.pt` 1.0.0 del P3 exportado a ONNX FP32, sin cuantizar. Mismos pesos que el original; VAL-01 verificó el linaje y la paridad con PyTorch (1.3e-5) |
| Entrada | float32 `[1, 3, 224, 224]`, NCHW, RGB normalizado |
| Imágenes | Los JPEG de la cámara de EDGE-03 (`cat`, `dog`, `person`; 1920 × 1080), recorridos en orden fijo |

**Qué cuenta cada repetición.** Se mide desde los bytes del JPEG ya leídos hasta la clase predicha: decodificar el JPEG, `modelo/preprocesar.py`, `sesion.run` y softmax. Es el mismo camino que la inferencia real. El CSV separa `ms_preprocesamiento` y `ms_inferencia`.

**Qué queda fuera.** La lectura del archivo, la captura HTTP de la cámara y la carga del modelo, que se registra aparte como `ms_carga`. Tampoco el envío a AWS: el benchmark no hace ninguna llamada de red y el envío se mide en EDGE-06.

**Condiciones equivalentes.** Los dos modelos usan el mismo runtime, el mismo preprocesamiento, las mismas imágenes en el mismo orden y el mismo número de repeticiones. Cada modelo corre **en su propio proceso**, así la memoria pico es la de ese modelo. Además, si el FP32 no cargara (por ejemplo, por falta de memoria), su error queda registrado como evidencia de incompatibilidad, como pide la rúbrica.

**Protocolo por modelo:**
1. Verificar el SHA-256 del archivo.
2. Cargar la sesión.
3. **10 calentamientos**, marcados `calentamiento` y excluidos.
4. **200 mediciones**, marcadas `medicion` (el mínimo es 100).

Entre los dos modelos hay una pausa de 60 s. En cada repetición se registra la temperatura del SoC.

**Condiciones del dispositivo**, guardadas en `benchmark.json`:
- modelo de la Raspberry, CPU, núcleos y RAM;
- sistema operativo y kernel;
- versiones de Python, onnxruntime, numpy y Pillow;
- gobernador y frecuencias del CPU;
- `vcgencmd` (temperatura, reloj y *throttling*) y la carga del sistema, al inicio y al final;
- el SHA-256 de los modelos, de las imágenes, de `benchmark.py` y de `preprocesar.py`.

## Pasos

### 1. Josué: hacer llegar `model_fp32.onnx` a la Raspberry

El archivo está en `s3://p4-capturas-474665692638/modelos/clasificador-edge/1.0.0-int8-e05.1/model_fp32.onnx` (44 702 717 bytes). Josué genera un enlace temporal de solo lectura, válido 2 horas, y se lo pasa a Omar por un canal privado. El enlace da acceso al archivo mientras está vigente, así que no se publica:

```bash
aws s3 presign s3://p4-capturas-474665692638/modelos/clasificador-edge/1.0.0-int8-e05.1/model_fp32.onnx --expires-in 7200 --profile default
```

Otra opción es copiar el archivo desde una laptop que lo tenga, con USB o `rsync`. La procedencia no importa: el benchmark exige el SHA-256 antes de cargarlo.

### 2. Omar: copiar el código a la Raspberry

Desde la laptop con el repositorio actualizado, igual que en EDGE-03:

```bash
rsync -av Proyecto4/edge/benchmark.py pi@<ip-de-la-raspberry>:/home/pi/edge01/app/benchmark.py
rsync -av Proyecto4/modelo/preprocesar.py pi@<ip-de-la-raspberry>:/home/pi/edge01/modelo/preprocesar.py
```

Se copia también `preprocesar.py` para asegurar que el dispositivo use el mismo que validó VAL. El verificador comprueba su SHA-256.

### 3. Omar: preparar en la Raspberry

En la Terminal de la Raspberry:

```bash
cd "$HOME/edge01"
source .venv/bin/activate
curl -fSL "<enlace-que-te-paso-Josue>" -o modelo/model_fp32.onnx
sha256sum modelo/model_int8.onnx modelo/model_fp32.onnx
ls evidencias/EDGE-03/cat evidencias/EDGE-03/dog evidencias/EDGE-03/person
```

Los hashes deben ser exactamente estos:

```
ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12  modelo/model_int8.onnx
6b640343a5862ad546d074e0b2a7701d5da61d65552f18555d1b4dccf30506c1  modelo/model_fp32.onnx
```

Cada carpeta de EDGE-03 debe tener su JPEG.

**Condiciones de la prueba:**
- La Raspberry con su fuente y su gabinete de siempre, los mismos de la demostración.
- Navegador y cualquier otro programa cerrados. La cámara no hace falta: el benchmark usa las fotos guardadas.
- La red puede quedarse como en la demostración, porque el benchmark no la usa.
- Dejarla en reposo unos 2 minutos antes de empezar y no usarla mientras corre.

### 4. Omar: correr el benchmark

```bash
python app/benchmark.py
```

Tarda unos minutos (estimado: menos de 5; incluye la pausa de 60 s). Al final debe decir, para cada modelo, `ok, 10 calentamientos, 200/200 mediciones validas`, y escribir `evidencias/VAL-05/tiempos.csv` y `evidencias/VAL-05/benchmark.json`. Toma una captura de la Terminal.

Si el FP32 falla (memoria, error del runtime), **no lo corrijas ni repitas con otros parámetros**: el error queda en `benchmark.json` y es la evidencia que pide la rúbrica. El INT8 se mide igual.

### 5. Omar: devolver la evidencia

Copia `evidencias/VAL-05/tiempos.csv`, `evidencias/VAL-05/benchmark.json` y la captura de la Terminal a la laptop:

```bash
rsync -av pi@<ip-de-la-raspberry>:/home/pi/edge01/evidencias/VAL-05/ Proyecto4/evidencias/VAL-05/
```

Envíaselos a Josué. No se editan.

### 6. Josué: verificar

Con los archivos en `Proyecto4/evidencias/VAL-05/`:

```bash
python validacion/verificar_benchmark.py
```

[`verificar_benchmark.py`](../validacion/verificar_benchmark.py) solo usa la biblioteca estándar. Comprueba:
- que el CSV sea el que registra el JSON;
- que cada modelo medido tenga al menos 10 calentamientos marcados y al menos 100 mediciones válidas, con los calentamientos antes de las mediciones;
- milisegundos por repetición;
- la identidad de los modelos contra la conversión verificada en VAL-01;
- que el dispositivo sea aarch64 y esté documentado;
- que `preprocesar.py` sea el del repositorio.

Un modelo que no cargó pasa la verificación solo si su error quedó registrado.

## Corrida en la Raspberry (16 oct de 2026)

Omar la ejecutó con `python -u app/benchmark.py`, a las 01:05–01:07 (UTC−06:00). El JSON registra el comando sin `-u`, porque `sys.argv` no guarda las opciones del intérprete; `-u` solo quita el búfer de la salida. La evidencia está en [`evidencias/VAL-05/`](../evidencias/VAL-05/):
- [`tiempos.csv`](../evidencias/VAL-05/tiempos.csv): 420 filas en milisegundos;
- [`benchmark.json`](../evidencias/VAL-05/benchmark.json);
- [la captura de la Terminal](../evidencias/VAL-05/Captura%20de%20pantalla%202026-10-16%20010957.png).

Llegó en `VAL-05.zip` (SHA-256 `d5c582ea…943a`) y se copió sin editar. `python validacion/verificar_benchmark.py` → **VERIFICADO**. El CI vuelve a verificarla en `tests/test_benchmark.py`.

| | Registrado |
|---|---|
| Dispositivo | Raspberry Pi 4 Model B Rev 1.5 (revisión `a03115`, 1 GB): 4 núcleos Cortex-A72 (`CPU part 0xd08`), 927 380 kB de RAM visibles |
| Sistema | Debian GNU/Linux 13 (trixie), kernel `6.18.50+rpt-rpi-v8`, aarch64 |
| Runtime | Python 3.13.5, onnxruntime 1.31.0 (`CPUExecutionProvider`, hilos automáticos), numpy 2.5.4, Pillow 12.3.0 |
| Código | `benchmark.py` `ed31ef43…` y `preprocesar.py` `8fa139aa…`, los dos idénticos a los del repositorio |
| Modelos | INT8 `ba89ee43…` (11 295 280 bytes) y FP32 `6b640343…` (44 702 717 bytes), los de la conversión verificada en VAL-01 |
| Imágenes | Las 3 de EDGE-03 (`cat`, `dog`, `person`), JPEG de 1920 × 1080 |
| CPU | Gobernador `ondemand`, 1.8 GHz (máximo) en los 4 núcleos al inicio y al final |
| Temperatura | 49.2 °C al inicio y 75.0 °C al final; máximo de 78.4 °C en una repetición del FP32 |
| *Throttling* | `vcgencmd get_throttled` = `0x0` al inicio y al final: sin limitación de frecuencia ni de voltaje |
| Carga del sistema | `loadavg` de 0.13 antes de empezar: dispositivo en reposo |

| Modelo | Calentamientos | Mediciones válidas | Carga de la sesión | Memoria pico del proceso | Clase por imagen |
|---|---:|---:|---:|---:|---|
| INT8 | 10 | 200 / 200 | 152.0 ms | 114.4 MB | cat → cat, dog → dog, person → person |
| FP32 | 10 | 200 / 200 | 311.6 ms | 184.2 MB | cat → cat, dog → dog, person → person |

El original (FP32) **sí corre** en este dispositivo y se midió en las mismas condiciones, así que no hubo ninguna incompatibilidad que documentar.

**Estabilidad y efecto térmico.** El FP32 corrió segundo y con el dispositivo más caliente. Aun así, la mediana del tiempo total es la misma en la primera y en la segunda mitad de cada modelo: 113.4 contra 113.6 ms en el INT8, y 190.1 contra 190.1 ms en el FP32. Las 200 mediciones de cada modelo caben en un rango de unos 6 ms y no hubo *throttling*. El calor no sesgó la comparación. Solo los primeros calentamientos son más lentos: 129 ms en el INT8, y 210 y 281 ms en el FP32. Por eso se excluyen.

**Vista rápida** (medianas, ms; los p50 y p95 formales, recalculables, son de VAL-06):

| Modelo | Total | Preprocesamiento | Inferencia |
|---|---:|---:|---:|
| INT8 | 113.5 | 42.3 | 71.0 |
| FP32 | 190.1 | 42.6 | 147.3 |

El preprocesamiento es el mismo código y cuesta lo mismo en los dos. La diferencia está en la inferencia.

## Probado antes de llevarlo al dispositivo

- `tests/test_benchmark.py` (CI): calentamientos marcados antes de las mediciones; recorrido fijo de imágenes; repetición fallida registrada como inválida; mínimos de 10 y 100; identidad de los modelos igual al registro de conversión; verificación de conteos, identidad, CSV, dispositivo y preprocesamiento; original incompatible con su error registrado.
- Una corrida completa en la laptop de VAL, con los modelos reales, terminó con 10 + 100 repeticiones por modelo y las tres clases correctas. El verificador la **rechaza** por no ser el dispositivo (`AMD64`). Esos tiempos no son evidencia y no se versionan: la rúbrica no permite comparar con la laptop.
