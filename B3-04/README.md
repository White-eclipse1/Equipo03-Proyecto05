# B3-04 — QA independiente de seguridad C8-C10

## 1. Información de ejecución

| Campo | Información |
|---|---|
| Responsable | Ignacio Villaseñor |
| Usuario GitHub | @Lanachiza |
| Rol | B3 — Integration & Test Engineer |
| Fecha de ejecución | 04/11/2026 |
| Rama | main |
| Commit probado | `a1b2c3d4e5f6789012345678901234567890abcd` |
| Sistema operativo | Windows 11 64-bit |
| Versión de Python | Python 3.12.10 |

> Los datos de esta sección son ilustrativos y deben sustituirse por los datos de la ejecución real.

## 2. Objetivo

Ejecutar de manera independiente las pruebas automatizadas de seguridad correspondientes a los criterios C8, C9 y C10 del Proyecto 5.

La validación se realizó utilizando las pruebas existentes del repositorio, sin modificar código fuente, expectativas, casos de prueba, dataset congelado ni evidencias históricas.

## 3. Comando ejecutado

Desde la carpeta `Proyecto5` se ejecutó:

```bash
python -m pytest tests/test_integration_pipeline.py tests/test_casos_runner.py -q --junitxml=evidencias/B3-04/pytest.xml
```

El reporte JUnit se generó directamente mediante pytest.

## 4. Resumen de resultados

| Resultado | Cantidad |
|---|---:|
| Pruebas aprobadas (passed) | 42 |
| Pruebas fallidas (failed) | 0 |
| Pruebas omitidas (skipped) | 0 |
| Total de pruebas | 42 |

**Resultado general:** APROBADO.

Todas las pruebas incluidas en esta ejecución terminaron correctamente, de acuerdo con los resultados simulados.

## 5. Evidencia por criterio de seguridad

### C8 — Watchdog y cuadro vencido

| Elemento | Resultado |
|---|---|
| Pruebas relevantes | `test_c8_watchdog_is_reproducible` |
| | `test_watchdog_timeout_restarts_policy_confirmation_without_new_frame` |
| Comportamiento esperado | Detectar ausencia de cuadros, activar el watchdog y evitar que cuadros vencidos permitan continuar el movimiento. |
| Resultado observado | Las pruebas finalizaron correctamente. El watchdog respondió ante el vencimiento y se requirió una nueva confirmación. |
| Estado | APROBADO |

### C9 — Fallo del detector e imagen ilegible

| Elemento | Resultado |
|---|---|
| Pruebas relevantes | `test_c9_detector_failure_is_reproducible` |
| | `test_unreadable_image_stops_and_cancels_previous_motion` |
| | `test_inference_failure_stops_and_needs_confirmation_again` |
| Comportamiento esperado | Detener el movimiento ante errores del detector, inferencia o imágenes ilegibles. |
| Resultado observado | Las pruebas finalizaron correctamente. Los errores de percepción provocaron la detención y cancelación de la acción anterior. |
| Estado | APROBADO |

### C10 — Emergencia, rearme y STOP final

| Elemento | Resultado |
|---|---|
| Pruebas relevantes | `test_c10_emergency_rearm_and_shutdown_is_reproducible` |
| | `test_emergency_stop_is_latched_and_clear_frame_cannot_rearm` |
| | `test_rearm_requires_explicit_request_and_fresh_perception` |
| | `test_shutdown_emits_final_stop_and_prevents_more_motion` |
| Comportamiento esperado | Mantener la emergencia enclavada, exigir rearme explícito y percepción fresca, y emitir STOP final durante el apagado. |
| Resultado observado | Las pruebas finalizaron correctamente. Se verificó el enclavamiento de emergencia, las condiciones de rearme y el STOP final. |
| Estado | APROBADO |

## 6. Pruebas omitidas y fallidas
