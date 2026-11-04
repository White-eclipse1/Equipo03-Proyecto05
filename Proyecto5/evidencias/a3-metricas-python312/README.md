# A3-04-F01 — Inferencia en Python 3.12 soportado

Seguimiento de [#29](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/29),
[#40](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/40),
relacionado con [#16](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/16)
y [#17](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/17).
Fecha local: 2026-11-04. **Cierre técnico F01: completo.**

Se ejecutó el evaluador existente con el detector real sobre los 128 cuadros,
sin reutilizar predicciones como entrada y sin calibrar con evaluación.

| Dato | Resultado |
|---|---|
| Commit del evaluador | `7b4adb45b85483cf0a65e1cf275fa3ba5cc4bede` |
| Run | `2c12ae75ecda419bb0f9601f5357ad3b` |
| Runtime | Python 3.12.16, Windows AMD64, CPU |
| Dependencias | Todas las versiones de requirements.lock.txt verificadas en comparacion.json |
| Manifiesto SHA-256 | `5dab9ee3f65cad0a1b31695d6d81c7a50c81fe3934f07572e53f64dc7e2ffeeb` |
| Modelo SHA-256 | `427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7` |
| Predicciones SHA-256 | `b97a6814620aba4686e1d6c67d3c1601678228cb41fed5543c55b4e67bab4cc5` |
| Umbrales conservados | Confianza 0.50, IoU 0.50, detector 0.10, NMS 0.45 |
| TP / FP / FN | 64 / 2 / 27 |
| Precision / Recall / F1 | 0.9696969696969697 / 0.7032967032967034 / 0.8152866242038217 |
| Errores de inferencia | 0 |

## Comparación y trazabilidad

`comparacion.json` verifica las versiones instaladas contra el lock, los hashes
del modelo y manifiesto, y que el código del evaluador y dataset no cambiaron
desde el commit declarado. Registra hashes del código fuente, configuración
del entorno, verificador y artefactos históricos y nuevos.

Los cuatro artefactos históricos siguen idénticos a sus blobs de Git.
Las nuevas predicciones, resultados por cuadro y CSV son idénticos byte a byte
a la ejecución histórica `1b625493b15d428d9a216ec308db7699` en Python 3.13.15.
En `metricas.json` solo cambia `ejecucion`: run, fecha, commit y runtime.
No hay diferencias numéricas ni de detecciones que documentar.

El auditor independiente se aplicó a todos los 128 cuadros nuevos, comprobando
emparejamientos, IoU, TP/FP/FN y P/R/F1. `fallos_auditoria` está vacío.
`auditoria-historica/` conserva además la reproducción de la auditoría original;
su observación de Python 3.13 describe la fuente histórica, que sigue intacta.

## Reproducción

Desde Proyecto5, usando un entorno Python 3.12 con requirements.lock.txt instalado.
En esta máquina ese entorno es `.venv312`; cada salida debe ser nueva.

```powershell
$env:PYTHONPATH = "src;../Proyecto3/src"
.venv312/Scripts/python -m p5.detector.weights --verify-only
.venv312/Scripts/python -m p5.metrics --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --score-threshold 0.50 --output resultados/a3-f01-inferencia
.venv312/Scripts/python scripts/verificar_a3_04_f01.py --evidence resultados/a3-f01-inferencia --output resultados/a3-f01-comparacion.json
$env:P5_DETECTOR_WEIGHTS = (Resolve-Path models/yolox_tiny.onnx).Path
.venv312/Scripts/python -m pytest tests/test_metrics.py tests/test_audit_a3_04.py
```

Los metadatos identifican el commit ejecutado, no el futuro commit que incorpore
esta evidencia. No se modificó el evaluador para producir esta repetición.
Verificación: **52 pruebas aprobadas**, incluidas las de inferencia real de
métricas; reporte JUnit en `pruebas.xml`. Ruff, formato y `git diff --check`
correctos. Dataset, evidencia histórica, evaluador y lock sin modificaciones.
Este resultado resuelve la discrepancia de entorno; conserva las limitaciones
de clase única, cuadros correlacionados y observaciones de cajas de #41.
Los enlaces documentan el seguimiento; no se publicó ni cerró ningún issue.
