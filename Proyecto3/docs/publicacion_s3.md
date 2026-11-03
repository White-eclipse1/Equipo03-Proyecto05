# Publicación del modelo en AWS S3 — F7 (T17, T18)

Paquetes del modelo publicados en S3 real, recuperables y verificados (criterios 5.1–5.3). Sin credenciales en el repo: el perfil de `~/.aws` de cada integrante (ver [almacenamiento.md](almacenamiento.md)).

## Versiones publicadas

`s3://dataset-quality-releases-750702272375/models/clasificador/` (bucket con versionado):

| Versión | Corrida | ¿Seleccionada? | SHA-256 de `model.pt` | `VersionId` de `model.pt` | `VersionId` de `MODEL_CARD.md` | Activa |
|---|---|---|---|---|---|---|
| **1.0.0** | r10 `9f9b62c202f0446a8a4b411a10321eff` | Sí (`selection.json`), accuracy en test 0.9793 | `e4acca429ebf73d0e5a60fb0dda383a6a5322dccb1decf04b4e40ab9db989172` | `VtRww5se97lomVTcKJUv6d9mYSL7TXOf` | `7LNRNnVo01WUgE.aDEHjCya.n7fnDWZg` | **Sí** |
| 0.9.0 | r08 `5ebc2c9f94fa491e9e9adc7b7c8184ac` | No: empató con r10 en `val_accuracy` y perdió por `val_loss`. **Sin evaluación en test** | `ab4d1f4452cfa716a452844f8f0263ebc7647cd7b3820e7d53d3e0fef1608bd8` | `ElFQBtWzSAoR0zJAk7av.PR00H_v2OeI` | `_pvyZGAx7b0__trMMToT4b1A9ARs2fUx` | No |

Cada carpeta `<versión>/` trae `model.pt`, `class_map.json`, `preprocessing.json`, `config.json`, `requirements.lock.txt`, `MODEL_CARD.md` y `model_version.json` (contratos §6). `registry.json` guarda para cada versión la corrida, el manifiesto, la llave, el SHA-256 y el `VersionId` de cada archivo, y la versión activa (la lee el servicio de inferencia de F4).

**Por qué 0.9.0 es r08 y no otro empaquetado de r10:** la rúbrica (5.3) pide que una versión anterior siga recuperable y que *cambiar la versión cambie el artefacto cargado*. Con los mismos pesos, cambiar de versión no cambiaría las predicciones. r08 es el otro candidato empatado en validación. Para no usar el test para comparar modelos, **solo 1.0.0 se evaluó en test**: el paquete de 0.9.0 lleva `test_metrics: null` y su tarjeta lo explica (`p3.registry.package` rechaza métricas de test en una versión no seleccionada).

## Cómo se publicó

```bash
cd Proyecto3
../Proyecto2/.venv/Scripts/dvc pull mlflow_snapshot.dvc          # corridas y checkpoints
.venv/Scripts/python scripts/publish_model.py --version 0.9.0 --run-id 5ebc2c9f94fa491e9e9adc7b7c8184ac --profile <perfil>
.venv/Scripts/python scripts/publish_model.py --version 1.0.0 --selected --activate --profile <perfil>
```

`p3.registry.publish.publish_version` sube cada archivo, confirma con `head-object` que existe con el tamaño esperado, descarga `model.pt` y compara su SHA-256 con el local y con `model_version.json`. **Solo entonces** escribe `registry.json`. Si algo falla, el registro no cambia, y nunca se marca publicado un objeto inexistente (6.4). Las versiones son inmutables.

**Incidencia:** el primer intento de 0.9.0 se detuvo antes de escribir el registro. La política del equipo no incluye `s3:GetObjectVersion` (la del evaluador sí), así que no se puede pedir una versión concreta. `scripts/publish_model.py` descarga la versión actual y exige que su `VersionId` sea el recién subido (`6fef274`). Después se reintentó.

## Verificación independiente (5.2)

Con la CLI de AWS (solo lectura, perfil de Diego), 27 sep 2026:

```text
head-object 0.9.0/model.pt       -> VersionId ElFQBtWzSAoR0zJAk7av.PR00H_v2OeI  44783563 bytes
head-object 0.9.0/MODEL_CARD.md  -> VersionId _pvyZGAx7b0__trMMToT4b1A9ARs2fUx  4217 bytes
head-object 1.0.0/model.pt       -> VersionId VtRww5se97lomVTcKJUv6d9mYSL7TXOf  44783563 bytes
head-object 1.0.0/MODEL_CARD.md  -> VersionId 7LNRNnVo01WUgE.aDEHjCya.n7fnDWZg  4836 bytes
aws s3 cp (descarga) -> sha256sum 0.9.0/model.pt = ab4d1f44…8bd8   (igual al registro)
                        sha256sum 1.0.0/model.pt = e4acca42…9172   (igual a selection.json)
```

**Carga e inferencia en un entorno limpio:** venv nuevo instalado solo con `requirements.lock.txt`, sobre los paquetes descargados de S3, con el código de la sección "Cómo cargarlo" de cada tarjeta y un recorte de **validación** (`0.1.3:a1330`, `dog`):

| Versión | cat | dog | person |
|---|---:|---:|---:|
| 1.0.0 | 0.0514 | **0.9438** | 0.0048 |
| 0.9.0 | 0.0963 | **0.8501** | 0.0536 |

La probabilidad de 1.0.0 (`dog` 0.943828) coincide con la que midió F4 para el mismo recorte con el servicio de inferencia. Las dos versiones dan probabilidades distintas: cambiar de versión cambia el modelo cargado.

`tests/test_publish.py::test_activar_otra_version_cambia_el_modelo_que_usa_la_inferencia` prueba lo mismo contra el `InferenceService` de F4.

## Pendiente: permiso `s3:GetObjectVersion` para el equipo

El servicio de inferencia (F4) pide cada `model.pt` por su `VersionId`, y la política de los integrantes (`Proyecto2/terraform/modules/oidc_github/main.tf`, `ReadWriteDvcObjects`) no incluye `s3:GetObjectVersion`. **Con el perfil de un integrante, el servicio recibirá AccessDenied.** Hay dos opciones:
- agregar `s3:GetObjectVersion` a esa política y aplicarla (`terraform apply`, lo hace quien administra la cuenta);
- que el servicio descargue la versión actual y compare el `VersionId`, como el script de publicación.

El usuario de solo lectura del evaluador sí tiene el permiso.
