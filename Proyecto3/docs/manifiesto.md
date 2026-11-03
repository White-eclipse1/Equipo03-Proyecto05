# Manifiesto 70/20/10 — `m-0.1.3-s42-1` (F3 T08)

Manifiesto derivado del release aprobado **0.1.3** de P2: una fila por recorte con su partición `train` / `val` / `test` (criterio 1.3, compuerta M3). Es un manifiesto **nuevo**: no sobrescribe ni reutiliza el split 70/15/15 de P2.

## Identidad y procedencia

| Campo | Valor |
|---|---|
| `manifest_id` | `m-0.1.3-s42-1` |
| `manifest_hash` (SHA-256 de `manifest.jsonl`) | `45600f297d13f51685e051e0cbc4962beb1f7c6a4e03247cbf61a345e6fa4305` |
| Semilla | `42` |
| Release de origen | `0.1.3`, `quality_status: pass` |
| `dataset_fingerprint` | `2200274dc6bbe6d0bc516e0136ae68651c0040bc6cab64a871794924fa39aa84` |
| `archive_sha256` del release | `787742988af1df41d9a58573b81b5c9b4fe7ab24a647b25f2e71d3eb323838b5` |
| Imágenes del release (DVC) | `Proyecto2/data/raw.dvc`, md5 `ca56420c9992f8b75fdb10f2ece81704.dir`, 2046 archivos; el script exige `dvc status` limpio antes de generar |
| Split 70/15/15 de P2 al que se vincula | `splits_fingerprint 9a87e0de3fb3069f06686065f149d64787593c04d90265a3e0f667a170d66279` |
| Clases | `config/classes.yaml`: cat (0), dog (1), person (2) |
| Versionado | DVC en `Proyecto3/` (remote `prod`, `s3://dataset-quality-dvc-cache-750702272375`); puntero [`data/manifests/m-0.1.3-s42-1.dvc`](../data/manifests/m-0.1.3-s42-1.dvc), md5 `64eae7e52ddd9c73261680c860805494.dir` |

Todo esto va también dentro de `manifest.meta.json`, junto con `created_at`, `code_commit` (`c2002f6`, el commit exacto del código que lo generó: el script se niega a correr con cambios sin commit), las 661 exclusiones (todas `excluded_category`: car y bicycle) y los conteos.

## Cómo se reparte (`src/p3/data/split.py`)

1. **Unidad indivisible = grupo de casi duplicados.** Todos los recortes de un original van juntos, y todos los originales de un grupo de pHash también. Los grupos salen del código de P2 (`dataset_quality.analyzers.duplicates.duplicate_groups`) con el umbral de `Proyecto2/quality.yaml` (distancia de Hamming ≤ 5 de 64 bits). El id del grupo es `g<menor image_id>`.
2. **Estrato = clase más minoritaria de la unidad** (por recortes en el release), como en los splits de P2.
3. **Por estrato:** orden por `dup_group_id`, barajado con `random.Random(42)` y cada unidad a la partición con mayor déficit de recortes respecto a 70/20/10.

**Casi duplicados en 0.1.3:** P2 no encontró ningún par a distancia ≤ 5 (su reporte de calidad dice lo mismo: `duplicates pass, 0 pares`), así que cada original forma su propio grupo. A distancia ≤ 10 habría 2 pares; el umbral no se cambia porque es la política declarada de P2.

## Conteos por clase y partición

**Recortes**

| Clase | train | val | test | Total |
|---|---:|---:|---:|---:|
| cat | 230 | 67 | 32 | 329 |
| dog | 263 | 78 | 38 | 379 |
| person | 529 | 147 | 75 | 751 |
| **Total** | **1022 (70.05 %)** | **292 (20.01 %)** | **145 (9.94 %)** | **1459** |

**Originales distintos**

| Clase | train | val | test |
|---|---:|---:|---:|
| cat | 221 | 63 | 28 |
| dog | 240 | 74 | 34 |
| person | 302 | 92 | 47 |

Cada clase tiene recortes en `val` y en `test`. La desviación global máxima es 0.06 puntos (test), muy por debajo de ±5.

## Evidencia de aislamiento (M3)

Intersecciones calculadas directamente sobre `manifest.jsonl`, con un cálculo independiente del generador:

| Identificador | train ∩ val | train ∩ test | val ∩ test |
|---|---:|---:|---:|
| `crop_id` | 0 | 0 | 0 |
| `source_image_id` | 0 | 0 | 0 |
| `dup_group_id` | 0 | 0 | 0 |

La aumentación no crea filas: se aplica en memoria y solo a `train` (F4). El test no se usa para nada hasta la evaluación final (F6).

## Reproducibilidad

```bash
cd Proyecto2
PYTHONPATH="../Proyecto3/src;src" .venv/Scripts/python ../Proyecto3/scripts/generate_manifest.py --release 0.1.3 --profile <perfil-aws> --check
```

Resultado (26 sep 2026): `m-0.1.3-s42-1: regenerado 45600f29…; escrito identico: True`. Misma semilla y mismo release dan el mismo archivo byte a byte.

Para recuperar el manifiesto en un clon limpio: `cd Proyecto3 && dvc pull data/manifests/m-0.1.3-s42-1.dvc` (con un perfil de AWS configurado en `.dvc/config.local`).

## Pruebas

`tests/test_split.py`: las filas cumplen el contrato; ningún identificador en dos particiones; ±5 puntos global y por clase; cada clase en `val` y `test`; misma semilla → mismo hash; el orden de entrada no importa; la caja degenerada del fixture no llega al manifiesto. `check_manifest` detecta un original en dos particiones, una clase ausente de `test` y proporciones fuera de tolerancia.

Mutaciones: repartir por imagen (fuga real), ignorar la semilla, no barajar, no estratificar, no revisar `dup_group_id`, quitar la tolerancia y no exigir clases en `test` ponen la suite en rojo. Una mutación que arma mal las unidades pero sigue asignando por `dup_group_id` queda en verde: no produce fuga, porque cada fila toma la partición de su grupo.

## Segundo manifiesto congelado: `m-0.1.3-s7-1` (F12, criterio 1.1)

Mismo release 0.1.3 con **semilla 7**, para demostrar que elegir otro manifiesto cambia el split. Los releases 0.1.2, 0.1.4 y 0.1.5 tienen la misma huella que 0.1.3, así que con ellos los conteos no cambiarían: solo la semilla los cambia.

| | `m-0.1.3-s42-1` (barrido) | `m-0.1.3-s7-1` |
|---|---|---|
| `manifest.jsonl` (SHA-256) | `45600f29…` | `c7319207ae60b636e8ef45cd0a6f904e3c2b07755e9536fd2eded140a5089f01` |
| Puntero DVC (md5) | `64eae7e5….dir` | `82a38b4019bfecc9c25bcb12e98aa3d4.dir` |
| Recortes train / val / test | 1022 / 292 / 145 | 1020 / 291 / 148 |
| Intersecciones (9) | 0 | 0 |
| Reproducible (`--check`) | sí | sí, idéntico byte a byte |

Generado con `generate_manifest.py --release 0.1.3 --seed 7` sobre el árbol limpio de `fix/ronda-2` (`002a8aa`). Se entrena **solo en `p3-pruebas`**: `p3-clasificador` es el barrido sobre `m-0.1.3-s42-1`, y el worker rechaza otro manifiesto en ese experimento (409), así que `/api/p3/runs` y la selección no cambian.
