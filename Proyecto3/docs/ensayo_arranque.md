# Ensayo de arranque desde clon limpio (F10 T28 · compuerta M1/M4)

Objetivo: que el evaluador levante todo siguiendo el [README](../../README.md)
al pie de la letra, recorra las 5 páginas con datos reales, recargue durante un
trabajo, cambie la versión del modelo, pruebe un archivo inválido, y cargue el
checkpoint publicado en un proceso limpio para inferir (M4).

**Estado:** ensayo **parcial** hecho el 27 sep 2026. F4–F7 ya están en `main`, así
que se levantó el stack real con `python scripts/up.py`: **M1 pasó** (todos los
contenedores `Healthy`, `/health` ok). Falta el recorrido de las **5 páginas con
datos reales**, que necesita el portal de F8 en `main` (PR #10) — la rama de este
ensayo tiene el backend pero aún no el portal. El recorrido completo queda para
cuando F8 esté fusionado.

## Checklist

| Paso del README | Estado | Evidencia / nota |
|---|---|---|
| §Pruebas de P3: `venv` + `pip install -r requirements.lock.txt` + `-e .` | ✅ verificado | Instalación limpia OK en Python 3.12. |
| §Pruebas de P3: `ruff check .` + `ruff format --check .` | ✅ verificado | Sin hallazgos; 52 archivos formateados. |
| §Pruebas de P3: `pytest` | ✅ verificado | **144 passed, 2 skipped** (los 2 skips: el flujo E2E completo y un caso ya marcado). |
| Portal `Proyecto2/web`: `npm ci` + `npm run test:unit` + `npm run build` | ✅ verificado | 31/31 pruebas de componente; build/typecheck limpios. |
| `python scripts/up.py` levanta app + MariaDB + MinIO + MLflow + worker + inference desde clon limpio | ✅ **verificado (M1)** | 27 sep: build OK y **13 servicios** arriba, todos `Healthy` (`dq_app`, `p3_worker`, `p3_inference`, `p3_mlflow`, `dq_mariadb`, `dq_minio`, `dq_mcp`). `/health` → `status: ok` (mariadb up, minio up). Nota: la build tardó ~92 min por la descarga de ~3–4 GB de CUDA (ver hallazgo 1). |
| Las 5 páginas (Training, Experiments, Evaluation, Models, Inference) con **datos reales** | ⏳ pendiente | Falta el portal de F8 en `main` (PR #10): la rama de este ensayo tiene el backend pero no las páginas. `GET /api/p3/releases` ya responde con datos reales (0.1.1/0.1.2/0.1.3). |
| Recargar durante un trabajo corto conserva estado y logs | ⏳ pendiente | Mecanismo implementado y probado contra el mock (T19); recarga real contra el backend el 30. |
| Cambiar la versión del modelo (Models) | ⏳ pendiente | Página Models es F9. |
| Probar un archivo inválido (Inference) | ⏳ pendiente | Página Inference es F9. |
| M4: cargar el checkpoint publicado en un proceso limpio e inferir | ✅ verificado in-process | El E2E (`tests/test_e2e.py::test_e2e_flujo_completo`) publica el checkpoint en un almacén S3 y `InferenceService` lo descarga, verifica su SHA-256, lo carga y predice. Falta repetirlo contra el bucket real (S3/MinIO) en el ensayo del 30. |

## Hallazgos del arranque real (27 sep) — a atender por el equipo

Estos son de **backend** (F5/F6/F7), no del portal ni de la CI; se surgen aquí
porque es lo que T28 debe destapar. Avisar a los responsables:

1. **La build descarga ~3–4 GB de CUDA (torch) en una máquina sin GPU** →
   `up.py` tardó ~92 min. El lockfile de P3 pinnea `torch==2.14.0` (build con
   CUDA). **Recomendación (F4):** que las imágenes `p3-worker`/`p3-inference`
   instalen el wheel **CPU** (`torch==2.14.0+cpu` vía el índice CPU de PyTorch)
   para un arranque liviano. Impacta también el tiempo de CI.
2. **`GET /api/p3/runs` no está registrado** en la app (cae al SPA). La página
   **Experiments (F8/T20)** lo consume; sin él no carga las corridas.
   **Avisar a Edith (F5):** exponer `GET /api/p3/runs` (y `/runs/{id}`) según
   `contratos.md §4`.
3. **`GET /api/p3/selection`, `/models` y `/evaluation` responden `500`** por
   `botocore.exceptions.NoCredentialsError: Unable to locate credentials`: el
   servicio `p3-inference` intenta leer artefactos de **S3 sin credenciales** en
   el arranque local. **Avisar a Edith/Diego (F5/F7):** apuntar el cliente S3 al
   **MinIO local** (credenciales del `.env`) o devolver un estado limpio
   (404/409) cuando aún no hay selección/modelo/evaluación, en vez de 500.

## Observaciones sobre el README

1. **Build del frontend en el arranque — RESUELTO.** El `Dockerfile` de P2 tiene
   una etapa `node:22-slim` que hace `vite build` y copia el resultado a
   `/opt/dq/static`; `up.py --build` (por defecto) la ejecuta. No hace falta
   compilar el web a mano.
2. **Pruebas del portal.** La sección §Pruebas de P3 solo cubre Python; conviene
   añadir las pruebas de componente del portal (`Proyecto2/web`: `npm run
   test:unit`), que ya bloquean cada PR en `ci.yml`.
3. **Perfil de AWS para el dataset.** El `dvc pull` exige un perfil autorizado en
   `~/.aws`; el evaluador sin credenciales solo podrá usar el fixture. Dejar
   claro qué se puede hacer sin el dataset real.

Cuando F4–F7 estén en `main`, se ejecuta el ensayo completo en una máquina/carpeta
limpia, se corrigen los pasos que fallen **en el momento**, y se marcan aquí las
casillas ⏳ con su evidencia (salida de comando, capturas de las 5 páginas).
