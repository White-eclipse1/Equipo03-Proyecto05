# Almacenamiento — Proyecto 3 (F2 T31)

Dónde viven los datos de DVC, los artefactos de MLflow y los modelos publicados, y cómo se accede a ellos **sin claves en Git**. Aquí solo aparecen nombres de buckets, perfiles y variables; nunca valores de credenciales.

## Resumen

| Qué | Dónde | Versionado | Decidido en |
|---|---|---|---|
| Datos de DVC (`Proyecto2/data/raw`, 2046 archivos) | `s3://dataset-quality-dvc-cache-750702272375` (remote DVC `prod`) | Sí (`aws_s3_bucket_versioning`, `Proyecto2/terraform/modules/s3/main.tf:20`) | PR #1 (`chore/s3-cuenta-propia`) |
| Releases de P2 (`<version>/dataset.tar.zst`: COCO + `quality.json` + `splits.json`) | `s3://dataset-quality-releases-750702272375/<version>/` | Sí (mismo módulo) | PR #1 |
| Modelos publicados (F7) | `s3://dataset-quality-releases-750702272375/models/clasificador/<version-semver>/` | Sí (mismo bucket) | [decisiones.md §6](decisiones.md#6-destino-s3-del-modelo-y-permisos) |
| Registros y artefactos de MLflow | Volumen Docker `mlflow_data` (SQLite + `/mlflow/artifacts`), servidos por `--serve-artifacts` | Persiste a `down`/`up` | [decisiones.md §5](decisiones.md#5-servicio-de-mlflow) |

Región: `us-east-1`. Cuenta AWS del equipo: `750702272375`. Ambos buckets los crea Terraform (`Proyecto2/terraform/main.tf`, módulos `s3` y `s3_releases`) con versionado, cifrado SSE y bloqueo de acceso público.

**Por qué no un bucket nuevo con prefijos `dvc/`, `mlflow/` y `models/`:** los dos buckets de la cuenta del equipo ya existen, con versionado y permisos por Terraform, y el remote `prod` de DVC ya apunta a uno de ellos. Moverlos cambiaría las URLs que citan `versions.json` y `decisiones.md` sin ganar nada. MLflow queda en volumen porque así se decidió en el kickoff (no depende de credenciales AWS para registrar corridas).

## Permisos

| Quién | Cómo se autentica | Permisos | Dónde se define |
|---|---|---|---|
| Integrantes (`dataset-quality-<nombre>`) | Perfil de `~/.aws` en su máquina | Lectura y escritura (`ListBucket`, `GetObject`, `PutObject`, `DeleteObject`) sobre los dos buckets | `Proyecto2/terraform/modules/team_access/main.tf` + política de `modules/oidc_github/main.tf:113` |
| CI (GitHub Actions) | Rol OIDC, sin llaves de larga vida | Igual que integrantes | `modules/oidc_github`, variable de repo `AWS_ROLE_ARN` |
| Evaluador (`dataset-quality-evaluator`) | Perfil de `~/.aws` | Solo lectura (`ListBucket`, `ListBucketVersions`, `GetObject`, `GetObjectVersion`) | `modules/team_access/main.tf` |

Como los buckets tienen versionado, un `DeleteObject` accidental deja un *delete marker* y el objeto se puede recuperar.

## Variables y archivos locales (solo nombres)

| Nombre | Dónde | Para qué | En Git |
|---|---|---|---|
| Perfil de AWS (p. ej. `p3-diego`) | `~/.aws/config` y `~/.aws/credentials` | Acceso de cada integrante | No (fuera del repo) |
| `profile` del remote `prod` | `Proyecto2/.dvc/config.local` | Que `dvc pull -r prod` use tu perfil | No (`Proyecto2/.dvc/.gitignore`) |
| `PROD_REGION` | `Proyecto2/.env` | Región del cliente S3 de P2 (`dataset_quality.storage.get_prod_s3_client`) | No; plantilla en `.env.example` |
| `AWS_PROFILE` | Entorno del proceso | Perfil que usa boto3 al leer releases o publicar modelos | No |
| `AWS_ROLE_ARN` | Variables de GitHub Actions | Rol OIDC de CI | No es secreto (ARN) |

## Recuperar el dataset desde un clon limpio

```bash
git clone <repo> && cd <repo>/Proyecto2
python -m venv .venv && . .venv/Scripts/activate      # Python 3.12
pip install -r requirements.lock.txt && pip install --no-deps -e .
aws configure --profile <tu-perfil>                     # llaves de TU usuario IAM, nunca en Git
dvc remote modify --local prod profile <tu-perfil>      # se escribe en .dvc/config.local (ignorado)
dvc pull -r prod data/raw.dvc
dvc status data/raw.dvc                                 # "Data and pipelines are up to date"
```

`dvc pull` sin `-r` usa el remote por defecto `dev` (MinIO local de P2), que en un clon limpio está vacío; para el release aprobado se usa siempre `-r prod`.

## Evidencia (T31)

| Comprobación | Resultado | Fecha |
|---|---|---|
| `dvc pull -r prod data/raw.dvc` + `dvc status data/raw.dvc` sin datos ni caché previos | 2047 archivos descargados del remote `prod`, 2046 agregados; "Data and pipelines are up to date". Perfil de Diego, solo lectura | 25 sep |
| Versionado de los buckets | `get-bucket-versioning` está fuera de la política de mínimo privilegio (AccessDenied para integrantes). Evidencia equivalente: `head-object` de `0.1.3/dataset.tar.zst` devuelve `VersionId riojb0ulsh1fzPYrMiAicAGps.5f1JBI`, que S3 solo asigna en buckets versionados; Terraform lo declara en `modules/s3/main.tf:20` | 25 sep |
| `aws s3api head-object` de `0.1.3/dataset.tar.zst` con `VersionId` | F1: `VersionId riojb0ulsh1fzPYrMiAicAGps.5f1JBI` ([decisiones.md §1](decisiones.md#1-release-dvc-de-origen)) | 24 sep |
| gitleaks sobre el historial tras el cambio | `ghcr.io/gitleaks/gitleaks` v8.30.1 (`sha256:c00b6bd0aeb3…`), `git --redact`: 159 commits escaneados, **no leaks found** | 25 sep |
