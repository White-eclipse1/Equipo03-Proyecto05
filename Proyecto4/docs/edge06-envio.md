# EDGE-06 — Envío real al receptor

`edge/enviar.py` lee un JSON de `eventos/` de EDGE-05 y el JPEG indicado en
`image_ref`. Verifica campos del contrato, hash de foto, JPEG y límites de tamaño
antes de hacer POST multipart con partes `evento` y `foto`. No reejecuta inferencia
ni cambia capture_id, captured_at, JSON o fotografía. Rechaza metadatos locales
como estado, width, height e image_bytes dentro del evento.

La URL predeterminada es `https://54-80-197-58.sslip.io/api/p4/capturas`.
Puede configurarse con P4_RECEPTOR_URL o --url. Se exige HTTPS con verificación
de certificado normal; no se siguen redirecciones. El token se obtiene únicamente
de P4_TOKEN_DISPOSITIVO, no de argumentos ni archivos versionados.

## Ejecución en Raspberry

Distribuir `edge/enviar.py` a `/home/pi/edge01/app/enviar.py`. Reutiliza
eventos.py, camara.py, inferencia.py y modelo/preprocesar.py ya instalados.
No se carga el modelo para enviar un evento guardado.

```bash
cd "$HOME/edge01"
source .venv/bin/activate
mkdir -p evidencias/EDGE-06
read -r -s -p "Token vigente del dispositivo: " P4_TOKEN_DISPOSITIVO
echo
export P4_TOKEN_DISPOSITIVO
```

Seleccionar un evento real de EDGE-05 y ejecutar dos veces, con exactamente
el mismo archivo. Sustituir capture_id por el ID seleccionado:

```bash
python -u app/enviar.py --evento "evidencias/EDGE-05/eventos/<capture_id>.json" --log evidencias/EDGE-06/envios.jsonl
python -u app/enviar.py --evento "evidencias/EDGE-05/eventos/<capture_id>.json" --log evidencias/EDGE-06/envios.jsonl
```

La primera aceptación devuelve 201 creado; la repetición, 200 duplicado. Se
confirma éxito solo si estado y capture_id de respuesta corresponden al envío.
El log incluye HTTP, respuesta, fecha, hashes del JSON y JPEG, intentos y tiempo
de envío, separado de la inferencia local. Authorization y token no se registran.

Compartir el capture_id con el responsable del portal para contrastar imagen,
predicción, versión y registro único en portal/S3. Una respuesta HTTP aceptada
no sustituye esa comprobación de integración conjunta.

## Errores, reintentos y evidencias

Solo se reintenta ante 503 o error de red, hasta tres intentos totales. Se utiliza
el mismo cuerpo multipart dentro de la ejecución, leído de archivos ya guardados.
Los 4xx, 500 y redirecciones se muestran sin reintento automático. No se borra
ningún archivo local, tampoco cuando se interrumpe el proceso o falla la red.
401 requiere corregir el token; 422 requiere revisar los detalles y el contrato.

Para prueba de persistencia de transporte, ejecutar con el mismo evento y
`--url https://127.0.0.1:1/api/p4/capturas` (puerto local cerrado), conservar el
error y después reenviar al receptor normal. Nunca cambiar el evento original
ni el ID para reintentar. Esta prueba controlada no sustituye el envío real.

Para comprobar conflicto 409, copiar un evento ya aceptado y cambiar únicamente
su confianza por otro número válido, conservando capture_id e imagen. Enviar
la copia: debe aparecer 409 una sola vez, sin reintento. Etiquetar la copia como
prueba de conflicto; no atribuirla a una predicción física nueva. Conservar el
original intacto y no reenviar la copia para intentar sobrescribir lo guardado.

Guardar el log, captura de Terminal, JPEG y evento originales o su referencia
a EDGE-05, evidencia de fallo/reintento y confirmación del responsable del portal.
No transferir tokens ni .env a la carpeta de evidencias.

```bash
unset P4_TOKEN_DISPOSITIVO
```

## Pruebas locales

Desde Proyecto4:

```bash
python -m unittest discover -s edge -p test_enviar.py -v
```

Se comprueban multipart, creado/duplicado, conservación del evento, reintento
ante red/503 con cuerpo idéntico, ausencia de reintento ante 4xx/500 y rechazo
de campos locales o JPEG alterado antes de invocar red. Usan transporte simulado.

## Resultados físicos y recepción real

Evidencias del 16 de octubre de 2026 en
[`evidencias/EDGE-06/`](../evidencias/EDGE-06/), usando la captura real
`edge01-211538a088644fe19b3f579367d5b2c8` de EDGE-05:

| Hora local UTC−06:00 | Resultado |
|---|---|
| 16:34:01 | Captura e inferencia guardadas por EDGE-05 |
| 17:24:14 a 17:24:27 | Tres intentos con error de red; mismo evento y foto |
| 17:26:59 | 201 creado, confirmado por el receptor |
| 17:28:43 | 200 duplicado, mismo received_at y claves de almacenamiento |
| 17:29:48 | 409 conflicto_capture_id ante copia con confidence 0.5; sin reintento |

La captura fue generada y guardada durante EDGE-05; se envió posteriormente en
EDGE-06. Por eso captured_at y received_at difieren aproximadamente 53 minutos:
no es una medición de latencia ni, por sí sola, indicio de reloj desincronizado.
El envío duró 581.72 ms en la aceptación y 938.80 ms en el duplicado, excluyendo
captura e inferencia. Para la demo se debe comprobar NTP y enviar una captura nueva.

El diagnóstico mostró una ruta por defecto USB preferida sobre Wi-Fi. Al quitar
temporalmente esa ruta por defecto, conservando la subred de cámara USB, el receptor
fue accesible por wlan0. El GET sin credenciales devuelve Basic 401 por Caddy;
el POST de dispositivo usa Bearer y obtuvo las respuestas anteriores.

Se verificaron los hashes del JSON original y JPEG contra todos los intentos:
`c3e01eb1f394963081e365b0dc4955fd8a934587c47d72dba4b10038deed94fe`
y `2f753f34f2fba7d45dfb4c960914516545531d25889f4d844191a23493ef1250`,
respectivamente. La copia de conflicto cambia solamente confidence. Las dos
capturas de Terminal recibidas muestran 201 y 409; el log original también
conserva 200 duplicado y los errores de transporte, sin credenciales.

El responsable de integración reportó verificación en S3 con usuario de solo
lectura: JPEG 1920 × 1080 íntegro, mismo SHA-256, cat 0.9987, versión/hash correctos
y una sola versión de foto y registro. Es una confirmación comunicada por el
equipo, no una consulta S3 ejecutada en esta revisión. La revisión visual del
portal sigue pendiente de su confirmación.

La foto quedó girada 90°: orientar físicamente el teléfono para las nuevas
capturas de demostración. No rotar ni sobrescribir este JPEG ya aceptado, porque
cambiaría su hash y rompería el vínculo con el evento almacenado.
