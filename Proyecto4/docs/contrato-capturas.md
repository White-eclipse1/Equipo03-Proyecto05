# Contrato de capturas: dispositivo → portal (`schema_version` 1)

Cómo manda el dispositivo edge cada captura al portal y qué responde el receptor. Lo implementa el receptor de [`src/p4/capturas/`](../src/p4/capturas/) y lo consume el programa del dispositivo (EDGE-05, EDGE-06). Un cambio de forma sube `schema_version`, va explícito en el PR y se avisa al equipo.

## Envío

`POST /api/p4/capturas` en el portal, `multipart/form-data` con dos partes:

| Parte | Contenido |
|---|---|
| `evento` | Texto con el JSON del evento (tabla de abajo). Máximo 16 KiB. |
| `foto` | Archivo JPEG (`image/jpeg`), máximo 5 MB: los mismos bytes que el dispositivo guardó en su registro local. |

Cabecera obligatoria: `Authorization: Bearer <P4_TOKEN_DISPOSITIVO>`. El token vive en una variable de entorno del dispositivo y en el `.env` del portal. **Nunca** se escribe en el código ni en Git, y el dispositivo no tiene credenciales de AWS: solo habla con el receptor.

## Campos del evento

Todos obligatorios salvo `region`. Un campo que no esté en la tabla se rechaza (422), para que un error de tipeo no se guarde en silencio.

| Campo | Tipo | Regla |
|---|---|---|
| `schema_version` | entero | `1` |
| `capture_id` | texto | Único por captura y **clave de idempotencia**. `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`. Sugerido: `{device_id}-{AAAAMMDDTHHMMSS}-{n:04d}` |
| `captured_at` | texto | ISO 8601 **con zona**: `2026-10-15T10:30:00-06:00` o `...Z`. Sin zona se rechaza |
| `predicted_class` | texto | Una de las clases del modelo del P3, en su orden de salida: `cat`, `dog`, `person` |
| `confidence` | número | Probabilidad de la clase predicha, entre 0 y 1, sin redondear. No se aceptan texto ni booleanos |
| `device_id` | texto | Identidad configurable del dispositivo. `^[A-Za-z0-9._-]{1,64}$` |
| `model_version` | texto | Versión del artefacto optimizado cargado. Debe estar en `P4_MODELOS_ACEPTADOS` del receptor |
| `model_sha256` | texto | SHA-256 (64 hex en minúsculas) del archivo del modelo cargado; debe corresponder a `model_version` |
| `image_sha256` | texto | SHA-256 de los bytes del JPEG enviado. El receptor lo recalcula y debe coincidir |
| `image_ref` | texto | Ruta de la foto en el registro local del dispositivo |
| `region` | objeto o `null` | Si se clasifica un recorte fijo: `{"x", "y", "width", "height"}` en píxeles enteros de la foto, dentro de ella. `null` u omitido si se usa la foto completa |

Ejemplo: [`contrato/evento_ejemplo.json`](../contrato/evento_ejemplo.json). Plantilla de configuración del dispositivo, sin secretos: [`contrato/dispositivo.env.example`](../contrato/dispositivo.env.example).

El receptor agrega al guardar: `received_at` (UTC), `image_key`, `image_bytes`, `image_width` e `image_height`.

## Respuestas

Los errores siempre tienen la forma `{"error": "<código>", "detail": "<mensaje>", "detalles": [...]}`.

| Caso | HTTP | `estado` / `error` | ¿Reintentar? |
|---|---:|---|---|
| Captura nueva guardada | 201 | `creado` | — |
| Mismo `capture_id` con los mismos datos y la misma foto | 200 | `duplicado` (no se escribe nada) | — |
| Mismo `capture_id` con otros datos u otra foto | 409 | `conflicto_capture_id`; `detalles` lista cada campo guardado contra recibido | No: es un error del dispositivo |
| Falta `evento` o `foto`, multipart roto, JSON inválido | 400 | `solicitud_invalida` | No |
| Token ausente o incorrecto | 401 | `no_autorizado` | No |
| `evento` de más de 16 KiB / foto de más de 5 MB | 413 | `evento_demasiado_grande` / `foto_demasiado_grande` | No |
| La foto no es un JPEG legible o declara más de 40 millones de píxeles | 415 | `foto_no_soportada` | No |
| Evento que no cumple la tabla | 422 | `evento_invalido`; `detalles` trae **todos** los campos con problema | No |
| Receptor sin token configurado | 503 | `receptor_no_configurado` | Sí, con el mismo evento |
| Almacén (S3) caído o sin configurar | 503 | `almacen_no_disponible` | Sí, con el mismo evento |

Respuesta de éxito (201 o 200):

```json
{
  "estado": "creado",
  "capture_id": "edge01-20261015T103000-0001",
  "image_key": "edge-capturas/fotos/edge01-20261015T103000-0001.jpg",
  "record_key": "edge-capturas/eventos/edge01-20261015T103000-0001.json",
  "received_at": "2026-10-15T16:30:04.512+00:00"
}
```

## Lo que debe hacer el dispositivo

1. **Registro local primero:** guardar el JPEG y el JSON del evento **antes** de enviar. El registro local se conserva aunque el envío falle.
2. **Reintento seguro:** solo ante 503 o error de red (sin respuesta, timeout), releyendo **el mismo JSON** guardado: mismo `capture_id` y mismo `captured_at`. Si el primer envío sí había llegado, la respuesta es `200 duplicado`. Un 4xx no se reintenta: se muestra y se corrige.
3. **Fallas visibles:** mostrar en pantalla el código y el mensaje de cada error. Nada de reintentos silenciosos.
4. **Hora con zona:** sincronizar el reloj por NTP antes de la demostración y generar la fecha con `datetime.now().astimezone().isoformat(timespec="seconds")`.
5. **Modelo:** mandar `model_version` y el SHA-256 del archivo **realmente cargado**, el mismo que el programa muestra al arrancar.

## Lecturas (portal y evidencias)

| Endpoint | Qué devuelve |
|---|---|
| `GET /api/p4/capturas?limite=N` | `{items, total, errores}`, de más reciente a más antigua por `captured_at` en UTC. `errores` lista los registros ilegibles o sin fecha válida: no se esconden ni tumban el listado |
| `GET /api/p4/capturas/{capture_id}` | Un registro (404 si no existe) |
| `GET /api/p4/capturas/{capture_id}/foto` | La foto, leída del almacén por el servidor |
| `GET /api/p4/capturas/exportar?formato=csv\|json` | Todos los eventos; en CSV, `region` va en `region_x`, `region_y`, `region_width`, `region_height` |

## Almacenamiento

Una foto y un registro por `capture_id`, en el bucket `P4_BUCKET` bajo `P4_PREFIJO` (por defecto `edge-capturas/`):

```
edge-capturas/fotos/{capture_id}.jpg      la foto tal como llegó; metadato S3 `sha256`
edge-capturas/eventos/{capture_id}.json   el evento + los campos del receptor
```

La idempotencia es una escritura condicional (`If-None-Match: *`): la foto primero y después el registro. Nunca se sobrescribe; un reintento completa una escritura que se quedó a la mitad. En local se usa el MinIO del compose de Proyecto2 (ver `Proyecto2/.env.example`, sección Proyecto 4).

**En AWS:** bucket `p4-capturas-474665692638` (cuenta `474665692638`, `us-east-1`), privado (bloqueo de acceso público completo), cifrado SSE-S3, con versionado y propietario forzado. Se probó el receptor contra este bucket el 14 oct: alta, reintento `duplicado` y conflicto `409` dejaron una sola versión de la foto y del registro.

Para usar S3 real desde una laptop con credenciales de `aws login`, boto3 necesita el paquete `awscrt`; sin él, el receptor responde `503 almacen_no_disponible` con `MissingDependencyException`. En la EC2 no hace falta: el receptor usa el rol de la instancia.
