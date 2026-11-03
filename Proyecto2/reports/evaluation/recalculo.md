# Recalculo independiente del dataset

Generado por `python scripts/recalculo_independiente.py`. La columna
**Reportado** sale de `reports/quality.json` y `reports/stats.json`, que escribe
`dataset_quality`. La columna **Recalculado** sale de leer
`data/raw/annotations.coco.json` y las imagenes desde cero, con un pHash
reimplementado sobre numpy: este script no importa `dataset_quality` ni
`imagehash`, asi que un error del analizador no puede propagarse a los dos lados.

| Metrica | Reportado | Recalculado | Coincide |
| --- | --- | --- | --- |
| totales.images | `2045` | `2045` | si |
| totales.annotations | `2120` | `2120` | si |
| totales.categories | `5` | `5` | si |
| cajas por clase | `bicycle=341, car=320, cat=329, dog=379, person=751` | `bicycle=341, car=320, cat=329, dog=379, person=751` | si |
| imagenes por clase | `bicycle=240, car=247, cat=312, dog=348, person=441` | `bicycle=240, car=247, cat=312, dog=348, person=441` | si |
| objetos pequenos (ratio) | `0.108962` | `0.108962` | si |
| objetos pequenos (cajas) | `231` | `231` | si |
| objetos pequenos (ids) | `231 ids: 5, 6, 18, 46, 59, 61, 83, 84, ... (+223)` | `231 ids: 5, 6, 18, 46, 59, 61, 83, 84, ... (+223)` | si |
| objetos pequenos por clase | `person=180, car=28, bicycle=23` | `person=180, car=28, bicycle=23` | si |
| sesgo espacial (celda mas poblada) | `0.674528` | `0.674528` | si |
| cajas degeneradas (ratio) | `0.000000` | `0.000000` | si |
| cajas degeneradas (ids) | `(vacio)` | `(vacio)` | si |
| desbalance (max/min) | `1.837500` | `1.837500` | si |
| duplicados (ratio) | `0.000000` | `0.000000` | si |
| duplicados (pares) | `0` | `0` | si |
| duplicados (copias sobrantes) | `0` | `0` | si |
| duplicados (ids sobrantes) | `(vacio)` | `(vacio)` | si |

> Sobre duplicados: en este dataset el valor correcto es cero, asi que la fila
> de arriba confirma que ambos lados coinciden en un negativo. Que el detector
> encuentre una copia CUANDO la hay se prueba aparte, inyectandola:
> `tests/test_mutaciones.py::test_mutacion_copia_recomprimida`.

## Comprobaciones extra que el pipeline no hace

- Anotaciones cuyo campo `area` del COCO no coincide con `ancho*alto` de su `bbox`: **0**.
- Imagenes del COCO sin archivo legible en `data/raw/images/`: **0** (se hashearon 2045).

## Veredicto

**Las 17 metricas coinciden.** El recalculo independiente reproduce exactamente lo que reporta el pipeline.
