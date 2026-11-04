# B3-01 — Recorrido completo con el detector real

## Objetivo

Llevar una imagen real por todo el sistema, sin detecciones escritas a mano, y poder seguir cada cuadro de principio a fin:

imagen → detección → estado → decisión → comando

## Componentes

- src/p5/integration/pipeline.py: `FrameInput`, `Pipeline`, `FrameTrace` y la conversión de la decisión al adaptador.
- src/p5/integration/\_\_main\_\_.py: comando de línea.
- tests/test_integration_pipeline.py: comportamiento y errores de cada etapa, con una sesión simulada.
- tests/test_integration_real_weights.py: pesos e imágenes reales.

## Etapas

| Etapa | Pieza | Rol |
|---|---|---|
| Imagen | `load_manifest`, de `p5.dataset.paquete` | A2 |
| Detección | `detect_frame`, de `p5.detector.frame` | A1 |
| Estado y decisión | `PoliticaDecision.decidir_crudo`, de `p3.policy.politica` | B1 |
| Comando | `VirtualControlAdapter.apply`, de `p5.control.adapter` | B2 |

Del manifiesto solo pasan `sequence_id`, `frame_id`, `t_capture_ms`, las dimensiones esperadas y la ruta de la imagen. `road_state`, `annotations` y `allowed_actions` no llegan al recorrido.

## Preparación

La de [A1-01_DETECTOR.md](A1-01_DETECTOR.md). Si ya tenías el entorno, repite el paso `pip install --no-deps -e .`: es el que deja importable la política de Proyecto3.

## Uso

Desde Proyecto5.

### PowerShell

```powershell
.venv\Scripts\python -m p5.integration --manifest data\p5-eval-v1\manifiesto.jsonl --sequence seq02 --output resultados\seq02.jsonl
Select-String seq02-0003 resultados\seq02.jsonl
```

### Linux

```bash
.venv/bin/python -m p5.integration --manifest data/p5-eval-v1/manifiesto.jsonl --sequence seq02 --output resultados/seq02.jsonl
grep seq02-0003 resultados/seq02.jsonl
```

El segundo comando muestra el recorrido de un cuadro.

Opciones:

- `--sequence`: sin ella, recorre todo el manifiesto.
- `--output`: cualquier ruta. Crea las carpetas que falten. Si el archivo ya existe, termina con código 1 y no lo toca. resultados/ no se versiona.
- `--weights`: models/yolox_tiny.onnx por defecto.
- `--policy-config`: ../Proyecto3/config/politica.yaml por defecto.

Al terminar imprime `frames=<total> errors=<cuadros con error> output=<ruta>`. Cada comando también queda en el log, en stderr, con su `frame_id`.

## Traza

Una línea JSON por cuadro. Este es el cuadro seq02-0003 real, con los campos largos recortados:

```json
{
  "sequence_id": "seq02",
  "frame_id": "seq02-0003",
  "t_capture_ms": 1106,
  "image": "data/p5-eval-v1/secuencias/seq02/seq02-0003.jpg",
  "perception": {
    "frame_id": "seq02-0003",
    "t_capture_ms": 1106,
    "status": "ok",
    "detections": [
      {"class_name": "person", "confidence": 0.869, "bbox_xyxy": [222.4, 68.7, 283.9, 203.9]}
    ],
    "error": null
  },
  "decision": {
    "frame_id": "seq02-0003",
    "t_capture_ms": 1106.0,
    "estado": "BLOCKED",
    "accion": "EVADE_LEFT",
    "reason_code": "EVASION_IZQUIERDA",
    "velocidad": 0.2,
    "direccion": -0.5,
    "valido_hasta_ms": 1606.0
  },
  "command": {
    "speed": 0.2,
    "direction": "left",
    "steering": -0.5,
    "timestamp": 1793761482.078,
    "frame_id": "seq02-0003",
    "decision_id": "seq02:seq02-0003",
    "reason_code": "EVASION_IZQUIERDA",
    "valid_until_ms": 1606.0
  },
  "errors": []
}
```

- `frame_id` es el mismo en cada etapa.
- `t_capture_ms` es relativo al inicio de la secuencia; `timestamp` es la hora en que el adaptador emitió el comando, en segundos Unix. La traza es lo que relaciona ambos.
- `decision` es `null` solo si la política no llegó a decidir: porque falló, o porque el cuadro ya estaba vencido.
- La traza siempre es JSON estricto: un valor no finito se guarda como `null` y se registra en `errors`.
- Usa fin de línea LF en todos los sistemas. Aun así, dos corridas no dan el mismo hash: `timestamp` cambia y `image` usa la ruta del sistema.

## Conversión de la decisión al comando

| Acción de la política | Acción del adaptador | Velocidad y giro |
|---|---|---|
| STOP | STOP | 0.0 y 0.0 |
| FORWARD | FORWARD | `velocidad` de la política, sin giro |
| SLOW | FORWARD | `velocidad` de la política, sin giro |
| EVADE_LEFT | LEFT | `velocidad` y `direccion` de la política |
| EVADE_RIGHT | RIGHT | `velocidad` y `direccion` de la política |

- `decision_id` no existe en la política: el recorrido lo forma como `<sequence_id>:<frame_id>`.
- La acción original de la política sigue disponible en `decision.accion`: un SLOW y un FORWARD solo se distinguen ahí y en la velocidad.
- Para respetar `direccion`, `ControlDecision` ganó el campo opcional `requested_steering`. Sin él, el adaptador se comporta como antes, con giro completo. Ver [B2-01_VIRTUAL_CONTROL_ADAPTER.md](B2-01_VIRTUAL_CONTROL_ADAPTER.md).

## Errores

Cada fallo se registra en el log con `integration_error stage=<etapa> frame_id=<cuadro> detail=<detalle>` y en `errors` de la traza. En todas estas etapas, salvo `trace`, el comando es STOP, que reemplaza el comando de movimiento anterior. `trace` no cambia el comando: la registra junto al fallo que haya causado el valor.

| Etapa | Cuándo | Resultado |
|---|---|---|
| `detector` | Imagen ilegible o fallo de inferencia | Política en FAULT, `ERROR_PERCEPCION`. La vía hay que volver a confirmarla |
| `contract` | La salida no cumple el contrato A → B | Política en FAULT, `SALIDA_MALFORMADA` |
| `policy` | Cuadro con tiempo no creciente | `CUADRO_FUERA_DE_ORDEN`. La política conserva lo que recordaba: es regla de B1 |
| `policy` | La política lanza una excepción | `decision: null`, comando con `FALLO_INTEGRACION`. La vía hay que volver a confirmarla |
| `adapter` | El adaptador rechaza la decisión o falla | Comando con `FALLO_INTEGRACION`. La vía hay que volver a confirmarla |
| `failsafe` | Tampoco se pudo emitir el STOP de respaldo | El comando vigente se anula y este `Pipeline` no vuelve a emitir movimiento |
| `stale` | Con `now_ms`, el cuadro ya venció | `decision: null`, comando con `CUADRO_VENCIDO`. La vía hay que volver a confirmarla. Ver [B2-02_WATCHDOG.md](B2-02_WATCHDOG.md) |
| `trace` | Hay un número no finito en la traza | Ese valor se guarda como `null`, y `detail` indica en qué campo estaba |
| `output` | El archivo de salida ya existe | Fin de la corrida antes de procesar ningún cuadro. La traza anterior no cambia |
| `output` | No se puede escribir la traza | STOP con `FALLO_INTEGRACION` y fin de la corrida. Solo va al log, porque esa línea no se pudo guardar |

Volver a confirmar la vía significa que la política reinicia sus zonas: harán falta 3 cuadros libres para avanzar.

Con `stage=failsafe`, el adaptador no llegó a generar el comando: la traza lo muestra como STOP con `reason_code: STOP_NO_EMITIDO` y `timestamp: null`. `last_command` del adaptador queda en `None`, y el comando anulado pasa a `cancelled` y al log como `virtual_control_cancel`. Para volver a moverse hay que crear otro `Pipeline`. El rearme controlado es de B2-03 (#6).

Códigos de salida:

- **0:** todos los cuadros pasaron sin error.
- **1 con traza:** algún cuadro falló. La traza queda completa, salvo con `stage=output`.
- **1 sin traza:** falló el arranque (`stage=startup`) por pesos, política o manifiesto. No se emite ningún comando.

## Uso desde código

B3-02 puede usar el mismo recorrido sin pasar por el comando. Un objeto `Pipeline` por recorrido:

```python
pipeline = Pipeline(detector, PoliticaDecision(config, config_sha256), VirtualControlAdapter())
trace = pipeline.process(frame)
```

## Verificación

Con la verificación de A1-01 y `P5_DETECTOR_WEIGHTS` definida, la suite incluye estas pruebas. Para correr solo las del recorrido, desde Proyecto5:

### PowerShell

```powershell
$env:P5_DETECTOR_WEIGHTS = "models/yolox_tiny.onnx"
.venv\Scripts\python -m pytest tests\test_integration_pipeline.py tests\test_integration_real_weights.py tests\test_virtual_control_adapter.py
```

### Linux

```bash
export P5_DETECTOR_WEIGHTS=models/yolox_tiny.onnx
.venv/bin/python -m pytest tests/test_integration_pipeline.py tests/test_integration_real_weights.py tests/test_virtual_control_adapter.py
```

## Resultados con imágenes reales

Las 128 imágenes de data/p5-eval-v1, con el detector real: 128 comandos y ningún error.

| Secuencia | Caso | Cuadros | STOP | FORWARD | SLOW | EVADE_LEFT | EVADE_RIGHT |
|---|---|---:|---:|---:|---:|---:|---:|
| seq01 | C1 | 15 | 2 | 13 | 0 | 0 | 0 |
| seq02 | C2 | 24 | 2 | 8 | 6 | 6 | 2 |
| seq03 | C3 | 12 | 2 | 0 | 10 | 0 | 0 |
| seq04 | C4 | 12 | 2 | 0 | 10 | 0 | 0 |
| seq05 | C5 | 15 | 2 | 0 | 0 | 10 | 3 |
| seq06 | C7 | 50 | 2 | 30 | 11 | 0 | 7 |

Los 2 STOP de cada secuencia son sus primeros cuadros: la política todavía no ha confirmado ninguna zona libre.

## Hallazgos para B1, B3-02 y A3

El recorrido funciona, pero 5 de los 128 cuadros reciben una acción fuera de `allowed_actions`. No son errores de integración: la traza muestra que el detector pierde a la persona y la política actúa con lo que recibe.

| Cuadro | Realidad anotada | Detector | Decisión |
|---|---|---|---|
| seq06-0036 | Persona al centro | person 0.15 | FORWARD a 0.6 |
| seq06-0038 | Persona al centro | Sin person en el centro | FORWARD a 0.6 |
| seq05-0008 a 0010 | Personas al centro y a la derecha | Solo la del centro es firme | EVADE_RIGHT, hacia la otra persona |

Los dos primeros son los más delicados. En seq06, entre los cuadros 0036 y 0039 la persona alterna entre firme y perdida (0.15, 0.73, sin detección, 0.58). `cuadros_para_bloquear` exige 2 cuadros firmes seguidos, así que en esos cuadros la zona central no llega a OCUPADA, y un cuadro sin detección da vía libre.

Este PR no cambia la política ni sus umbrales. Decidir si ajustarlos corresponde a B1, y B3-02 verá estos cuadros al correr C5 y C7 con el detector real.

## Límites conocidos

- **Vigencia del comando:** el comando la lleva en `valid_until_ms`, pero `python -m p5.integration` reproduce la secuencia sin reloj y no la comprueba. El watchdog se usa con `Pipeline.tick`. Ver [B2-02_WATCHDOG.md](B2-02_WATCHDOG.md).
- **Identificación de la corrida:** la traza no incluye `run_id`, commit, SHA-256 del modelo y del manifiesto, umbrales ni runtime. Solo guarda `config_sha256` de la política. Queda para B3-03 (#9).
- **Reinicio de la política:** el recorrido reescribe `memoria` de `PoliticaDecision` porque la política no expone un método para reiniciarse. Una prueba comprueba que el resultado coincide con el reinicio por error del detector, salvo `ultimo_t_ms`.
- **Emergencia y cierre:** no hay emergencia enclavada, rearme ni STOP final al cerrar. Son de B2-03 (#6).
- **Motores:** el adaptador es virtual. Nada de este recorrido llama a las rutas de motores del carro.
- **Hardware:** se probó con imágenes capturadas por el carro, pero no en tiempo real ni en su hardware.
- **Instalación:** `p3` solo queda importable con la instalación editable `pip install -e .`. Un wheel de P5 no lo incluye.
