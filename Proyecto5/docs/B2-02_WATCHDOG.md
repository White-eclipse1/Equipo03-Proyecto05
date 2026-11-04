# B2-02 — Watchdog, timeout y percepción vencida

## Objetivo

Garantizar que una pérdida de percepción detenga el sistema incluso cuando no llegue un frame nuevo.

El watchdog trabaja sobre el adaptador virtual de B2 y puede reproducirse de forma determinista mediante un reloj inyectable.

## Componentes

- `src/p5/control/models.py`: tiempos de captura y vigencia.
- `src/p5/control/adapter.py`: timeout, validación temporal y watchdog.
- `src/p5/integration/pipeline.py`: propagación de tiempos desde B1 hacia B2.
- `src/p5/casos/runner.py`: reproducción determinista de C8.
- `tests/test_virtual_control_adapter.py`: pruebas del watchdog.
- `tests/test_integration_pipeline.py`: contrato temporal B1 -> B2.
- `tests/test_casos_runner.py`: reproducción de C8.

## Contrato temporal

`ControlDecision` puede incluir `t_capture_ms` y `valid_until_ms`.

B1 produce `t_capture_ms` y `valido_hasta_ms`; el pipeline traduce este último a `valid_until_ms` para B2.

## Timeout configurable

`VirtualControlAdapter` acepta `timeout_ms`.

Cuando no existe `valid_until_ms`, pero sí `t_capture_ms`, se calcula:

`valid_until_ms = t_capture_ms + timeout_ms`

El timeout debe ser finito y mayor que cero.

## Reloj testeable

El adaptador acepta `clock_ms`, permitiendo avanzar el tiempo artificialmente sin usar `sleep()`.

## Percepción vencida

Una decisión de movimiento vencida genera STOP con:

- `speed = 0.0`
- `steering = 0.0`
- `reason_code = watchdog_timeout`

El evento queda registrado mediante logging.

## Watchdog sin nuevos cuadros

`check_watchdog()` revisa el último comando activo sin necesitar un nuevo frame.

Al vencer el movimiento genera STOP y llamadas posteriores no generan STOPs duplicados.

## Caso C8

C8 reproduce de forma determinista:

1. movimiento válido;
2. interrupción de cuadros;
3. avance del reloj;
4. STOP por watchdog sin recibir otro frame;
5. llegada de percepción vencida;
6. rechazo del movimiento vencido.

No requiere hardware ni tiempo real.

## Seguridad

`physical_output_enabled` permanece en `False`.

Una percepción vencida no puede reactivar un movimiento detenido por el watchdog.

## Verificación

Desde `Proyecto5`:

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m ruff format --check .`
- `git diff --check`
