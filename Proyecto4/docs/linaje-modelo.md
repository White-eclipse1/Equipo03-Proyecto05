# Linaje del modelo — VAL-01 (#1, M1, criterio 1.1)

Demuestra que la variante del edge `1.0.0-int8-e05.1` sale del modelo publicado 1.0.0 del Proyecto 3 y no de un modelo externo. La cadena se reconstruye y se contrasta con [`modelo/verificar_linaje.py`](../modelo/verificar_linaje.py); su salida queda en [`modelo/registros/linaje_verificacion.json`](../modelo/registros/linaje_verificacion.json).

```
P3 1.0.0  model.pt  e4acca42…9172   (run 9f9b62c2…, Proyecto3/docs/selection.json)
   │  modelo/convertir.py + modelo/conversion.yaml + requirements-conversion.lock.txt
   ▼
registro_conversion.json   entrada e4acca42…  →  salidas fp32 6b640343…, int8 ba89ee43…, paquete 3edc0ce2…
   │  publicado en s3://p4-capturas-474665692638/modelos/
   ▼
P4 1.0.0-int8-e05.1  model_int8.onnx  ba89ee43…2a12  +  model_package.json (cat, dog, person; 224×224)
```

**Resultado (15 oct de 2026, niveles «registros» y «s3» con `arn:aws:iam::474665692638:user/Josue`): 20 ok, 0 fallas, 0 pendientes.**

## Ficha

| Dato | Original (Proyecto 3) | Variante (Proyecto 4) |
|---|---|---|
| Versión | `1.0.0` | `1.0.0-int8-e05.1` |
| Run ID de MLflow | `9f9b62c202f0446a8a4b411a10321eff` (r10, mejor época 6, `selection.json`) | — (sale de ese run) |
| Checkpoint / archivo | `mlflow-artifacts:/3/9f9b62c2…/artifacts/checkpoint/model.pt` | `model_int8.onnx` (ONNX opset 18, INT8 estática QDQ, pesos INT8 por canal, activaciones UINT8) |
| Publicado por el P3 | `s3://dataset-quality-releases-750702272375/models/clasificador/1.0.0/model.pt`, VersionId `VtRww5se97lomVTcKJUv6d9mYSL7TXOf` (`Proyecto3/docs/publicacion_s3.md`) | — |
| Copia que usa el P4 | `s3://p4-capturas-474665692638/modelos/clasificador-p3/1.0.0/model.pt`, VersionId `VZ9XZWXFgue21n2uPf8t4HSpIIjNGmxV` | `s3://p4-capturas-474665692638/modelos/clasificador-edge/1.0.0-int8-e05.1/model_int8.onnx`, VersionId `b6mYULAWBVpbLcHvZ2qGG5gGtXZK3zeS` |
| SHA-256 | `e4acca429ebf73d0e5a60fb0dda383a6a5322dccb1decf04b4e40ab9db989172` | `ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12` |
| Bytes | 44 783 563 | 11 295 280 (74.78 % menos) |
| Mapa de clases (índice de salida) | `0 cat`, `1 dog`, `2 person` (`Proyecto3/config/classes.yaml`) | El mismo (`model_package.json`) |
| Preprocesamiento | RGB, `resize_to_square` a 224×224 (bilineal con antialias), escala a [0, 1], media `[0.485, 0.456, 0.406]`, desviación `[0.229, 0.224, 0.225]` (`Proyecto3/src/p3/data/transforms.py`, `docs/corridas.md`) | El mismo en [`modelo/preprocesar.py`](../modelo/preprocesar.py) (numpy + Pillow); entrada `entrada` float32 `[1, 3, 224, 224]`, salida `logits` `[1, 3]` |

La copia del P4 es **byte a byte** el modelo que publicó el P3: tiene el mismo SHA-256 que registran `selection.json` y `publicacion_s3.md` del P3. El VersionId cambia porque es otro bucket.

Conversión: [`modelo/convertir.py`](../modelo/convertir.py), configuración [`modelo/conversion.yaml`](../modelo/conversion.yaml), registro [`modelo/registros/registro_conversion.json`](../modelo/registros/registro_conversion.json) (SHA-256 `d467aef7…7f3b`, igual al publicado en S3). Ficha técnica de la variante: [`modelo-optimizado.md`](modelo-optimizado.md).

### Objetos publicados (verificados el 15 oct)

| Llave en `s3://p4-capturas-474665692638/` | VersionId | Bytes | SHA-256 |
|---|---|---:|---|
| `modelos/clasificador-p3/1.0.0/model.pt` | `VZ9XZWXFgue21n2uPf8t4HSpIIjNGmxV` | 44 783 563 | `e4acca42…9172` |
| `modelos/clasificador-edge/1.0.0-int8-e05.1/model_int8.onnx` | `b6mYULAWBVpbLcHvZ2qGG5gGtXZK3zeS` | 11 295 280 | `ba89ee43…2a12` |
| `…/model_fp32.onnx` | `p6aJRFUytlrCTi4WauBbJc_xzdl_kpjR` | 44 702 717 | `6b640343…06c1` |
| `…/model_package.json` | `tQeOuMdnye0ZvNQJ13Qdj49a8w6z.Aua` | 950 | `3edc0ce2…d6dd` |
| `…/registro_conversion.json` | `UvobFaQyI5LK0nnXTA81JbfFT64C7N0g` | 3 269 | `d467aef7…7f3b` |
| `…/calibracion_ids.jsonl` | `dtQBtAkHYaNrHDnqRN3BSIBwj6OQTDlD` | 18 597 | `229bdff9…b28a` |

Cada SHA-256 se recalculó sobre el objeto descargado y coincide con el registro de conversión (o con el archivo en Git) y con el metadato `sha256` del objeto.

## Criterios de aceptación

| Criterio del issue #1 | Comprobación | Fuentes que se contrastan | Estado |
|---|---|---|---|
| Versión original 1.0.0 | `origen.version` | `conversion.yaml`, registro, `publicacion_s3.md` del P3 | ok |
| run_id de origen | `origen.run_id` | `conversion.yaml`, registro, `selection.json`, `publicacion_s3.md` y `reports/evaluation/9f9b62c2…/metrics.json` del P3 | ok |
| Checkpoint original | `origen.checkpoint` | URI de MLflow en `selection.json`, ruta en `conversion.yaml` y en el registro | ok |
| SHA-256 del original | `origen.sha256_registros`, `s3.model.pt` | `conversion.yaml`, registro, `selection.json`, `publicacion_s3.md`; recalculado sobre el objeto en S3 | ok |
| Variante identificada | `variante.version` | `conversion.yaml`, registro, `modelo-optimizado.md` | ok (ver nota) |
| SHA-256 de la variante | `variante.sha256_registros`, `s3.model_int8.onnx` | registro, `modelo-optimizado.md`, línea `P4_MODELOS_ACEPTADOS` del receptor; recalculado sobre el objeto en S3 | ok |
| Orden de clases cat, dog, person | `clases.orden`, `paquete.reconstruido`, `s3.paquete_contenido` | `Proyecto3/config/classes.yaml` → `model_package.json` → `CLASES_P3` del receptor | ok |
| Preprocesamiento | `preprocesamiento`, `paquete.reconstruido` | `transforms.py` y `corridas.md` del P3 → `preprocesar.py` → `model_package.json` | ok |
| Referencia al script y la configuración | `conversion.referencia` | `convertir.py` lee `conversion.yaml`; el registro guarda la configuración completa y el comando; lockfile presente | ok |
| El registro identifica entrada y salida | `conversion.entrada_salida` | `registro_conversion.json`: entrada y salidas con archivo, bytes y SHA-256 | ok |
| No se sustituye por un modelo externo | `origen.no_externo`, `calibracion.train` | `convertir.py` carga con `load_checkpoint` del P3 y se detiene si el SHA-256 no coincide; ONNX FP32 igual a PyTorch (máx. \|Δlogit\| 1.3e-5); calibración con 300 recortes de train y ninguno de los 145 del test del P3 | ok |

**Nota:** el issue #1 dice `1.0.0-int8.1`, que era el nombre de la variante del equipo anterior. La variante de este equipo es `1.0.0-int8-e05.1`. Hay que actualizar el texto del issue y de EDGE-03 (#9).

Dos comprobaciones hacen que la cadena no dependa solo de que los registros coincidan entre sí:

- **`paquete.reconstruido`:** el script genera de nuevo `model_package.json` con la misma plantilla que `convertir.py`. Toma las clases de `Proyecto3/config/classes.yaml` y el preprocesamiento de `transforms.py` y `corridas.md` del P3, no del registro. El resultado tiene el mismo SHA-256 que el registro y que el objeto publicado (`3edc0ce2…d6dd`). Así, el paquete que lee el dispositivo declara exactamente las clases y el preprocesamiento del P3.
- **`calibracion.train`:** los 300 IDs de calibración son únicos, todos de train y ninguno aparece en `predictions_test.csv` del P3. El test del P3 no se usó para cuantizar.

## Reproducir

Desde `Proyecto4/`, con Python 3.11 o superior y PyYAML (boto3 solo para `--profile`):

```bash
python modelo/verificar_linaje.py                                # solo registros, sin red
python modelo/verificar_linaje.py --profile <perfil-cuenta-p4>   # además recalcula en S3
python -m pytest tests/test_linaje.py
```

`--local` recalcula los SHA-256 de las copias locales (`dvc pull` en `Proyecto3/` y `modelo/artefactos/1.0.0-int8-e05.1/`, que deja `convertir.py`). Las pruebas corren en el CI de P4: comprueban que el linaje actual pasa y que el script detecta otro hash de variante, otro orden de clases, otro run de origen, otro preprocesamiento en el edge, una muestra de test en la calibración y binarios sustituidos en S3.

## Fuera de VAL-01

- **Reproducir la conversión** requiere el manifiesto y los recortes del P3. Hoy solo están en el remoto DVC `dataset-quality-dvc-cache-750702272375`, que el equipo no puede leer. Lo mismo bloquea VAL-02 y VAL-03, que necesitan la validación del P3. Hay que copiar `Proyecto3/data/manifests/m-0.1.3-s42-1/` y `Proyecto3/data/crops/0.1.3/` a `p4-capturas-474665692638`, como se hizo con `model.pt`.
