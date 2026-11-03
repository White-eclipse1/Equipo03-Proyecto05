# INT-02: prueba del contrato contra el receptor desplegado

**Fecha:** 15 de octubre de 2026, 16:40 (UTC-06:00)

**Receptor:** `https://54-80-197-58.sslip.io/api/p4/capturas`, en la EC2 `i-06a5651301e9b6c39` de la cuenta `474665692638`.

**Comando**, desde la raíz del repo, en PowerShell:

```powershell
.\Proyecto2\.venv\Scripts\python.exe Proyecto4\scripts\enviar_prueba.py --profile p4-equipo
```

[`scripts/enviar_prueba.py`](../../scripts/enviar_prueba.py) hace lo que hará el dispositivo:

1. Guarda la foto y el evento **antes** de enviar.
2. Lee el token de Parameter Store; nunca lo imprime ni lo guarda.
3. Comprueba cada respuesta del [contrato](../../docs/contrato-capturas.md).

La foto es una imagen sintética que dice "PRUEBA DEL CONTRATO", no una captura de cámara. Se envió con `device_id=prueba-int` para distinguirla de las del dispositivo.

## Resultado ([`resultado.json`](resultado.json))

| Caso | Esperado | Obtenido |
|---|---|---|
| 1. Evento válido | 201 `creado` | ✅ 201 `creado` |
| 2. El mismo evento otra vez (reintento) | 200 `duplicado` | ✅ 200 `duplicado`, con el mismo `received_at` del primer envío |
| 3. Mismo `capture_id` con otra clase | 409 `conflicto_capture_id` | ✅ 409 |
| 4. `captured_at` sin zona horaria | 422 `evento_invalido` | ✅ 422 |
| 5. Sin token | 401 `no_autorizado` | ✅ 401 |

Después de la revisión del PM, el script comprueba también, como caso 6, que el reintento devuelva el `received_at` del primer envío. En esta corrida ya coincidían: `2026-10-15T22:40:25.035+00:00` en los casos 1 y 2 de `resultado.json`.

El token real ahora solo se envía a la URL del receptor desplegado: con otra `--url` el script se detiene, salvo con `--token-de-entorno` y un token de prueba. `tests/test_enviar_prueba.py` lo prueba en CI, junto con los 6 casos, contra el receptor en memoria.

## Persistencia en AWS ([`consulta-s3.txt`](consulta-s3.txt))

Consulta con [`scripts/consultar_captura.py`](../../scripts/consultar_captura.py) sobre `prueba-int-20261015T164022-0001`, hecha con el usuario IAM de **solo lectura** `p4-lectura` (no con root). Sus permisos solo permiten leer `edge-capturas/`, `modelos/` y `models/`. El intento de escritura con ese mismo perfil fue denegado ([`escritura-denegada.txt`](escritura-denegada.txt)):

| Objeto | Detalle |
|---|---|
| Registro | `s3://p4-capturas-474665692638/edge-capturas/eventos/prueba-int-20261015T164022-0001.json`, VersionId `HUw1H2f3RY85bJst6kQyobzDXV_x4CcN` |
| Foto | `.../edge-capturas/fotos/prueba-int-20261015T164022-0001.jpg`, VersionId `AtoUfsFwsQZJ5wU_Z7CZAI9tyLPEeHvw`, 18 285 bytes |

El SHA-256 de la foto descargada (`229b542d…d84a`) es igual al de los metadatos de S3, al `image_sha256` del [evento local](evento.json) y al de [`foto.jpg`](foto.jpg).

**Una sola versión de cada objeto:** el reintento y el conflicto no escribieron nada, así que no hay duplicados ni sobrescrituras.

## Sin secretos

Se buscó el token real del dispositivo (64 caracteres) en esta carpeta, en `scripts/` y en el registro local: **no aparece**. `resultado.json` guarda las respuestas del receptor, no las solicitudes ni sus cabeceras.
