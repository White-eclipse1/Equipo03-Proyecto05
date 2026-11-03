# Capturas de operación: 24 del dispositivo en AWS y en Capturas Edge (INT-08)

La rúbrica pide al menos 20 eventos repartidos entre las clases, con sus fotos, **recuperables en AWS** y visibles en Capturas Edge, contrastando cámara, inferencia, AWS y portal ([`docs/rubrica.md`](../../docs/rubrica.md), "Capturas de operación").

## Qué hay

| Capturas de `edge01` | Origen | En la Raspberry |
|---|---|---|
| 22 | Serie de operación continua y reinicio, 16 oct 18:52–19:00 (UTC-06:00) | [`EDGE-07/`](../EDGE-07/) |
| 1 | Traza de punta a punta, 16 oct 16:34 | [`EDGE-05/`](../EDGE-05/), recorrido en [`int-06/`](../int-06/) |
| 1 | Ensayo del runbook, 16 oct 20:14 | [`EDGE-08/`](../EDGE-08/) |

Las 22 de EDGE-07 se generaron con `app/operacion.py`, que no envía. Omar las envió después, el 17 oct a las 03:35 UTC, con `app/enviar.py`, sin cambiarlas (mismos eventos y JPEG). Por eso su `received_at` es posterior a `captured_at`.

Clases predichas por el dispositivo en las 24: **13 `cat`, 7 `person` y 4 `dog`**. Son operación, no validación etiquetada: la rúbrica no les pone umbral de accuracy.

El portal también muestra 2 capturas `prueba-int-…` (`device_id=prueba-int`, foto sintética "PRUEBA DEL CONTRATO"). Son las pruebas del contrato de INT-02/INT-05 y **no cuentan** entre las 24.

## Evidencia

- [`verificacion-s3.txt`](verificacion-s3.txt): las 22 de EDGE-07 consultadas en S3 con el usuario de solo lectura `p4-lectura`. Para cada una se usó `consultar_captura.py <id> --evento-local <evento de EDGE-07> --foto-local <JPEG de EDGE-07>`. Resultado: **22 de 22 `OK`**. El evento es igual en sus 11 campos, la foto es idéntica byte por byte y hay **una sola versión** del registro y de la foto: sin duplicados ni sobrescrituras. Las otras dos se verificaron igual: la de EDGE-05 en [`int-06/`](../int-06/), y la de EDGE-08 (`edge01-6ce3c340…`, `cat` 0.9996) el 17 oct con `p4-lectura` (evento igual en sus 11 campos, una versión de cada objeto).
- [`portal-capturas-edge.webp`](portal-capturas-edge.webp): Capturas Edge en el portal desplegado, después de Actualizar. Muestra **26 captura(s)** de la más reciente a la más antigua, con foto, clase, confianza, ID, fechas, dispositivo y modelo.
- [`capturas-edge-20261017T035327Z.csv`](capturas-edge-20261017T035327Z.csv): exportación del portal (enlace **CSV** de Capturas Edge, `/api/p4/capturas/exportar?formato=csv`), del 17 oct a las 03:53 UTC. Tiene 26 filas sin IDs repetidos, en orden descendente por `captured_at`. Las 24 filas de `edge01` coinciden con su evento en la Raspberry en `captured_at`, `device_id`, `predicted_class`, `confidence`, `model_version`, `model_sha256`, `image_sha256` e `image_ref`.

## Repetir la comprobación

En la laptop, desde `Proyecto4/`, con `aws login --profile p4-lectura`:

```bash
for e in evidencias/EDGE-07/sesiones/*/eventos/*.json; do
  id=$(basename "$e" .json); s=$(dirname "$(dirname "$e")")
  python scripts/consultar_captura.py "$id" --profile p4-lectura --evento-local "$e" --foto-local "$s/capturas/$id.jpg" | tail -1
done
```

Cada línea debe decir `Resultado: OK`.
