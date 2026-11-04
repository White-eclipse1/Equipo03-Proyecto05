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
| Cuadro recibido | `now_ms - t_capture_ms >= vigencia` | En el límite ya está vencido |

Un reloj no finito cuenta como vencido: sin hora confiable, lo seguro es detenerse.

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

Si el cuadro ya venció:

- No pasa por el detector ni por la política: `decision` queda en `null`, y `perception` en `status: "error"`.
- Emite STOP con `reason_code: CUADRO_VENCIDO`, que cancela el comando anterior.
- Se registra con `stage=stale`.
- Hay que volver a confirmar la vía.

Sin `now_ms`, `process` no comprueba la antigüedad. Así funciona `python -m p5.integration`, que reproduce la secuencia sin reloj.

## C8

1. Se avanza con cuadros válidos.
2. Se dejan de entregar cuadros y avanza el reloj: `tick` no hace nada antes del límite, y en el límite emite STOP.
3. Llega un cuadro capturado una vigencia antes: se rechaza, y no reinicia el movimiento.

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

- **Sin bucle en tiempo real:** nada llama a `tick` por sí solo. Una aplicación en vivo debe llamarlo periódicamente, también si la captura se bloquea.
- **Un reloj por recorrido:** `t_capture_ms` vuelve a empezar en cada secuencia, así que hay que usar un `Pipeline` por secuencia si se usa `tick`.
- **Motores:** nada de esto se probó con el carro: el adaptador es virtual.
- **Emergencia, rearme y cierre:** son de B2-03 (#6).
- **Reinicio de la política:** el recorrido sigue reescribiendo `memoria` desde fuera, como se declara en B3-01.
