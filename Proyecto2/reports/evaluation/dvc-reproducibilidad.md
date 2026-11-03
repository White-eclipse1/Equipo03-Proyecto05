# Reproducibilidad del pipeline DVC

Generado por `python scripts/evidencia_dvc.py` el 2026-09-18T19:24:38+00:00.

Alcance: **grafo completo**.

## Veredicto

**El pipeline es reproducible.** La segunda corrida de `dvc repro` no
ejecuto ninguna etapa y los hashes de `dvc.lock` no se movieron.

| Comprobacion | Resultado |
| --- | --- |
| Etapas ejecutadas en la 1a corrida | ninguna |
| Etapas ejecutadas en la 2a corrida | ninguna |
| Hashes de `dvc.lock` estables | si |
| Cache local contra remote `dev` | en sincronia |
| Cache local contra remote `prod` | en sincronia |

## Hashes de salida registrados en `dvc.lock`

Son los mismos en DEV y en PROD porque el hash lo determina el CONTENIDO,
no el destino: `dvc status -r dev` y `-r prod` contrastan este mismo cache
local contra cada remote.

| Etapa | Salida | md5 |
| --- | --- | --- |
| analyze | `reports/exploration.json` | `b92a0527a081cdc041235621e3726552` |
| analyze | `reports/stats.json` | `5cf7c4517ea6476f89b518c6c6facabb` |
| gate | `reports/quality.json` | `2426fc8a8fe438edbd080cf49a4bc118` |
| split | `reports/splits.json` | `4c78ae41d5381a252741726e64fbf072` |
| release | `reports/versions.json` | `9ac0de9cd34491abf5e05ff33eb72ebd` |

## Salida cruda de cada comando

### Primera corrida (grafo completo)

`$ C:\Users\angel\OneDrive\Documentos\semestre 9 intercambio\mlops\proyecto 2\ruta-al-dataset-v1\Proyecto2\.venv\Scripts\python.exe -m dvc repro` (exit 0)

```
Stage 'analyze' didn't change, skipping
Stage 'gate' didn't change, skipping
Stage 'split' didn't change, skipping
Stage 'release' didn't change, skipping
Data and pipelines are up to date.
```

### Segunda corrida (grafo completo)

`$ C:\Users\angel\OneDrive\Documentos\semestre 9 intercambio\mlops\proyecto 2\ruta-al-dataset-v1\Proyecto2\.venv\Scripts\python.exe -m dvc repro` (exit 0)

```
Stage 'analyze' didn't change, skipping
Stage 'gate' didn't change, skipping
Stage 'split' didn't change, skipping
Stage 'release' didn't change, skipping
Data and pipelines are up to date.
```

### Estado del grafo (grafo completo)

`$ C:\Users\angel\OneDrive\Documentos\semestre 9 intercambio\mlops\proyecto 2\ruta-al-dataset-v1\Proyecto2\.venv\Scripts\python.exe -m dvc status` (exit 0)

```
Data and pipelines are up to date.
```

### Estado contra el remote dev

`$ C:\Users\angel\OneDrive\Documentos\semestre 9 intercambio\mlops\proyecto 2\ruta-al-dataset-v1\Proyecto2\.venv\Scripts\python.exe -m dvc status -r dev` (exit 0)

```
Cache and remote 'dev' are in sync.
```

### Estado contra el remote prod

`$ C:\Users\angel\OneDrive\Documentos\semestre 9 intercambio\mlops\proyecto 2\ruta-al-dataset-v1\Proyecto2\.venv\Scripts\python.exe -m dvc status -r prod` (exit 0)

```
Cache and remote 'prod' are in sync.
```
