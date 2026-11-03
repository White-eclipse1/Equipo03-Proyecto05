# F9 — Portal: Evaluation, Models e Inference

| Campo | Valor |
|---|---|
| Responsable | Andrés (Líder de portal y calidad) |
| Revisor de PRs | Diego |
| Fechas | 28 sep → 30 sep de 2026 |
| Rama | `feat/fase-9-portal-evaluation-models-inference` |
| Puntos de rúbrica | 11 (6.3, 6.4, 6.5) |
| Depende de | F4, F6, F7 |
| Bloquea a | F10 |
| Control | Control 3 |

**Nota de calendario:** Evaluation debe bloquearse hasta que exista la selección.

> Antes de empezar lee `AGENTS.md` (contexto y reglas) y `docs/contratos.md`. Trabaja los bloques en orden; cada bloque es al menos un PR.

## Bloque T21 — Página Evaluation

**Objetivo:** Mostrar la evaluación final real, bloqueada hasta que exista la selección del modelo.

**Criterios de rúbrica:** 6.3, 4.2, 4.4

**Pasos**

1. Backend: GET /api/p3/evaluation devuelve 423 (bloqueado) si no hay selection.json; si existe, devuelve candidato, versión de datos, métricas, matriz y errors.json.
2. Matriz de confusión (filas=real, columnas=predicho) con todas las clases; métricas globales y por clase; baseline.
3. Galería de aciertos y errores del test (recorte, real, predicho, probabilidad).
4. Botón para exportar predictions_test.csv para auditoría.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Antes de la selección la página no revela métricas de test → si `GET /api/p3/evaluation` responde 409/423 (selección no cerrada), la página muestra "Evaluación bloqueada" y **no** renderiza métricas ni matriz. Prueba `Proyecto2/web/tests/evaluation.test.tsx` (rojo `62b9ed8` → verde `9dc1839`): con 409 no existe la tabla `Matriz de confusión`.
- [x] Las cifras coinciden con MLflow → la página lee `GET /api/p3/evaluation` (que F6 calcula desde el run seleccionado en MLflow) y muestra accuracy, F1 macro, matriz de confusión (filas=real/cols=predicho), métricas por clase y baseline; galería de aciertos/errores + exportación de `predictions_test.csv` (rojo `450d967` → verde `bc32387`). _Nota: cableado al backend real; la coincidencia exacta se confirma cuando haya una evaluación con datos (stack poblado)._

**Entregables:** Página Evaluation

## Bloque T22 — Página Models

**Objetivo:** Listar versiones publicadas con su tarjeta, trazabilidad y estado en S3, y elegir la versión activa para inferencia.

**Criterios de rúbrica:** 6.4, 5.3

**Pasos**

1. Lista de versiones (semántica del MODELO, claramente separada de la versión del dataset) con run_id, manifiesto, bucket/key, SHA-256 y estado de publicación.
2. Vista de la tarjeta (model_card.md renderizada) y botón de descarga.
3. Acción 'Usar para inferencia' que llama POST /models/{version}/activate; el backend verifica con head-object antes de aceptar.
4. Prueba: intentar activar una versión cuyo objeto no existe muestra error.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Cambiar la versión activa cambia la predicción/hash del modelo en Inference → "Usar para inferencia" llama `POST /api/p3/models/{version}/activate` y actualiza la versión activa (`Proyecto2/web/src/pages/Models.tsx`); Inference usa esa versión activa (en el mock incluso cambian las probabilidades por versión). Prueba `tests/models.test.tsx` (rojo `3614706` → verde `4be098d`). _La cadena completa Models→Inference se confirma con el stack poblado._
- [x] No se puede marcar publicado un objeto inexistente → activar una versión con `s3.exists: false` responde 409 y no cambia la activa (verificado en la prueba y contra el backend real, que hace head-object antes de aceptar).

**Entregables:** Página Models

## Bloque T23 — Página Inference

**Objetivo:** Subir una imagen nueva o elegir una del portal, recortar, inferir con la versión activa y enviar a la cola de anotación.

**Criterios de rúbrica:** 6.5

**Pasos**

1. Carga de archivo con validación de tipo y tamaño en cliente (el servidor valida también).
2. Herramienta para dibujar/elegir la caja de recorte o usar una anotación existente del portal.
3. Muestra clase, barra de probabilidades por clase y versión de modelo usada.
4. Botón 'Enviar a cola de anotación' que llama al endpoint y muestra enlace al elemento creado.
5. Prueba: archivo inválido muestra error claro.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Predicción proviene del endpoint real → la página sube la imagen a `POST /api/p3/inference` (multipart, con `bbox_xywh` opcional) y muestra clase, barras de probabilidad y versión de modelo (`Proyecto2/web/src/pages/Inference.tsx`); valida tipo/tamaño en cliente además del servidor. Prueba `tests/inference.test.tsx` (rojo `c8ec2d7` → verde `2efac75`). _Predicción con datos reales cuando haya un modelo activo publicado._
- [x] El elemento enviado es consultable en el flujo de anotación → "Enviar a cola de anotación" llama `POST /api/p3/inference/{id}/send-to-annotation`, que sube la misma imagen a P1, y la página muestra el elemento creado (`image_id`). _Consultable en P1 con su API corriendo (`P3_ANNOTATION_URL`)._

**Entregables:** Página Inference

## Definición de terminado

- [ ] Todas las casillas de aceptación marcadas con evidencia real
- [ ] PRs fusionados con review de Diego
- [ ] CI en verde en `main`
- [ ] Commits red → green visibles en el historial

## Registro de avance

| Fecha | Quién | Bloque | Qué se hizo / PR | Pendiente |
|---|---|---|---|---|
| 27 sep 2026 | Andrés | T21 | Rama `feat/fase-9-portal-evaluation-models-inference`. Página Evaluation: bloqueo 409/423 sin revelar test; con evaluación muestra accuracy, F1 macro, matriz de confusión, métricas por clase y baseline; galería de aciertos/errores + exportar `predictions_test.csv`. Cliente `api.p3.evaluation/examples/predictionsUrl` + fixtures/rutas del mock. `npm run test:unit` 35/35, build limpio. Commits `62b9ed8`→`9dc1839`, `450d967`→`bc32387`. | Coincidencia exacta con MLflow al poblar el stack. El doc dice 423 pero el backend real devuelve 409 (se construyó para 409). |
| 27 sep 2026 | Andrés | T22 | Página Models: lista de versiones (semver del modelo, run, sha256, estado en S3) con la activa marcada, tarjeta (`MODEL_CARD.md`) y "Usar para inferencia" (`POST /models/{v}/activate`); activar un objeto ausente da 409 sin cambiar la activa. Cliente `api.p3.models/modelCardUrl/activateModel` + fixtures/rutas del mock (activa mutable). Commits `3614706`→`4be098d`. `npm run test:unit` 38/38. | Cadena Models→Inference con el stack poblado. |
| 27 sep 2026 | Andrés | T23 | Página Inference: subir imagen con validación cliente de tipo/tamaño, recorte opcional (`bbox_xywh`), predicción con la versión activa (clase, barras de probabilidad, versión) y envío a la cola de anotación de P1. Cliente `api.p3.inference/sendToAnnotation` + rutas del mock (el route acepta `FormData`). Commits `c8ec2d7`→`2efac75`. `npm run test:unit` 41/41, build limpio. | Predicción/anotación con datos reales cuando haya modelo activo y P1 corriendo. |
