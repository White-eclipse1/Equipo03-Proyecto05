# INT-08: ficha final, paquete de evidencias y preparación de la evaluación

Cierre del P4. La ficha de entrega es [`README.md`](../../README.md), el índice de evidencias es [`evidencias/README.md`](../README.md) y el guion de la demostración es [`docs/guion-demo.md`](../../docs/guion-demo.md).

**Lo que no se hizo, por decisión del equipo:** el **simulacro** de 10–15 minutos y la **reproducción del runbook de EDGE-08 por un integrante distinto de Omar**. No hubo tiempo de reunir al equipo con la Raspberry antes de la entrega, así que todo lo del dispositivo lo operó Omar. La evidencia del dispositivo es la de su propio ensayo ([`EDGE-08/`](../EDGE-08/)), y no se atribuye a nadie más. Los criterios que dependen de esto están marcados abajo como **no realizados**.

## Ficha de entrega

| Criterio | Dónde (en [`README.md`](../../README.md)) |
|---|---|
| Equipo y roles | "Equipo" |
| Dispositivo y cámara; sistema operativo y runtime | "Dispositivo": Raspberry Pi 4 Model B, POCO C65 con IP Webcam por USB, Debian 13 aarch64, Python 3.13.5, onnxruntime 1.31.0 |
| Modelo original y optimizado, con sus SHA-256 | "Modelo": `1.0.0` (`e4acca42…9172`) y `1.0.0-int8-e05.1` (`ba89ee43…2a12`) |
| Técnica INT8 | "Modelo": cuantización estática QDQ, pesos INT8 por canal, activaciones UINT8 y calibración con 300 recortes de train |
| Comandos de instalación y de arranque | "Reproducir": portal en AWS ([`despliegue.md`](../../docs/despliegue.md)) y dispositivo ([`edge08-runbook.md`](../../docs/edge08-runbook.md) y los comandos de `eventos.py` y `enviar.py`) |
| URL del portal y ruta de Capturas Edge | "Accesos": https://54-80-197-58.sslip.io → **Capturas Edge** (`#/capturas-edge`) |
| Referencias a las evidencias | "Comprobaciones repetibles" y el [índice](../README.md) |

## Puertas M1, M2 y M3

| Puerta | Evidencia |
|---|---|
| **M1:** el modelo del P3 `1.0.0` está identificado y la conversión es demostrable | Linaje de 20 comprobaciones sin fallas ([`linaje-modelo.md`](../../docs/linaje-modelo.md), VAL-01) y conversión reproducible con SHA-256 ([`modelo-optimizado.md`](../../docs/modelo-optimizado.md)). La variante final es `1.0.0-int8-e05.1`: el nombre `1.0.0-int8.1` del texto del issue era una variante anterior ([`edge03-inferencia.md`](../../docs/edge03-inferencia.md)) |
| Mapa de clases y preprocesamiento iguales | `cat`, `dog`, `person` en el mismo orden. El tensor preprocesado en la Raspberry es **idéntico bit a bit** al offline en 295 entradas ([`preprocesamiento-edge.md`](../../docs/preprocesamiento-edge.md), VAL-07) |
| **M2:** cámara física, inferencia local, sin red y versión visible | [`EDGE-02/`](../EDGE-02/) a [`EDGE-04/`](../EDGE-04/) y [`EDGE-08/`](../EDGE-08/): fotos nuevas de la cámara, inferencia con `CPUExecutionProvider`, dos capturas sin Internet con la misma sesión y `modelo_cargado` con versión y SHA-256 |
| **M3:** captura nueva en AWS, recuperable, en Capturas Edge y con el mismo `capture_id` | [`int-06/`](../int-06/): una captura física seguida por ID de la Raspberry a S3 y al portal. [`operacion/`](../operacion/): 24 capturas del dispositivo en S3 y en el portal |

## Evidencia de operación

| Criterio | Evidencia |
|---|---|
| 20 capturas disponibles | **24** de `edge01` en S3 y en Capturas Edge (13 `cat`, 7 `person`, 4 `dog`), verificadas contra la Raspberry: [`operacion/`](../operacion/) |
| Cinco minutos de operación | Serie continua de 21 capturas en 326.52 s, sin fallos ([`edge07-operacion.md`](../../docs/edge07-operacion.md)) |
| Reinicio | Proceso nuevo con recarga del modelo y una captura nueva, la misma configuración y el historial conservado (EDGE-07 y EDGE-08) |
| Falla y reintento | 3 fallas de red, luego `201` y `200 duplicado` con el mismo `capture_id` ([`int-04/`](../int-04/)) |
| Sin duplicados tras el reintento | Una sola versión del registro y de la foto en S3, para las 24 capturas del dispositivo |

## Evidencia del modelo

| Criterio | Evidencia |
|---|---|
| Predicciones del original y del INT8 por muestra | [`VAL-08/validacion/predicciones_val.csv`](../VAL-08/validacion/predicciones_val.csv), con el INT8 ejecutado en la Raspberry |
| Accuracy y F1 recalculables | `python recalcular.py` en [`VAL-08/`](../VAL-08/) → `VERIFICADO`: 99.658 % → 99.315 % (−0.34 pp) |
| Tiempos crudos del benchmark | [`VAL-05/tiempos.csv`](../VAL-05/tiempos.csv): 10 calentamientos y 200 mediciones por modelo en la Raspberry |
| p50/p95 recalculables | `python validacion/recursos.py` ([`recursos-edge.md`](../../docs/recursos-edge.md)): p50 190.11 → 113.51 ms y p95 191.52 → 114.34 ms |

## Preparación de la evaluación

| Criterio | Resultado |
|---|---|
| Simulacro de 10–15 minutos | **No realizado** (decisión del equipo, por tiempo) |
| El presentador no necesita improvisar comandos | El [guion](../../docs/guion-demo.md) tiene cada paso con su responsable y su comando, y [`fallo-reintento.md`](../../docs/fallo-reintento.md) tiene el procedimiento de falla probado. **No se ensayó** en conjunto |
| Portal probado | 17 oct, 03:50 UTC: Capturas Edge muestra las 26 capturas ([`operacion/portal-capturas-edge.webp`](../operacion/portal-capturas-edge.webp)). Sin usuario responde `401` ([`comprobaciones.txt`](comprobaciones.txt)) |
| Dispositivo probado | Omar, 17 oct a las 03:35 UTC: envío de las 22 capturas de EDGE-07, todas `201` y verificadas en S3. Ensayo del runbook el 16 oct ([`EDGE-08/`](../EDGE-08/)). La reproducción por otro integrante **no se realizó** |
| Acceso de lectura a AWS probado | [`comprobaciones.txt`](comprobaciones.txt): identidad `p4-lectura`, escritura denegada (`AccessDenied`) y 24 eventos de `edge01`; además, las 22 consultas de [`operacion/verificacion-s3.txt`](../operacion/verificacion-s3.txt) |
| Todos los enlaces del paquete abren | [`scripts/verificar_enlaces.py`](../../scripts/verificar_enlaces.py): 35 documentos y 0 enlaces rotos. El CI lo repite en `tests/test_enlaces.py` |

[`comprobaciones.txt`](comprobaciones.txt) también registra que el receptor sin token responde `401 no_autorizado`.

## Sin secretos

Ningún archivo del paquete contiene el token del dispositivo, contraseñas, llaves de AWS ni URLs firmadas. La búsqueda de patrones de llaves y tokens en `Proyecto4/` solo encontró nombres de parámetros en el código, y gitleaks corre en el CI. La contraseña del evaluador se entrega por canal privado ([`acceso-evaluacion.md`](../../docs/acceso-evaluacion.md)).

## Después de la evaluación

Borrar el usuario IAM `p4-lectura`, apagar o terminar la EC2 y liberar la IP elástica ([`despliegue.md`](../../docs/despliegue.md), "Costo y apagado").
