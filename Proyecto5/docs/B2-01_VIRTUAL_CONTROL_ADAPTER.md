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

## Comando generado

Cada salida contiene speed, direction, steering, timestamp, frame_id, decision_id y reason_code.

## Reglas de seguridad

STOP siempre produce speed = 0.0, direction = stop y steering = 0.0.
Un STOP reemplaza el último comando activo.
Las velocidades de movimiento deben ser finitas y estar dentro del rango 0.0 a 1.0. Los valores inválidos son rechazados.

## Motores físicos

El adaptador es virtual y physical_output_enabled permanece en False.
No existe activación de motores físicos en B2-01.

## Registro

Cada comando queda en el historial del adaptador, se guarda como last_command y genera un evento mediante logging.

## Compatibilidad con integración

ControlDecision representa actualmente la frontera local de B2.
El contrato definitivo de B1 podrá adaptarse posteriormente sin modificar las reglas de seguridad.

## Verificación

Desde Proyecto5 ejecutar:

python -m pytest
python -m ruff check .
python -m ruff format --check .

## Pendiente

La integración del adaptador con la salida real de la política B1 todavía está pendiente.
Este avance implementa y valida la base del adaptador virtual.

Resultado actual: 15 pruebas automatizadas pasando.


