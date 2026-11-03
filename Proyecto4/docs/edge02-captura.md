# EDGE-02 — Aplicación de captura física

`edge/camara.py` solicita un JPEG nuevo al servidor local de IP Webcam en cada
disparo. Requiere Python y Pillow; no carga modelos ni se conecta al portal.
La captura puede iniciarse manualmente con Enter o por intervalo configurable.

Instalación de la dependencia en un entorno virtual:

```bash
python -m pip install -r edge/requirements-camara.txt
```

## Ejecución en Raspberry

Copiar `edge/camara.py` a `/home/pi/edge01/app/camara.py`. Activar el entorno y
definir `CAMERA_URL` con la URL local accesible de IP Webcam terminada en `/shot.jpg`:

```bash
cd "$HOME/edge01"
source .venv/bin/activate
python app/camara.py --url "$CAMERA_URL" --cantidad 3 --salida evidencias/EDGE-02/manual
```

Antes de cada Enter, cambiar el objeto o su disposición. Abrir los JPEG y
contrastarlos con las escenas físicas. La aplicación conserva por captura:

- JPEG con nombre basado en UUID y device_id (`edge01` por defecto).
- JSON con capture_id, captured_at con zona, ruta absoluta, dimensiones y hash.
- Entrada en `capturas.jsonl`, también mostrada en Terminal.

Los JSON son registros de captura; no son eventos de inferencia para el backend.
La aplicación no lee imágenes precargadas como fuente de captura.

Para cinco fotografías automáticas, con tres segundos de espera entre capturas:

```bash
python app/camara.py --url "$CAMERA_URL" --intervalo 3 --cantidad 5 --salida evidencias/EDGE-02/intervalo
```

El tiempo entre inicios incluye el tiempo de adquisición y escritura más la espera
configurada; no es una frecuencia de tiempo real garantizada.

## Error visible

Detener el servidor IP Webcam y ejecutar:

```bash
python app/camara.py --url "$CAMERA_URL" --intervalo 1 --cantidad 1 --salida evidencias/EDGE-02/error
```

El programa muestra y registra `error_camara`, y termina con código 1. No inventa
una captura exitosa. Reiniciar el servidor y verificar otra fotografía nueva.

## Sin Internet

Mantener el enlace USB y el servidor IP Webcam activos. Desde una consola local,
desactivar las conexiones a Internet de la Raspberry y los datos móviles/Wi-Fi
del teléfono. No cortar el enlace USB utilizado por la cámara. Si el teléfono
desactiva tethering al quitar datos, restablecer el enlace y resolver esa limitación
antes de declarar válida la prueba offline.

Guardar evidencia de interfaces, rutas y estado de los controles de conectividad.
Un timeout a una web por sí solo no demuestra aislamiento. Conservar el resultado:

```bash
mkdir -p evidencias/EDGE-02/offline
{ date --iso-8601=seconds; ip -br address; ip route; curl --connect-timeout 5 --max-time 10 -I https://example.com; } > evidencias/EDGE-02/offline/red.txt 2>&1
python app/camara.py --url "$CAMERA_URL" --cantidad 2 --salida evidencias/EDGE-02/offline
```

Presentar dos escenas nuevas. Conservar JPEG, JSON, logs y evidencia del estado
sin Internet; después restablecer conectividad. Esta prueba requiere validación
física: las pruebas unitarias no la sustituyen.

## Validación y entrega

Pruebas locales sin cámara real, desde `Proyecto4`:

```bash
python -m unittest discover -s edge -p test_camara.py -v
```

Revisar IDs distintos, fechas con zona, correspondencia JSON/JPEG y fotos nuevas.
Adjuntar evidencias físicas de modo manual, intervalo, error y captura sin Internet.
El cierre del ticket requiere además revisión e integración del PR.

## Resultados de la validación física

Evidencias del 15 de octubre de 2026 en
[`evidencias/EDGE-02/`](../evidencias/EDGE-02/), obtenidas con Raspberry Pi 4 y
POCO C65 mediante IP Webcam. Se verificaron las copias transferidas desde el dispositivo:

| Prueba | Resultado y evidencia |
|---|---|
| Manual | Tres JPEG de 1920 × 1080, con IDs distintos, entre las 22:41:07 y 22:41:55; [log](../evidencias/EDGE-02/manual/capturas.jsonl) |
| Intervalo | Tres JPEG de 1920 × 1080, entre las 22:45:14 y 22:45:31; [log](../evidencias/EDGE-02/intervalo/capturas.jsonl) |
| Cámara detenida | `error_camara` de tipo URLError a las 22:46:15 y salida 1 mostrada en Terminal; [log](../evidencias/EDGE-02/error/capturas.jsonl) |
| Captura por USB durante prueba offline | Dos JPEG a las 23:10:05 y 23:10:48, después de corregir el endpoint y usar HTTP; [log](../evidencias/EDGE-02/offline/capturas.jsonl) |
| Estado de red | A las 23:11:33, Ethernet DOWN, Wi-Fi DORMANT, USB activo y fallo de resolución de example.com; [registro](../evidencias/EDGE-02/offline/red.txt) |

Las ocho capturas tienen IDs únicos, fechas con zona UTC−06:00, rutas locales
absolutas y JSON concordantes con el log. En cada JPEG se verificaron formato,
dimensiones, tamaño en bytes y SHA-256 contra su registro. La validación automática
de integridad no sustituye la revisión visual de las escenas.

El log offline conserva seis errores previos a los dos éxitos. Los primeros intentos
usaron la página principal sin `/shot.jpg` o HTTPS en un servidor HTTP. Se mantienen
como evidencia del diagnóstico, sin contarlos como capturas exitosas.

Las fotos de Terminal están en
[`capturas_pantalla/`](../evidencias/EDGE-02/capturas_pantalla/). El registro de red
se obtuvo después de las dos capturas y conserva una ruta por defecto a través del
teléfono. Un fallo DNS no prueba aislamiento completo: para acreditar el estado sin
Internet se requiere además la confirmación y evidencia visual de Wi-Fi y datos
móviles apagados en el teléfono durante la prueba. Esa evidencia de controles no
está incluida entre los archivos recibidos en esta revisión.
