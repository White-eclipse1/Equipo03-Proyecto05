# B2-02 — Watchdog y percepción vencida

Ticket: #5. Entregables: E4 y E5. Cubre C8.

## Objetivo

Detener el sistema si se pierde la percepción, incluso cuando no llega ningún cuadro nuevo, y rechazar los datos demasiado antiguos.

## Componentes

- src/p5/control/adapter.py: `is_expired`, la vigencia de cada comando y el reloj de `timestamp`.
- src/p5/integration/pipeline.py: `Pipeline.tick`, `WatchdogEvent` y el rechazo de cuadros vencidos en `Pipeline.process`.
- tests/test_watchdog.py: los límites exactos y C8 completo, con un reloj controlado.

## Reloj

El watchdog usa el reloj de la secuencia, en milisegundos, igual que `t_capture_ms`. No lee ningún reloj del sistema: quien llama le pasa la hora. Por eso C8 se reproduce igual en cada corrida y no necesita esperar.

`timestamp` del comando es otra cosa: la hora en que el adaptador lo emitió. `VirtualControlAdapter(clock=...)` permite controlarla en pruebas.

## Plazo

Hay un solo valor configurable: `vigencia_comando_ms` en `Proyecto3/config/politica.yaml`, hoy 500 ms. Se usa en dos lugares:

| Comprobación | Cuándo vence | Límite exacto |
|---|---|---|
| Comando de movimiento | `now_ms >= valid_until_ms`, que es `t_capture_ms` + vigencia | En el límite ya está vencido |
| Cuadro recibido | `now_ms - t_capture_ms >= vigencia`, o `t_capture_ms > now_ms` | En el límite ya está vencido. Con `t_capture_ms == now_ms` todavía vale |

Un reloj no finito cuenta como vencido, y un cuadro con hora futura se rechaza: sin hora confiable, lo seguro es detenerse. Si se aceptara, el comando que genera tendría una vigencia que `tick` no alcanzaría hasta esa hora futura.

## Watchdog

```python
event = pipeline.tick(now_ms)
```

- **No necesita un cuadro:** no llama al detector ni a la política para decidir.
- **Si no venció nada:** devuelve `None`.
- **Si venció un comando de movimiento:**
  - Emite STOP al adaptador con `reason_code: WATCHDOG_VENCIDO`, que reemplaza el comando anterior.
  - Reinicia la confirmación de la política: harán falta 3 cuadros libres para volver a avanzar.
  - Registra `watchdog_expired` en el log.
  - Devuelve un `WatchdogEvent` con el instante, el cuadro y la decisión que vencieron, el límite, el comando y los errores. `event.to_json()` lo deja en JSON estricto.
- **Solo actúa una vez:** después del STOP ya no hay movimiento vigente.
- **Si tampoco se puede emitir el STOP:** el recorrido hace lo mismo que en `stage=failsafe`: anula el comando y no vuelve a moverse.

## Cuadro vencido

```python
trace = pipeline.process(frame, now_ms=now_ms)
```

**Primero comprueba el comando anterior.** `process` llama a `tick`, porque un cuadro nuevo no perdona un comando vencido: si llega antes del siguiente `tick`, el vencimiento igual emite STOP con `WATCHDOG_VENCIDO` y hay que volver a confirmar la vía. El evento queda en `trace.watchdog`, que es `null` si no venció nada. El cuadro sigue su recorrido, pero su comando será STOP hasta confirmar la vía.

**Después comprueba el cuadro.** Si venció o viene del futuro:

- No pasa por el detector ni por la política: `decision` queda en `null`, y `perception` en `status: "error"`.
- Emite STOP con `reason_code: CUADRO_VENCIDO`, que cancela el comando anterior.
- Se registra con `stage=stale`.
- Hay que volver a confirmar la vía.
- Su hora no llega a la política, así que un cuadro futuro no deja a los siguientes fuera de orden.

Sin `now_ms`, `process` no comprueba el tiempo. Así funciona `python -m p5.integration`, que reproduce la secuencia sin reloj.

## C8

1. Se avanza con cuadros válidos.
2. Se dejan de entregar cuadros y avanza el reloj: `tick` no hace nada antes del límite, y en el límite emite STOP.
3. Llega un cuadro capturado una vigencia antes: se rechaza, y no reinicia el movimiento.

Las pruebas también cubren las dos variantes: un cuadro nuevo que descubre el vencimiento antes de `tick`, y un cuadro con hora futura.

`tests/test_watchdog.py` lo corre dos veces y exige el mismo resultado en todos los comandos.

Falta conectarlo al runner de #8 para que C8 deje de estar `PENDIENTE`.

## Verificación

Desde Proyecto5.

### PowerShell

```powershell
.venv\Scripts\python -m pytest tests\test_watchdog.py
```

### Linux

```bash
.venv/bin/python -m pytest tests/test_watchdog.py
```

## Hallazgo para B1 y B2: la vigencia es muy corta para el hotspot

**Con 500 ms, todos los comandos vencerían antes del siguiente cuadro.** En `p5-eval-v1`, los 122 huecos entre cuadros miden 500 ms o más: de 500 a 2843 ms. Con 1000 ms seguirían vencidos 18 huecos.

Un bucle en tiempo real que llame a `tick` con esta configuración frenaría el carro entre un cuadro y otro. Para el carro real hay que capturar más rápido, reducir los huecos del WiFi o subir la vigencia. Este cambio no ajusta `politica.yaml`, porque cambia su hash y lo decide B1.

Esto no afecta C1–C7, porque reproducen las secuencias sin `tick`.

## Límites conocidos

- **Sin bucle en tiempo real:** nada llama a `tick` por sí solo. Una aplicación en vivo debe llamarlo periódicamente, también si la captura se bloquea, y pasar `now_ms` a `process`.
- **Un reloj por recorrido:** `t_capture_ms` vuelve a empezar en cada secuencia, así que hay que usar un `Pipeline` por secuencia si se usa `tick`.
- **Motores:** nada de esto se probó con el carro: el adaptador es virtual.
- **Emergencia, rearme y cierre:** son de B2-03 (#6).
- **Reinicio de la política:** el recorrido sigue reescribiendo `memoria` desde fuera, como se declara en B3-01.
