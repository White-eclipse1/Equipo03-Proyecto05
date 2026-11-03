# INT-04: idempotencia, fallas y reintento controlado

Dos partes: la falla y el reintento **desde la Raspberry** con una captura física, y el comportamiento del receptor desplegado (duplicado, conflicto, sin sobrescritura) con una captura de prueba.

## Falla y reintento desde el dispositivo

**Captura:** `edge01-211538a088644fe19b3f579367d5b2c8` (`cat` 0.9987), tomada por Omar el 16 oct de 2026 a las 16:34:01 (UTC-06:00) y enviada con el programa de EDGE-06. Su recorrido completo está en INT-06.

**Por qué falló y cómo se recuperó** (detalle en `docs/edge06-envio.md` de EDGE-06, #45):
- La Raspberry tenía como ruta por defecto el enlace USB del teléfono que hace de cámara (`usb0`), y el teléfono tenía el Wi-Fi y los datos móviles **apagados**. Sin salida a Internet, los 3 intentos fallaron por red. [`telefono-sin-wifi-ni-datos.webp`](telefono-sin-wifi-ni-datos.webp) muestra el teléfono así el viernes 16 oct; la foto no tiene hora, así que la que vale es la del log.
- Omar quitó esa ruta por defecto (`sudo ip route del default … dev usb0`), sin tocar la subred de la cámara, y la Raspberry salió por su Wi-Fi (`wlan0`). Se ve en la captura de la terminal de EDGE-06. Es reversible: la ruta se vuelve a crear al reconectar el anclaje USB, y nada se borra.

[`envios-edge06.jsonl`](envios-edge06.jsonl) es el log de envíos que escribió la Raspberry, entregado sin editar (manifiesto con SHA-256; `3b0c826b…c4d9`):

| Hora (UTC-06:00) | Resultado | `capture_id` y hashes |
|---|---|---|
| 17:24:14 | Sin respuesta: "Error de red o timeout; evento local conservado", reintentable | mismo ID; evento `c3e01eb1…94fe`, foto `2f753f34…1250` |
| 17:24:18 | Igual (intento 2) | iguales |
| 17:24:27 | Igual (intento 3) | iguales |
| 17:26:59 | `201 creado`, `received_at` `2026-10-16T23:26:59.521+00:00` | iguales |
| 17:28:43 | `200 duplicado`, con el **mismo** `received_at` | iguales |

[`consulta-s3-edge01.txt`](consulta-s3-edge01.txt): en S3 el evento es igual en sus 11 campos al evento local de la Raspberry, la foto es idéntica byte por byte y hay **una sola versión** del registro y de la foto. Ni las 3 fallas ni el reenvío dejaron duplicados.

| Criterio | Evidencia |
|---|---|
| Procedimiento reversible para provocar la falla | Dejar la Raspberry sin salida a Internet (aquí, la ruta por el teléfono sin datos) y restablecerla (quitar esa ruta y salir por `wlan0`). Para la demostración: [`docs/fallo-reintento.md`](../../docs/fallo-reintento.md) (puerto cerrado, probado). Corte de red real: [abajo](#procedimiento-en-el-dispositivo) |
| La falla queda visible en el dispositivo | El programa registra cada intento fallido con su motivo: 3 líneas de 17:24 en el log |
| El evento local se conserva | Cada falla dice "evento local conservado", y el mismo evento (`c3e01eb1…`) es el que llegó después a S3 |
| Al restablecer la conectividad se reintenta | 17:26:59 → `201 creado` |
| El reintento usa exactamente el mismo `capture_id` | Los 5 intentos llevan el mismo ID y los mismos SHA-256 de evento y foto |
| AWS contiene un solo registro final y una foto recuperable | Una versión de cada objeto; foto descargada idéntica a la de la Raspberry |
| Repetir exactamente el evento produce `duplicado` | 17:28:43 → `200 duplicado`, sin cambiar `received_at` |
| Reutilizar el ID con otro contenido produce conflicto, también desde el dispositivo | 17:29:48: una copia de prueba del evento con `confidence` 0.5 → `409 conflicto_capture_id` (`guardado` 0.9987…, `recibido` 0.5), sin reintento. Log en `evidencias/EDGE-06/conflicto/` (#45). S3 sigue con 0.9987 y una sola versión |

## Receptor desplegado y S3, con una captura de prueba

Prueba del contrato del 16 oct de 2026, 00:59 (UTC-06:00), contra `https://54-80-197-58.sslip.io/api/p4/capturas`, con [`scripts/enviar_prueba.py`](../../scripts/enviar_prueba.py). Usó la captura de prueba `prueba-int-20261016T005939-0001` (`device_id=prueba-int`, foto sintética).

- [`resultado-receptor.json`](resultado-receptor.json): las respuestas del receptor. No incluye las solicitudes ni el token.
- [`consulta-s3.txt`](consulta-s3.txt): la consulta de solo lectura con `p4-lectura`, comparada con el registro local que guardó el script **antes** de enviar.

| Criterio | Evidencia |
|---|---|
| Repetir exactamente el evento produce `duplicado` | Caso 2: `200 duplicado` con el **mismo** `received_at` del primer envío (`2026-10-16T06:59:43.941+00:00`, caso 6). El reintento no escribe nada |
| Reutilizar el ID con otro contenido produce conflicto | Caso 3: `409 conflicto_capture_id`. En `detalles` aparece el campo que cambió: `predicted_class` guardado `dog`, recibido `cat` |
| No se sobrescribe en silencio el registro original | Tras el conflicto, S3 conserva `dog`. Hay **una sola versión** del registro (`1DcpFr826x6U5nXG.k_REtNvphYfEJSI`) y de la foto (`eVpJrcV3ldZfhW86h3_CRWqPhxX0_4fS`); el bucket tiene versionado, así que una sobrescritura dejaría una segunda versión |
| AWS contiene un solo registro final | Una versión por objeto, después de 1 alta, 1 reintento y 1 conflicto |
| AWS contiene una foto recuperable | Se descargó: 18 282 bytes, SHA-256 `aeff07d6…9002`, igual en el archivo, en S3, en el evento y en la foto local |
| El reintento usa el mismo `capture_id` | El reintento mandó el **mismo** evento guardado. Los 11 campos del contrato en S3 son iguales a los del registro local (`evento (11 campos del contrato) igual: True`) |

También lo cubren las pruebas del CI, contra un S3 simulado:

| Prueba | Qué comprueba |
|---|---|
| `test_reintento_identico_es_duplicado_sin_escribir` | El reintento responde `duplicado` y no escribe nada |
| `test_otra_foto_con_el_mismo_id_es_conflicto`, `test_otros_datos_con_el_mismo_id_es_conflicto` | Mismo ID con otra foto u otros datos → conflicto |
| `test_falla_a_la_mitad_se_completa_con_el_reintento` | Si S3 guarda la foto y falla antes del registro, el reintento completa la escritura sin duplicar |
| `test_sin_red_es_no_disponible`, `test_error_de_s3_al_guardar_es_no_disponible` | Si S3 falla, el receptor responde `503`, que es el caso en que el dispositivo **sí** reintenta (contrato) |
| `test_permiso_denegado_es_no_disponible_y_no_conflicto` | Un permiso denegado no se confunde con un conflicto |

## Procedimiento en el dispositivo

Cómo repetir en la Raspberry la prueba del 16 oct. Para la demostración hay una variante más corta, que provoca la falla con un puerto cerrado, en [`docs/fallo-reintento.md`](../../docs/fallo-reintento.md).

**Son dos programas distintos y se corren por separado:**

| Programa | Qué hace | Qué no hace |
|---|---|---|
| `app/eventos.py` (EDGE-05) | Pide una foto nueva a la cámara, la clasifica en local y guarda el JPEG en `<salida>/capturas/` y el evento en `<salida>/eventos/<capture_id>.json` | **No envía nada** |
| `app/enviar.py` (EDGE-06) | Lee un evento ya guardado y su JPEG y los envía al receptor. Reintenta solo ante falla de red o `503`, con el mismo cuerpo. Registra cada intento en `--log` | **No captura ni clasifica**: no cambia el `capture_id` ni el evento |

Opera desde el teclado y la pantalla de la Raspberry, **no por SSH**, porque al cambiar la red la sesión se puede cortar. El cable USB al teléfono se queda conectado, porque es el enlace con la cámara.

**0. Preparar la Terminal.** El token se escribe sin que se vea y no se guarda en archivos:

```bash
cd "$HOME/edge01" && source .venv/bin/activate
read -r -s -p "Token del dispositivo: " P4_TOKEN_DISPOSITIVO; echo; export P4_TOKEN_DISPOSITIVO
```

**1. Capturar (`eventos.py`).** Una foto nueva. La URL es la de IP Webcam en el teléfono, terminada en `/shot.jpg`. Pulsa Enter para tomarla:

```bash
python -u app/eventos.py --modelo modelo/model_int8.onnx --url "http://<ip-del-telefono>:8080/shot.jpg" --cantidad 1 --salida <salida>
```

En pantalla sale la línea `evento_guardado` con el `capture_id`. Anótalo; abajo es `<id>`.

**2. Dejar la Raspberry sin salida a Internet.** Así ocurrió el 16 oct:
- en el teléfono, apaga el **Wi-Fi y los datos móviles**, pero deja el anclaje USB e IP Webcam;
- la Raspberry tiene como ruta por defecto el teléfono (`usb0`), así que se queda sin salida.

Compruébalo y guarda el estado:

```bash
ip route get 54.80.197.58
{ date --iso-8601=seconds; ip -br address; ip route; curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 https://54-80-197-58.sslip.io/; } > red-sin-salida.txt 2>&1
```

El primer comando debe decir `dev usb0` y el `curl` debe fallar, sin código HTTP.

**3. Enviar (`enviar.py`): falla.**

```bash
python -u app/enviar.py --evento <salida>/eventos/<id>.json --log <salida>/envios.jsonl
```

Se ven 3 intentos con `"http_status": null` y "Error de red o timeout; evento local conservado". **Toma una foto o captura de la pantalla, con la hora visible.** Comprueba que el registro local sigue ahí:

```bash
ls -l <salida>/eventos/<id>.json <salida>/capturas/<id>.jpg
sha256sum <salida>/eventos/<id>.json <salida>/capturas/<id>.jpg
```

**4. Corregir la ruta de red.** Quita la ruta por defecto por el teléfono para que la Raspberry salga por su Wi-Fi (`wlan0`, conectado a una red con Internet). La subred de la cámara por USB no se toca:

```bash
ip route | grep "^default"                       # anota el <gateway> de la línea "default via <gateway> dev usb0"
sudo ip route del default via <gateway> dev usb0
ip route get 54.80.197.58                        # ahora debe decir "dev wlan0"
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 https://54-80-197-58.sslip.io/   # debe imprimir 401
```

Guarda la salida de estos comandos en `red-corregida.txt`.

**5. Reintentar (`enviar.py`), con el mismo evento y el mismo comando del paso 3:** responde `201 creado`. **6. Repetirlo:** responde `200 duplicado`, con el mismo `received_at`.

**7. Verificar en la laptop.** Copia `<salida>/eventos/<id>.json` y `<salida>/capturas/<id>.jpg` (por ejemplo con `scp`) y corre:

```bash
python Proyecto4/scripts/consultar_captura.py <id> --profile p4-lectura --evento-local <id>.json --foto-local <id>.jpg
```

Debe terminar en `Resultado: OK`: S3 guardó exactamente el evento y la foto del registro local, con una sola versión de cada objeto.

**8. Dejar la red como estaba (opcional).** La ruta por el teléfono vuelve sola al desconectar y reconectar el anclaje USB. También se puede volver a crear:

```bash
sudo ip route add default via <gateway> dev usb0
```

Al terminar: `unset P4_TOKEN_DISPOSITIVO`. Guarda en esta carpeta `red-sin-salida.txt`, `red-corregida.txt`, la foto de la pantalla del paso 3, `envios.jsonl`, la salida de `sha256sum` y la de la consulta.

## Sin secretos

`resultado-receptor.json`, `envios-edge06.jsonl` y las consultas guardan respuestas, no solicitudes ni cabeceras: no contienen el token ni contraseñas. La foto del teléfono no muestra datos personales.
