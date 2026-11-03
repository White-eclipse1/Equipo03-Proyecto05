# EDGE-05 — Eventos locales compatibles con el receptor

`edge/eventos.py` reutiliza captura física de EDGE-02 e inferencia de EDGE-03.
Verifica y carga el modelo, solicita una fotografía nueva, infiere sobre sus bytes
y construye un evento con campos explícitos del
[contrato de capturas](contrato-capturas.md). Cada foto recibe un UUID nuevo;
se conserva su capture_id y captured_at al construir el evento.

## Registro local

| Archivo | Contenido |
|---|---|
| `capturas/<capture_id>.jpg` | JPEG original obtenido desde IP Webcam |
| `capturas/<capture_id>.json` | Registro local de cámara, con dimensiones y tamaño |
| `capturas/capturas.jsonl` | Log de capturas |
| `eventos/<capture_id>.json` | Solo campos del contrato, listo para el envío posterior |
| `eventos.jsonl` | Modelo cargado, evento guardado, métricas y prueba de persistencia |

El evento contiene schema_version 1, capture_id, captured_at con zona, clase,
confianza sin redondear, device_id, versión/hash del modelo cargado, hash/ruta del
JPEG y region null (imagen completa). No contiene estado, width, height,
image_bytes, logits ni tiempos. Esos campos permanecen en los logs locales.

Se comprueba el hash de la fotografía antes de construir el evento. El JSON se
escribe y sincroniza a un temporal y se publica completo mediante enlace duro,
sin sobrescribir un evento anterior del mismo ID. Repetir los mismos datos
conserva el archivo; datos distintos con ese ID provocan conflicto visible.
Esta publicación requiere un sistema de archivos con soporte de enlaces duros,
como el directorio Linux habitual de la Raspberry.

## Prueba física

Distribuir `edge/eventos.py` a `/home/pi/edge01/app/eventos.py`. Conservar las
dependencias de inferencia ya instaladas y los archivos camara.py, inferencia.py,
modelo/preprocesar.py y modelo/model_int8.onnx.

```bash
cd "$HOME/edge01"
source .venv/bin/activate
python -u app/eventos.py --modelo modelo/model_int8.onnx --url "http://10.60.188.31:8080/shot.jpg" --cantidad 3 --salida evidencias/EDGE-05 --probar-fallo-envio
```

Sustituir la dirección por la URL HTTP local vigente, terminada en /shot.jpg.
Presentar tres escenas nuevas; cada Enter toma una foto, clasifica y guarda el
evento. Si se usan imágenes en pantalla, indicar esa condición en la entrega.

La opción de prueba hace un POST multipart a **127.0.0.1:1** después de guardar
foto y evento. Con ese puerto local cerrado, se registra fallo de conexión y
se comparan los bytes antes/después. No usa token, AWS ni el portal. Es una prueba
controlada de persistencia ante fallo de transporte; la integración real y los
reintentos del receptor corresponden a EDGE-06. Si ese puerto responde o no se
produce fallo de red, no se considera demostrada esta prueba.

Para cada captura deben aparecer `evento_guardado` y `fallo_envio_controlado`, con
`evento_conservado`, `jpeg_conservado` y `bytes_intactos` verdaderos. Conservar JPEG,
JSON de captura/evento, logs y captura de Terminal. Elegir un ID y contrastar
visualmente imagen → evento → predicción → versión del modelo. No enviar los
JSON de captura ni el log completo al receptor.

## Pruebas locales

### Evidencia física del 16 de octubre de 2026

Archivos en [`evidencias/EDGE-05/`](../evidencias/EDGE-05/): tres JPEG y registros
de cámara, tres eventos del contrato, log `eventos.jsonl` y cinco capturas de
Terminal. Cada evento tiene capture_id distinto y fecha con zona UTC−06:00.

| capture_id | Clase | Confianza |
|---|---|---|
| edge01-211538a088644fe19b3f579367d5b2c8 | cat | 0.9987449645996094 |
| edge01-fac80255e2cb4637985a05f459f53f08 | dog | 0.5797439813613892 |
| edge01-56850aed5f384bb6a129471dd2763f40 | person | 0.9963647723197937 |

Se revisaron JPEG legibles, hashes concordantes entre foto, captura y evento,
fecha de captura conservada, campos exclusivos del contrato y correspondencia
entre predicción/confianza del log y evento guardado. Los tres eventos registran
`1.0.0-int8-e05.1` con hash
`ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12`.

Para el capture_id `edge01-211538a088644fe19b3f579367d5b2c8` se inspeccionó además
el JPEG y se contrastó con su evento y predicción cat. El fallo de transporte
controlado aparece después del guardado de cada evento; los tres casos registran
foto y evento conservados y bytes intactos. Los originales transferidos mantienen
los hashes declarados. Esta evidencia demuestra persistencia ante el fallo local
controlado, no recepción ni idempotencia en el portal.

### Ejecución de pruebas

Desde Proyecto4:

```bash
python -m unittest discover -s edge -p test_eventos.py -v
```

Comprueban campos explícitos del contrato, hash de imagen, confianza y fecha,
idempotencia/conflicto local y persistencia byte a byte ante un error de red
simulado. La validación física y revisión/merge del PR completan la entrega.
