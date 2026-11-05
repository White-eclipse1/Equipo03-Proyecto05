# B3-02 — Runner de casos C1–C10

Ticket: #8. Entregable: E5.

## Objetivo

Reproducir con un comando los diez casos que pide la evaluación, guardar cada resultado y terminar con error si uno no se cumple.

## Estado

| Caso | Entrada | Estado actual |
|---|---|---|
| C1–C5 y C7 | Secuencias de `p5-eval-v1` con el detector real | Se ejecutan |
| C6 | Detecciones sintéticas del caso de B1 | Se ejecuta |
| C8 | Corte de cuadros y cuadro vencido | Se ejecuta con reloj determinista y watchdog de B2 |
| C9 | Fallo de inferencia e imagen ilegible | Se ejecuta con detector sintético, política real y adaptador virtual |
| C10 | Emergencia, rearme y cierre | Se ejecuta con detector sintético, reloj determinista, política real y adaptador virtual |

Los diez casos ya se ejecutan. C5 y C7 fallan con el detector real, y esos fallos se siguen en #3.

Las secuencias reales corren por el mismo recorrido de la aplicación, `Pipeline` de B3-01: detector, política y adaptador virtual. C6 solo evalúa decisiones de la política.

## Componentes

- src/p5/casos/runner.py: el runner.
- casos/c1_c10.yaml: entradas, expectativas y plazos de cada caso.
- tests/test_casos_runner.py: pruebas del runner, incluido el fallo inducido.

## Uso

Desde Proyecto5, después de la preparación de A1-01_DETECTOR.md. `pip install --no-deps -e .` deja importable la política de Proyecto3.

### PowerShell

```powershell
.venv\Scripts\python -m p5.casos.runner --cases casos/c1_c10.yaml --config config/politica.yaml --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --output <carpeta-nueva>
```

Para ver el código de salida, corre `$LASTEXITCODE` justo después.

### Linux

```bash
.venv/bin/python -m p5.casos.runner \
  --cases casos/c1_c10.yaml \
  --config config/politica.yaml \
  --dataset data/p5-eval-v1 \
  --weights models/yolox_tiny.onnx \
  --output <carpeta-nueva>
```

Para ver el código de salida, corre `echo $?` justo después.

Corre en CPU, sin red ni hardware: nunca llama a las rutas de motores.

Sale con código 1 si un caso falla o sigue pendiente, y con 0 solo si pasan los diez. No sobrescribe una carpeta existente.

`--filtro-mediana` es opcional y está apagado por defecto. Solo es para la corrida acordada de #3, descrita en [B1-03_DETECTOR.md](B1-03_DETECTOR.md).

## Resultados

| Archivo | Contenido |
|---|---|
| `resultados.json` | La ejecución (commit, hashes del modelo, manifiesto y configuración, umbrales, entorno) y, por caso: entrada, estado inicial, expectativa, resultado, fallos y decisiones |
| `decisiones.jsonl` | Una línea por cuadro, con su caso, detecciones, estado, razón, vigencia, comando del adaptador y errores |

## Cómo se decide un caso

**Sin fuga de etiquetas:** el recorrido solo recibe `FrameInput`: `sequence_id`, `frame_id`, `t_capture_ms`, las dimensiones y la ruta de la imagen. `annotations`, `road_state` y `allowed_actions` se usan después, para comparar.

**Cada cuadro falla si:**

- La acción de la política no está en `allowed_actions` del manifiesto.
- El recorrido registró un error.
- El comando del adaptador no coincide con la decisión: dirección, velocidad y giro. El runner hace esta comparación por su cuenta, para comprobar la conversión de B3-01 en lugar de repetirla.
- El recorrido lanza una excepción inesperada. La secuencia se detiene ahí, porque ya no se puede confiar en su estado.

Si el STOP de respaldo tampoco se puede emitir, el recorrido lo registra con `stage=failsafe`, y el cuadro falla por el error registrado, aunque la traza muestre `direction: stop`.

**Reglas por caso:**

| Regla | Qué exige | Para qué |
|---|---|---|
| `alguna` | Al menos una de esas acciones en el rango | Que detenerse siempre no apruebe C1, C3, C4 ni C7 |
| `reaccion` | Una de esas acciones con la vía en `BLOCKED`, dentro del plazo. `plazo_cuadros` incluye el cuadro `desde`: plazo 2 desde el cuadro 30 son los cuadros 30 y 31 | Que el STOP de arranque no cuente como reacción |
| `direccion_min`, `direccion_max` | Límites de la dirección en toda la secuencia | Comprobar el signo en C3 y C4 |

**C9 y C10 comprueban cada paso:**

| Caso | Qué exige |
|---|---|
| C9 | Después de avanzar, un fallo de inferencia y una imagen ilegible registran el error y emiten STOP, sin avance residual |
| C10 | STOP inmediato con la emergencia; sigue parado sin rearme y con un rearme sobre un cuadro vencido; solo reanuda con rearme, percepción fresca y la vía confirmada otra vez; STOP al cerrar |

**Fallos de percepción:** si el detector falla, el recorrido marca el cuadro con `status: "error"` y emite STOP. Nunca se toma como escena vacía.

**Comprobación de las expectativas:** las pruebas corren C1–C5 y C7 con las etiquetas como si fueran un detector perfecto, y todos pasan. Si uno fallara ahí, el error estaría en la expectativa, no en el sistema.

## Última corrida

Con YOLOX-Tiny sobre `p5-eval-v1`, sin filtro, en `62a1bf3`: **8 pasan, 2 fallan y 0 pendientes**, y el comando termina con código 1. Los resultados y las trazas de la corrida de referencia, en `8e76180`, están en [c1-c10-sin-filtro/](../evidencias/B1-03-detector/c1-c10-sin-filtro/).

Estos son fallos reales del sistema, y no deben corregirse cambiando las expectativas:

| Caso | Cuadros | Observado | Por qué es un fallo |
|---|---|---|---|
| C5 | `seq05` 8, 9 y 10 | `EVADE_RIGHT` | Hay una persona a la derecha |
| C7 | `seq06` 36 y 38 | `FORWARD` | Hay una persona al centro |
| C7 | `seq06` 30 y 31 | Solo `SLOW`, sin `BLOCKED` | No confirma el bloqueo dentro del plazo de 2 cuadros |

En C5 y C7 el detector pierde a la persona, y la política necesita 2 cuadros firmes seguidos para bloquear. Cualquier ajuste se define con `p5-ajuste-v1`, no con estas secuencias. El diagnóstico y la propuesta, todavía sin medir en evaluación, están en [B1-03_DETECTOR.md](B1-03_DETECTOR.md).

## Verificación

Con `P5_DETECTOR_WEIGHTS` definida, las pruebas también corren el detector real.

### PowerShell

```powershell
$env:P5_DETECTOR_WEIGHTS = "models/yolox_tiny.onnx"
.venv\Scripts\python -m pytest tests/test_casos_runner.py
```

### Linux

```bash
export P5_DETECTOR_WEIGHTS=models/yolox_tiny.onnx
.venv/bin/python -m pytest tests/test_casos_runner.py
```

## Fallo inducido

Para comprobar que una expectativa incorrecta hace fallar al runner, en una copia de `casos/c1_c10.yaml` cambia la regla de C1:

```yaml
alguna:
  - {cuadros: [3, 15], acciones: [EVADE_LEFT]}
```

C1 sale como `FALLA` y el comando termina con código 1. Una prueba lo comprueba también.

## Límites conocidos

- Las secuencias grabadas C1-C5 y C7 no interpretan el intervalo entre timestamps como silencio de una aplicación en vivo. C8 prueba la expiración temporal por separado mediante `Pipeline`, política real y un reloj determinista.
- C8, C9 y C10 usan un detector sintético, así que comprueban la reacción del sistema, no la precisión del detector real.
- Los plazos se miden en cuadros del recorrido, no en tiempo físico de frenado.
- `seq01`, `seq03` y `seq04` no tienen un tramo que cambie de libre a ocupado, y C2 y C5 empiezan con la persona ya en su lugar.
- Las expectativas se escribieron después de ver cómo se comporta el sistema en estas secuencias, durante la captura. Su base es la geometría de las etiquetas y las reglas de la política.
