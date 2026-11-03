# A2 — Dataset de evaluación

Tickets: #13 A2-01, #14 A2-02 y #15 A2-03. Entregable: E3.

## Objetivo

Capturar cuadros reales de la cámara del carro, anotarlos y congelar un manifiesto que A3 y B3 puedan consumir.

## Componentes

- src/p5/dataset/captura.py: guarda una secuencia desde `/stream`.
- src/p5/dataset/anotar.py: anotador local de cajas, solo en 127.0.0.1.
- src/p5/dataset/paquete.py: valida el paquete y congela el manifiesto.

Solo usan la biblioteca estándar. Ninguno llama a las rutas de motores.

## Preparación

Desde Proyecto5. El comando `--no-deps -e .` de A1-01 exige Python 3.12; estas herramientas también corren con `PYTHONPATH=src`:

```bash
export PYTHONPATH=src
```

1. Abre Compartir Internet en el iPhone y conecta la PC al hotspot.
2. Enciende el carro y espera unos 20 segundos.
3. **Cierra la página del carro.** El firmware atiende un solo cliente del stream a la vez; con la página abierta, la captura se queda esperando.

## Paso 1: revisar la orientación

Los cuadros de ajuste no cuentan para la evaluación, así que estos sirven de prueba:

```bash
python -m p5.dataset.captura --url http://172.20.10.13:81/stream --dataset data/p5-eval-v1 --sequence aj01 --frames 5
```

La dirección del carro puede cambiar. Abre los JPG de `data/p5-eval-v1/secuencias/aj01/` y comprueba:

- Que la imagen esté derecha. `rotate(90deg)` de `app_httpd.cpp:307` es CSS de la página: no afecta estos cuadros.
- Que un objeto a la izquierda del carro aparezca a la izquierda de la imagen. Las zonas de la política usan el eje X.

Si sale de cabeza, agrega esto después de `set_framesize` en `ESP32CAM_Car.ino` y vuelve a subir el sketch. `/control` no está registrado en este firmware, así que no se puede corregir en caliente.

```cpp
s->set_vflip(s, 1);
s->set_hmirror(s, 1);
```

Si cambias la orientación, las capturas anteriores dejan de servir. Borra `aj01` y vuelve a empezar.

## Paso 2: comprobar que el detector ve los obstáculos

Pasa `aj01` por el detector de A1-01. La política solo reconoce person, bicycle, car, motorcycle, bus, truck, cat y dog, y una detección es firme desde 0.50. Si un objeto no se detecta desde la altura de la cámara, cámbialo o acércalo antes de capturar la evaluación. Esas pruebas se quedan en secuencias de ajuste.

## Paso 3: capturar

El carro no necesita moverse: basta con que el objeto cambie de posición entre cuadros. Los cuadros iguales se descartan por hash, pero una escena inmóvil produce cuadros casi idénticos, así que muévete durante la captura.

| Secuencia | Caso | Escena | Cuadros |
|---|---|---|---:|
| seq01 | C1 | Vía despejada, sin objetos de las clases evaluadas | 15 |
| seq02 | C2 | Libre y luego un obstáculo en el centro | 12 |
| seq03 | C3 | Obstáculo solo a la izquierda, centro libre | 12 |
| seq04 | C4 | Obstáculo solo a la derecha, centro libre | 12 |
| seq05 | C5 | Varios obstáculos, con el centro y un lado ocupados | 12 |
| seq06 | C7 | Libre, obstáculo persistente y libre otra vez | 15 |

```bash
python -m p5.dataset.captura --url http://172.20.10.13:81/stream --dataset data/p5-eval-v1 --sequence seq01 --frames 15
```

`--interval-ms` vale 500 por defecto. `--warmup-ms` vale 2000 y descarta los primeros cuadros, que el sensor entrega con tinte verde y cortes. Una secuencia existente no se sobrescribe: si sale mal, captura otra con un ID nuevo o borra su carpeta.

Evita personas u objetos de esas clases en el fondo: hay que etiquetarlos todos, y uno sin etiquetar cuenta como falso positivo. El repositorio es público, así que pide permiso a quien aparezca.

## Paso 4: declarar las secuencias

Crea `data/p5-eval-v1/secuencias.json`. Toda secuencia pertenece a un solo split: `evaluacion` o `ajuste`.

```json
{
  "sequences": {
    "aj01": {"split": "ajuste", "scenario": "orientacion"},
    "seq01": {"split": "evaluacion", "scenario": "C1"},
    "seq02": {"split": "evaluacion", "scenario": "C2"},
    "seq03": {"split": "evaluacion", "scenario": "C3"},
    "seq04": {"split": "evaluacion", "scenario": "C4"},
    "seq05": {"split": "evaluacion", "scenario": "C5"},
    "seq06": {"split": "evaluacion", "scenario": "C7"}
  }
}
```

## Paso 5: anotar

```bash
python -m p5.dataset.anotar --dataset data/p5-eval-v1
```

Abre http://127.0.0.1:8765. Las líneas punteadas marcan las zonas de la política. Etiqueta todos los objetos de las clases evaluadas y elige el estado de la vía:

| road_state | Geometría exigida | Acciones admisibles |
|---|---|---|
| `libre` | Sin objetos | FORWARD, SLOW, STOP |
| `lateral_izquierda` | Solo la zona izquierda | FORWARD, SLOW, STOP |
| `lateral_derecha` | Solo la zona derecha | FORWARD, SLOW, STOP |
| `centro` | Al menos una caja en el centro | STOP, SLOW, EVADE_LEFT, EVADE_RIGHT |
| `varios` | 2 o más objetos, con el centro y otra zona | STOP, SLOW, EVADE_LEFT, EVADE_RIGHT |

SLOW y STOP cubren las transiciones de la política, que tarda varios cuadros en confirmar o liberar una zona. Cuándo aplica cada acción lo acotan los casos C1–C7 de B3.

Las zonas y clases son copia de `Proyecto3/config/politica.yaml`. Si B1 las cambia, hay que actualizar `paquete.py` antes de congelar.

## Paso 6: validar y congelar

```bash
python -m p5.dataset.paquete validate --dataset data/p5-eval-v1
```

Sale con código 1 y lista cada error. Los mínimos se cuentan solo sobre `evaluacion`: 6 secuencias, 60 cuadros, 20 con obstáculo, 20 despejados y los casos C1–C5 y C7.

Cuando no haya errores, haz commit de los cuadros y las anotaciones y congela:

```bash
python -m p5.dataset.paquete freeze --dataset data/p5-eval-v1 --version v1
```

Escribe `manifiesto.jsonl` y `congelamiento.json`, con el SHA-256 del manifiesto, la fecha y el commit base. Si el contenido cambia después, `freeze` lo rechaza: cualquier corrección va en un dataset con una versión nueva.

Después de congelar, `validate` también falla si `manifiesto.jsonl` ya no coincide con el SHA-256 registrado, si falta alguno de los dos archivos, o si los cuadros o las anotaciones cambiaron.

## Formato para A3 y B3

`load_manifest` de `paquete.py` lee el manifiesto, con una fila JSON por cuadro. Lanza `ValueError` si el archivo no coincide con el SHA-256 de `congelamiento.json`, o si ese registro falta o no es válido. Usa esta función en lugar de leer el JSONL directamente:

```json
{
  "sequence_id": "seq02",
  "frame_id": "seq02-0004",
  "split": "evaluacion",
  "scenario": "C2",
  "image": "secuencias/seq02/seq02-0004.jpg",
  "sha256": "…",
  "t_capture_ms": 1500,
  "image_width": 400,
  "image_height": 296,
  "road_state": "centro",
  "annotations": [{"class_name": "person", "bbox_xyxy": [160.0, 100.0, 240.0, 280.0]}],
  "allowed_actions": ["STOP", "SLOW", "EVADE_LEFT", "EVADE_RIGHT"]
}
```

- `bbox_xyxy` usa píxeles del cuadro original, con origen arriba a la izquierda, igual que el contrato A → B.
- Un cuadro sin objetos tiene `annotations: []`.
- `image` es relativa a la carpeta del dataset.
- **El detector y la política solo deben recibir `image`, `sequence_id`, `frame_id` y `t_capture_ms`.** `road_state`, `annotations` y `allowed_actions` son para evaluar.
- Las métricas usan solo las filas con `split: "evaluacion"`.

## Verificación

```bash
python -m pytest tests/test_dataset_captura.py tests/test_dataset_paquete.py tests/test_dataset_anotar.py
```

## Límites conocidos

- Las pruebas usan un stream simulado con el formato de `app_httpd.cpp`. Falta capturar del carro real.
- El tiempo de cada cuadro se toma al recibirlo en la PC: incluye la latencia del WiFi, no el instante exacto de exposición.
- `jpeg_size` revisa la estructura del JPEG, pero no decodifica la imagen.
