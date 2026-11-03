# EDGE-08 — Ensayo físico del runbook

Operador: Omar. Fecha: 16 de octubre de 2026, America/Mexico_City (UTC−06:00).
Esta ejecución asistida es un ensayo del [runbook](../../docs/edge08-runbook.md).
No constituye una reproducción independiente por Diego, Lemus o Josué.

## Evidencia principal

- `entorno.txt`: reloj sincronizado por NTP, Python 3.13.5, ONNX Runtime 1.31.0 y SHA-256 del modelo.
- Modelo: `1.0.0-int8-e05.1`, SHA-256 `ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12`. Las sesiones utilizan CPUExecutionProvider.
- `normal/`: captura `edge01-6ce3c340a0f445ed8db325420081702d`, JPEG original, metadatos, evento e inferencia local (cat, confianza 0.9995785355567932).
- `envios.jsonl`: seis intentos con error de red conservados, seguidos de HTTP 201 a las 20:20:09 y HTTP 200 duplicado a las 20:20:48. Los hashes del evento y JPEG se mantienen. Los errores de transporte no prueban por sí solos ausencia de Internet.
- `capturas/`: fotografías de la terminal; incluyen intentos fallidos y la ejecución terminada. Los archivos originales de logs y JPEG son la referencia principal.

## Secuencia offline y reconexión

La sesión válida es `2b4e74ca11a84c1082648ebb1ecd282a`, PID 3405, en `offline-final/offline.jsonl`.

| Hora local | Hecho | Archivo |
|---|---|---|
| 20:42:56 | Modelo cargado antes de desconectar | `offline-final/offline.jsonl` |
| 20:44:04 | Wi-Fi sin dirección, Ethernet desconectado, sin ruta por defecto; falla DNS | `offline-final/red-offline-antes.txt` |
| 20:45:33 | Captura e inferencia cat, confianza 0.9998477697372437 | `offline-final/sin_internet/edge01-b7a8d5745d014539879dddd550e40db8.jpg` y log |
| 20:46:01 | Captura e inferencia dog, confianza 0.9943007230758667 | `offline-final/sin_internet/edge01-b308d52da97947e3ab860fcc2a8acb78.jpg` y log |
| 20:46:33 | Se conserva el estado sin Internet después de ambas capturas | `offline-final/red-offline-despues.txt` |
| 20:47:07 | Wi-Fi reconectado, ruta por wlan0 y HTTP/2 200 | `offline-final/red-reconectada.txt` |
| 20:48:12 | Nueva captura person, confianza 0.944076657295227 | `offline-final/reconectado/edge01-cbf62513c0134ef48713f89e95b1ad1b.jpg` y log |
| 20:48:13 | Demostración finalizada con la misma sesión y PID | `offline-final/offline.jsonl` |

Los registros de red encierran las dos capturas offline. La conexión exitosa precede a la tercera captura. Se conserva USB para la cámara local.
`offline-final/offline.jsonl` también contiene una carga previa del PID 3364 sin capturas; no se utiliza para demostrar esta secuencia.
`offline/` y `red-offline-antes.txt` en la raíz corresponden a intentos anteriores y no sustituyen los registros de la sesión válida.

## Reinicio

`reinicio/operacion.jsonl` registra dos procesos consecutivos, con recarga del modelo y una nueva captura en cada uno:

- PID 3515, sesión `cc6f6b56316b446abbb1d8611be8fcdb`: carga 20:51:50, captura `edge01-5f7420d5259440e3bc471493ab64f4ea` a las 20:51:55.
- PID 3525, sesión `2ba0e735c87f408a9ed562373c597fab`: carga 20:52:29, captura `edge01-d51e5be8d41c4229b8aa66bbb352f6af` a las 20:52:31.

Ambos conservan configuración SHA-256 `919f0ac833954b3eb50c99fe709360a363d5d79b75f3c66d93783095c9162862`, modelo e historial.
Los dos se ejecutaron con etiqueta `fase: continua`; el reinicio se demuestra por los procesos y sesiones diferentes, no por esa etiqueta.
El indicador de veinte capturas/cinco minutos es falso en estas pruebas cortas, como corresponde. La prueba de estabilidad está en EDGE-07.

## Verificación y pendientes

Se comprobaron los nueve JSON con referencia a imagen: todos corresponden a su JPEG por capture_id y SHA-256 (seis fotografías únicas). Se recalculó softmax de los logits de los registros y coincide con probabilidades, clase y confianza dentro de 1e-6.

La evidencia técnica del ensayo incluye captura normal, envío, duplicado, desconexión, reconexión y reinicio. La comprobación visual del portal y la reproducción independiente por otro integrante no quedan acreditadas por este paquete. Mantener pendiente esa verificación de la Definition of Done, o documentar un cambio del criterio acordado por el equipo. No atribuir este ensayo a otra persona.
