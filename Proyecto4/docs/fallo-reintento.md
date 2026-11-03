# Falla de envío y reintento sin duplicado: procedimiento de demostración (INT-04)

Cómo mostrar al evaluador que una captura cuyo envío falla se conserva en el dispositivo, se reintenta con el **mismo** `capture_id` y queda **una sola vez** en AWS y en el portal. La falla es reversible y solo del lado del dispositivo: no se toca AWS ni el portal.

Esta secuencia se probó el 16 oct de 2026 con la captura física `edge01-211538a088644fe19b3f579367d5b2c8`: 3 fallas de red, `201 creado`, `200 duplicado` y `409` ante una copia alterada. Evidencia en [`evidencias/int-04/`](../evidencias/int-04/). El programa de envío es [`edge/enviar.py`](../edge/enviar.py), documentado en [`edge06-envio.md`](edge06-envio.md).

**Son dos programas distintos:**
- `app/eventos.py` (EDGE-05) **captura y clasifica**: guarda el JPEG y el evento en `<salida>/`, pero no envía nada.
- `app/enviar.py` (EDGE-06) **solo envía** un evento ya guardado. No captura ni cambia el `capture_id`.

Por eso la falla y el reintento se hacen con el mismo evento.

**Roles:** Omar opera la Raspberry y Diego hace la consulta en AWS y muestra el portal. Duración: unos 2 minutos.

## Antes

- Una captura nueva, **todavía no enviada**, tomada con `eventos.py`. `<id>` es el `capture_id` que imprime en la línea `evento_guardado`:

  ```bash
  python -u app/eventos.py --modelo modelo/model_int8.onnx --url "http://<ip-del-telefono>:8080/shot.jpg" --cantidad 1 --salida <salida>
  ```
- El token cargado en la Terminal de la Raspberry, sin mostrarse ni guardarse en archivos:

  ```bash
  cd "$HOME/edge01" && source .venv/bin/activate
  read -r -s -p "Token del dispositivo: " P4_TOKEN_DISPOSITIVO; echo; export P4_TOKEN_DISPOSITIVO
  ```

- La sesión de `p4-lectura` vigente en la laptop: `aws sts get-caller-identity --profile p4-lectura`.

## Secuencia

**1. Falla (Omar).** Envía el evento a un puerto local cerrado, como si no hubiera red:

```bash
python -u app/enviar.py --evento <salida>/eventos/<id>.json --log <salida>/envios.jsonl --url https://127.0.0.1:1/api/p4/capturas
```

Se ven 3 intentos con `"http_status": null`, "Error de red o timeout; evento local conservado" y `"reintentable": true`. Nada llegó al receptor. El evento y la foto siguen en el registro local:

```bash
ls -l <salida>/eventos/<id>.json <salida>/capturas/<id>.jpg
```

**2. Reintento (Omar).** El mismo comando, **sin** `--url` y con el mismo archivo de evento (mismo `capture_id` y mismo `captured_at`). Responde `201 creado`:

```bash
python -u app/enviar.py --evento <salida>/eventos/<id>.json --log <salida>/envios.jsonl
```

**3. Repetición (Omar).** Otra vez el comando del paso 2. Responde `200 duplicado`, con el mismo `received_at` del paso anterior.

**4. Un solo registro (Diego).** En la laptop:

```bash
python Proyecto4/scripts/consultar_captura.py <id> --profile p4-lectura
```

Muestra **una sola versión** del registro y de la foto y termina en `Resultado: OK`. En el portal, **Capturas Edge** → **Actualizar**: la captura aparece una sola vez.

Para comparar también con el registro local, Omar copia `<salida>/eventos/<id>.json` y `<salida>/capturas/<id>.jpg` a la laptop (`scp`). Luego se agrega `--evento-local <id>.json --foto-local <id>.jpg` a la consulta: los 11 campos del contrato y la foto deben ser iguales a S3.

**5. Conflicto (opcional, si el evaluador lo pide).** Omar copia el evento, cambia **solo** `confidence` y envía la copia:

```bash
python -c "import json,sys; e=json.load(open(sys.argv[1])); e['confidence']=0.5; json.dump(e, open(sys.argv[2],'w'), indent=2)" <salida>/eventos/<id>.json /tmp/conflicto.json
python -u app/enviar.py --evento /tmp/conflicto.json --log <salida>/conflicto.jsonl
```

Responde `409 conflicto_capture_id`, con `confidence` guardado contra recibido, y **no** se reintenta. El evento original no se toca, y el paso 4 sigue mostrando el valor original y una sola versión.

## Variante: corte de red real

En lugar del puerto cerrado se puede dejar la Raspberry sin salida a Internet, como pasó el 16 oct: el teléfono sin datos como ruta por defecto (`usb0`). Luego se corrige la ruta con `sudo ip route del default via <gateway> dev usb0`, para salir por `wlan0`. El paso a paso, con cómo encontrar el `<gateway>` y cómo dejar la red como estaba, está en [`evidencias/int-04/`](../evidencias/int-04/README.md#procedimiento-en-el-dispositivo). Opera desde el teclado y la pantalla de la Raspberry, porque una sesión SSH se corta, y no desconectes el cable USB del teléfono: es el enlace de la cámara.

## Si algo sale distinto

| Pasa | Qué hacer |
|---|---|
| El paso 2 también falla por red, aunque el Wi-Fi de la Raspberry está conectado | La ruta por defecto puede ir por el teléfono (`usb0`) sin datos. Comprobar con `ip route get 54.80.197.58`; si sale `dev usb0`, `sudo ip route del default via <gateway> dev usb0` y repetir el paso 2. Así se resolvió el 16 oct (EDGE-06) |
| El paso 2 responde `200 duplicado` en lugar de `201` | El evento ya se había enviado antes. Es correcto, pero para la demo conviene una captura nueva |
| Responde `401` | El token no coincide: volver a cargarlo. Lo da Diego, que lo lee de Parameter Store (`/p4/token-dispositivo`) |
| Responde `422` | Leer los `detalles`, que dicen qué campo no cumple el [contrato](contrato-capturas.md). No se reintenta: se corrige |

Al terminar, en la Raspberry: `unset P4_TOKEN_DISPOSITIVO`.
