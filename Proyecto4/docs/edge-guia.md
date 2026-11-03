# EDGE-01 — Configuración del dispositivo y cámara

Configuración física utilizada para Proyecto 4, verificada en la Raspberry el
15 de octubre de 2026. El [índice de evidencias](edge01-entrega.md) describe los
archivos originales y la procedencia de las corridas.

## Ficha EDGE-01

| Componente | Configuración |
|---|---|
| Dispositivo | Raspberry Pi 4 Model B Rev 1.5 |
| Sistema operativo | Debian GNU/Linux 13 (Trixie), versión 13.7 |
| Arquitectura | ARM64, aarch64, 64 bits |
| Python | 3.13.5 |
| ONNX Runtime | 1.31.0 |
| Providers disponibles | AzureExecutionProvider y CPUExecutionProvider |
| Cámara | POCO C65, IP Webcam 1.19.0.913 |
| Sistema del teléfono | Versión 2.0.208.0, reportada por el responsable |
| Conexión | HTTP mediante USB tethering |
| JPEG comprobado | 1920 × 1080, 62 556 bytes |
| Entorno virtual | `/home/pi/edge01/.venv` |
| Captura | Manual: un disparo por ejecución del comando |
| Región | Imagen completa (`region: null`) |
| device_id | `edge01` |
| Modelo local | `/home/pi/edge01/modelo/model_int8.onnx` |
| Versión del modelo | `1.0.0-int8-e05.1` |
| SHA-256 verificado | `ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12` |

La fotografía del montaje muestra la marca POCO y la conexión USB a la Raspberry.
El modelo exacto C65 y las versiones del teléfono y de la aplicación fueron
confirmados por Omar. Los providers se obtuvieron con `get_available_providers()`;
este ticket no acredita todavía la ejecución de una sesión de inferencia.

## Arranque de la cámara

1. Conectar el teléfono a la Raspberry con un cable USB de datos.
2. Activar anclaje USB en el teléfono.
3. Abrir IP Webcam, permitir acceso a la cámara y pulsar **Iniciar servidor**.
4. Comprobar en el navegador de la Raspberry que la dirección local del servidor
   es accesible y que `/shot.jpg` devuelve una fotografía.

La dirección y el puerto se consultan para cada conexión. La verificación no
requiere tokens del portal ni credenciales AWS.

## Comandos de verificación

Ejecutar en la Terminal de la Raspberry:

```bash
mkdir -p "$HOME/edge01/modelo" "$HOME/edge01/evidencias/EDGE-01"
source "$HOME/edge01/.venv/bin/activate"
cat /proc/device-tree/model
cat /etc/os-release
uname -m
getconf LONG_BIT
python --version
python -c "import onnxruntime as ort; print(ort.__version__); print(ort.get_available_providers())"
timedatectl status
```

Definir la URL local completa, terminada en `/shot.jpg`, y solicitar una fotografía nueva:

```bash
read -r -p "URL completa de la cámara terminada en /shot.jpg: " CAMERA_URL
curl --fail --show-error --connect-timeout 5 --max-time 30 -H "Cache-Control: no-cache" "$CAMERA_URL" -o "$HOME/edge01/evidencias/EDGE-01/camara-nueva.jpg"
```

Verificar formato y resolución y abrir el archivo en el visor de imágenes para
contrastarlo con la escena física:

```bash
python -c "from PIL import Image; from pathlib import Path; p=Path.home()/'edge01/evidencias/EDGE-01/camara-nueva.jpg'; im=Image.open(p); print('Formato:', im.format); print('Resolución:', im.size); im.verify(); print('Verificación: imagen legible')"
```

Verificar el modelo local:

```bash
sha256sum "$HOME/edge01/modelo/model_int8.onnx"
```

El resultado debe coincidir exactamente con el hash de la ficha.
`modelo-sha256.txt` conserva el resultado obtenido en el dispositivo.

## Alcance

Las evidencias acreditan hardware disponible, runtime instalado, fotografía JPEG
nueva y acceso local al modelo con hash correcto. La imagen fue validada con
Pillow y confirmada visualmente. Se documentan captura manual, imagen completa
e identidad estable del dispositivo.

La aplicación de captura, inferencia y envío al portal pertenecen a otros tickets.
La Definition of Done de EDGE-01 también exige revisión e integración del PR.
