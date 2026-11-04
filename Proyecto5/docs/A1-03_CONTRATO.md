# A1-03 — Contrato de salida del detector (A → B)

## Objetivo

Entregar cada cuadro en el formato que consume la política de B1, sin que un fallo del detector se pueda confundir con una escena despejada.

## Componentes

- src/p5/detector/frame.py: `detect_frame` y `PerceptionFrame`.
- docs/examples/a1-03/: ejemplos generados con el detector real.
- tests/test_detector_frame.py: validación contra el contrato y la política reales.

## Dónde vive el contrato

La definición sigue en Proyecto3/src/p3/policy/contrato.py (`Cuadro`), la propuesta de B1. Este avance no la modifica ni la copia.

Las pruebas de Proyecto5 importan `Cuadro` y `PoliticaDecision` directamente, así que un cambio incompatible en ese contrato hace fallar el CI de P5. El CI también corre cuando cambian Proyecto3/src/p3/policy/ o Proyecto3/config/politica.yaml.

`p5.detector` no depende de `p3` para ejecutarse: pydantic y pyyaml solo se usan en las pruebas.

## Formato

Un objeto JSON por cuadro. Con JSONL, una línea por cuadro con `PerceptionFrame.to_json()`.

| Campo | Tipo | Significado |
|---|---|---|
| `sequence_id` | texto no vacío | Secuencia a la que pertenece el cuadro. |
| `frame_id` | texto no vacío | Identificador del cuadro. |
| `t_capture_ms` | número ≥ 0 | Tiempo relativo al inicio de la secuencia. |
| `image_width`, `image_height` | enteros > 0 | Tamaño de la imagen original, en píxeles. |
| `status` | `"ok"` o `"error"` | Estado de percepción. |
| `detections` | lista | Detecciones del cuadro. Siempre vacía con `status: "error"`. |
| `error` | texto o `null` | Motivo del fallo. Solo con `status: "error"`. |

Cada detección tiene:

| Campo | Tipo | Significado |
|---|---|---|
| `class_name` | texto | Clase COCO. |
| `confidence` | número en [0, 1] | Confianza. |
| `bbox_xyxy` | 4 números | `[x1, y1, x2, y2]`, con `x2 > x1` e `y2 > y1`. |

Las coordenadas están en píxeles de la imagen original, no de la entrada de 416x416. El origen está en la esquina superior izquierda; x crece a la derecha e y hacia abajo.

## Escena vacía y error

| Situación | `status` | `detections` | `error` | Decisión de la política |
|---|---|---|---|---|
| Sin objetos | `ok` | `[]` | `null` | Puede llegar a `VIA_LIBRE` tras 3 cuadros libres |
| Fallo del detector | `error` | `[]` | motivo | Siempre STOP con `ERROR_PERCEPCION` |

Generan `status: "error"` una imagen que no se puede leer y los fallos de preprocesamiento, inferencia o posprocesamiento. Cada uno también queda en el log como `detector_error`.

## Ejemplos

- [Con detecciones](examples/a1-03/frame_ok.json)
- [Escena vacía](examples/a1-03/frame_empty.json)
- [Error](examples/a1-03/frame_error.json)

## Uso

Con las filas del manifiesto de A2:

```python
from pathlib import Path

from p5.dataset.paquete import load_manifest
from p5.detector.frame import detect_frame
from p5.detector.yolox import YoloxDetector

dataset = Path("data/p5-eval-v1")
detector = YoloxDetector.from_weights("models/yolox_tiny.onnx")

for row in load_manifest(dataset / "manifiesto.jsonl"):
    frame = detect_frame(
        detector,
        dataset / row["image"],
        sequence_id=row["sequence_id"],
        frame_id=row["frame_id"],
        t_capture_ms=row["t_capture_ms"],
        image_size=(row["image_width"], row["image_height"]),
    )
    print(frame.to_json())
```

La salida de `frame.to_dict()` se pasa sin cambios a `PoliticaDecision.decidir_crudo`.

- **Identificadores y tiempo:** los entrega quien llama, porque el detector no los conoce. `detect_frame` no recibe `road_state`, `annotations` ni `allowed_actions`.
- **`image_size`:** es (ancho, alto) esperado y solo se usa si la imagen no se puede leer, porque el contrato exige dimensiones también en un error. Si se puede leer, se informa su tamaño real.
- **`t_capture_ms`:** la política exige que crezca dentro de la secuencia. `detect_frame` no lo comprueba porque procesa un cuadro a la vez.
- **Umbral:** `from_weights` usa 0.10 por defecto, así que llegan detecciones débiles. La política ignora las menores de 0.30 y las deja registradas como `bajo_umbral`.

## Errores que no producen un cuadro

- **Pesos que no cargan:** `YoloxDetector.from_weights` lanza `DetectorError`, porque todavía no hay ningún cuadro que reportar. Quien integra debe tratarlo como un fallo de arranque y no mover el carro.
- **Datos inválidos de quien llama:** `detect_frame` lanza `ValueError` si `sequence_id` o `frame_id` están vacíos, si `t_capture_ms` es negativo o no finito, o si `image_size` no es positivo.

## Verificación

Desde Proyecto5, después de la preparación de A1-01_DETECTOR.md.

### PowerShell

```powershell
.venv\Scripts\python -m pip install -r requirements.lock.txt
$env:P5_DETECTOR_WEIGHTS = "models/yolox_tiny.onnx"
.venv\Scripts\python -m pytest tests/test_detector_frame.py tests/test_detector_real_weights.py
```

### Linux

```bash
.venv/bin/python -m pip install -r requirements.lock.txt
export P5_DETECTOR_WEIGHTS=models/yolox_tiny.onnx
.venv/bin/python -m pytest tests/test_detector_frame.py tests/test_detector_real_weights.py
```

## Pendiente

- Aceptación del Grupo B (B1, B2 y B3).
