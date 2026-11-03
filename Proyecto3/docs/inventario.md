# Inventario del repositorio y línea base — Proyecto 3

Estado del repositorio al arrancar P3 (F1, bloque T01): dónde está cada pieza de P1 y P2 que P3 va a consumir. Las rutas son relativas a la raíz del repositorio. No se imprimen valores de credenciales.

Levantado el 24 sep de 2026 en Windows 11 con Docker 29.7.2, Python 3.12.10, Node 22.15.0 y DVC 3.67.1 (desde `Proyecto2/requirements.lock.txt`).

## Línea base

| Comando | Resultado |
|---|---|
| `git rev-parse --short HEAD` | `1da110d` en `main` (merge de `chore/s3-cuenta-propia`); la rama `feat/fase-1-arranque-contratos` parte de ahí |
| `git status --short` | limpio |
| `git branch -a` | `main`, `origin/main`, `origin/chore/s3-cuenta-propia` |
| `dvc remote list -v` (en `Proyecto2/`) | `dev s3://dvc-cache (default)` · `prod s3://dataset-quality-dvc-cache-750702272375` |
| `dvc pull -r prod data/raw.dvc` | 2046 archivos; `dvc status data/raw.dvc` → "Data and pipelines are up to date" |
| `dvc status` (pipeline completo) | **no limpio**: etapas `analyze`, `gate`, `split` y `release` con dependencias modificadas (ver hallazgo 2) |
| `ruff check .` · `ruff format --check .` · `pytest` (en `Proyecto2/`) | en verde |

El historial `git log --oneline --graph --all` termina en los merges de P2 (`#10` a `#15`) y el PR `#1` que movió los buckets a la cuenta `750702272375` y agregó `Proyecto3/docs/`.

## Dónde está cada pieza

### Arranque

| Elemento | Ruta |
|---|---|
| Arranque de P2 (portal de calidad, base de P3) | `Proyecto2/scripts/up.py:131` (`main`), que ejecuta `docker compose up -d --wait` en `Proyecto2/scripts/up.py:162`; documentado en `Proyecto2/README.md:29` |
| Alias de arranque | `Proyecto2/Makefile:9` (`make up`) |
| Servicios de P2 | `Proyecto2/docker-compose.yml`: `mariadb`, `minio` (`:27`), `minio-init` (`:47`), `mcp`, `app` |
| Arranque de P1 (portal de anotación) | `Proyecto1/package.json:23` (`npm run up` → `Proyecto1/scripts/up.ts`) |
| URLs locales | P2: `http://localhost:8000` (UI + API), MinIO `:9100`/`:9101`, MariaDB `:3307`. P1: API `:3000`, web `:5173` |
| README en la raíz | **no existe** (cada proyecto tiene el suyo) |

### Datos: COCO, imágenes y releases

| Elemento | Ruta |
|---|---|
| Puntero DVC del dataset | `Proyecto2/data/raw.dvc` (`md5 ca56420c…dir`, 2046 archivos) |
| COCO e imágenes en disco | `Proyecto2/data/raw/annotations.coco.json` y `Proyecto2/data/raw/images/`; el contenedor los ve por el montaje `./:/app` de `Proyecto2/docker-compose.yml` |
| Remotes DVC | `Proyecto2/.dvc/config` (`dev` = MinIO local, `prod` = S3) |
| Pipeline DVC | `Proyecto2/dvc.yaml` (etapas `analyze` → `gate` → `split` → `release`) y `Proyecto2/dvc.lock` |
| Registro de releases | `Proyecto2/reports/versions.json`, escrito por `Proyecto2/src/dataset_quality/tiers/release.py:216` (`write_manifest`) |
| Estado de la compuerta por release | campo `quality_status` en `Proyecto2/src/dataset_quality/models/versions.py:69`, tomado del reporte en `Proyecto2/src/dataset_quality/tiers/release.py:181` |
| Huella del dataset | `Proyecto2/src/dataset_quality/tiers/gate.py:39` (`dataset_fingerprint`) |
| Reporte de la compuerta | `Proyecto2/reports/quality.json` (`status: pass`) |
| Split 70/15/15 de P2 (no se reutiliza) | `Proyecto2/reports/splits.json`, generado por `Proyecto2/src/dataset_quality/tiers/splits.py` |
| API que sirve los artefactos | `Proyecto2/src/dataset_quality/api/artifacts.py`: `GET /api/versions` (`:139`), `/api/quality` (`:127`), `/api/splits` (`:133`), `/api/stats` (`:232`), `/api/exploration/thumbnail/{image_id}` (`:185`, miniatura desde `data/raw/images/`) |
| Exportación COCO de P1 | `Proyecto1/src/api/routes/coco.ts:15` (`GET /api/coco/export`); imagen original en `Proyecto1/src/api/routes/images.ts:55` (`GET /api/images/:id/file`) |

P2 no tiene un endpoint que entregue el COCO completo ni las imágenes originales; los lee del disco. P3 debe leerlos igual, desde `data/raw/` del release elegido.

### Stack

| Capa | P1 | P2 |
|---|---|---|
| Backend | Hono + Drizzle, TypeScript (`Proyecto1/package.json:55`) | FastAPI + SQLAlchemy, Python 3.12 (`Proyecto2/pyproject.toml:12`) |
| Frontend | React 19 + Vite (`Proyecto1/package.json:60`) | React 19 + Vite (`Proyecto2/web/package.json:15`) |
| BD / objetos | MariaDB + MinIO | MariaDB + MinIO |
| Lint | Biome | Ruff |

### Router de páginas y de la API

| Elemento | Ruta |
|---|---|
| Páginas del portal de P2 | lista `PAGES` en `Proyecto2/web/src/App.tsx:16` (navegación por hash `#/<id>`) |
| Routers de la API de P2 | `Proyecto2/src/dataset_quality/main.py:76` (`include_router`) |
| Rutas de la API de P1 | `Proyecto1/src/api/app.ts:20` |

### Credenciales (solo dónde se leen)

| Elemento | Ruta |
|---|---|
| Settings de P2 | `Proyecto2/src/dataset_quality/settings.py:23`: lee `.env` (`:27`); secretos como `SecretStr` (`db_password` `:53`, `minio_root_password` `:59`, `gemini_api_key` `:44`) |
| Plantilla | `Proyecto2/.env.example` (valores locales de desarrollo; `.env` real en `.gitignore`) |
| Compose sin valores por defecto | `Proyecto2/docker-compose.yml`, sintaxis `${VAR:?}` |
| Cliente S3 | `Proyecto2/src/dataset_quality/storage.py:24` (MinIO) y `:37` (`get_prod_s3_client`, perfil de `~/.aws`) |
| DVC `prod` | perfil de `~/.aws` guardado solo por nombre en `Proyecto2/.dvc/config.local` (ignorado por Git) |
| Usuarios IAM | `Proyecto2/terraform/modules/team_access/main.tf` (uno por integrante + evaluador de solo lectura) |
| CI | rol OIDC en `.github/workflows/ci.yml` (variable `AWS_ROLE_ARN`), sin llaves de larga vida |

## Hallazgos: pasos del README que fallan o faltan

| # | Paso | Qué pasa | Impacto | Responsable propuesto |
|---|---|---|---|---|
| 1 | `python scripts/up.py` (`Proyecto2/README.md:31`) | Las imágenes fijadas `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` y `quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z` (`Proyecto2/docker-compose.yml:27` y `:47`) ya no se publican (`no such manifest`, tampoco en Docker Hub). Desde un clon limpio el arranque falla. Solo arranca con imágenes guardadas localmente (se probó con copias arm64 corriendo por emulación). | **M1** | Edith (F1 T02) |
| 2 | `dvc status` debe decir "Data and pipelines are up to date" (`Proyecto2/README.md:447`) | Con el dataset correcto (`dvc status data/raw.dvc` limpio y `dataset_fingerprint` recalculado = `2200274d…`, el del release 0.1.3), el pipeline completo reporta dependencias modificadas: `dvc.lock` registra `annotations.coco.json` con md5 `587344dd…`, pero el archivo del puntero tiene `87ef439a…`, y `quality.yaml` y parte de `src/` cambiaron después del último `dvc repro`. `dvc.lock` cambió por última vez en `005ca04` y `3696933` (18 sep). | Evidencia de reproducibilidad de P2 (no se recalifica, pero el evaluador corre `dvc status` en la Fase 0) | Diego |
| 3 | `cd ruta-al-dataset-v1/Proyecto2` (`Proyecto2/README.md:30`) | El repositorio ahora se llama `Proyecto-3-Clasificador-de-imagenes`; la ruta no existe tras clonar. | Paso literal que falla | Edith (F1 T02, al actualizar el README) |
| 4 | `git clone …/JGO-07/Proyecto_Identificacion_imagenes.git` y `cd Proyecto_Identificacion_imagenes` (`Proyecto1/README.md:23`) | Apunta al repositorio original de P1; en este repo la carpeta es `Proyecto1/`. | Menor (P1 no se recalifica) | Andrés (F10) |
| 5 | Sin README en la raíz | El evaluador "sigue el README" desde un clon limpio y no hay uno que explique el arranque de P3 (portal + worker + MLflow). | **M1** | Edith (F1 T02) |
| 6 | Dataset real | Requiere `dvc pull -r prod data/raw.dvc` con un perfil de `~/.aws` autorizado; está documentado en `Proyecto2/README.md:427`, pero no en un flujo único de arranque. | Bajo | Edith (F1 T02) |
| 7 | CI | `.github/workflows/ci.yml` solo cubre `Proyecto2/` y Terraform; nada de P3. | 7.3 | Andrés (F10) |

**Resueltos en T02 (24 sep):** 1 (`042295d`), 3, 5 y 6 (`d14f462`). Pendientes: 2 (Diego), 4 y 7 (Andrés).

**Resuelto en F4 T24 (27 sep):** 4 — P1 usaba la misma imagen de MinIO que ya no existe y su README apuntaba al repositorio viejo.
