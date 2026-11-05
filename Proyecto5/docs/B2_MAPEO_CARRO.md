# B2 — Mapeo de comandos al carro

Entregable: E4. Criterio 2.3.

## Objetivo

Dejar comprobable cómo se traduciría un comando virtual al controlador del carro, con sus unidades y límites, sin activar motores.

**Esta entrega es virtual y no mueve el carro.** `route_for` solo devuelve el texto de una ruta: no abre conexiones, y `physical_output_enabled` sigue en `False`.

**El sentido físico de los giros sigue sin verificar.** `left` y `right` son los nombres de las rutas del firmware; no se ha comprobado hacia dónde gira el carro con cada una.

## Componentes

- src/p5/control/mapeo.py: `route_for`, de `ControlCommand` a ruta del firmware.
- tests/test_control_mapeo.py: rutas, límites y valores inválidos, además de los comandos reales registrados en `c1-c10-sin-filtro`.

## Controlador previsto

| Parte | Valor |
|---|---|
| Placa | ESP32-CAM AI Thinker, con cámara OV2640 |
| Motores | Driver L298N, sin control de ENA ni ENB: cada lado solo enciende o apaga |
| Rutas | HTTP GET en el puerto 80. Responden `OK` y no aceptan parámetros |
| Cámara | `/stream` en el puerto 81, un solo cliente a la vez |
| Pines | Izquierda: 14 y 2. Derecha: 13 y 15 |

El sketch no se versiona porque contiene las credenciales del WiFi.

## Mapeo

Este mapeo enlaza nombres de comandos y rutas, sin afirmar el movimiento físico:

| `direction` del comando | Ruta | Acciones de la política | Salidas del firmware (`Lf`, `Lb`, `Rf`, `Rb`) |
|---|---|---|---|
| `stop` | `/stop` | STOP | Todas en LOW |
| `forward` | `/go` | FORWARD y SLOW | HIGH, LOW, HIGH, LOW |
| `left` | `/left` | EVADE_LEFT | HIGH, LOW, LOW, HIGH |
| `right` | `/right` | EVADE_RIGHT | LOW, HIGH, HIGH, LOW |

La ruta `/back` existe en el firmware, pero la política nunca retrocede, así que no se usa.

## Unidades y límites

| Campo | Unidad | Rango aceptado | Si no se cumple |
|---|---|---|---|
| `speed` | Fracción, sin unidad | Mayor que 0 y hasta 1 | STOP, `velocidad_invalida` |
| `steering` | Fracción; negativo a la izquierda | De −1 a 1, con el signo de la dirección y 0 en `forward` | STOP, `giro_invalido` |
| `direction` | Texto | `stop`, `forward`, `left` o `right` | STOP, `direccion_invalida` |
| `valid_until_ms` | Milisegundos, en el reloj de la secuencia | Número finito | STOP, `sin_vigencia` |
| `now_ms`, obligatorio | Milisegundos, en el reloj de la secuencia | Número finito y menor que `valid_until_ms` | STOP, `reloj_invalido` o `vencido` |

**Ninguna ruta de movimiento sale sin comprobar la vigencia:** `route_for` exige `now_ms`, y omitirlo es un error. STOP no depende del reloj. Los valores no finitos también terminan en STOP. El adaptador virtual ya rechaza velocidades, giros y vigencias inválidos antes de esto; ver [B2-01_VIRTUAL_CONTROL_ADAPTER.md](B2-01_VIRTUAL_CONTROL_ADAPTER.md) y [B2-02_WATCHDOG.md](B2-02_WATCHDOG.md). `route_for` lo vuelve a comprobar porque sería la última defensa antes de los motores.

## Límites del controlador

- **Sin velocidad variable:** el L298N no recibe PWM, así que todo `speed` positivo se vuelve el mismo `/go`. **SLOW no reduciría la velocidad física.**
- **Sin giro proporcional:** `steering` solo se valida. Toda evasión gira con la fuerza completa.
- **Sin watchdog en el firmware:** `/go`, `/left` y `/right` siguen activas hasta recibir otra orden. `route_for` comprueba la vigencia solo al calcular la ruta; no detiene un movimiento ya enviado. Un cliente real tendría que enviar `/stop` al vencer el comando, y una caída del WiFi lo impediría. Por eso, sin una parada en la placa, este mapeo no basta para operar el carro. Es una limitación documentada de esta entrega virtual.
- **Sentido de giro:** con los nombres del sketch, `/left` adelanta el lado izquierdo y retrasa el derecho, lo que giraría a la derecha. Sus comentarios no coinciden entre sí, y **no se ha probado con las ruedas levantadas**. Hay que comprobarlo antes de conectar el mapeo a los motores.
- **Sin prueba física:** nada de este documento se ejecutó contra el carro. Es una limitación documentada de esta entrega virtual.

## Verificación

Desde Proyecto5.

### PowerShell

```powershell
.venv\Scripts\python -m pytest tests\test_control_mapeo.py
```

### Linux

```bash
.venv/bin/python -m pytest tests/test_control_mapeo.py
```
