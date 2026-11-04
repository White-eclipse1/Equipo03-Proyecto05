# A1-02 — Procedencia del detector

## Objetivo

Dejar completamente identificable el artefacto que usa el Proyecto 5, y poder recuperarlo y verificarlo sin intervención del equipo.

## Artefacto

| Campo | Valor |
|---|---|
| Detector | YOLOX-Tiny, preentrenado en COCO |
| Autores | Megvii-BaseDetection |
| Versión | Release `0.1.1rc0` (prerelease "0.1.1 pre release") |
| Commit del tag | e1052df71842031413f6030723c3607b839c80ce |
| Archivo de pesos | yolox_tiny.onnx |
| URL | https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx |
| Tamaño | 20 219 662 bytes |
| SHA-256 | 427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7 |
| Publicado | 2021-08-18, por la cuenta FateScript; sin cambios desde entonces según GitHub |
| Formato | ONNX, IR 6, opset 11, exportado con PyTorch 1.7 |
| Entrada | `images`: 1x3x416x416, float32 |
| Salida | `output`: 1x3549x85, float32 |

El programa usa estos mismos valores desde src/p5/detector/weights.py (`WEIGHTS_URL`, `WEIGHTS_SHA256` y `WEIGHTS_SIZE`), de donde A3 también puede tomarlos para el benchmark.

## Licencia

El repositorio de YOLOX declara **Apache-2.0**, tanto en su rama principal como en el commit del tag.

- Los pesos se publican como archivos de ese mismo release.
- No se encontró una declaración de licencia específica para los pesos, ni un archivo NOTICE en la rama principal.
- Los pesos se entrenaron con COCO, cuyas imágenes tienen sus propios términos de uso.

Por eso aquí se documenta lo que declara el proyecto, y no una conclusión legal sobre los pesos. Si el proyecto se usara fuera del ámbito académico, habría que revisarlo aparte.

## Clases

Las 80 clases de COCO, en src/p5/detector/coco_classes.py. El orden coincide con la lista oficial de YOLOX, porque cada índice de la salida del modelo corresponde a una posición de esa lista.

## Runtime requerido

| Pieza | Versión |
|---|---|
| Python | 3.12 |
| onnxruntime | 1.31.1, solo con CPUExecutionProvider |
| numpy | 2.5.4 |
| opencv-python-headless | 5.0.0.93 |

Las versiones están fijadas en requirements.lock.txt. Probado en Windows x86-64 y en Linux x86-64 (contenedor `python:3.12` y CI en Ubuntu). No se ha probado en el hardware del carro.

## Recuperar los pesos

Los pesos no se versionan en Git: models/ está en .gitignore. Se descargan del release original, sin depender de AWS ni de otro servicio del equipo. Después de la descarga solo se necesitan en local.

Con la preparación de [A1-01_DETECTOR.md](A1-01_DETECTOR.md), desde Proyecto5:

### PowerShell

```powershell
.venv\Scripts\python -m p5.detector.weights
.venv\Scripts\python -m p5.detector.weights --verify-only
```

### Linux

```bash
.venv/bin/python -m p5.detector.weights
.venv/bin/python -m p5.detector.weights --verify-only
```

Sin opciones, el comando deja el archivo en models/yolox_tiny.onnx e imprime su hash y su ruta. Con `--path` se usa otra ruta, y con `--verify-only` solo se comprueba el archivo, sin descargar.

La descarga puede tardar varios minutos si la conexión con GitHub es lenta.

## Verificación del hash

- **Después de descargar:** el archivo se baja a un temporal y solo pasa a su ruta final si el tamaño y el SHA-256 coinciden.
- **Si falla:** el comando termina con código 1, registra `weights_error` en el log y no deja archivos parciales. Si ya existía un archivo, lo conserva.
- **Si el archivo existente es correcto:** no vuelve a descargarlo.
- **Si el archivo existente es incorrecto:** registra `weights_invalid` y lo reemplaza solo con una descarga verificada.

El CI usa este mismo comando en cada corrida.

## Límites conocidos

- **Origen del hash:** GitHub no publica un digest para este archivo y el proyecto no publica hashes. El SHA-256 se calculó del archivo descargado el 2026-11-03: garantiza que siempre se usa ese mismo archivo, no que coincida con un valor publicado por los autores.
- **Relación con el commit:** el archivo se subió al release antes de publicarlo, y no hay evidencia verificable de que se haya exportado exactamente desde el commit del tag.
- **Disponibilidad:** si los autores retiran el archivo, la descarga falla y el hash no permite recuperarlo. Habría que publicar una copia, revisando antes la licencia.
- **Métricas de los autores:** reportan mAP 0.5:0.95 de 32.8 en COCO val, a 416x416. Ese valor no se reprodujo aquí; las métricas del proyecto corresponden a A3.
