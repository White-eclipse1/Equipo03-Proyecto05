# [A3-04-F02] Revisar criterio de caja visible en seq06-0028 sin modificar v1

Seguimiento de #29; observación de QA para el responsable del dataset.

## Observación concreta

En `data/p5-eval-v1/secuencias/seq06/seq06-0028.jpg` la anotación es
`person`, caja `xyxy=[44,0,111,144]`. La cabeza visible comienza aproximadamente
en y=12, mientras la caja empieza en y=0: hay margen vacío superior de unos
12 píxeles. La imagen y la clase corresponden; no se afirma objeto omitido.
Es una observación visual, pendiente de una segunda revisión con criterio
explícito sobre holgura y oclusión, no una corrección geométrica automática.

La predicción publicada tiene confianza `0.5792305472960777`, caja
`[39.90876919643592,5.412403140325433,88.18847337898944,113.37848747997954]`.
Su IoU con el GT congelado es `0.47284356754785883`, correctamente FP+FN a 0.50.
Esta observación no autoriza cambiar la caja para convertir el par en TP.

## Evidencia y reproducción

- `evidencias/A3-04/revision_visual.csv`, fila `seq06-0028`.
- `evidencias/A3-04/recalculo/laminas/seq06.jpg`, último cuadro de la lámina.
- `evidencias/A3-04/recalculo/auditoria.json`, pareja no emparejada de ese frame.
- Manifiesto SHA-256 `5dab9ee3f65cad0a1b31695d6d81c7a50c81fe3934f07572e53f64dc7e2ffeeb`.

```powershell
.venv/Scripts/python scripts/auditar_a3_04.py --output resultados/a3-04-caja --laminas
```

## Cierre propuesto

- Segunda revisión de la imagen original y de la política de anotación.
- Registrar aceptación de la holgura o la discrepancia justificada.
- Si corresponde corregir, hacerlo en una versión posterior del dataset,
  conservando intactos p5-eval-v1 y sus resultados; no ajustar el umbral.

Estado de este archivo: texto preparado; todavía no publicado como issue.
