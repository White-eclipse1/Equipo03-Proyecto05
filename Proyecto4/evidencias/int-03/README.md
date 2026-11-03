# INT-03: persistencia real en AWS y recuperación

Evidencia de que un evento recibido por la API (`POST /api/p4/capturas` del portal desplegado) queda guardado en S3, se recupera completo y sobrevive a un reinicio del portal.

**Captura usada:** `prueba-int-20261015T164022-0001`, enviada por la API el 15 oct de 2026 con [`scripts/enviar_prueba.py`](../../scripts/enviar_prueba.py) (detalle en [`../int-02/`](../int-02/)). Es una captura de prueba (`device_id=prueba-int`). Cuando el dispositivo envíe (EDGE-06), una captura real se sigue de punta a punta en INT-06.

## Criterios

| Criterio | Evidencia |
|---|---|
| El evento aparece en almacenamiento AWS real | `s3://p4-capturas-474665692638/edge-capturas/eventos/prueba-int-20261015T164022-0001.json`, VersionId `HUw1H2f3RY85bJst6kQyobzDXV_x4CcN` ([`consulta-s3.txt`](consulta-s3.txt)) |
| JPEG recuperable | `.../edge-capturas/fotos/prueba-int-20261015T164022-0001.jpg`, VersionId `AtoUfsFwsQZJ5wU_Z7CZAI9tyLPEeHvw`, 18 285 bytes, descargado |
| Registro de metadatos recuperable | Descargado de S3 y leído campo por campo en [`consulta-s3.txt`](consulta-s3.txt) |
| `capture_id`, `captured_at`, `predicted_class`, `confidence`, `device_id` y `model_version` coinciden | El registro en S3 es igual al [evento enviado](../int-02/evento.json) (`2026-10-15T16:40:22-06:00`, `dog`, `0.5`, `prueba-int`, `1.0.0-int8-e05.1`) |
| El hash de la imagen coincide | SHA-256 `229b542d…d84a` igual en el archivo descargado, en los metadatos de S3, en el `image_sha256` del evento y en la [foto local](../int-02/foto.jpg) |
| Reiniciar el portal no elimina la captura | [`reinicio-portal.txt`](reinicio-portal.txt): se **recreó** el contenedor de la app (de `36232cb10f14` a `c2b199cae24b`, que arrancó el 16 oct a las 06:01:48 UTC) y la captura sigue en el listado, con el registro idéntico antes y después y la misma foto (`229b542d…`) |
| Evidencia por consulta de lectura | [`scripts/consultar_captura.py`](../../scripts/consultar_captura.py) (`get-object`, `list-object-versions`) |
| Sin credenciales administrativas | La consulta se hizo con el usuario IAM `p4-lectura`, de solo lectura y sin llaves (ver [`../int-02/escritura-denegada.txt`](../int-02/escritura-denegada.txt)) |

Hay **una sola versión** del registro y de la foto: ni el reintento ni el conflicto de la prueba de INT-02 sobrescribieron nada. Tras el reinicio, el portal sigue pidiendo usuario (401 en `/`) y el receptor sigue exigiendo el token (`401 no_autorizado`).
