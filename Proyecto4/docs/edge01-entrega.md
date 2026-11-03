# EDGE-01 — Configuración física y evidencias

Configuración verificada mediante archivos generados en la Raspberry y
confirmaciones de Omar. La [ficha de configuración](edge-guia.md#ficha-edge-01)
registra hardware, cámara, runtime, modo manual, imagen completa y device_id.

## Archivos recibidos

| Evidencia | Resultado |
|---|---|
| [Hardware y runtime](../evidencias/EDGE-01/hardware-runtime.txt) | Raspberry Pi 4 Model B Rev 1.5, Debian 13.7, aarch64, Python 3.13.5, ONNX Runtime 1.31.0; CPUExecutionProvider disponible |
| [Reloj](../evidencias/EDGE-01/reloj.txt) | NTP activo, reloj sincronizado, America/Mexico_City |
| [JPEG original](../evidencias/EDGE-01/camara-nueva.jpg) | JPEG legible, 1920 × 1080, 62 556 bytes; contenido confirmado por Omar |
| [Verificación de captura](../evidencias/EDGE-01/captura-verificacion.txt) | Resultado de Pillow ejecutado en la Raspberry |
| [Hash del modelo local](../evidencias/EDGE-01/modelo-sha256.txt) | Coincide con la variante 1.0.0-int8-e05.1 |
| [Fotografía de la imagen abierta](<../evidencias/EDGE-01/WhatsApp Image 2026-10-15 at 9.33.10 PM.jpeg>) | Muestra la escena del JPEG en pantalla |
| [Montaje físico](<../evidencias/EDGE-01/WhatsApp Image 2026-10-15 at 9.53.13 PM.jpeg>) | Raspberry y teléfono conectado mediante cable USB |

La evidencia incluye cuatro PNG de Terminal:
`Captura de pantalla 2026-10-15 205153.png`,
`Captura de pantalla 2026-10-15 205227.png`,
`Captura de pantalla 2026-10-15 205238.png` y
`Captura de pantalla 2026-10-15 210845.png`.

El JPEG transferido se volvió a verificar localmente con Pillow: formato JPEG,
1920 × 1080, sin error de integridad. SHA-256 de la copia recibida:
`605479b4a5e4f8d28efee22f8933c5576328b7162869c4222b1cb751a289b21a`.

El modelo permanece en `/home/pi/edge01/modelo/model_int8.onnx`. Su hash reportado
por `sha256sum` es
`ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12`.
No se recibió ni se ejecutó el binario en esta revisión local; EDGE-01 comprueba
su identidad y disponibilidad en la Raspberry. La inferencia corresponde a EDGE-03.

## Cámara y comando de captura

La cámara es un POCO C65 con sistema 2.0.208.0, IP Webcam 1.19.0.913 y conexión
mediante USB tethering. La fotografía del montaje muestra la marca POCO y la
conexión física; el modelo exacto y las versiones fueron confirmados por Omar.
Inicio: conectar USB, habilitar anclaje USB y pulsar Iniciar servidor
en IP Webcam. Con `CAMERA_URL` apuntando a la dirección accesible del teléfono
terminada en `/shot.jpg`, ejecutó:

```bash
curl --fail --show-error --connect-timeout 5 --max-time 30 -H "Cache-Control: no-cache" "$CAMERA_URL" -o "$HOME/edge01/evidencias/EDGE-01/camara-nueva.jpg"
```

La transferencia terminó correctamente y Pillow confirmó un JPEG legible.
El tipo de enlace se registra por confirmación de Omar; las salidas de curl
por sí solas no distinguen USB de Wi-Fi.

## Procedencia de las corridas

Las capturas y los TXT corresponden a ejecuciones distintas del 15 de octubre
de 2026, con zona horaria America/Mexico_City (UTC−06:00):

| Evidencia | Corrida |
|---|---|
| Capturas de hardware/runtime | 20:51; incluye 64 bits y sincronización del reloj |
| `hardware-runtime.txt` | 21:36:08; repite hardware, SO, arquitectura y versiones, sin sección de sincronización |
| `reloj.txt` | 21:37:40; comprobación independiente de NTP activo y reloj sincronizado |

Los TXT no se presentan como transcripciones de las capturas. Ambas corridas
registran el mismo hardware, SO, Python y ONNX Runtime. Los archivos originales
se conservan sin modificar sus fechas ni secciones.

## Criterios de entrega

Las evidencias acreditan hardware disponible, cámara probada, runtime identificado,
configuración documentada y acceso local al modelo correcto. El cierre del ticket
requiere además revisión e integración del Pull Request.
