# Proyecto 5 — Detección y decisión de movimiento

Detecta obstáculos en imágenes reales del carro, decide cómo moverse y genera un comando, todo en CPU y con un adaptador virtual: **los motores nunca se activan**.

imagen → detección → estado → decisión → comando

## Estado de la entrega

**La reproducción está completa.** Desde una copia limpia, todos los pasos dan `ok` en Linux y en Windows, incluidos los 10 casos C1–C10. El resultado y los límites conocidos están en [docs/B3-03_REPRODUCCION.md](docs/B3-03_REPRODUCCION.md).

## Equipo

Ocho personas, en dos grupos con un PM y tres integrantes cada uno. Los grupos acuerdan el contrato de [docs/A1-03_CONTRATO.md](docs/A1-03_CONTRATO.md).

### Grupo A: Percepción y datos

| Rol | Responsable | Responsabilidad |
|---|---|---|
| PM A | Mauricio Figueroa Guerrero (@White-eclipse1) | Coordina el grupo y acuerda el contrato con el grupo B |
| A1 | Josué Godoy (@JGO-07) | Detector y runtime |
| A2 | Diego Lemus (@D-Lemus) | Secuencias y anotaciones |
| A3 | Omar Oswaldo Ramírez Arenas (@OmarCTMX) | Métricas de detección, benchmark y auditoría |

### Grupo B: Control y verificación

| Rol | Responsable | Responsabilidad |
|---|---|---|
| PM B | Santiago Ortiz Soto (@Sir-roboot) | Coordina el grupo y acuerda el contrato con el grupo A |
| B1 | Andrés Quiroz Valdovinos (@AndresQuiVal) | Política temporal |
| B2 | Luis Leal (@lluisvl) | Adaptador de control y paradas |
| B3 | Ignacio Villaseñor (@Lanachiza) | Integración y pruebas |

**Apoyos entre roles:** Diego Lemus implementó las métricas (#16 y #17) y el runner de casos (#8). Josué Godoy implementó el recorrido integrado (#7), el benchmark (#18) y la reproducción (#9). Los responsables de cada entrega están en sus tickets y documentos.

## Requisitos

- Python 3.12 y Git.
- Red solo para clonar, instalar y descargar los pesos. Después, nada usa la red: ni AWS ni otro servicio externo.

## Preparación

Desde la raíz del repositorio, en orden y en la misma terminal. No hace falta activar el entorno virtual.

### PowerShell

`py -3.12` encuentra el Python 3.12 instalado desde python.org. Con otra instalación, como la de uv, usa la entrada que muestre `py -0p`, por ejemplo `py -V:Astral/CPython3.12.16 -m venv .venv`.

```powershell
cd Proyecto5
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock.txt
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\python -m p5.detector.weights
```

### Linux

```bash
cd Proyecto5
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m p5.detector.weights
```

El último comando descarga el detector y verifica su SHA-256. El dataset ya viene en el repositorio.

## Reproducir todo

Desde Proyecto5. Corre cada comando de abajo y las pruebas, y deja todo en una carpeta nueva. Tarda unos minutos.

### PowerShell

```powershell
.venv\Scripts\python scripts\reproducir.py --output resultados\reproduccion
```

### Linux

```bash
.venv/bin/python scripts/reproducir.py --output resultados/reproduccion
```

El resumen queda en `reproduccion.json`, con un estado por paso:

| Estado | Significado |
|---|---|
| `ok` | El comando corrió y se cumple lo esperado |
| `incompleto` | El comando corrió, pero algún caso C1–C10 falla o sigue pendiente |
| `falla` | El comando falló, o su resultado no es válido |

El comando solo termina con código 0 si todos los pasos dan `ok`. La salida de cada paso queda en `registros/`.

## Comandos por separado

Desde Proyecto5. Todos aceptan una carpeta o archivo de salida a elección, y no reemplazan resultados anteriores: para repetir uno, cambia la ruta. Solo el comando de inferencia imprime por pantalla.

### PowerShell

```powershell
.venv\Scripts\python -m p5.detector.weights --verify-only
.venv\Scripts\python -m p5.dataset.paquete validate --dataset data\p5-eval-v1
.venv\Scripts\python -m p5.dataset.paquete validate --dataset data\p5-ajuste-v1 --against data\p5-eval-v1
.venv\Scripts\python -m p5.detector --weights models\yolox_tiny.onnx --image ..\Proyecto4\evidencias\EDGE-01\camara-nueva.jpg
.venv\Scripts\python -m p5.integration --manifest data\p5-eval-v1\manifiesto.jsonl --sequence seq02 --output resultados\recorrido\seq02.jsonl
.venv\Scripts\python -m p5.policy --output resultados\politica
.venv\Scripts\python -m p5.casos.runner --cases casos\c1_c10.yaml --config config\politica.yaml --dataset data\p5-eval-v1 --weights models\yolox_tiny.onnx --output resultados\casos
.venv\Scripts\python -m p5.metrics --dataset data\p5-eval-v1 --weights models\yolox_tiny.onnx --output resultados\metricas
.venv\Scripts\python -m p5.benchmark --manifest data\p5-eval-v1\manifiesto.jsonl --output resultados\benchmark
$env:P5_DETECTOR_WEIGHTS = "models/yolox_tiny.onnx"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
```

### Linux

```bash
.venv/bin/python -m p5.detector.weights --verify-only
.venv/bin/python -m p5.dataset.paquete validate --dataset data/p5-eval-v1
.venv/bin/python -m p5.dataset.paquete validate --dataset data/p5-ajuste-v1 --against data/p5-eval-v1
.venv/bin/python -m p5.detector --weights models/yolox_tiny.onnx --image ../Proyecto4/evidencias/EDGE-01/camara-nueva.jpg
.venv/bin/python -m p5.integration --manifest data/p5-eval-v1/manifiesto.jsonl --sequence seq02 --output resultados/recorrido/seq02.jsonl
.venv/bin/python -m p5.policy --output resultados/politica
.venv/bin/python -m p5.casos.runner --cases casos/c1_c10.yaml --config config/politica.yaml --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --output resultados/casos
.venv/bin/python -m p5.metrics --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --output resultados/metricas
.venv/bin/python -m p5.benchmark --manifest data/p5-eval-v1/manifiesto.jsonl --output resultados/benchmark
export P5_DETECTOR_WEIGHTS=models/yolox_tiny.onnx
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Los comandos de casos y de reproducción terminan con código 1 si algún caso falla o queda pendiente.

## Seguir un cuadro

Después del comando de recorrido, esto muestra todas las etapas de un cuadro: detecciones, estado, decisión y comando, con el mismo `frame_id`.

### PowerShell

```powershell
Select-String seq02-0003 resultados\recorrido\seq02.jsonl
```

### Linux

```bash
grep seq02-0003 resultados/recorrido/seq02.jsonl
```

La reproducción completa también lo resume en `cuadro_trazado.json`. El formato está en [docs/B3-01_RECORRIDO.md](docs/B3-01_RECORRIDO.md).

## Entregables

| Entregable | Contenido | Dónde |
|---|---|---|
| E1 | Repositorio y reproducción | Este README, [docs/B3-03_REPRODUCCION.md](docs/B3-03_REPRODUCCION.md) y [evidencias/B3-03/](evidencias/B3-03/) |
| E2 | Detector, procedencia y contrato | [docs/A1-01_DETECTOR.md](docs/A1-01_DETECTOR.md), [docs/A1-02_PROCEDENCIA.md](docs/A1-02_PROCEDENCIA.md) y [docs/A1-03_CONTRATO.md](docs/A1-03_CONTRATO.md) |
| E3 | Dataset congelado | [docs/A2_DATASET.md](docs/A2_DATASET.md) y [data/](data/) |
| E4 | Política y adaptador virtual | [docs/B1-01_POLITICA.md](docs/B1-01_POLITICA.md), [docs/B1-02_TEMPORAL.md](docs/B1-02_TEMPORAL.md), [docs/B2-01_VIRTUAL_CONTROL_ADAPTER.md](docs/B2-01_VIRTUAL_CONTROL_ADAPTER.md), [docs/B2-02_WATCHDOG.md](docs/B2-02_WATCHDOG.md) y [docs/B2_MAPEO_CARRO.md](docs/B2_MAPEO_CARRO.md) |
| E5 | Casos C1–C10 | [docs/B3-02_RUNNER.md](docs/B3-02_RUNNER.md), [docs/B1-03_VALIDACION.md](docs/B1-03_VALIDACION.md) y [casos/c1_c10.yaml](casos/c1_c10.yaml) |
| E6 | Métricas del detector | [docs/A3_METRICAS.md](docs/A3_METRICAS.md), [evidencias/a3-metricas-mediana3/](evidencias/a3-metricas-mediana3/), vigente; [evidencias/a3-metricas-v1/](evidencias/a3-metricas-v1/) y [evidencias/a3-metricas-python312/](evidencias/a3-metricas-python312/), sin filtro |
| E7 | Benchmark | [docs/A3-03_BENCHMARK.md](docs/A3-03_BENCHMARK.md), [evidencias/A3-03-mediana3/](evidencias/A3-03-mediana3/), vigente, y [evidencias/A3-03/](evidencias/A3-03/), sin filtro |
| Auditoría | Revisión independiente de datos, métricas y benchmark | [docs/A3-04_AUDITORIA.md](docs/A3-04_AUDITORIA.md) |

## Seguridad

- **Motores:** `VirtualControlAdapter` tiene `physical_output_enabled = False`, y ningún comando de esta guía llama a las rutas de motores.
- **Red:** solo `p5.detector.weights` descarga los pesos, y solo `p5.dataset.captura` lee la cámara. Una prueba comprueba que ningún otro módulo pueda abrir una conexión.
- **Secretos:** el CI revisa el repositorio con gitleaks, y este proyecto no necesita credenciales.
