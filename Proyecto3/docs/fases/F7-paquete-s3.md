# F7 — Paquete, tarjeta y publicación en S3

| Campo | Valor |
|---|---|
| Responsable | Diego (PM · datos · evaluación · entrega) |
| Revisor de PRs | Edith |
| Fechas | 29 sep → 30 sep de 2026 |
| Rama | `feat/fase-7-paquete-s3` |
| Puntos de rúbrica | 10 (5.1, 5.2, 5.3) |
| Depende de | F5, F6 |
| Bloquea a | F9, F11 |
| Control | Control 3 |

**Nota de calendario:** El bucket ya existe desde F2; aquí solo se empaqueta, se publica y se verifica la descarga. Debe estar en S3 el miércoles 30 a mediodía para que Models e Inference funcionen.

> Antes de empezar lee `AGENTS.md` (contexto y reglas) y `docs/contratos.md`. Trabaja los bloques en orden; cada bloque es al menos un PR.

## Bloque T17 — Paquete del modelo y tarjeta

**Objetivo:** Empaquetar el artefacto seleccionado con todo lo necesario para reproducir su inferencia y documentarlo en una tarjeta fiel.

**Criterios de rúbrica:** 5.1

**Pasos**

1. Arma el paquete: model.pt (state_dict), config de arquitectura, classes.json, preprocess.json (image_size, mean, std), requirements con versiones fijadas.
2. Escribe model_card.md con: propósito; clases incluidas y exclusiones; release DVC de origen con hash; manifiesto y split; run_id de MLflow y configuración; desempeño global y POR CLASE en test (tomado de T15, no reescrito a mano) y baseline; preprocesamiento exacto (image_size, mean, std); limitaciones; origen de pesos preentrenados; modo de cargarla (código mínimo de carga e inferencia); versión semántica 1.0.0.
3. Prueba: cargar el paquete en un proceso limpio e inferir una imagen.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] La tarjeta describe exactamente el run de selection.json — `MODEL_CARD.md` de 1.0.0: run `9f9b62c2…`, SHA-256 `e4acca42…` (el de `selection.json`); `p3.registry.package` rechaza otro checkpoint u otra corrida ([publicacion_s3.md](../publicacion_s3.md))
- [x] La tarjeta incluye desempeño por clase, preprocesamiento y modo de carga — generada desde `metrics.json` de F6 (plantilla `src/p3/registry/model_card_template.md`); `tests/test_package.py::test_la_tarjeta_usa_las_cifras_de_la_evaluacion`
- [x] El paquete carga en venv limpio siguiendo solo la tarjeta — venv nuevo con `requirements.lock.txt` y el código de la sección "Cómo cargarlo" sobre los paquetes descargados de S3: 1.0.0 → `dog` 0.943828 en el recorte de val `a1330` ([publicacion_s3.md](../publicacion_s3.md#verificación-independiente-52))

**Entregables:** `models/p3/<version>/ (ignorado en git salvo metadatos)`; `model_card.md`

## Bloque T18 — Publicación en AWS S3 real y registro de versiones

**Objetivo:** Subir pesos y tarjeta a un bucket S3 real, recuperables y verificables, y registrar la versión para que el portal la resuelva.

**Criterios de rúbrica:** 5.2, 5.3, 6.4 (no marcar publicado un objeto inexistente)

**Pasos**

1. Pruebas primero (con moto o MinIO): publicar calcula SHA-256 local, sube, hace head-object y solo marca 'publicado' si el objeto existe; activar una versión cambia el artefacto cargado.
2. Habilita versionado en el bucket; sube model.pt, model_card.md y el paquete a s3://<bucket>/models/<nombre>/<version>/ usando credenciales de entorno (nunca en el repo).
3. Guarda en el registro de modelos: versión semántica, run_id, manifiesto, bucket/key, VersionId, SHA-256. Si usan MLflow Model Registry, backend persistente.
4. Descarga en un entorno limpio (venv nuevo), verifica SHA-256 e infiere una imagen; guarda la salida como evidencia.
5. Publica al menos dos versiones (p. ej. 1.0.0 y 1.0.1) para demostrar que una anterior sigue recuperable.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] head-object muestra ambos objetos con VersionId — `model.pt` y `MODEL_CARD.md` de 0.9.0 y 1.0.0 con su `VersionId` (CLI de AWS, solo lectura)
- [x] SHA-256 local coincide tras descargar — `sha256sum` de los `model.pt` descargados: 0.9.0 `ab4d1f44…`, 1.0.0 `e4acca42…`, iguales a `registry.json` (y 1.0.0 a `selection.json`)
- [x] Inferencia exitosa con el modelo descargado — en un venv nuevo, las dos versiones infieren; sus probabilidades difieren (1.0.0 `dog` 0.9438, 0.9.0 `dog` 0.8501): cambiar de versión cambia el modelo

**Entregables:** `src/p3/registry/publish.py`; `docs/publicacion_s3.md (sin secretos)`

## Definición de terminado

- [ ] Todas las casillas de aceptación marcadas con evidencia real
- [ ] PRs fusionados con review de Edith
- [ ] CI en verde en `main`
- [x] Commits red → green visibles en el historial — paquete `0117b49` → `9adbf86`; versión no seleccionada `60f0771` → `e374a23`; publicación `4dd9c0b` → `07ba8ed`; API de modelos `39c48e8` → `7d20d05`

## Registro de avance

| Fecha | Quién | Bloque | Qué se hizo / PR | Pendiente |
|---|---|---|---|---|
| 27 sep 2026 | Diego | T17 | `src/p3/registry/package.py` + plantilla de tarjeta: paquete del contrato §6 con los mismos bytes del checkpoint seleccionado y tarjeta generada con las cifras de F6. Versión no seleccionada sin métricas de test. 9 mutaciones detectadas. | — |
| 27 sep 2026 | Diego | T18 | `src/p3/registry/publish.py` (publicar, activar y listar con verificación de `head` y SHA-256), `s3.py`, `api.py` y `proxy.py` (`/api/p3/models`), `scripts/publish_model.py`. **Publicadas en S3** 0.9.0 (r08, sin evaluación en test) y **1.0.0 (r10, activa)**, con `VersionId` y SHA-256 verificados con la CLI y carga e inferencia en un venv nuevo. 8 mutaciones detectadas. | `s3:GetObjectVersion` en la política del equipo (lo usa la inferencia de F4); ver [publicacion_s3.md](../publicacion_s3.md) |
| 29 sep 2026 | Diego | T18 | Hallazgo 3 del ensayo de F10: `/api/p3/models`, `/card` y `/activate` respondían 500 con `NoCredentialsError`. Ahora **503** con el motivo y qué configurar (sin credenciales, perfil inexistente, sin red o acceso denegado). Red `d99978b` → green (este PR); 11 mutaciones detectadas. Con el perfil real sigue en 200 (`1.0.0` activa). | — |
