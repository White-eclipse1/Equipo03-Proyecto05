# B2-01 — Adaptador virtual de comandos

## Objetivo

Implementar un adaptador de control que reciba decisiones de movimiento y genere comandos estructurados sin activar motores físicos.

El adaptador puede utilizarse durante pruebas e integración offline.

## Componentes

- src/p5/control/models.py: Action, ControlDecision y ControlCommand.
- src/p5/control/adapter.py: VirtualControlAdapter.
- tests/test_virtual_control_adapter.py: pruebas de comportamiento y seguridad.

## Decisiones soportadas

- STOP
- FORWARD
- LEFT
- RIGHT

Cada decisión incluye acción, velocidad solicitada, frame_id, decision_id y reason_code.

De forma opcional puede incluir `requested_steering`, en [-1, 1] con negativo a la izquierda. Sin él, LEFT y RIGHT usan el giro completo (-1.0 y 1.0).

## Comando generado

Cada salida contiene speed, direction, steering, timestamp, frame_id, decision_id y reason_code.

## Reglas de seguridad

STOP siempre produce speed = 0.0, direction = stop y steering = 0.0.
Un STOP reemplaza el último comando activo.
Las velocidades de movimiento deben ser finitas y estar dentro del rango 0.0 a 1.0. Los valores inválidos son rechazados.
`requested_steering` debe ser finito, estar en [-1, 1] y coincidir con la acción: negativo en LEFT, positivo en RIGHT y 0.0 en FORWARD. Los valores inválidos son rechazados. STOP lo ignora.

## Motores físicos

El adaptador es virtual y physical_output_enabled permanece en False.
No existe activación de motores físicos en B2-01.

## Registro

Cada comando queda en el historial del adaptador, se guarda como last_command y genera un evento mediante logging.

`cancel()` deja last_command en None sin generar un comando. Es el último recurso cuando un STOP no se pudo emitir. El comando anulado queda en cancelled, no en el historial, que solo guarda comandos emitidos, y genera un evento `virtual_control_cancel` en el log.

## Integración

El recorrido de B3-01 convierte la decisión de la política en `ControlDecision`. Ver [B3-01_RECORRIDO.md](B3-01_RECORRIDO.md).

## Verificación

Desde Proyecto5 ejecutar:

python -m pytest
python -m ruff check .
python -m ruff format --check .
