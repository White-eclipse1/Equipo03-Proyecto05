# INT-05: Capturas Edge con datos reales de AWS y actualización

Evidencia de que la página **Capturas Edge** del portal desplegado (`https://54-80-197-58.sslip.io`, usuario `evaluador`) muestra lo que está guardado en S3 y que se actualiza al llegar una captura nueva.

**Capturas usadas:** las dos son de prueba (`device_id=prueba-int`), enviadas por la API con [`scripts/enviar_prueba.py`](../../scripts/enviar_prueba.py):

- `prueba-int-20261015T164022-0001`: la de INT-02/INT-03.
- `prueba-int-20261016T005939-0001`: enviada el 16 oct de 2026 a las 06:59:43 UTC **con la página ya abierta**, para probar la actualización.

Cuando el dispositivo envíe capturas (EDGE-06), una captura real se sigue de punta a punta en INT-06.

## Recorrido

1. [`01-portal-una-captura.png`](01-portal-una-captura.png): Capturas Edge abierta con **1 captura(s)**, "Actualizada 12:58:40 AM" (hora local, UTC-06:00).
2. Con la página abierta se envió la captura nueva: las 6 pruebas del contrato dieron `201`, `200 duplicado`, `409`, `422`, `401` y el reintento conservó `received_at`.
3. [`02-portal-dos-capturas.png`](02-portal-dos-capturas.png): sin recargar el navegador, la página muestra **2 captura(s)** y la nueva va **arriba**. Dice "Actualizada 1:01:09 AM".
4. [`consulta-s3.txt`](consulta-s3.txt): la captura nueva se consultó en S3 con el usuario de solo lectura `p4-lectura`. Resultado `OK`: una sola versión del registro y de la foto, y el SHA-256 de la foto es igual en el archivo, en S3 y en el evento.

## Portal contra AWS (captura nueva)

| Portal (captura 2) | S3 ([`consulta-s3.txt`](consulta-s3.txt)) |
|---|---|
| ID `prueba-int-20261016T005939-0001` | `capture_id` igual |
| Foto: imagen de prueba con ese ID | `edge-capturas/fotos/prueba-int-20261016T005939-0001.jpg`, VersionId `eVpJrcV3ldZfhW86h3_CRWqPhxX0_4fS`, SHA-256 `aeff07d6…9002` |
| `dog` | `predicted_class: dog` |
| 50.0 % | `confidence: 0.5` |
| Capturada 2026-10-16 00:59:39 (UTC-06:00) | `captured_at: 2026-10-16T00:59:39-06:00` (se respeta la zona del dispositivo) |
| Recibida 2026-10-16 06:59:43 (UTC) | `received_at: 2026-10-16T06:59:43.941+00:00` |
| Dispositivo `prueba-int` | `device_id: prueba-int` |
| Modelo `1.0.0-int8-e05.1`, `ba89ee435c…` | `model_version: 1.0.0-int8-e05.1`, `model_sha256: ba89ee435c…2a12` |
| Sin recorte | `region: null` (foto completa) |

La captura de ayer también coincide campo por campo con su registro en S3 ([`../int-03/consulta-s3.txt`](../int-03/consulta-s3.txt)): `dog`, 50.0 %, 2026-10-15 16:40:22 (UTC-06:00), recibida 22:40:25 UTC.

## Criterios

| Criterio | Evidencia |
|---|---|
| Está dentro de la navegación del portal previo, no es una galería aislada | En las capturas de pantalla, **Capturas Edge** es una entrada más del menú lateral del portal, entre Inference y Settings, junto a las páginas de P2 y P3. Prueba `app-nav.test.tsx`: "aparece en el menú después de Inference y abre su página" |
| Muestra foto, clase, confianza, fecha, `capture_id`, `device_id` y versión del modelo | Capturas de pantalla y tabla de arriba. Prueba "muestra cada captura con foto y metadatos" |
| Muestra la región cuando aplica | Estas capturas son de foto completa (`region: null`), así que no hay recorte que dibujar. Prueba "dibuja el recorte en porcentajes de la foto": recuadro sobre la foto y fila **Recorte** `x,y · ancho×alto` |
| Ordena de la más reciente a la más antigua | Captura 2: la de 2026-10-16 va antes que la de 2026-10-15. El backend ordena por `captured_at` en UTC (`test_listado_de_mas_reciente_a_mas_antigua_en_utc`) y la página respeta ese orden ("en el orden del backend") |
| Actualizar trae capturas nuevas | Paso 3 del recorrido. Prueba "Actualizar trae la captura nueva arriba" |
| La actualización automática funciona | Casilla **cada 30 s**, activada por defecto (se ve en las capturas de pantalla). Prueba "cada 30 s vuelve a pedir la lista; al desmarcarlo deja de hacerlo" |
| El estado de carga es visible | "Cargando capturas…" en la primera carga y botón **Actualizando…** desactivado mientras llega la respuesta. Prueba "muestra Cargando mientras llega la primera respuesta" |
| La lista vacía tiene un mensaje útil | "Todavía no hay capturas. Aparecerán aquí en cuanto el dispositivo envíe la primera." Prueba "lista vacía con un mensaje útil" |
| El error de la API tiene un mensaje útil | En la primera carga: "No se pudieron cargar las capturas." con el detalle. Con el almacén sin configurar (503): "Capturas no disponibles: …, revisa la configuración del receptor (P4_*)". Si una actualización falla (incluido un 503), se **conserva la última lista** con el aviso "No se pudo actualizar: …". Hay cuatro pruebas de estos casos |
| Los datos coinciden con AWS | Tabla de arriba, comparada con la consulta de solo lectura en S3 |

Las pruebas de la página están en [`Proyecto2/web/tests/capturas-edge.test.tsx`](../../../Proyecto2/web/tests/capturas-edge.test.tsx) y [`app-nav.test.tsx`](../../../Proyecto2/web/tests/app-nav.test.tsx), y las del backend en [`Proyecto4/tests/test_consulta.py`](../../tests/test_consulta.py). Los estados vacío y de error se prueban con respuestas simuladas, no en el portal desplegado: para verlos ahí habría que borrar capturas de S3 o romper la configuración del receptor en producción.

Las capturas de pantalla no muestran contraseñas ni tokens: el navegador ya tenía la sesión de `evaluador` y el token del dispositivo se lee de Parameter Store dentro del script.
