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

Publicado como [issue #40](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/40).

## Cierre técnico verificado — 2026-11-04

Se completaron los cuatro puntos del cierre propuesto. La nueva inferencia y
su comparación están en [a3-metricas-python312](../../evidencias/a3-metricas-python312/README.md),
enlazadas al seguimiento de [#29](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/29).
Python 3.12.16 y todas las dependencias coinciden con las versiones fijadas.
Se conservaron manifiesto, modelo y umbrales; las predicciones y resultados
por cuadro son idénticos byte a byte a los históricos. Se reproducen 64 TP,
2 FP y 27 FN, sin errores, también mediante el auditor independiente sobre
los 128 cuadros. La ejecución histórica no se sobrescribió.

El cierre se refiere a la discrepancia de entorno F01. Las observaciones de
cajas F02 y las limitaciones del dataset conservan su alcance propio.
Este registro local no cambia el estado del issue en GitHub.
