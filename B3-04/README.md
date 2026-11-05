# B3-04 — QA independiente de seguridad C8-C10

Relacionado con [#45](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/45).

## 1. Datos de ejecución

| Dato | Resultado |
|---|---|
| Ejecutor | Ignacio Villaseñor |
| Fecha | [FECHA DE EJECUCIÓN] |
| Commit probado | [COMMIT COMPLETO] |
| Sistema operativo | [SISTEMA OPERATIVO] |
| Python | [VERSIÓN DE PYTHON] |
| Rama | main |

## 2. Comando ejecutado

```bash
python -m pytest tests/test_integration_pipeline.py tests/test_casos_runner.py -q --junitxml=evidencias/B3-04/pytest.xml
```

## 3. Resumen de resultados

| Resultado | Cantidad |
|---|---:|
| Pruebas aprobadas | [N] |
| Pruebas fallidas | [N] |
| Pruebas omitidas | [N] |
| Total | [N] |

## 4. Trazabilidad de seguridad

| Criterio | Pruebas relevantes | Comportamiento esperado | Resultado observado | Estado |
|---|---|---|---|---|
| C8 — Watchdog y cuadro vencido | `test_c8_watchdog_is_reproducible`, `test_watchdog_timeout_restarts_policy_confirmation_without_new_frame` | Ante la ausencia de cuadros debe activarse el watchdog, emitir STOP y rechazar cuadros vencidos. | [RESULTADO REAL] | [PASA/FALLA/OMITIDA] |
| C9 — Fallo del detector e imagen ilegible | `test_c9_detector_failure_is_reproducible`, `test_unreadable_image_stops_and_cancels_previous_motion`, `test_inference_failure_stops_and_needs_confirmation_again` | Un error de percepción o imagen ilegible debe cancelar el movimiento y emitir STOP. | [RESULTADO REAL] | [PASA/FALLA/OMITIDA] |
| C10 — Emergencia, rearme y STOP final | `test_c10_emergency_rearm_and_shutdown_is_reproducible`, `test_emergency_stop_is_latched_and_clear_frame_cannot_rearm`, `test_rearm_requires_explicit_request_and_fresh_perception`, `test_shutdown_emits_final_stop_and_prevents_more_motion` | La emergencia debe enclavarse, requerir rearme explícito y percepción fresca, y garantizar STOP al cerrar. | [RESULTADO REAL] | [PASA/FALLA/OMITIDA] |

## 5. Fallos y limitaciones

No hubo fallos

Esta ejecución utiliza las pruebas automatizadas y el adaptador virtual del proyecto.

No representa una validación física del vehículo.

- Hardware real: no probado.
- Stream de cámara en vivo: no probado.
- Pesos reales del detector: [INDICAR SI SE UTILIZARON O NO].
- Motores físicos: no probados.

Las pruebas sintéticas y las pruebas del pipeline no deben interpretarse como una validación del hardware.

## 6. Evidencia

El reporte JUnit generado por pytest se encuentra en:

`evidencias/B3-04/pytest.xml`

Este archivo contiene los resultados de la ejecución, incluyendo pruebas aprobadas, fallidas y omitidas.

## 7. Conclusión



La evidencia corresponde exclusivamente a la ejecución identificada por el commit y el entorno documentados en este archivo.
