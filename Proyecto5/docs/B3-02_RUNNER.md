# B3-02 â€” Runner de casos C1â€“C10

Ticket: #8. Entregable: E5.

## Objetivo

Reproducir con un comando los diez casos que pide la evaluaciÃ³n, guardar cada resultado y terminar con error si uno no se cumple.

## Estado

| Caso | Entrada | Estado actual |
|---|---|---|
| C1â€“C5 y C7 | Secuencias de `p5-eval-v1` con el detector real | Se ejecutan |
| C6 | Detecciones sintÃ©ticas del caso de B1 | Se ejecuta |
| C8 | Corte de cuadros y cuadro vencido | Se ejecuta con reloj determinista y watchdog de B2 |
| C9 y C10 | Fallo del detector, emergencia, rearme y cierre | **Pendiente de #6** |

Los comandos todavÃ­a no pasan por el adaptador: el runner compara las decisiones de la polÃ­tica, hasta que #7 integre el recorrido. Por eso #8 sigue abierto.

## Componentes

- src/p5/casos/runner.py: el runner.
- casos/c1_c10.yaml: entradas, expectativas y plazos de cada caso.
- tests/test_casos_runner.py: pruebas del runner, incluido el fallo inducido.

## Uso

Desde Proyecto5, despuÃ©s de la preparaciÃ³n de A1-01_DETECTOR.md. La polÃ­tica vive en Proyecto3, asÃ­ que hay que incluirla en `PYTHONPATH`.

### PowerShell

```powershell
$env:PYTHONPATH = "src;../Proyecto3/src"
.venv\Scripts\python -m p5.casos.runner --cases casos/c1_c10.yaml --config ../Proyecto3/config/politica.yaml --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --output <carpeta-nueva>
```

Para ver el cÃ³digo de salida, corre `$LASTEXITCODE` justo despuÃ©s.

### Linux

```bash
export PYTHONPATH="src:../Proyecto3/src"
.venv/bin/python -m p5.casos.runner \
  --cases casos/c1_c10.yaml \
  --config ../Proyecto3/config/politica.yaml \
  --dataset data/p5-eval-v1 \
  --weights models/yolox_tiny.onnx \
  --output <carpeta-nueva>
```

Para ver el cÃ³digo de salida, corre `echo $?` justo despuÃ©s.

Corre en CPU, sin red ni hardware: nunca llama a las rutas de motores.

Sale con cÃ³digo 1 si un caso falla o sigue pendiente, y con 0 solo si pasan los diez. No sobrescribe una carpeta existente.

## Resultados

| Archivo | Contenido |
|---|---|
| `resultados.json` | La ejecuciÃ³n (commit, hashes del modelo, manifiesto y configuraciÃ³n, umbrales, entorno) y, por caso: entrada, estado inicial, expectativa, resultado, fallos y decisiones |
| `decisiones.jsonl` | Una decisiÃ³n por lÃ­nea, con su caso, cuadro, detecciones, estado, razÃ³n y vigencia |

## CÃ³mo se decide un caso

**Sin fuga de etiquetas:** la percepciÃ³n solo recibe `sequence_id`, `frame_id`, `image`, `t_capture_ms` y las dimensiones. `annotations`, `road_state` y `allowed_actions` se usan despuÃ©s, para comparar.

**Cada cuadro:** la acciÃ³n debe estar en `allowed_actions` del manifiesto.

**Reglas por caso:**

| Regla | QuÃ© exige | Para quÃ© |
|---|---|---|
| `alguna` | Al menos una de esas acciones en el rango | Que detenerse siempre no apruebe C1, C3, C4 ni C7 |
| `reaccion` | Una de esas acciones con la vÃ­a en `BLOCKED`, dentro del plazo. `plazo_cuadros` incluye el cuadro `desde`: plazo 2 desde el cuadro 30 son los cuadros 30 y 31 | Que el STOP de arranque no cuente como reacciÃ³n |
| `direccion_min`, `direccion_max` | LÃ­mites de la direcciÃ³n en toda la secuencia | Comprobar el signo en C3 y C4 |

**Fallos de percepciÃ³n:** si la percepciÃ³n lanza una excepciÃ³n, el cuadro pasa a `status: "error"` y la polÃ­tica detiene el carro. Nunca se toma como escena vacÃ­a.

**ComprobaciÃ³n de las expectativas:** las pruebas corren C1â€“C5 y C7 con las etiquetas como si fueran un detector perfecto, y todos pasan. Si uno fallara ahÃ­, el error estarÃ­a en la expectativa, no en el sistema.

## Ãšltima corrida

Con YOLOX-Tiny sobre `p5-eval-v1`: **5 pasan, 2 fallan y 3 pendientes.** Estos son fallos reales del sistema, y no deben corregirse cambiando las expectativas:

| Caso | Cuadros | Observado | Por quÃ© es un fallo |
|---|---|---|---|
| C5 | `seq05` 8, 9 y 10 | `EVADE_RIGHT` | Hay una persona a la derecha |
| C7 | `seq06` 36 y 38 | `FORWARD` | Hay una persona al centro |
| C7 | `seq06` 30 y 31 | Solo `SLOW`, sin `BLOCKED` | No confirma el bloqueo dentro del plazo de 2 cuadros |

En C5 y C7 el detector pierde a la persona en cuadros alternos, y la polÃ­tica necesita 2 cuadros firmes seguidos para bloquear. Se debe ajustar con `p5-ajuste-v1`, no con estas secuencias.

## VerificaciÃ³n

Con `P5_DETECTOR_WEIGHTS` definida, las pruebas tambiÃ©n corren el detector real.

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

C1 sale como `FALLA` y el comando termina con cÃ³digo 1. Una prueba lo comprueba tambiÃ©n.

## LÃ­mites conocidos

- Las secuencias reales se comparan solo con decisiones de la polÃ­tica, sin el adaptador, hasta #7.
- Los plazos se miden en cuadros del recorrido, no en tiempo fÃ­sico de frenado.
- `seq01`, `seq03` y `seq04` no tienen un tramo que cambie de libre a ocupado, y C2 y C5 empiezan con la persona ya en su lugar.
- Las expectativas se escribieron despuÃ©s de ver cÃ³mo se comporta el sistema en estas secuencias, durante la captura. Su base es la geometrÃ­a de las etiquetas y las reglas de la polÃ­tica.

## Pendiente

- C8: #5.
- C9 y C10: #6.
- Pasar los comandos por el adaptador: #7.
