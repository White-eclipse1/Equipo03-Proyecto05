# EDGE-08 — Runbook de demostración del dispositivo

Para el operador del equipo que reproduce el recorrido en Raspberry Pi 4 con
POCO C65 e IP Webcam 1.19.0.913. Modelo: `1.0.0-int8-e05.1`, ejecución CPU local.
Este procedimiento debe ser ejecutado por Lemus o Josué, dejando nombre, fecha,
comandos y resultados en el paquete de evidencia. La documentación por sí sola
no acredita reproducción independiente. Dependencias: EDGE-07 e INT-06.

## Antes de comenzar

- Confirmar que EDGE-07 e INT-06 están integrados o aceptados por sus responsables.
- Reservar acceso físico a pantalla/teclado de la Raspberry y al teléfono. La
  Terminal de la prueba offline debe ser local; SSH por Wi-Fi se interrumpe al
  apagar esa conexión.
- El operador debe tener por canal privado el token vigente, acceso al portal
  y el archivo del modelo o un enlace temporal vigente. No necesita AWS CLI ni
  credenciales AWS en la Raspberry.
- Tener una copia del repositorio que incluya todos los scripts citados. Anotar
  `git rev-parse HEAD` desde esa copia en el registro de reproducción.
- Completar el [registro del operador](edge08-registro.template.md) en una copia
  dentro de `evidencias/EDGE-08/registro-operador.md`. No marcar pasos sin ejecutarlos.

En un dispositivo ya preparado, comprobar instalación, archivos, hash y reloj;
no reinstalar paquetes ni recrear el entorno para repetir la demostración.

## 1. Instalación y distribución

En Raspberry con sistema ARM64, Python y acceso sudo:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl ca-certificates openssh-server rsync
sudo systemctl enable --now ssh
mkdir -p "$HOME/edge01/app" "$HOME/edge01/modelo" "$HOME/edge01/evidencias/EDGE-08"
python3 -m venv "$HOME/edge01/.venv"
source "$HOME/edge01/.venv/bin/activate"
```

Usar el entorno existente si ya está instalado. En Windows abrir `wsl -d Ubuntu`;
en Ubuntu, desde una copia del repositorio con los scripts de EDGE-02 a EDGE-07,
definir PROYECTO e IP actual de la Raspberry y transferir:

PROYECTO debe apuntar a la carpeta Proyecto4 de la copia local del operador.
El ejemplo usa la laptop de Omar; sustituir esa ruta si se utiliza otra laptop.

```bash
PROYECTO='/mnt/c/Users/Omar Ramirez/Documents/Escuela/proyecto4/MP4_Equipo05/Proyecto4'
read -r -p "IP actual de la Raspberry: " RPI_IP
rsync -av "$PROYECTO/edge/camara.py" "$PROYECTO/edge/inferencia.py" "$PROYECTO/edge/eventos.py" "$PROYECTO/edge/enviar.py" "$PROYECTO/edge/offline.py" "$PROYECTO/edge/operacion.py" "$PROYECTO/edge/requirements-inferencia.txt" "pi@${RPI_IP}:/home/pi/edge01/app/"
rsync -av "$PROYECTO/modelo/preprocesar.py" "pi@${RPI_IP}:/home/pi/edge01/modelo/"
```

En Raspberry:

```bash
cd "$HOME/edge01"
source .venv/bin/activate
python -m pip install -r app/requirements-inferencia.txt
python -c "import sys, onnxruntime as o; print(sys.version); print(o.__version__); print(o.get_available_providers())"
```

Entorno de las pruebas previas: Debian 13 ARM64, Python 3.13.5, ONNX Runtime 1.31.0,
NumPy 2.5.4 y Pillow 12.3.0. Registrar las versiones efectivamente utilizadas.

## 2. Modelo y reloj

Recuperar mediante el canal autorizado del equipo el objeto
`s3://p4-capturas-474665692638/modelos/clasificador-edge/1.0.0-int8-e05.1/model_int8.onnx`
y colocarlo en `/home/pi/edge01/modelo/model_int8.onnx`. Se puede transferir desde
una laptop o descargar con un enlace temporal privado. No necesita credenciales
AWS en el dispositivo. No guardar enlaces temporales en documentación o evidencias.

Si el archivo está en la copia autorizada de la laptop, desde WSL:

```bash
rsync -av "$PROYECTO/modelo/model_int8.onnx" "pi@${RPI_IP}:/home/pi/edge01/modelo/"
```

Si se recupera mediante URL temporal, desde Raspberry con Internet disponible:

```bash
read -r -s -p "URL temporal del modelo INT8: " MODEL_URL
echo
curl -4 --interface wlan0 --fail --show-error --location "$MODEL_URL" -o modelo/model_int8.onnx
unset MODEL_URL
```

Ante HTTP 403 solicitar un enlace vigente. El modelo no se recupera mediante
Git porque los binarios están excluidos del repositorio.

```bash
sha256sum modelo/model_int8.onnx
timedatectl status
```

Hash obligatorio:
`ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12`.
Si no coincide, detener la demo. Verificar NTP activo y reloj sincronizado antes
del corte de Internet. Si no lo está, con conectividad disponible:

```bash
sudo timedatectl set-ntp true
```

Volver a comprobar el estado; no asumir sincronización inmediata.

Guardar evidencia inicial:

```bash
{ date --iso-8601=seconds; timedatectl status; sha256sum modelo/model_int8.onnx; python -m pip freeze; } > evidencias/EDGE-08/entorno.txt 2>&1
```

## 3. Cámara y configuración externa

Conectar USB de datos, activar anclaje USB e iniciar servidor en IP Webcam.
Orientar físicamente el teléfono para que las fotos nuevas se vean derechas.
Consultar la dirección local vigente y abrir /shot.jpg desde Chrome de la Raspberry.

```bash
read -r -p "URL HTTP local completa terminada en /shot.jpg: " CAMERA_URL
export CAMERA_URL
```

El texto entre comillas es un mensaje: pegar la URL cuando el comando la solicite.
Configurar backend y token en la misma Terminal que enviará las fotos:

```bash
export P4_RECEPTOR_URL='https://54-80-197-58.sslip.io/api/p4/capturas'
read -r -s -p "Token vigente del dispositivo: " P4_TOKEN_DISPOSITIVO
echo
export P4_TOKEN_DISPOSITIVO
```

No mostrar ni capturar el token. Un nuevo shell no hereda variables de otro shell.
device_id se mantiene `edge01`, captura manual, imagen completa y region null.

## 4. Captura normal e integración

```bash
python -u app/eventos.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --cantidad 1 --salida evidencias/EDGE-08/normal
```

Mostrar el modelo cargado, predicción/confianza y ruta del evento. Abrir el JPEG
para contrastar la escena y copiar el capture_id exacto. Sustituirlo en:

```bash
python -u app/enviar.py --evento "evidencias/EDGE-08/normal/eventos/<capture_id>.json" --log evidencias/EDGE-08/envios.jsonl
```

Esperar 201 creado; repetir exactamente el mismo comando para obtener 200 duplicado.
El responsable del portal debe verificar foto, predicción, modelo e identidad única
en Capturas Edge y S3. No rotar o editar el JPEG/evento ya aceptado.

## 5. Demo sin Internet y reconexión: misma sesión

Usar pantalla/teclado local. Preparar dos escenas distintas de clases diferentes
antes de desconectar; si son imágenes en pantalla, anotarlo. En la Terminal principal:

```bash
python -u app/offline.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --salida evidencias/EDGE-08/offline
```

**Puerta 1:** esperar MODELO CARGADO y guardar captura de Terminal. No pulsar Enter.
Apagar Wi-Fi/Ethernet de la Raspberry y Wi-Fi/datos del teléfono conservando USB
e IP Webcam. Guardar fotos de controles. En una segunda Terminal local:

```bash
{ date --iso-8601=seconds; ip -br address; ip route; curl -4 --connect-timeout 5 --max-time 10 -I https://example.com; } > "$HOME/edge01/evidencias/EDGE-08/offline/red-offline-antes.txt" 2>&1
```

Volver a la primera Terminal, confirmar corte y clasificar dos escenas nuevas.
**Puerta 2:** al solicitar reconectar, dejar el programa esperando; no pulsar Enter.
En la segunda Terminal, todavía sin Internet:

```bash
{ date --iso-8601=seconds; ip -br address; ip route; curl -4 --connect-timeout 5 --max-time 10 -I https://example.com; } > "$HOME/edge01/evidencias/EDGE-08/offline/red-offline-despues.txt" 2>&1
```

Restablecer Wi-Fi de la Raspberry. Guardar prueba exitosa por esa interfaz:

```bash
{ date --iso-8601=seconds; ip -br address; ip route; curl -4 --interface wlan0 --connect-timeout 5 --max-time 15 -I https://example.com; } > "$HOME/edge01/evidencias/EDGE-08/offline/red-reconectada.txt" 2>&1
cat "$HOME/edge01/evidencias/EDGE-08/offline/red-reconectada.txt"
```

**Puerta 3:** continuar solo si hay HTTP exitoso. Si falla, diagnosticar mientras
el programa sigue abierto. Después volver a la primera Terminal, confirmar
reconexión y realizar la tercera captura. El log debe tener una carga previa al
corte, dos clases diferentes offline, conexión exitosa anterior a la tercera
inferencia y el mismo session_id/PID en los tres resultados.

## 6. Reinicio y estabilidad

El historial de 21 capturas durante más de cinco minutos y la prueba de fallo
y recuperación están en [EDGE-07](edge07-operacion.md). Mostrar sus evidencias;
no atribuirlas al nuevo operador. Si el evaluador solicita repetir la serie,
seguir el protocolo completo de esa guía.

Para reproducir el reinicio durante este recorrido, ejecutar dos procesos nuevos:

```bash
python -u app/operacion.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --cantidad 1 --intervalo 16 --fase continua --salida evidencias/EDGE-08/reinicio
```

Presentar una escena nueva, pulsar Enter y esperar la finalización y el retorno
al prompt. Luego ejecutar:

```bash
python -u app/operacion.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --cantidad 1 --intervalo 16 --fase reinicio --salida evidencias/EDGE-08/reinicio
```

Presentar otra escena y pulsar Enter. Comprobar nueva carga correcta, session_id
y PID diferentes, config_sha256 igual y un capture_id nuevo, sin perder historial.
El indicador combinado de cinco minutos y 20 capturas será false en estas dos
sesiones cortas; es esperado y no sustituye la evidencia de estabilidad EDGE-07.

## 7. Solución de errores

| Síntoma | Acción |
|---|---|
| ModuleNotFoundError / externally-managed-environment | Activar `$HOME/edge01/.venv`; comprobar `which python`; instalar requisitos dentro del entorno |
| JPEG inválido / HTTPError en cámara | Usar http si IP Webcam está en HTTP y endpoint /shot.jpg; comprobar URL vigente, servidor y USB |
| Cámara inaccesible sin Internet | Conservar anclaje USB; revisar `ip -br address` e `ip route`; no cortar la interfaz de cámara |
| Envío falla aunque Wi-Fi funciona | Revisar rutas; la ruta por defecto del teléfono puede tener prioridad sobre wlan0 |
| Ruta por defecto USB sin salida externa | En consola local, identificar gateway exacto; se puede quitar temporalmente solo `default via <gateway> dev usb0`, conservando la ruta de subred de cámara; guardar diagnóstico antes/después |
| GET al portal devuelve 401 Basic | Es esperado sin credenciales web; POST /api/p4/capturas utiliza Bearer independiente |
| POST 401 | Pedir token vigente y cargarlo externamente; no modificar el evento |
| POST 422 | Revisar detalles; enviar JSON de eventos/, no de capturas/ ni logs |
| POST 409 | Mismo ID con otros datos; conservar original, no sobrescribir ni reintentar automáticamente |
| Hash de modelo no coincide | Detener y recuperar artefacto correcto; no cambiar el hash esperado |
| rsync no encuentra carpeta | Linux distingue Edge-04 de EDGE-04; consultar ruta exacta con find |
| Captura girada | Orientar el teléfono para nuevas fotos; no alterar una imagen ya aceptada |

Para diagnosticar el caso de rutas, en la Terminal de Raspberry:

```bash
ip route
ip route get 54.80.197.58
curl -4 --interface wlan0 --connect-timeout 5 --max-time 15 -I https://example.com
```

Si el acceso por wlan0 funciona pero la ruta automática usa un teléfono sin
Internet, consultar el gateway USB en `ip route`. Solo en ese caso, desde consola
local, sustituir `<gateway_USB>` por el valor observado:

```bash
sudo ip route del default via <gateway_USB> dev usb0
ip route get 54.80.197.58
```

La ruta local a la cámara USB debe permanecer. La eliminación es temporal; al
reconectar el anclaje puede reaparecer la ruta por DHCP. No copiar los signos
`< >` ni una IP de otra corrida. No desactivar TLS para resolver este problema.

## 8. Evidencia y reproducción independiente

Guardar JSON/JPEG originales, logs, capturas de pantalla, NTP, estado de red antes
y después de las capturas offline, HTTP exitoso antes de la tercera y comprobación
en portal. Anotar nombre del operador, fecha, commit utilizado y cualquier
instrucción que haya faltado; actualizar el runbook si requirió ayuda adicional.
No declarar reproducción independiente hasta que Lemus o Josué la ejecute.

Para volver a Windows, desde WSL con PROYECTO y RPI_IP configurados:

```bash
mkdir -p "$PROYECTO/evidencias/EDGE-08"
rsync -av "pi@${RPI_IP}:/home/pi/edge01/evidencias/EDGE-08/" "$PROYECTO/evidencias/EDGE-08/"
```

Los eventos contienen rutas originales de Raspberry; no cambiarlas al copiar
evidencias. Para compartir por mensajería, adjuntar originales como documentos
o ZIP, sin recomprimir fotografías. No incluir tokens, .env ni enlaces temporales.

Al terminar, retirar el token de la Terminal:

```bash
unset P4_TOKEN_DISPOSITIVO
```
