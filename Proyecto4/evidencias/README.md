# Evidencias del Proyecto 4

Índice de la evidencia que pide la rúbrica ([`docs/rubrica.md`](../docs/rubrica.md), "Entrega solicitada al equipo"), con el estado de cada pieza. ✅ = en el repo o en AWS, verificable. ⏳ = pendiente, con su responsable y su issue.

**Sin secretos:** ningún archivo de esta carpeta contiene tokens, contraseñas, llaves de AWS ni URLs firmadas. Antes de entregar se vuelve a revisar (INT-07 / INT-08), además de gitleaks en el CI.

## Evidencia solicitada

| Evidencia | Dónde | Estado |
|---|---|---|
| Ficha de entrega y README | [`../README.md`](../README.md) | ✅ con el dispositivo (EDGE-01), los comandos de captura, envío y sin red, y el runbook de EDGE-08 ([`../docs/edge08-runbook.md`](../docs/edge08-runbook.md)) |
| Identificación del modelo del P3 | [`../docs/linaje-modelo.md`](../docs/linaje-modelo.md), [`../modelo/registros/linaje_verificacion.json`](../modelo/registros/linaje_verificacion.json) | ✅ VAL-01 |
| Variante optimizada | [`../docs/modelo-optimizado.md`](../docs/modelo-optimizado.md), [`../modelo/registros/registro_conversion.json`](../modelo/registros/registro_conversion.json); archivo en `s3://p4-capturas-474665692638/modelos/clasificador-edge/1.0.0-int8-e05.1/` | ✅ |
| Comparación de calidad (predicciones por muestra, accuracy y F1) | Predicciones por muestra del original y del INT8 sobre las 292 de `val`: [`../validacion/resultados/predicciones_val.csv`](../validacion/resultados/predicciones_val.csv), verificador [`../validacion/verificar_predicciones.py`](../validacion/verificar_predicciones.py) y [`../docs/comparacion-modelos.md`](../docs/comparacion-modelos.md) (VAL-02, VAL-03); métricas por clase y errores: [`../validacion/resultados/metricas_val.csv`](../validacion/resultados/metricas_val.csv) y [`../docs/metricas-val.md`](../docs/metricas-val.md) (VAL-04); INT8 en la Raspberry con preprocesamiento bit a bit ([`VAL-07/`](VAL-07/)). Paquete recalculable: [`VAL-08/`](VAL-08/) (`python recalcular.py` → `VERIFICADO`) | ✅ |
| Comparación de recursos (tamaños, más de 100 tiempos tras 10 calentamientos, p50/p95) | Tamaños ✅ en la ficha del modelo. Tiempos ✅ en la Raspberry: 10 calentamientos + 200 mediciones del INT8 y del FP32 en [`VAL-05/`](VAL-05/) y [`../docs/benchmark-edge.md`](../docs/benchmark-edge.md) (VAL-05). p50/p95 y comparación: [`../validacion/resultados/recursos_edge.json`](../validacion/resultados/recursos_edge.json) y [`../docs/recursos-edge.md`](../docs/recursos-edge.md) (VAL-06) | ✅ |
| Capturas de operación (20 eventos repartidos entre las clases) | **24** capturas de `edge01` en S3 y en Capturas Edge (13 `cat`, 7 `person`, 4 `dog`), verificadas contra la Raspberry, con la exportación CSV del portal: [`operacion/`](operacion/) | ✅ |
| Evidencia de AWS | [`../docs/despliegue.md`](../docs/despliegue.md), [`../docs/acceso-evaluacion.md`](../docs/acceso-evaluacion.md), [`../scripts/consultar_captura.py`](../scripts/consultar_captura.py) | ✅ con capturas de prueba ([`int-03/`](int-03/), [`int-05/`](int-05/)) y con una captura del dispositivo seguida hasta S3 y el portal ([`int-06/`](int-06/)) |
| Acceso al portal | https://54-80-197-58.sslip.io → Capturas Edge, usuario `evaluador` | ✅ |
| Demostración funcional | Guion: [`../docs/guion-demo.md`](../docs/guion-demo.md); runbook del dispositivo: [`../docs/edge08-runbook.md`](../docs/edge08-runbook.md) y su ensayo en [`EDGE-08/`](EDGE-08/). Simulacro y reproducción por otro integrante **no realizados**, por decisión del equipo ([`int-08/`](int-08/)) | 🟡 |
| Video opcional | No se entrega: es opcional en la rúbrica | — |

## Requisitos mínimos

| Requisito | Evidencia | Estado |
|---|---|---|
| **M1:** la variante procede del modelo del P3 | Linaje verificado: 20 comprobaciones, 0 fallas (VAL-01); conversión reproducible con SHA-256 de entrada y salida | ✅ listo para mostrar |
| **M2:** clasificación local en un dispositivo físico con cámara | Dispositivo, cámara y modelo verificados en la Raspberry ([`EDGE-01/`](EDGE-01/)), captura física ([`EDGE-02/`](EDGE-02/)), inferencia INT8 local con las tres clases ([`EDGE-03/`](EDGE-03/)) y clasificación con la red desconectada ([`EDGE-04/`](EDGE-04/)) | ✅ |
| **M3:** fotos nuevas en AWS y en Capturas Edge | Receptor y portal desplegados. Con capturas de prueba: persistencia en S3 y reinicio del portal ([`int-03/`](int-03/)), y Capturas Edge con datos de AWS y actualización ([`int-05/`](int-05/)). Con una captura física de la Raspberry, la misma por ID en el dispositivo, S3 y el portal ([`int-06/`](int-06/)); falla de red y reintento sin duplicado ([`int-04/`](int-04/)) | ✅ |

## Carpetas

| Carpeta | Issue | Contenido |
|---|---|---|
| [`EDGE-01/`](EDGE-01/) | EDGE-01 (#5) | Hardware y runtime de la Raspberry, foto nueva de la cámara, hash del modelo local y montaje físico |
| [`EDGE-02/`](EDGE-02/) | EDGE-02 | Captura física con la cámara: modo manual, por intervalo, sin red y con error |
| [`EDGE-03/`](EDGE-03/) | EDGE-03 | Inferencia INT8 en la Raspberry con una foto por clase y sus dependencias |
| [`EDGE-04/`](EDGE-04/) | EDGE-04 (#10) | Clasificación local con Wi-Fi y Ethernet desconectados: registros de red antes y después, capturas y su log |
| [`EDGE-05/`](EDGE-05/) | EDGE-05 (#11) | Capturas con inferencia local, eventos del contrato y su log |
| [`EDGE-06/`](EDGE-06/) | EDGE-06 (#12) | Envío al receptor: log, prueba de conflicto y capturas de la Terminal |
| [`VAL-05/`](VAL-05/) | VAL-05 (#17) | Benchmark en la Raspberry: tiempos crudos (CSV), condiciones del dispositivo y captura de la Terminal |
| [`int-02/`](int-02/) | INT-02 (#4) | Prueba del contrato contra el receptor desplegado: 5 respuestas, consulta en S3 y foto de prueba |
| [`int-03/`](int-03/) | INT-03 (#15) | Captura persistida en S3, recuperada con un usuario de solo lectura y que sobrevive al reinicio del portal |
| [`int-04/`](int-04/) | INT-04 (#16) | Falla de red y reintento desde la Raspberry con el mismo ID, duplicado y conflicto; guía para repetirlo |
| [`int-05/`](int-05/) | INT-05 (#21) | Capturas Edge en el portal desplegado: antes y después de una captura nueva, comparada campo por campo con S3 |
| [`int-06/`](int-06/) | INT-06 (#22) | Una captura física seguida por ID de la Raspberry a S3 y a Capturas Edge |
| [`EDGE-07/`](EDGE-07/) | EDGE-07 (#20) | Serie de 21 capturas en 326 s sin fallos, reinicio con recarga del modelo y una captura nueva; historial de 22 eventos |
| [`EDGE-08/`](EDGE-08/) | EDGE-08 (#23) | Ensayo del runbook: entorno, captura, envío, sin red, reconexión y reinicio |
| [`VAL-07/`](VAL-07/) | VAL-07 (#19) | Preprocesamiento y predicciones del INT8 en la Raspberry contra la laptop |
| [`VAL-08/`](VAL-08/) | VAL-08 (#24) | Paquete recalculable de calidad y recursos, con `SHA256SUMS.txt` |
| [`operacion/`](operacion/) | INT-08 (#26) | 24 capturas del dispositivo verificadas en S3, captura de pantalla de Capturas Edge y exportación CSV |
| [`int-08/`](int-08/) | INT-08 (#26) | Criterios del cierre, comprobaciones previas a la entrega y lo no realizado |
