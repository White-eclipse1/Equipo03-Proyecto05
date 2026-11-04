# A1-01 — Detector de objetos en CPU

## Objetivo

Integrar un detector real que procese imágenes completas y produzca bounding box, clase y confianza, ejecutándose únicamente en CPU.

## Componentes

- src/p5/detector/yolox.py: YoloxDetector, preprocesamiento y posprocesamiento.
- src/p5/detector/models.py: Detection y DetectionResult.
- src/p5/detector/coco_classes.py: las 80 clases, en el orden de salida del modelo.
- src/p5/detector/\_\_main\_\_.py: comando de línea.
- tests/test_detector.py: comportamiento y errores, con una sesión simulada.
- tests/test_detector_real_weights.py: pesos e imágenes reales.

## Detector

| Campo | Valor |
|---|---|
| Modelo | YOLOX-Tiny, preentrenado en COCO |
| Origen | Release 0.1.1rc0 de Megvii-BaseDetection/YOLOX |
| Licencia del repositorio | Apache-2.0 |
| Archivo | yolox_tiny.onnx, 20 219 662 bytes |
| SHA-256 | 427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7 |
| Runtime | onnxruntime 1.31.1, solo CPUExecutionProvider |
| Entrada | 1x3x416x416, float32 |
| Salida | 1x3549x85 |

La ficha completa de procedencia corresponde a A1-02.

## Preparación

Requiere Python 3.12. Los comandos se ejecutan desde la raíz del repositorio, en orden y en la misma terminal. No hace falta activar el entorno virtual. La carpeta models/ no se versiona.

### PowerShell

`py -3.12` encuentra el Python 3.12 instalado desde python.org. Con otra instalación, como la de uv, `py -3.12` puede fallar: usa en ese paso la entrada 3.12 que muestre `py -0p`, por ejemplo `py -V:Astral/CPython3.12.16 -m venv .venv`.

```powershell
cd Proyecto5
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt
.venv\Scripts\python -m pip install --no-deps -e .
New-Item -ItemType Directory -Force models | Out-Null
curl.exe -fsSL -o models\yolox_tiny.onnx https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx
if ((Get-FileHash models\yolox_tiny.onnx -Algorithm SHA256).Hash -ne "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7") { throw "SHA-256 no coincide" }
```

### Linux

```bash
cd Proyecto5
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps -e .
mkdir -p models
curl -fsSL -o models/yolox_tiny.onnx https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx
echo "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7  models/yolox_tiny.onnx" | sha256sum -c -
```

## Uso

Desde Proyecto5, con una imagen del repositorio como ejemplo. Para otra imagen, cambia la ruta de `--image`.

### PowerShell

```powershell
.venv\Scripts\python -m p5.detector --weights models\yolox_tiny.onnx --image ..\Proyecto4\evidencias\EDGE-01\camara-nueva.jpg
```

### Linux

```bash
.venv/bin/python -m p5.detector --weights models/yolox_tiny.onnx --image ../Proyecto4/evidencias/EDGE-01/camara-nueva.jpg
```

Opciones: `--score-threshold` (0.10 por defecto) y `--nms-threshold` (0.45 por defecto).

El JSON sale por stdout:

```json
{
  "image_path": "frame.jpg",
  "image_width": 1920,
  "image_height": 1080,
  "detections": [
    {"class_name": "person", "confidence": 0.876, "bbox_xyxy": [930.1, 406.2, 1235.4, 1080.0]}
  ]
}
```

`bbox_xyxy` está en píxeles de la imagen original, con origen arriba a la izquierda. Una escena sin objetos produce `detections: []`.

Este formato es la salida de A1-01. El contrato A → B, con frame_id, tiempo y estado de percepción, está en [A1-03_CONTRATO.md](A1-03_CONTRATO.md).

## Clases

Las 80 clases de COCO, en src/p5/detector/coco_classes.py. Incluyen todas las clases de obstáculo de la política: person, bicycle, car, motorcycle, bus, truck, cat y dog.

## Preprocesamiento

Igual al demo oficial de YOLOX:

1. Decodifica la imagen a BGR de 3 canales. OpenCV aplica la orientación EXIF.
2. Redimensiona sin deformar con interpolación lineal, para caber en 416x416.
3. Rellena con el valor 114 abajo y a la derecha.
4. Pasa a CHW y float32, con valores 0-255. No usa media ni desviación.

## Posprocesamiento

1. Decodifica cada celda de las mallas de stride 8, 16 y 32 a una caja en píxeles de entrada.
2. Calcula score = objectness × probabilidad de la clase más probable.
3. Descarta los scores que no superan `score_threshold`.
4. Divide las cajas entre el factor de escala para volver a la imagen original.
5. Recorta las cajas a los límites de la imagen.
6. Aplica NMS sin distinguir clase, con IoU 0.45, como el demo oficial.
7. Elimina las cajas que quedan sin área, por ejemplo las que caían solo en el relleno.

El umbral por defecto (0.10) es el previo al NMS del demo oficial. Es deliberadamente bajo: quien consume la salida aplica su propio umbral, como la política con 0.30 y 0.50. Las métricas deben fijar y declarar el suyo.

## Independencia de las etiquetas

La predicción solo usa los píxeles. No lee el nombre del archivo ni archivos de etiquetas, y hay una prueba que lo comprueba.

## Errores

Cualquier fallo se registra en el log con `detector_error stage=<etapa> source=<origen> detail=<detalle>` y lanza DetectorError. Las etapas son load, read, preprocess, inference y postprocess.

También falla si la sesión no corre solo en CPU, o si la salida del modelo tiene otra forma, valores no finitos o scores fuera de [0, 1].

El comando termina con código 1 y no imprime JSON. Una falla nunca se presenta como una escena vacía.

## Verificación

Desde Proyecto5.

### PowerShell

```powershell
$env:P5_DETECTOR_WEIGHTS = "models/yolox_tiny.onnx"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
```

### Linux

```bash
export P5_DETECTOR_WEIGHTS=models/yolox_tiny.onnx
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Sin `P5_DETECTOR_WEIGHTS`, las pruebas con pesos reales se omiten. El CI descarga los pesos, verifica su SHA-256 y las ejecuta.

Resultados con pesos reales y umbral 0.30:

| Imagen | Detecciones |
|---|---|
| Proyecto4/evidencias/EDGE-02/manual/edge01-0dc81034….jpg, calle (1920x1080) | 7 person, 1 car, 1 handbag |
| assets/dog.jpg del repositorio de YOLOX (768x576) | bicycle 0.89, car 0.70, cat 0.56 |
| Proyecto4/evidencias/EDGE-01/camara-nueva.jpg, botella detrás de un teléfono | refrigerator 0.46, tie 0.34 |
| Imagen gris lisa (640x480) | ninguna |

También se comparó la salida con una copia literal de la lógica oficial de YOLOX en tres imágenes, y clases, confianzas y cajas coincidieron.

## Límites conocidos

- YOLOX-Tiny puede confundir clases: en dog.jpg el perro sale como cat. Ambas son obstáculo para la política, pero contarían como error en las métricas por clase de A3.
- Con confianzas bajas aparecen falsos positivos, como refrigerator y tie en la imagen de la botella.
- Estas imágenes solo comprueban que el detector funciona de punta a punta. La calidad real se medirá con el dataset de A2 y las métricas de A3.

## Pendiente

- A1-02: procedencia completa y descarga reproducible con verificación del hash.
