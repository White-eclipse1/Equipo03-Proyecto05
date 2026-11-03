# EDGE-07 — Operación continua y reinicio

`edge/operacion.py` reutiliza cámara, inferencia y eventos de EDGE-02/03/05.
Carga el modelo una vez por proceso y guarda JPEG, registro de cámara, evento
del contrato y resultados de inferencia de cada captura. No envía al portal.
La integración real se verifica con `enviar.py` y las evidencias de EDGE-06.

## Dependencias y alcance

El cierre de EDGE-07 requiere EDGE-04, EDGE-06 y VAL-07. La serie física de
operación no sustituye la validación del preprocesamiento ni el envío real
comprobados en los tickets dependientes.

VAL-07 está integrado en main mediante el PR #47 (`fa51e38`). Su resultado
documenta el contraste de la Raspberry con la laptop. La rama EDGE-07 incorpora
esos commits mediante el merge `ce3902f`.

## Serie de más de cinco minutos

Distribuir `operacion.py` a `/home/pi/edge01/app/`. Conservar camara.py,
inferencia.py, eventos.py y el preprocesador/modelo de los tickets anteriores.

```bash
cd "$HOME/edge01"
source .venv/bin/activate
python -u app/operacion.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --cantidad 21 --intervalo 16 --fase continua --salida evidencias/EDGE-07
```

Definir CAMERA_URL con la dirección HTTP local real terminada en /shot.jpg.
Antes de comenzar, preparar sujetos o representaciones de gato, perro y persona.
Si se usan imágenes en pantalla, documentar esa condición. La cámara debe tomar
fotografías físicas nuevas; el programa no lee una carpeta de fotos como entrada.

El programa espera un Enter inicial y luego toma 21 fotos automáticamente:
1–7 de gato, 8–14 de perro y 15–21 de persona. Anuncia la clase a presentar antes
de cada espera. Cambiar encuadre o escena para cada foto. La primera es inmediata;
entre las siguientes espera 16 s más el tiempo de captura/inferencia/escritura.
Veinte esperas suman 320 s: no cerrar la Terminal durante la serie.

Las clases solicitadas son instrucciones al operador, no etiquetas que fuerzan
la predicción. El resumen cuenta las clases realmente predichas. Para acreditar
reparto entre las tres clases debe existir al menos un resultado de cada clase,
además de revisión visual de las escenas capturadas.

## Reinicio del programa

Cuando la serie termine y aparezca el prompt de la Terminal, ejecutar un proceso
nuevo con el mismo modelo, URL, device_id e intervalo:

```bash
python -u app/operacion.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --cantidad 1 --intervalo 16 --fase reinicio --salida evidencias/EDGE-07
```

Presentar una escena nueva de gato y pulsar Enter. No es necesario reiniciar el
sistema operativo. La nueva sesión debe volver a cargar el modelo con hash
correcto, conservar config_sha256 y agregar una captura al historial existente.

## Archivos y verificación

### Fallo físico de cámara y recuperación

Esta prueba complementa la serie continua; no exige repetir las 21 capturas.
Detener únicamente el servidor de IP Webcam, conservando cable y anclaje USB.
Con la URL local habitual configurada, ejecutar:

```bash
python -u app/operacion.py --modelo modelo/model_int8.onnx --url "$CAMERA_URL" --cantidad 2 --intervalo 90 --fase continua --salida evidencias/EDGE-07/fallo-recuperacion
```

Pulsar Enter con el servidor todavía detenido. Esperar el registro real
`fallo_captura` del primer intento. Guardar captura de Terminal y volver a iniciar
el servidor en el teléfono durante la espera de 90 s. Presentar una escena nueva
de perro, que es la clase solicitada para el segundo intento de esta serie corta.
La segunda captura debe producir JPEG, evento y `captura_completa` en el mismo
proceso. Conservar el log y los archivos incluso si el restablecimiento falla.

El resumen esperado es un fallo y una captura completa; el código de salida 1 es
intencional porque no se completaron los dos intentos. El indicador combinado de
20 capturas y cinco minutos será false en esta prueba corta; se acredita en la
serie principal. Para revisar recuperación se exige fallo real seguido de éxito
con el mismo session_id y PID, no un error generado por un doble de prueba.

### Estructura de archivos

- `operacion.jsonl`: cargas de modelo, session_id, PID, configuración identificada
  por SHA-256, fallos, eventos completos, predicciones y resumen de cada sesión.
- `historial.jsonl`: export de eventos del contrato de todas las sesiones.
- `sesiones/<session_id>/configuracion.json`: configuración sin tokens.
- `sesiones/<session_id>/capturas/`: JPEG y registros de cámara.
- `sesiones/<session_id>/eventos/`: JSON completos del contrato.

La duración se mide con reloj monotónico; `serie_s` excluye la espera inicial
del operador y la carga del modelo. `entre_primera_ultima_captura_s` permite
contrastar que el periodo contenga capturas reales. Un fallo queda en el log
y el programa intenta la captura siguiente; no se inventa una predicción.
Si no hay fallos se esperan 21 eventos en la serie y uno tras reiniciar.

Conservar los originales y capturas de Terminal de carga, progreso, resumen y
nuevo arranque. Verificar al menos 20 eventos únicos, fechas con zona, JPEG/hash
correspondientes, clases/confianzas y modelo, serie >=300 s y una captura posterior
al reinicio con la misma configuración. Si hay fallos, conservarlos y comprobar
los conteos reales antes de afirmar cumplimiento.

## Evidencia física del 16 de octubre de 2026

Archivos originales en [`evidencias/EDGE-07/`](../evidencias/EDGE-07/), con
export `historial.jsonl`, log `operacion.jsonl`, carpetas por sesión y capturas
de Terminal en `capturas_pantalla/`.

| Comprobación | Resultado |
|---|---|
| Sesión continua | 25c10a75e5d94c95b3c5ec3c1dd412cc, PID 2379 |
| Carga del modelo | 18:52:14, versión 1.0.0-int8-e05.1, CPUExecutionProvider |
| Serie física | 21 capturas completas; 326.52 s; cero fallos |
| Predicciones reales de la serie | cat 10, dog 4, person 7 |
| Sesión de reinicio | 3496bcee8b764806bb1e922b8d92a877, PID 2416 |
| Recarga correcta | 18:59:41, mismo hash del modelo |
| Captura posterior al reinicio | Un evento nuevo; sesión finalizada a las 19:00:14 |
| Configuración de ambas sesiones | 919f0ac833954b3eb50c99fe709360a363d5d79b75f3c66d93783095c9162862 |
| Historial acumulado | 22 eventos, 22 capture_id únicos y 22 JPEG |

La revisión verificó JPEG legibles y SHA-256 coincidentes entre fotos, registros
de cámara y eventos; fechas con zona, clase/confianza concordantes con los logs
de inferencia y export completo. Las configuraciones guardadas producen el mismo
hash en ambas sesiones. Las fechas de captura de la serie abarcan 326.03 s,
coherentes con la duración monotónica registrada. El reinicio utiliza otro proceso
y vuelve a cargar el modelo, conservando la configuración y el historial.

Las cantidades por clase son predicciones observadas, no los siete objetivos por
clase que solicita el protocolo. No implican que todas las clasificaciones hayan
sido correctas. La sesión corta muestra false en el criterio combinado de 20
capturas/cinco minutos/tres clases; ese requisito lo acredita la sesión continua.
La corrida no tuvo fallos físicos; la continuidad ante fallo se prueba localmente
con un doble de cámara y no se presenta como un fallo ocurrido en esta serie.

Las entradas de la serie fueron imágenes mostradas en un monitor y fotografiadas
físicamente por el teléfono; no sujetos presentes en la escena. La ejecución no
usa las imágenes fuente como archivos precargados.

### Fallo y recuperación físicos verificados

La evidencia adicional está en
[`fallo-recuperacion/`](../evidencias/EDGE-07/fallo-recuperacion/). El operador
detuvo el servidor de IP Webcam y lo restableció durante la espera entre intentos.
La sesión `9ae1d49a57bc46eb8c9bea5377c63d7f`, PID 2477, registra:

| Hora local UTC−06:00 | Resultado |
|---|---|
| 19:25:22 | Modelo cargado, versión y hash correctos |
| 19:25:27 | Primer intento: fallo_captura, URLError visible |
| 19:26:57 | Segundo intento: captura e inferencia dog, confianza 0.9327709674835205 |
| 19:26:57 | Resumen: una captura completa y un fallo, serie de 90.46 s |

La misma sesión, PID y configuración se mantienen entre fallo y recuperación.
El evento `edge01-64243509029441bebb8637c55f3b02ce` coincide con el historial y
los bytes del JPEG, cuyo SHA-256 es
`3b3e0adcaffa9a50cfedf88173920fd0b88a95ce05d80653faef6f8909775519`.
Se revisaron el JPEG legible, registro de cámara, evento y log originales.
La captura de Terminal adicional está en
[`Captura de pantalla 2026-10-16 192854.png`](<../evidencias/EDGE-07/capturas_pantalla/Captura de pantalla 2026-10-16 192854.png>).

Esta prueba corta acredita fallo real y recuperación sin reiniciar el proceso;
la duración de cinco minutos y el reinicio se acreditan con las dos sesiones
principales. El intervalo de la prueba de recuperación es 90 s, en vez de los
16 s de la serie y su reinicio; no se exige igualar sus hashes de configuración.

Prueba local desde Proyecto4, sin cámara ni esperas reales:

```bash
python -m unittest discover -s edge -p test_operacion.py -v
```

Comprueba continuidad tras fallo, export y coincidencia de configuración entre
sesiones. No acredita duración ni capturas físicas; estas requieren la corrida real.
