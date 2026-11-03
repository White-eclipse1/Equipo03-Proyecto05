# Recorrido E2E del portal — F14 (7.2)

Recorrido de extremo a extremo con **infraestructura real** (MLflow + MinIO + el servicio `p3-inference`), no en memoria. Comprueba que el flujo entero funciona y queda trazable por una cadena de IDs: release aprobado → manifiesto 70/20/10 → trabajo corto en `p3-pruebas` (un run en MLflow) → evaluación del checkpoint sobre el test → publicación de la versión en un MinIO de prueba → activación → inferencia por `POST /api/p3/inference`.

Es el complemento «con infra real» del test en memoria `tests/test_e2e.py` (job `p3-e2e`), que **sigue en CI**. Este recorrido necesita Docker y el dataset, así que corre como job **manual** (`workflow_dispatch`), no en cada push.

> **Nunca toca AWS.** El script se niega a correr si `P3_S3_ENDPOINT` no apunta a un MinIO local o si `P3_MODELS_BUCKET` es el bucket de producción (`check_not_aws`, regla 14 de `AGENTS.md`). El `docker-compose.e2e.yml` levanta un MinIO de prueba y apunta `p3-inference` a él (`P3_S3_ENDPOINT=http://minio:9000`).

## Requisitos

- Docker con Compose.
- El entorno de Proyecto3 con PyTorch (`.venv`), que es quien entrena en el host.
- No hace falta `~/.aws`: el recorrido usa credenciales **de prueba** del MinIO del compose.

## 1. Levantar el stack de prueba

```bash
cd Proyecto3
docker compose -f docker-compose.e2e.yml up -d --build
```

Servicios y puertos del host (distintos a los del stack principal, para convivir):

| Servicio | Puerto host | Para qué |
|---|---|---|
| `minio` | `9100` (consola `9101`) | almacén de modelos de prueba (bucket `p3-e2e`) |
| `mlflow` | `5500` | tracking de la corrida corta |
| `p3-inference` | `8010` | sirve la inferencia leyendo el modelo de MinIO |
| `mariadb` | `3307` | tabla de inferencias de `p3-inference` |

## 2. Correr el recorrido

```bash
cd Proyecto3
P3_S3_ENDPOINT=http://localhost:9100 \
P3_S3_ACCESS_KEY=minioadmin P3_S3_SECRET_KEY=minioadmin \
P3_MODELS_BUCKET=p3-e2e P3_MODELS_PREFIX=models/clasificador \
P3_MLFLOW_URL=http://localhost:5500 P3_INFERENCE_API=http://localhost:8010 \
.venv/Scripts/python scripts/e2e_portal.py
```

El `P3_MODELS_BUCKET` del comando debe coincidir con el del `p3-inference` del compose (`p3-e2e`), para que el servicio lea lo que el script publica.

## 3. Cadena de IDs esperada

El script imprime, al final, algo así (los IDs cambian en cada corrida):

```text
Cadena de IDs del recorrido E2E del portal:
  release_id:        0.1.3
  manifest_id:       m-0.1.3-s42-1
  manifest_hash:     45600f29...
  run_id (MLflow):   7c1f...e2  [experimento p3-pruebas]
  val_accuracy:      0.6667
  checkpoint_sha256: 9a3b...<64 hex>
  test_accuracy:     0.5000 (test_size 3)
  model_version:     1.0.0  [activa]
  inference_id:      inf-...  -> dog
  almacen:           http://localhost:9100/p3-e2e/models/clasificador  (MinIO de prueba, NO AWS)
```

El recorrido es un **control de flujo**, no de exactitud del modelo: entrena pocas épocas sobre el fixture de 3 clases, así que las métricas son bajas a propósito. Lo que valida es que cada eslabón conecta con el siguiente y que la inferencia usa el modelo recién publicado (comprueba que `model_sha256` de la respuesta coincide con el `checkpoint_sha256`).

### Corrida real — 2 oct 2026 (rama `feat/f14-portal-e2e`, `5b72e3e`)

Docker Desktop 29.8 en Windows, `docker compose -f docker-compose.e2e.yml up -d --build` (los cuatro servicios `healthy`) y el comando del paso 2. Terminó con código 0:

```text
Recorrido E2E del portal contra MinIO (http://localhost:9100, bucket p3-e2e).
  [1/6] manifiesto m-0.1.3-s42-1 (1e13542647f16ffa...), 28 recortes
  [2/6] run 35a93d101155487088b27465dc72238c en MLflow (p3-pruebas)
  [3/6] evaluacion: accuracy 0.3333 (test_size 3)
  [4/6] publicado 1.0.0 en MinIO (activa: 1.0.0)
  [5/6] inferencia 0485674280a24a588ae8dbfbec13271b -> cat
  [6/6] el servicio uso el modelo publicado (SHA-256 coincide)

Cadena de IDs del recorrido E2E del portal:
  release_id:        0.1.3
  manifest_id:       m-0.1.3-s42-1
  manifest_hash:     1e13542647f16ffa8b9a2f7942653ebfdff425db9fbdefdd3bacb6633a652cdf
  run_id (MLflow):   35a93d101155487088b27465dc72238c  [experimento p3-pruebas]
  val_accuracy:      0.3333
  checkpoint_sha256: dfc462b1e759b8623ceb65ad60b0f4a69303b6a6ddd34a8e208dd9ef4d5af060
  test_accuracy:     0.3333 (test_size 3)
  model_version:     1.0.0  [activa]
  inference_id:      0485674280a24a588ae8dbfbec13271b -> cat
  almacen:           http://localhost:9100/p3-e2e/models/clasificador  (MinIO de prueba, NO AWS)
```

- El manifiesto es el del **fixture** de 3 clases (`tests/fixtures/p3`, 28 recortes) con el id `m-0.1.3-s42-1`; por eso su hash (`1e135426…`) no es el del manifiesto congelado real (`45600f29…`), y las métricas son bajas a propósito.
- El paso 6 compara el `model_sha256` que devuelve `POST /api/p3/inference` con el `checkpoint_sha256` publicado: la inferencia salió del archivo recién publicado en MinIO.
- **La guarda contra AWS**, comprobada a mano en la misma sesión: sin `P3_S3_ENDPOINT` y con `P3_S3_ENDPOINT=https://s3.amazonaws.com`, el script responde `E2E RECHAZADO` sin tocar nada.
- En Windows, con la salida redirigida a un archivo, conviene `PYTHONIOENCODING=utf-8`: MLflow imprime un emoji que la consola cp1252 no puede escribir.
- Después: `docker compose -f docker-compose.e2e.yml down -v` (contenedores y volúmenes de prueba eliminados).

## 4. Limpieza

```bash
docker compose -f docker-compose.e2e.yml down -v
```

## Notas

- **Se niega contra AWS:** sin `P3_S3_ENDPOINT`, o con un endpoint no local, o con el bucket de producción, el script sale con código 2 y un mensaje, sin tocar nada. La guarda tiene prueba unitaria (`tests/test_e2e_portal_guard.py`), que sí corre en CI.
- **Miniaturas de la evaluación (4.4):** las sirve `GET /api/p3/evaluation/crops/{crop_id}` (contrato C1, #29) desde los recortes en disco (`P3_CROPS_DIR`), solo para el test del manifiesto elegido. No se re-registra nada en la corrida evaluada: la evaluación de test se hace una sola vez (4.1).
- **Descargar pesos (6.4):** `GET /api/p3/models/{version}/download` (contrato C2, #28) sirve el `model.pt` solo si su SHA-256 es el registrado, con `X-Model-SHA256`. En producción, el de `1.0.0` tiene SHA-256 `e4acca42…` (ver [publicacion_s3.md](publicacion_s3.md)); descárgalo y verifica con `sha256sum`.
