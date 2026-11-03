# EDGE-04 — Clasificación local sin Internet

## Evidencia principal para revisión

La sesión válida para la clasificación sin Internet es
**`cd3cfa51a5fe4be2ba79cce6a61c7016` (PID 5663)** del 16 de octubre de 2026.
Se encuentra en [corrida-final/offline.jsonl](../evidencias/EDGE-04/corrida-final/offline.jsonl).

| Hito | Hora local (UTC−06:00) | Evidencia |
|---|---|---|
| Modelo cargado y hash verificado | 01:16:42 | Una sola carga, CPUExecutionProvider |
| Estado sin Internet previo | 01:19:49 | [red-offline-antes.txt](../evidencias/EDGE-04/corrida-final/red-offline-antes.txt) |
| Captura nueva de gato, resultado cat | 01:20:02 | Confianza 0.8389561176300049, capture_id edge01-08a24c7015864f81b5b39a73a8f5b740 |
| Captura nueva de perro, resultado dog | 01:20:14 | Confianza 0.6013272404670715, capture_id edge01-d9a833fcac934a4580ef577e0e177140 |
| Estado sin Internet posterior | 01:20:39 | [red-offline-despues.txt](../evidencias/EDGE-04/corrida-final/red-offline-despues.txt) |

Los dos registros de red rodean las capturas y muestran Wi-Fi inactivo,
Ethernet desconectado y fallo de resolución DNS, conservando el enlace local USB.
Los JPEG corresponden a imágenes de gato y perro presentadas en pantalla.
La sesión y el PID se mantienen; fotos y resultados quedan guardados localmente.

Esta sesión respalda la clasificación sin Internet de EDGE-04. No demuestra por
sí sola una reconexión efectiva posterior. Para la demo final EDGE-08 se requiere
una secuencia completa: carga, corte documentado, dos capturas, HTTP exitoso
antes de la tercera y misma sesión hasta finalizar.

Los archivos de la raíz de `evidencias/EDGE-04/` corresponden a intentos anteriores;
los de `corrida-final/` corresponden a las sesiones posteriores. Los registros
de red homónimos deben identificarse por su ruta completa y fecha. Se conservan
sus ubicaciones originales para no invalidar referencias de los PR existentes.

## Funcionamiento

`edge/offline.py` reutiliza la cámara de EDGE-02 y el modelo de EDGE-03. Carga y
verifica el ONNX una sola vez, antes de solicitar la desconexión. Después solicita
dos capturas nuevas sin Internet y una tercera tras reconectar, usando la misma
instancia `Modelo` y sesión CPU. No se realiza ningún envío al portal ni a AWS.

Cada resultado se guarda en `offline.jsonl`, con session_id, PID, timestamp,
capture_id, clase, confianza, logits, probabilidades y versión/hash del modelo.
JPEG y JSON de captura se conservan en `sin_internet/` y `reconectado/`.
Los registros son evidencia local, no eventos para el receptor.

## Preparación

Distribuir `edge/offline.py` a `/home/pi/edge01/app/offline.py` mediante rsync.
Requiere `app/camara.py`, `app/inferencia.py`, `modelo/preprocesar.py`, el binario
local de EDGE-03 y las dependencias ya instaladas en `.venv`.

Usar pantalla y teclado de la Raspberry; una conexión SSH que se corte al apagar
Wi-Fi no permite operar la demostración. Preparar previamente dos entradas de
clases diferentes, sin necesitar buscarlas en Internet durante la prueba.
Se pueden usar imágenes ya abiertas o impresas presentadas a la cámara, anotando
esa condición. La cámara debe generar fotografías nuevas en cada disparo.

## Ejecución

```bash
cd "$HOME/edge01"
source .venv/bin/activate
python -u app/offline.py --modelo modelo/model_int8.onnx --url "http://10.60.188.31:8080/shot.jpg" --salida evidencias/EDGE-04
```

Sustituir la URL si cambia la dirección local de IP Webcam. Esperar a
`MODELO CARGADO`. No cerrar el programa. Apagar Wi-Fi y desconectar Ethernet de
la Raspberry; en el teléfono apagar Wi-Fi y datos móviles manteniendo anclaje USB
e IP Webcam. No desconectar el cable USB: es el enlace local de cámara.

En una segunda Terminal local guardar evidencia antes de pulsar Enter:

```bash
{ date --iso-8601=seconds; ip -br address; ip route; curl --connect-timeout 5 --max-time 10 -I https://example.com; } > "$HOME/edge01/evidencias/EDGE-04/red-sin-internet.txt" 2>&1
```

Guardar evidencia visible de los controles de Wi-Fi/datos del teléfono y red de
la Raspberry. El fallo de curl por sí solo no prueba desconexión completa.
Volver a la primera Terminal, pulsar Enter e introducir la clase conocida de cada
una de las dos escenas. El programa captura al siguiente Enter y clasifica sin
recargar el modelo. Verificar que las clases predichas sean distintas; no alterar
los resultados si el modelo se equivoca.

Al solicitar reconexión, activar Internet y registrar en la segunda Terminal:

```bash
{ date --iso-8601=seconds; ip -br address; ip route; curl --connect-timeout 5 --max-time 10 -I https://example.com; } > "$HOME/edge01/evidencias/EDGE-04/red-reconectada.txt" 2>&1
```

Volver al programa y generar la tercera foto. El session_id y PID deben mantenerse,
y solo debe aparecer una carga del modelo en esa ejecución. Las fases del log son
declaradas por el operador; las pruebas externas de conectividad las respaldan.
Reconectar no activa inferencia remota ni envío automático.

## Evidencia y verificación

Conservar el log, tres JPEG y sus JSON, registros de red y capturas de pantalla
de carga previa al corte, resultados y controles de conectividad. Los resultados
deben persistir aunque no haya forma de enviarlos. La ejecución física debe
respaldarse con los registros y controles de red de la misma sesión.

### Intentos anteriores: archivos de la raíz

En `evidencias/EDGE-04/` se recibieron seis JPEG con sus JSON, el log de dos
sesiones completas y un intento fallido, dos registros de red, una comprobación
adicional de acceso externo y seis fotos de Terminal y conectividad.
Se verificó que los seis JPEG son legibles y que sus hashes y fechas
coinciden con los registros de captura e inferencia.

La sesión `603e22c5faf74bf18bd85a3dad4e2e7f` (PID 5347) carga el modelo a las
00:42:08, clasifica cat a las 00:42:24 y dog a las 00:42:36 en la fase declarada
sin Internet, y vuelve a clasificar a las 00:44:04 tras declarar reconexión.
El modelo se carga una sola vez y conserva sesión y proceso. En la última foto,
la clase esperada era cat y el resultado fue dog; se conserva sin corregirlo.

La evidencia de red todavía no acredita toda la secuencia:

- `red-sin-internet.txt` es de las 00:34:24, anterior a las dos sesiones completas.
  Muestra Wi-Fi inactivo, Ethernet desconectado y fallo DNS, pero mantiene ruta
  por defecto al teléfono USB.
- `red-reconectada.txt` es de las 00:43:27, durante la segunda sesión. Muestra
  Wi-Fi activo, pero la conexión HTTPS externa sigue fallando. No prueba acceso
  a Internet restablecido.
- `internet-wifi-verificado.txt` registra HTTP/2 200 a las 00:56:13 usando
  `curl --interface wlan0`. Confirma acceso externo por Wi-Fi en ese momento,
  posterior al final de las sesiones; no se atribuye retroactivamente a las
  capturas de las 00:41 o 00:44.
- Se agregaron dos fotografías de conectividad: el teléfono muestra Wi-Fi y
  datos móviles desactivados, IP Webcam en uso y conexión USB activa. La foto
  del menú de la Raspberry muestra la opción `Turn Off Wireless LAN`, que indica
  radio Wi-Fi habilitada; no demuestra por sí sola asociación ni acceso a Internet.
  El registro de red de las 00:34 sí muestra wlan0 DORMANT.

Estas fotografías de conectividad corresponden al primer intento (00:30–00:53),
no a la sesión principal de las 01:16–01:23; no se atribuyen a esa sesión.
Los archivos actuales se conservan como evidencia de los intentos originales.

### Sesiones de corrida-final y sus límites

`corrida-final/offline.jsonl` contiene otras dos sesiones completas. Sus seis
JPEG se verificaron contra los JSON y hashes del log:

| Sesión | Carga | Capturas declaradas offline | Captura posterior |
|---|---|---|---|
| `cd3cfa51a5fe4be2ba79cce6a61c7016`, PID 5663 | 01:16:42 | 01:20:02 cat; 01:20:14 dog | 01:23:55 dog |
| `18d0efd255004ce0872921bf0c4fff04`, PID 5829 | 01:27:33 | 01:27:59 cat; 01:28:11 dog | 01:29:16 cat, esperada dog |

Para la primera sesión, `red-offline-antes.txt` (01:19:49) y
`red-offline-despues.txt` (01:20:39) rodean las dos capturas y muestran Ethernet
desconectado, Wi-Fi inactivo y fallo de DNS. La primera conexión exitosa registrada
es posterior a la terminación de esa sesión.

Para la segunda sesión, `red-reconectada.txt` contiene HTTP/2 200 a las 01:28:45,
antes de la tercera captura de las 01:29:16, con el mismo PID y session_id. No se
recibió registro de red offline específico de esta segunda sesión. Además,
`red-reconectada-ok.txt` registra HTTP/2 200 a las 01:26:37, antes de que comience
la sesión. Por tanto, **la sesión 18d0efd2 no acredita clasificación sin Internet**:
la etiqueta `sin_internet` del log es una declaración manual sin corroboración;
las capturas pudieron realizarse con conectividad activa. Se conserva esa etiqueta
como parte del log original, no como prueba de aislamiento. Los TXT de las 01:19
y 01:20 pertenecen exclusivamente a cd3cfa51.
No se mezclan las dos sesiones para afirmar una única corrida totalmente
correlacionada. Se conserva el último resultado incorrecto y el empate de logits
cat/dog sin modificarlo.

Prueba local desde `Proyecto4`:

```bash
python -m unittest discover -s edge -p test_offline.py -v
```

Comprueba que la carga precede a la primera interacción y que las tres inferencias
reciben el mismo objeto de modelo. Usa dobles de prueba y no acredita por sí sola
la captura o inferencia offline en el hardware.
