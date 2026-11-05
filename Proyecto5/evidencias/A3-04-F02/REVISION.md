# Segunda revisión de seq06-0028 — A3-04-F02

Seguimiento de [#29](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/29)
y [#41](https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/41).
Fecha: 2026-11-04. Revisor: asistente IA, sin firma humana atribuida.

**Resultado: discrepancia de holgura superior confirmada.** Se completa la
segunda inspección documental y visual de QA; no se certifica una aprobación
humana del responsable del dataset ni se crea una anotación de reemplazo.

## Entradas revisadas

- [Imagen original, 400 × 296](../../data/p5-eval-v1/secuencias/seq06/seq06-0028.jpg),
  inspeccionada directamente, además de la lámina histórica.
- [Lámina seq06](../A3-04/recalculo/laminas/seq06.jpg), último cuadro con imagen.
- [Registro inicial](../A3-04/revision_visual.csv), fila `seq06-0028`.
- [Política documentada](../../docs/A2_DATASET.md), paso 5; instrucciones del
  anotador `src/p5/dataset/anotar.py`; observación de la auditoría original.
- [Criterio explícito de esta revisión](../../docs/CRITERIO_ANOTACION.md).

La documentación histórica no cuantificaba una tolerancia de holgura. No puede
afirmarse retrospectivamente que se incumplió una regla numérica existente.
Se deja constancia del defecto visual bajo el criterio explícito actual.

## Inspección y decisión

La imagen contiene una persona a la izquierda. La clase y la correspondencia
de imagen son consistentes. El GT congelado es `person [44,0,111,144]`.
La parte superior visible de la cabeza comienza aproximadamente en `y=12`;
entre ella y el borde `y=0` hay fondo visible. Los 12 píxeles son una estimación
visual, no una coordenada nueva de anotación ni una medición automática.

La cabeza no está truncada por el borde superior. Parte del cuerpo inferior
se superpone visualmente al mobiliario, con contraste limitado; no se infieren
extremos ocultos. Esa incertidumbre inferior no justifica el fondo por encima
de la cabeza. El calzado visible y la posición de las piernas tampoco autorizan
copiar el extremo inferior más corto de la predicción.

Con el criterio de caja visible, **no se acepta esa holgura superior como un
margen intencional justificado**. Se registra una discrepancia localizada de
ajuste; no se afirma omisión, clase errónea ni que todos los demás bordes sean
exactos. Tampoco se afirma que el margen superior sea la única causa del IoU.

## Tratamiento de la discrepancia

Se conserva la anotación v1 por su condición de conjunto congelado, no por
aceptación visual del margen. No se propone una caja numérica alternativa:
esta tarea registra la discrepancia, que es una de las salidas previstas por
el cierre de F02. Una reanotación que decida el responsable corresponde a una
versión posterior y sigue el procedimiento de CRITERIO_ANOTACION.md.

No se creó un paquete v2 ni se recalcularon métricas con etiquetas modificadas.
No se ajustó el umbral. El cierre documental de esta observación no equivale
a corregir todas las etiquetas de v1 ni a cambiar el estado de #41 en GitHub.

## Verificación numérica y preservación

La predicción publicada conserva confianza `0.5792305472960777` y caja
`[39.90876919643592,5.412403140325433,88.18847337898944,113.37848747997954]`.
El recálculo independiente da IoU `0.47284356754785883`: con confianza e IoU
de corte 0.50 sigue siendo **0 TP, 1 FP y 1 FN**. No se ensayaron cajas
alternativas ni umbrales para cambiar ese resultado.

`verificacion.json` registra el commit base original y el commit ejecutado del PR,
runtime, hashes de entradas y del criterio,
inventario de los 128 cuadros y hashes del paquete antes y después del auditor.
Compara explícitamente las entradas protegidas entre ambos commits con
`git diff --exit-code BASE PR`, y separadamente el árbol local contra el commit
del PR. Ambas comprobaciones se repiten después del auditor. `recalculo/`
contiene la nueva ejecución del auditor existente, incluida la lámina.
La comprobación automática acredita integridad y aritmética; la decisión
visual corresponde a la inspección descrita arriba.

Desde Proyecto5, con el entorno Python 3.12 y dependencias fijadas:

```powershell
$env:PYTHONPATH = "src;../Proyecto3/src"
.venv312/Scripts/python evidencias/A3-04-F02/verificar_revision.py --output resultados/a3-04-f02-verificacion
.venv312/Scripts/python scripts/auditar_a3_04.py --output resultados/a3-04-f02-reproduccion --laminas
.venv312/Scripts/python -m p5.dataset.paquete validate --dataset data/p5-eval-v1
Get-FileHash data/p5-eval-v1/manifiesto.jsonl -Algorithm SHA256
git diff --exit-code -- data/p5-eval-v1 evidencias/a3-metricas-v1 evidencias/A3-04
```

El manifiesto esperado sigue siendo
`5dab9ee3f65cad0a1b31695d6d81c7a50c81fe3934f07572e53f64dc7e2ffeeb`.
La carpeta de salida debe ser nueva. El entorno local se llama `.venv312`;
puede usarse `.venv` si contiene esas mismas versiones.

El verificador rechaza `--output` dentro de `data/` o `evidencias/`, incluyendo
sus subcarpetas y rutas con `..`, antes de crear archivos o ejecutar el auditor.
Las salidas reproducidas deben ir en `resultados/` u otra carpeta externa a
esas entradas. Las pruebas de F02 incluyen rechazos de salida y repositorios
Git temporales donde un cambio ya comprometido deja limpio el árbol local;
ese cambio debe seguir siendo detectado frente a la base.
