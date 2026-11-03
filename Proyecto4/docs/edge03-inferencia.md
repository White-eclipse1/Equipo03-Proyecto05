# EDGE-03 — Inferencia ONNX INT8 en Raspberry

La variante utilizada es `1.0.0-int8-e05.1`, SHA-256
`ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12`.
El nombre `1.0.0-int8.1` del texto original del ticket corresponde a la variante
anterior; no se intercambian sus hashes ni se renombra el binario.

## Implementación

[`edge/inferencia.py`](../edge/inferencia.py) verifica el SHA-256 antes de crear
una sesión ONNX Runtime con `CPUExecutionProvider`. La sesión recibe los mismos
bytes verificados. Valida entrada float32 `[1,3,224,224]` y salida `[1,3]`.

Lee los JPEG nuevos y JSON producidos por la aplicación de EDGE-02 en una carpeta
por clase esperada. Comprueba capture_id, hash de la foto y fecha con zona antes
de inferir. No modifica el registro de captura original ni utiliza el portal o AWS.
El programa de inferencia no realiza llamadas de red. La cámara de EDGE-02 usa
únicamente el enlace HTTP local para adquirir las imágenes.

El log JSONL conserva identidad del modelo, runtime, provider, formas de entrada,
orden de clases, capture_id, clase esperada y predicha, confianza, logits y las
tres probabilidades. La clase esperada es una anotación del operador y no afecta
la predicción. `matches_expected: false` se conserva como resultado real.

Estos registros locales no son el JSON de la parte multipart `evento` del receptor.
Según `docs/contrato-capturas.md`, el evento de envío contiene exclusivamente
`schema_version`, `capture_id`, `captured_at`, `predicted_class`, `confidence`,
`device_id`, `model_version`, `model_sha256`, `image_sha256`, `image_ref` y,
opcionalmente, `region`. No se envían `estado`, dimensiones, tamaño, logits,
probabilidades completas, tiempos ni etiquetas esperadas. La construcción y
persistencia del evento se entregan en EDGE-05 y el envío en EDGE-06; los registros
de captura e inferencia se conservan como evidencias locales.

## Correspondencia de preprocesamiento con P3

| Etapa | P3: `src/p3/data/transforms.py` | Variante edge: `modelo/preprocesar.py` |
|---|---|---|
| Entrada | Imagen RGB del pipeline de datos | Conversión explícita a RGB con Pillow |
| Tamaño | `Resize((224,224), antialias=True)` | Resize a cuadrado 224 × 224, Pillow bilineal |
| Escala | Conversión a float32 con `scale=True` | Array float32 dividido entre 255 |
| Media | 0.485, 0.456, 0.406 | Misma media por canal |
| Desviación | 0.229, 0.224, 0.225 | Misma desviación por canal |
| Orden | CHW; lote en inferencia | NCHW, lote 1 |
| Clases | cat, dog, person | cat, dog, person |

Se reutiliza el preprocesador entregado para la variante del equipo. El contraste
de código confirma la misma política de transformación. No constituye una prueba
de igualdad numérica bit a bit entre torchvision y Pillow en imágenes no uniformes.
Las pruebas locales verifican RGB, escala, normalización, dtype, forma y softmax.

## Instalación y distribución

Dependencias, dentro del entorno virtual:

```bash
python -m pip install -r edge/requirements-inferencia.txt
```

En la Raspberry sin Git, distribuir estos archivos mediante rsync:

- `edge/inferencia.py` → `/home/pi/edge01/app/inferencia.py`.
- `modelo/preprocesar.py` → `/home/pi/edge01/modelo/preprocesar.py`.
- `edge/requirements-inferencia.txt` → `/home/pi/edge01/app/requirements-inferencia.txt`.

Conservar `/home/pi/edge01/app/camara.py` de EDGE-02 y el modelo local ya verificado
en `/home/pi/edge01/modelo/model_int8.onnx`.

## Verificación física por clase

En la Terminal local de la Raspberry:

```bash
cd "$HOME/edge01"
source .venv/bin/activate
mkdir -p evidencias/EDGE-03
```

Definir `CAMERA_URL` con la dirección HTTP local de IP Webcam terminada en
`/shot.jpg`. Para cada clase, presentar una entrada conocida, encuadrada y con
buena iluminación. Capturar una imagen nueva usando EDGE-02:

```bash
python app/camara.py --url "$CAMERA_URL" --cantidad 1 --salida evidencias/EDGE-03/cat
python app/inferencia.py --modelo modelo/model_int8.onnx --carpeta evidencias/EDGE-03/cat --esperada cat --log evidencias/EDGE-03/inferencia.jsonl
```

Repetir ambos comandos con `dog` y después con `person`, cambiando la escena,
la carpeta y `--esperada`. La inferencia procesa todos los JPEG de cada carpeta.
Si se repite una prueba, el log agrega nuevas filas sin borrar las anteriores.

Comprobar en los logs:

- `estado: modelo_cargado`, versión/hash correctos y CPUExecutionProvider.
- Entrada `[1,3,224,224]`, float32; logits y probabilidades finitas.
- Clase y confianza reales por captura; contraste con la clase conocida.
- Predicciones que reaccionan a entradas diferentes. Variación de los logits
  sin cambio de clase ganadora no basta para afirmar que se verificaron las tres clases.

No editar resultados para hacerlos coincidir con las clases esperadas. Si todas
las entradas reciben la misma clase, revisar las imágenes, el encuadre y el
preprocesamiento con el responsable del modelo antes de cerrar el ticket.

Guardar JPEG, JSON de captura, `inferencia.jsonl`, versión de dependencias y
capturas de Terminal. Las imágenes originales permiten reproducir la inferencia.
Los archivos originales deben acompañar los resultados de la ejecución física
descritos a continuación.

## Resultados físicos reportados

La salida de Terminal compartida por Omar registra tres ejecuciones en Raspberry
el 16 de octubre de 2026, con ONNX Runtime 1.31.0 y CPUExecutionProvider. En las
tres se cargó la variante y hash indicados en esta ficha, con entrada float32
`[1,3,224,224]` y salida de tres logits:

| Clase esperada | capture_id | Predicción | Confianza | Preprocesamiento + inferencia |
|---|---|---|---|---|
| cat | edge01-9495b250a4e44d8d8e7aafed2ef76fbd | cat | 0.9999456405639648 | 208.70 ms |
| dog | edge01-e3bbf60be9974bf7a2f6eae6d9b55ff0 | dog | 0.9948855042457581 | 160.79 ms |
| person | edge01-9ca0684f7544466d864c8b253fb9e2b7 | person | 0.9977529644966125 | 162.17 ms |

Las capturas tienen fecha con zona UTC−06:00, hashes distintos y predicciones
ganadoras distintas. Los logits y las tres probabilidades aparecen en el log.
Estos tiempos individuales excluyen captura HTTP y carga inicial del modelo;
no constituyen un benchmark estadístico.

Los archivos originales están en
[`evidencias/EDGE-03/`](../evidencias/EDGE-03/): carpetas `cat`, `dog` y `person`
con JPEG y registros de captura, [log de inferencia](../evidencias/EDGE-03/inferencia.jsonl),
[dependencias](../evidencias/EDGE-03/dependencias.txt) y
[capturas de Terminal](../evidencias/EDGE-03/capturas_pantalla/).

Omar utilizó imágenes obtenidas mediante Google, presentadas a la cámara. Los
JPEG muestran imágenes de gato, perro y personas fotografiadas en una pantalla;
no se trata de sujetos presentes físicamente en la escena. IP Webcam produjo
fotografías nuevas de esas representaciones y la Raspberry ejecutó la inferencia
local sobre los bytes capturados. La selección de imágenes requirió acceso al
buscador; la obtención de la predicción no hace llamadas al buscador ni a AWS.

En la revisión de los archivos transferidos se verificó para las tres capturas:
JPEG legible de 1920 × 1080, tamaño y SHA-256 concordantes entre foto, JSON y log,
fechas con zona, y clase predicha concordante con argmax de softmax de los logits.
La revisión visual confirma las clases representadas. Las dependencias registradas
incluyen NumPy 2.5.4, Pillow 12.3.0 y ONNX Runtime 1.31.0.

Estos tres casos demuestran ejecución física y respuesta a entradas diferentes;
no estiman precisión general sobre escenas reales. La demostración de inferencia
con Internet desconectado corresponde a EDGE-04.

## Pruebas locales

Desde `Proyecto4`:

```bash
python -m unittest discover -s edge -p test_inferencia.py -v
```

Las pruebas usan una sesión simulada: comprueban rechazo de hash incorrecto antes
de invocar runtime, carga de bytes verificados en CPU, transformación de entrada,
softmax y rechazo de JPEG que no corresponde a su registro. No demuestran que el
binario INT8 funcione en la Raspberry. El cierre requiere ejecución física real,
evidencias de respuesta a las entradas y revisión e integración del PR.
