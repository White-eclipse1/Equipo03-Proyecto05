# INT-06: una captura seguida con el mismo ID, del dispositivo a AWS y al portal

**Captura:** `edge01-211538a088644fe19b3f579367d5b2c8`. Es la primera captura física del dispositivo aceptada por el receptor desplegado. La tomó Omar con la cámara de la Raspberry el 16 oct de 2026 a las 16:34:01 (UTC-06:00).

## Recorrido

| Paso | Dónde | Evidencia |
|---|---|---|
| 1. La cámara toma la foto y el dispositivo le asigna el `capture_id` | Raspberry (EDGE-05) | [JPEG original](../EDGE-05/capturas/edge01-211538a088644fe19b3f579367d5b2c8.jpg): 1920×1080, 138 805 bytes, SHA-256 `2f753f34…1250` |
| 2. La inferencia se hace en la Raspberry, antes de cualquier envío | Raspberry (EDGE-05) | [`eventos.jsonl`](../EDGE-05/eventos.jsonl): modelo `1.0.0-int8-e05.1` (`ba89ee43…2a12`) cargado con `CPUExecutionProvider`; logits `[5.429, −1.273, −5.027]` → `cat` 0.9987449645996094 |
| 3. El evento se guarda en local antes de enviar | Raspberry (EDGE-05) | [Evento local](../EDGE-05/eventos/edge01-211538a088644fe19b3f579367d5b2c8.json), SHA-256 `c3e01eb1…94fe` |
| 4. Envío: 3 fallas de red, luego `201 creado` y un reenvío `200 duplicado` | Raspberry → receptor (EDGE-06) | [`../int-04/envios-edge06.jsonl`](../int-04/envios-edge06.jsonl): los 5 intentos llevan el mismo `capture_id` y los mismos SHA-256 del evento y de la foto |
| 5. AWS guarda el evento y la foto | S3 | [`consulta-s3.txt`](consulta-s3.txt), con el usuario de solo lectura `p4-lectura` |
| 6. El portal la muestra | Capturas Edge | [`portal-capturas-edge.png`](portal-capturas-edge.png): primera de 3 capturas, con los mismos datos |

Por qué pasaron 53 minutos entre la captura y la recepción: se capturó en la corrida de EDGE-05 (16:34) y se envió después, con el programa de EDGE-06 (17:24–17:26). La fecha no viene de un reloj desfasado. `captured_at` es la hora de la cámara y `received_at` es la del receptor (`2026-10-16T23:26:59.521+00:00`, es decir, 17:26:59 en UTC-06:00, el mismo instante que registra el log de envíos).

## Dispositivo contra AWS

[`consulta-s3.txt`](consulta-s3.txt) compara S3 con el evento y la foto locales, que Omar entregó sin editar, con su manifiesto de SHA-256:

```
python Proyecto4/scripts/consultar_captura.py edge01-211538a088644fe19b3f579367d5b2c8 --profile p4-lectura --evento-local <evento local>.json --foto-local <foto local>.jpg
```

| Campo | Raspberry | S3 |
|---|---|---|
| `capture_id` | `edge01-211538a088644fe19b3f579367d5b2c8` | igual |
| `captured_at` | `2026-10-16T16:34:01.219627-06:00` | igual |
| `predicted_class` | `cat` | igual |
| `confidence` | `0.9987449645996094` | igual |
| `device_id` | `edge01` | igual |
| `model_version` | `1.0.0-int8-e05.1` | igual |
| `model_sha256` | `ba89ee43…2a12` | igual |
| `image_sha256` | `2f753f34…1250` | igual, y es el SHA-256 de la foto descargada de S3 |
| `region` | `null` (foto completa) | igual |

Los 11 campos del contrato son iguales y la foto de S3 es **idéntica byte por byte** al JPEG del dispositivo. El registro y la foto tienen **una sola versión** cada uno (`3suy_iSc4ZEup3D_zdQvUe1AeWIuartI` y `2U7ccpVVIcW_1dJCrSSDPaT5X3Hr_vco`): ni las fallas ni el reenvío duplicaron nada. `Resultado: OK`.

**La clase se calculó en el dispositivo:** el softmax de los logits registrados en la Raspberry, recalculado aparte, da `[0.99874, 0.00123, 0.00003]` para `cat`, `dog` y `person`. Coincide con las probabilidades del log y con la confianza que llegó a S3.

## Portal contra el dispositivo

[`portal-capturas-edge.png`](portal-capturas-edge.png), tomada en el portal desplegado (`https://54-80-197-58.sslip.io`, usuario `evaluador`) después de pulsar Actualizar. Muestra **3 captura(s)**, con la de `edge01` primero porque es la más reciente.

| En el portal | En la Raspberry |
|---|---|
| Foto: el gato, girado igual que el JPEG | JPEG original, servido desde S3 (byte por byte igual) |
| `cat` 99.9 % | `cat`, `0.9987449645996094` |
| ID `edge01-211538a088644fe19b3f579367d5b2c8` | mismo `capture_id` |
| Capturada 2026-10-16 16:34:01 (UTC-06:00) | `captured_at` `2026-10-16T16:34:01.219627-06:00` |
| Recibida 2026-10-16 23:26:59 (UTC) | `201 creado` a las 17:26:59 (UTC-06:00) en el log de envíos |
| Dispositivo `edge01` | `device_id` `edge01` |
| Modelo `1.0.0-int8-e05.1`, `ba89ee435c…` | `model_version` y `model_sha256` del modelo cargado |

## Criterios

| Criterio | Evidencia |
|---|---|
| La foto la toma físicamente Omar | Paso 1: JPEG de la cámara de la Raspberry |
| El `capture_id` nace en el dispositivo | Pasos 1 y 3: el ID aparece en la Raspberry antes de cualquier envío |
| La predicción ocurre en local | Paso 2: logits y probabilidades en la Raspberry, con el modelo INT8 y `CPUExecutionProvider` |
| El resultado local conserva clase y confianza | Paso 3: el evento local tiene `cat` y `0.9987449645996094` |
| El evento enviado conserva el mismo `capture_id` | Paso 4: los 5 intentos llevan el mismo ID y el mismo SHA-256 de evento (`c3e01eb1…`) |
| AWS guarda la foto correspondiente | Foto idéntica byte por byte, una versión |
| AWS guarda los metadatos correspondientes | Los 11 campos iguales, una versión |
| El portal muestra el mismo `capture_id` | Captura de pantalla del portal |
| La foto del portal coincide con la captura física | El portal muestra la foto que sirve S3, idéntica byte por byte al JPEG de la Raspberry |
| La clase del portal coincide con el resultado local | `cat` 99.9 % en el portal; `cat` 0.99874 en la Raspberry |
| La fecha, el `device_id` y el `model_version` coinciden | Iguales en la Raspberry, S3 y el portal |
| Se documenta el recorrido completo | Este README |

## Sin secretos

El log de envíos de [`int-04/`](../int-04/) guarda las respuestas del receptor, no las solicitudes ni sus cabeceras: no contiene el token. `consulta-s3.txt` no contiene credenciales.
