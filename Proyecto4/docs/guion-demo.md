# Guion de la demostración (INT-04, INT-06, INT-08)

Sigue el orden en que la rúbrica observa el recorrido ([`rubrica.md`](rubrica.md), "B. Observar el recorrido"). Duración objetivo: 10 a 15 minutos. Cada paso dice **quién** lo hace, **qué se muestra** y **con qué comando**, para que nadie improvise.

> Los comandos del dispositivo son los de EDGE-04 a EDGE-08, probados el 16 oct en la Raspberry. Runbook completo del dispositivo: [`edge08-runbook.md`](edge08-runbook.md).

**En el dispositivo se usan tres programas, cada uno por separado**, desde `$HOME/edge01`, con `source .venv/bin/activate` y la URL de la cámara en `CAMERA_URL` (`export CAMERA_URL="http://<ip-del-telefono>:8080/shot.jpg"`):

| Programa | Hace | Comando |
|---|---|---|
| `app/eventos.py` (EDGE-05) | Pide una foto nueva a la cámara, la clasifica en local y guarda el JPEG y el evento en `<salida>/`. **No envía** | `python -u app/eventos.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --cantidad <n> --salida demo` |
| `app/enviar.py` (EDGE-06) | Envía **un evento ya guardado** y su JPEG. Reintenta solo ante falla de red o 503, con el mismo evento | `python -u app/enviar.py --evento demo/eventos/<capture_id>.json --log demo/envios.jsonl` |
| `app/offline.py` (EDGE-04, EDGE-08) | Carga el modelo **una sola vez, antes del corte de red**, y sin cerrarse clasifica durante el corte y después de reconectar, con la misma sesión y el mismo PID. **No envía** | `python -u app/offline.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --salida demo/offline` |

`enviar.py` necesita el token en la Terminal, sin mostrarlo: `read -r -s -p "Token del dispositivo: " P4_TOKEN_DISPOSITIVO; echo; export P4_TOKEN_DISPOSITIVO`. Al terminar, `unset P4_TOKEN_DISPOSITIVO`.

## Roles en la demostración

| Persona | Hace |
|---|---|
| Omar | Opera el dispositivo y la cámara; lee en voz alta el `capture_id` de cada captura |
| Diego | Portal (Capturas Edge), consulta de solo lectura en AWS y fallo y reintento del envío |
| Josué | Modelo: linaje del P3, comparación de calidad y benchmark (paso 9) |
| Mauricio | Conduce, controla el tiempo y anota los `capture_id` que pide el evaluador |

## Antes de la demostración

**Un día antes** (y otra vez 30 minutos antes):

- [ ] Portal arriba: https://54-80-197-58.sslip.io abre y pide usuario. Con `evaluador` entra y se ve Capturas Edge.
- [ ] Contraseña del evaluador lista para entregarla por privado:
  ```powershell
  aws ssm get-parameter --name /p4/portal-evaluador --with-decryption --query Parameter.Value --output text --profile p4-equipo --region us-east-1
  ```
- [ ] Sesiones de AWS vigentes: `p4-lectura` (consultas de S3 en la demo, solo lectura) y `p4-equipo` (solo para leer secretos y operar la EC2). Comprobar con `aws sts get-caller-identity --profile <perfil>`; si caducó, `aws login --profile <perfil>`. **Duran máximo 12 horas: renovarlas la mañana de la demo.**
- [ ] Consulta de solo lectura probada con una captura existente:
  ```powershell
  .\Proyecto2\.venv\Scripts\python.exe Proyecto4\scripts\consultar_captura.py <capture_id> --profile p4-lectura
  ```
- [ ] Contenedores sanos (Session Manager, ver [`despliegue.md`](despliegue.md), "Operación").
- [ ] Dispositivo cargado y cámara conectada (USB e IP Webcam). **El teléfono en horizontal**: la captura del 16 oct quedó girada 90°.
- [ ] Reloj de la Raspberry sincronizado: `timedatectl` debe decir `System clock synchronized: yes`.
- [ ] Salida a Internet por el Wi-Fi: `ip route get 54.80.197.58` debe decir `dev wlan0`. Si dice `dev usb0`, corrige la ruta ([`fallo-reintento.md`](fallo-reintento.md), "Si algo sale distinto").
- [ ] Una captura de prueba con `eventos.py` y su envío con `enviar.py` → `201 creado`.
- [ ] Tres objetos a mano: un gato, un perro y una persona (fotos impresas o en pantalla, como en EDGE-03 a EDGE-05, o reales).
- [ ] Pestañas abiertas: portal en Capturas Edge, la [ficha del P4](../README.md), las evidencias de calidad y de benchmark.

## Recorrido

### 1. Dispositivo, modelo y runtime (Omar y Josué, 2 min)

- Omar arranca `eventos.py` (comando de arriba, `--cantidad 3`). La primera línea, `modelo_cargado`, muestra la versión `1.0.0-int8-e05.1`, el SHA-256 `ba89ee43…2a12` del modelo verificado, onnxruntime `1.31.0` con `CPUExecutionProvider` y el orden de clases.
- Josué muestra el origen en la [ficha del modelo](modelo-optimizado.md) y el [linaje](linaje-modelo.md): `model.pt` del P3 1.0.0 (`e4acca42…`) → conversión INT8 con registro de SHA-256.

### 2. Capturas nuevas con objetos que elige el evaluador (Omar, 2 min)

- El evaluador elige y acomoda los objetos; Omar pulsa Enter para cada uno. Por cada foto sale una línea `evento_guardado` con el `capture_id`, la clase, la confianza, los logits y el tiempo de preprocesamiento e inferencia. La foto y el evento quedan en `demo/capturas/` y `demo/eventos/`.

### 3. Sin red, con el modelo ya cargado (Omar, 3 min)

Es la secuencia de `offline.py` del [runbook de EDGE-08](edge08-runbook.md) (sección 5), ensayada el 16 oct ([`evidencias/EDGE-08/`](../evidencias/EDGE-08/), `offline-final/`). Demuestra que **el mismo proceso, con el modelo ya cargado, sigue clasificando al cortar la red**. Se opera desde la pantalla y el teclado de la Raspberry, porque una sesión SSH se corta, y con dos Terminales locales. Antes de empezar, Omar tiene a mano dos escenas de clases distintas.

1. **Terminal 1:** `python -u app/offline.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --salida demo/offline`. Espera `MODELO CARGADO` y **no pulsa Enter**.
2. **Corte:** apaga el Wi-Fi (y el Ethernet) de la Raspberry y el Wi-Fi y los datos del teléfono. El anclaje USB e IP Webcam se quedan encendidos, porque son la cámara. En la **Terminal 2** guarda el estado sin red:

   ```bash
   { date --iso-8601=seconds; ip -br address; ip route; curl -4 --connect-timeout 5 --max-time 10 -I https://example.com; } > "$HOME/edge01/demo/offline/red-offline-antes.txt" 2>&1
   ```

3. **Terminal 1:** confirma el corte y clasifica **dos escenas de clases distintas**. Siguen saliendo clase y confianza, con la misma sesión y el mismo PID.
4. Cuando el programa pide reconectar, **lo deja esperando**, sin Enter. En la Terminal 2, todavía sin red, repite el comando del paso 2 guardando en `red-offline-despues.txt`.
5. **Reconexión:** enciende el Wi-Fi de la Raspberry y comprueba la salida por esa interfaz. Debe responder HTTP correcto:

   ```bash
   { date --iso-8601=seconds; ip -br address; ip route; curl -4 --interface wlan0 --connect-timeout 5 --max-time 15 -I https://example.com; } > "$HOME/edge01/demo/offline/red-reconectada.txt" 2>&1; cat "$HOME/edge01/demo/offline/red-reconectada.txt"
   ```

6. **Terminal 1:** confirma la reconexión y hace la tercera captura. En `demo/offline/offline.jsonl` hay una sola carga del modelo, anterior al corte, y las tres clasificaciones tienen el mismo `session_id` y PID.

`offline.py` no envía: **estas capturas no se suben**, y la rúbrica no lo exige.

### 4. Captura nueva y envío a AWS (Omar, 1 min)

- Omar comprueba que la Raspberry sale por el Wi-Fi: `ip route get 54.80.197.58` debe decir `dev wlan0`. Si dice `dev usb0`, corrige la ruta ([`fallo-reintento.md`](fallo-reintento.md)).
- Hace **una captura nueva** con `eventos.py --cantidad 1` y la envía con `enviar.py`: `201 creado`. Lee su `capture_id` en voz alta y Mauricio lo anota.

### 5. La captura llega a AWS (Diego, 2 min)

Con el `capture_id` del paso 4:

```powershell
.\Proyecto2\.venv\Scripts\python.exe Proyecto4\scripts\consultar_captura.py <capture_id> --profile p4-lectura
```

Se muestra:

- **Dónde está:** el registro y la foto en `s3://p4-capturas-474665692638/edge-capturas/`, con el `VersionId` y la fecha que asignó S3.
- **Que la foto es la misma:** su SHA-256 recalculado, igual al de los metadatos de S3 y al del evento del dispositivo.
- **Que no hubo duplicados:** una sola versión de cada objeto.

Termina en `Resultado: OK`.

### 6. La misma captura en el portal (Diego, 1 min)

- Desde el menú del portal: **Capturas Edge**. Pulsar **Actualizar**: la captura del paso 4 aparece arriba, con la misma foto, clase, confianza, fechas, `capture_id`, dispositivo y versión del modelo.
- Recargar la página (F5): sigue ahí. También se actualiza sola cada 30 segundos.

### 7. Falla de envío controlada y reintento sin duplicado (Omar y Diego, 2 min, INT-04)

Procedimiento completo, probado: [`fallo-reintento.md`](fallo-reintento.md). En resumen, con una captura del paso 2 que **no se haya enviado**:

1. Omar la envía a un puerto local cerrado (`enviar.py … --url https://127.0.0.1:1/api/p4/capturas`): 3 intentos con error de red; el evento y la foto siguen en `demo/`.
2. Omar repite el envío **sin** `--url`, con el mismo evento: `201 creado`. Otra vez: `200 duplicado`, con el mismo `received_at`.
3. Diego corre la consulta del paso 5 con ese `capture_id`: **una sola versión** del registro y de la foto. En Capturas Edge aparece una sola vez.

Si el evaluador lo pide, el conflicto `409` (copia del evento con otra `confidence`) está en el mismo documento. Ya se hizo con la Raspberry el 16 oct: [`evidencias/int-04/`](../evidencias/int-04/).

Respaldo, si el dispositivo falla: la misma secuencia de respuestas (201, 200 duplicado, 409, 422, 401) ya está probada contra el receptor desplegado en [`evidencias/int-02/`](../evidencias/int-02/).

### 8. Reinicio del programa (Omar, 1 min)

- Omar cierra `eventos.py` (Ctrl+C conserva lo ya guardado) y lo vuelve a abrir: muestra otra vez `modelo_cargado` con la versión y el hash, `demo/` sigue con lo anterior y una captura nueva se clasifica y se envía. Secuencia de reinicio con `app/operacion.py`: [`edge07-operacion.md`](edge07-operacion.md).

### 9. Contraste de calidad o de latencia (Josué, 2 min)

- El evaluador elige un ID de la comparación de calidad ([`predicciones_val.csv`](../validacion/resultados/predicciones_val.csv)) o una fila del benchmark ([`tiempos.csv`](../evidencias/VAL-05/tiempos.csv)). Josué lo reproduce: la clase del original y del INT8 para esa imagen, o p50/p95 recalculados con `python validacion/recursos.py`. En el dispositivo: [`preprocesamiento-edge.md`](preprocesamiento-edge.md) (VAL-07) y el paquete [`evidencias/VAL-08/`](../evidencias/VAL-08/) (`python recalcular.py`).

## Si algo falla durante la demostración

| Falla | Qué hacer |
|---|---|
| El portal no abre | Revisar los contenedores por Session Manager (`docker compose ... ps`); si hace falta, `docker compose ... up -d` (ver [`despliegue.md`](despliegue.md)). No reiniciar la instancia: la IP elástica se conserva, pero tarda varios minutos |
| La consulta de AWS dice que la sesión caducó | `aws login --profile p4-equipo` y repetir |
| El envío falla por red con el Wi-Fi conectado | La ruta va por el teléfono (`usb0`) sin datos: `sudo ip route del default via <gateway> dev usb0` y reintentar el mismo evento ([`fallo-reintento.md`](fallo-reintento.md)) |
| El envío responde 401 | El token del dispositivo no coincide: leerlo otra vez de Parameter Store (`/p4/token-dispositivo`) |
| El envío responde 422 | Leer los `detalles`: indican qué campo no cumple el [contrato](contrato-capturas.md). No se reintenta: se corrige |
| La captura no aparece en el portal | Pulsar **Actualizar**; revisar que el envío respondió 201 o 200 y correr la consulta del paso 5 |

## Después de la evaluación

Apagar o terminar la EC2 y liberar la IP elástica para no generar costo (ver [`despliegue.md`](despliegue.md), "Costo y apagado").
