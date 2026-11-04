# [A3-04-F01] Repetir evidencia de métricas con Python 3.12 soportado

Seguimiento de #29; relacionado con #16 y #17.

## Observación reproducible

`Proyecto5/evidencias/a3-metricas-v1/metricas.json`, ejecución
`1b625493b15d428d9a216ec308db7699`, declara `Python 3.13.15`.
`Proyecto5/pyproject.toml` exige `>=3.12,<3.13`.
La fuente declara commit `0cf6dd9d35b567c92542681d820a7c9fd79f964c`.
La limitación ya aparece en `docs/A3_METRICAS.md`, pero falta evidencia de
inferencia en el entorno soportado. El auditor independiente reproduce
64 TP, 2 FP, 27 FN y P/R/F1 desde los artefactos; no detecta error aritmético.

## Reproducción

Desde Proyecto5:

```powershell
.venv/Scripts/python scripts/auditar_a3_04.py --output resultados/a3-04-entorno
Get-Content evidencias/a3-metricas-v1/metricas.json
Get-Content pyproject.toml
```

## Cierre propuesto

- Ejecutar el evaluador existente con Python 3.12 y las dependencias fijadas.
- Conservar el manifiesto `5dab9ee3f65cad0a1b31695d6d81c7a50c81fe3934f07572e53f64dc7e2ffeeb`,
  modelo y umbrales publicados: no calibrar con evaluación.
- Guardar la ejecución nueva en otra carpeta y comparar contra la evidencia
  histórica, documentando diferencias si aparecen. No sobrescribirla.
- Registrar commit, versiones y hashes de la nueva ejecución y enlazarla a #29.

Estado de este archivo: texto preparado; todavía no publicado como issue.
