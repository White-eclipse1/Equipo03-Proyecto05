# B1-03 — Por qué el detector pierde a la persona en C5 y C7

Ticket: #3. Continúa [B1-03_VALIDACION.md](B1-03_VALIDACION.md), que dejó pendiente recuperar a la persona en el detector.

## Estado

**La corrida acordada ya se hizo: pasan los 10 casos, y hay una reducción de velocidad falsa por revisar.** Ver [Resultado de la corrida](#resultado-de-la-corrida). El filtro ya está integrado al detector real, con métricas y benchmark nuevos: ver [Integración](#integración). **#3 sigue abierto:** falta aceptar la revisión y repetir la reproducción de #9.

No se cambiaron el modelo, los umbrales, la política, los datos ni las expectativas. Con `--filtro-mediana 0`, los casos corren sin el filtro.

## Conclusión

- **Causa:** en casi todos los cuadros que fallan, el modelo no da evidencia de la persona. La pérdida no viene del umbral, de NMS ni de la clase ganadora.
- **Solución propuesta:** aplicar un filtro de mediana 3×3 a la imagen antes del detector.
- **Resultado en `p5-ajuste-v1`:** las acciones no permitidas bajan de 13 a 0 con la misma política. Las personas firmes suben de 39 a 71 de 85.
- **Resultado en `p5-eval-v1`:** en la corrida única pasan C1–C10, C5 y C7 incluidos, y las acciones no permitidas bajan de 5 a 0. Aparece un SLOW falso de un cuadro en `seq06-0025`.
- **Falta:** confirmar si se acepta ese SLOW. El paquete de ajuste no tiene cuadros libres, así que esto solo se pudo ver en la evaluación.

## Dónde se pierde

Detector actual, sin filtro. *Crudo* es el mayor puntaje `person` del modelo sobre la caja anotada (IoU ≥ 0.50), antes del umbral de 0.10, de elegir clase y de NMS. Una detección es firme desde 0.50 y débil desde 0.30.

| Caso | Cuadro | Crudo | Salida del detector | Falla en ese cuadro |
|---|---|---|---|---|
| C5, persona derecha | `seq05` 5 | 0.830 | Firme | |
| | 6 | 0.069 | Nada | |
| | 7 | 0.002 | Nada | |
| | 8 | 0.006 | Nada | EVADE_RIGHT |
| | 9 | 0.000 | Nada | EVADE_RIGHT |
| | 10 | 0.000 | Nada | EVADE_RIGHT |
| C7, persona al centro | `seq06` 30 | 0.865 | Firme | |
| | 31 | 0.259 | Bajo `umbral_bajo` | No confirma el bloqueo |
| | 32 | 0.261 | Bajo `umbral_bajo` | |
| | 33 | 0.687 | Firme | |
| | 34 | 0.029 | Nada | |
| | 35 | 0.030 | Nada | |
| | 36 | 0.152 | Bajo `umbral_bajo` | FORWARD |
| | 37 | 0.727 | Firme | |
| | 38 | 0.018 | Nada | FORWARD |

- **Bajar umbrales no alcanza:** en los cuadros 6–10 de `seq05` y 34, 35 y 38 de `seq06` el puntaje crudo ya está por debajo del umbral de 0.10.
- **NMS y clase no son la causa:** en estas dos secuencias, ninguna persona anotada queda como `perdida_por_clase_o_nms`. En ajuste solo pasa una vez, de 85.
- **La política actúa según sus reglas:** con la vía sin evidencia durante 3 cuadros, libera la zona. Con cajas perfectas, C5 y C7 pasan.
- **El puntaje salta mucho entre cuadros:** en `seq06` 36–38 la caja anotada casi no cambia, y el puntaje pasa de 0.15 a 0.73 y luego a 0.02.

Todo está por persona y por cuadro en [capas_eval_sin_filtro.jsonl](../evidencias/B1-03-detector/capas_eval_sin_filtro.jsonl). `aj05` y `aj06` muestran el mismo patrón en [capas_ajuste_sin_filtro.jsonl](../evidencias/B1-03-detector/capas_ajuste_sin_filtro.jsonl).

## Comparación en `p5-ajuste-v1`

Se probaron 24 variantes de entrada con el mismo modelo y la misma política, sobre 70 cuadros y 85 personas anotadas. Ninguna variante corrió sobre `p5-eval-v1`, y `scripts/ajuste_detector.py` rechaza cualquier paquete que no sea de ajuste. Están todas en [ajuste_variantes.json](../evidencias/B1-03-detector/ajuste_variantes.json); estas son las que explican la decisión:

| Variante | No permitidas | Sin avance | Personas firmes | Inferencias por cuadro |
|---|---|---|---|---|
| Actual, sin filtro | 13 | 0 | 39 | 1 |
| **Mediana 3×3 (seleccionada)** | **0** | **7** | **71** | **1** |
| Mediana 5×5 | 0 | 11 | 81 | 1 |
| Gauss σ 1.0 más imagen volteada | 0 | 2 | 73 | 2 |
| Gauss σ 1.2 | 4 | 4 | 70 | 1 |
| Gauss σ 3.0 | 12 | 1 | 24 | 1 |
| Imagen volteada | 13 | 0 | 44 | 2 |
| Mosaico de recortes | 13 | 0 | 39 | 4 |
| CLAHE | 15 | 0 | 31 | 1 |
| Gamma 0.7 | 18 | 0 | 24 | 1 |

- **Lectura:** quitar ruido fino ayuda; subir el contraste empeora, y más vistas o más escala casi no cambian nada. Esto apunta a que el modelo es sensible al ruido de la imagen. Es una inferencia: no se separó si viene del sensor OV2640 o del JPEG.
- **Criterio:** primero menos *no permitidas*, luego menos inferencias por cuadro y luego menos *sin avance*. **Se fijó después de ver el barrido**, y pone el costo antes que el avance.
- **Alternativa descartada:** Gauss con imagen volteada avanza más, pero duplica la inferencia: cerca de 123 ms por cuadro contra 58–72 ms, en una medición informal en un laptop. El filtro de mediana solo suma unos 0.16 ms.
- **Política:** con la mediana, `p5.policy.ajuste` no encuentra una configuración mejor que la actual, así que no hay que tocar `politica.yaml`.

Los 7 cuadros *sin avance* son acciones permitidas con la persona en el lateral derecho:

| Cuadros | Acción | Por qué |
|---|---|---|
| `aj05` 16–18 | STOP | La persona acaba de salir del centro y la zona aún no se libera |
| `aj05` 23 y 24, `aj06` 5 y 16 | EVADE_LEFT | Evade hacia el lado contrario a la persona |

Son seguros, pero el carro avanza menos en esos cuadros.

## Límites

1. **C5 y C7 solo se comprobaron en una corrida.** Ver [Resultado de la corrida](#resultado-de-la-corrida).
2. **El ajuste no prueba la vía libre.** Sus cuadros son `centro`, `lateral_derecha` y `varios`, ninguno `libre`. Por eso la vía libre se revisó en C1 y en `seq06` 1–26 y 49–50.
3. **Falsos positivos:** no se pueden calcular en ajuste, porque `aj05` y `aj06` tienen personas sin etiquetar ([A2_DATASET.md](A2_DATASET.md)).
4. **Muestra pequeña:** son 70 cuadros de 3 escenas, quizá del mismo edificio que la evaluación, y 24 variantes. El resultado de ajuste puede ser optimista.
5. **Se miró `p5-eval-v1`:** este diagnóstico leyó los puntajes del detector actual en `seq05` y `seq06`, pero eso no eligió el filtro.
6. **Medición anterior:** [B1-03_VALIDACION.md](B1-03_VALIDACION.md) ya hizo una medición única en eval con otra configuración de política. Esta sería una segunda, de un cambio distinto.
7. **Alcance del filtro:** cuando se hizo la corrida, solo lo aplicaba el runner de casos. Ver [Integración](#integración).

## Condición para aprobarla como solución de #3

**La única corrida acordada en `p5-eval-v1` ya se hizo, y no hay que repetirla.** Usó el comando de [Medición en evaluación](#medición-en-evaluación). Sus resultados y trazas están en [c1-c10-mediana3/](../evidencias/B1-03-detector/c1-c10-mediana3/): `resultados.json` y `decisiones.jsonl`, sin editar.

Lo que se acordó revisar, y lo que mostró:

| Qué se revisó | Dónde | Sin filtro | Qué debía mostrar | Con filtro |
|---|---|---|---|---|
| C1 | `seq01`, 15 cuadros libres | 13 FORWARD y 2 STOP de arranque | Si el filtro detiene al carro sin obstáculo | Sin cambios |
| C5 | `seq05` | EVADE_RIGHT en 8, 9 y 10 | Ninguna evasión hacia la persona de la derecha | Se cumple: 13 EVADE_LEFT y 2 STOP de arranque |
| C7, bloqueo | `seq06` 30–44 | Sin BLOCKED en 30–31; FORWARD en 36 y 38 | Bloqueo en el plazo y ningún FORWARD con la persona al centro | Se cumple: bloquea en el cuadro 31 |
| Tramos libres de `seq06` | Cuadros 1–26 y 49–50 | 24 FORWARD y 2 STOP de arranque; 2 FORWARD | Si el filtro detiene al carro sin obstáculo | No lo detiene, pero hay un SLOW falso en el cuadro 25 |

**Que C1 y C7 digan `PASA` no basta para la vía libre.** Sus reglas piden al menos un avance en el rango, y STOP siempre está permitido, así que un STOP de más no los hace fallar. Por eso esos tramos se compararon cuadro por cuadro en `decisiones.jsonl` contra [c1-c10-sin-filtro/](../evidencias/B1-03-detector/c1-c10-sin-filtro/), y cada diferencia quedó anotada con su detección en [Resultado de la corrida](#resultado-de-la-corrida).

**Para aprobarla como solución de #3 falta:**
1. Que Andrés y Omar confirmen si aceptan el SLOW falso de `seq06-0025`.
2. Revisar la integración del filtro al detector real, con métricas y benchmark nuevos. Ver [Integración](#integración).
3. La reproducción final de #9.

Cualquier cambio posterior se elige otra vez con `p5-ajuste-v1`: esta corrida no se repite con otros valores.

## Resultado de la corrida

Corrida única sobre `62a1bf3`, en una copia limpia, con Python 3.12.16, dependencias fijadas, Windows 11 y solo CPU. Los archivos de [c1-c10-mediana3/](../evidencias/B1-03-detector/c1-c10-mediana3/) son los que escribió el runner, sin editar. Antes de correrla, la misma copia reprodujo la referencia sin filtro: las 155 filas de decisiones son iguales, salvo el campo `comando`, que trae la hora de emisión.

**10 pasan, 0 fallan y 0 pendientes.** Ninguna decisión queda fuera de las acciones permitidas por el manifiesto; sin filtro eran 5.

| Tramo | Cuadros | Sin filtro | Con filtro | Lectura |
|---|---:|---|---|---|
| C1, `seq01` | 15 | 13 FORWARD y 2 STOP | 13 FORWARD y 2 STOP | Sin cambios |
| C5, `seq05` | 15 | 10 EVADE_LEFT, 3 EVADE_RIGHT y 2 STOP | 13 EVADE_LEFT y 2 STOP | Ya no evade hacia la persona de la derecha |
| `seq06` libre, 1–26 | 26 | 24 FORWARD y 2 STOP | 23 FORWARD, 1 SLOW y 2 STOP | **Una reducción falsa, en el cuadro 25** |
| `seq06` bloqueo, 30–44 | 15 | 8 SLOW, 5 EVADE_RIGHT y 2 FORWARD | 14 EVADE_RIGHT y 1 SLOW | Bloquea en el cuadro 31; ya no avanza con la persona al centro |
| `seq06` libre, 49–50 | 2 | 2 FORWARD | 2 FORWARD | Sin cambios |

Los STOP de los tramos libres son los 2 de arranque. **No aparece ningún STOP nuevo con la vía libre.**

Estas son las 14 decisiones que cambian:

| Cuadro | Sin filtro | Con filtro | Detección con filtro (≥ 0.30) |
|---|---|---|---|
| `seq02-0017` | FORWARD, VIA_LIBRE | SLOW, LATERAL_OCUPADO | Ninguna; recuerda a la persona que ahora sí ve a la izquierda en el cuadro 15 |
| `seq05-0008` | EVADE_RIGHT | EVADE_LEFT | person 0.92 y 0.81 |
| `seq05-0009` | EVADE_RIGHT | EVADE_LEFT | person 0.92 y 0.64 |
| `seq05-0010` | EVADE_RIGHT | EVADE_LEFT | person 0.91 y 0.53 |
| **`seq06-0025`** | **FORWARD, VIA_LIBRE** | **SLOW, CENTRO_DEBIL** | **`truck` 0.44, débil, al centro: no hay ningún camión** |
| `seq06-0031` a `0032` | SLOW | EVADE_RIGHT | person 0.88 |
| `seq06-0033` | SLOW | EVADE_RIGHT | person 0.89 |
| `seq06-0034` a `0037` | SLOW o FORWARD | EVADE_RIGHT | person de 0.76 a 0.84 |
| `seq06-0038` | FORWARD | EVADE_RIGHT | Ninguna; el bloqueo se mantiene por la histéresis |
| `seq06-0039` | SLOW | EVADE_RIGHT | person 0.86 |

**Lo que hay que decidir:** `seq06-0025` es una detección falsa que causa un SLOW de un cuadro con la vía libre. Es una acción permitida y el carro no se detiene, pero el filtro sí la introduce. Falta aceptarla o rechazarla; no se ajustó nada para evitarla, porque eso sería elegir mirando la evaluación.

**Límites:**
- **`seq05` y `skateboard`:** el filtro también produce `skateboard` hasta 0.54 en `seq05` y 0.33 en `seq06`. Es una clase que la política ignora, así que no cambia decisiones, pero muestra que el filtro altera más que a las personas.
- **Muestra:** son 43 cuadros libres en C1 y C7, de dos escenas. Una sola detección falsa en ellos no permite estimar una tasa.
- **Era el runner:** en esta corrida, el filtro solo estaba en el runner. Ver [Integración](#integración).

Para repetir la comparación, desde `Proyecto5`:

```powershell
.venv\Scripts\python scripts\comparar_decisiones.py --con evidencias\B1-03-detector\c1-c10-mediana3\decisiones.jsonl --sin evidencias\B1-03-detector\c1-c10-sin-filtro\decisiones.jsonl
```

```bash
.venv/bin/python scripts/comparar_decisiones.py --con evidencias/B1-03-detector/c1-c10-mediana3/decisiones.jsonl --sin evidencias/B1-03-detector/c1-c10-sin-filtro/decisiones.jsonl
```

## Integración

El filtro pasó a `YoloxDetector`, encendido por defecto, en `39e72ad`. Ahora lo usan los casos, las métricas, el benchmark y el recorrido. `scripts/ajuste_detector.py` y `scripts/diagnostico_perdidas.py` siguen midiendo el modelo sin filtro, porque describen la decisión original.

- **Mismas decisiones:** con el detector integrado, C1–C10 repite la corrida acordada: las 155 filas son iguales, salvo la hora de emisión del comando.
- **Métricas:** F1 pasa de 0.8153 a 0.9486. Ver [A3_METRICAS.md](A3_METRICAS.md).
- **Benchmark:** nueva medición oficial en [A3-03_BENCHMARK.md](A3-03_BENCHMARK.md).
- **Corrección posterior:** `python -m p5.detector --filtro-mediana 0` no apagaba el filtro en `39e72ad`. Se corrigió solo ese comando, que no interviene en los casos, las métricas ni el benchmark, así que su evidencia sigue siendo válida.
- **Evidencia anterior:** queda sin cambios como referencia. `verificar_a3_04_f01.py` sigue comparando la repetición con Python 3.12 contra esa evidencia sin filtro, y describe al detector anterior.

## Cómo repetirlo

Desde `Proyecto5`, con la preparación del README.

### Comparación en ajuste

```powershell
.venv\Scripts\python scripts\ajuste_detector.py --output resultados\ajuste_variantes.json
```

### Dónde se pierde cada persona

```powershell
.venv\Scripts\python scripts\diagnostico_perdidas.py --dataset data\p5-eval-v1 --sequences seq05,seq06 --output resultados\capas_eval.jsonl
```

### Medición en evaluación

Ya se corrió, una sola vez, y no hay que repetirla. La selección quedó congelada en `b95612f`, antes de medir. Este fue el comando:

```powershell
.venv\Scripts\python -m p5.casos.runner --cases casos\c1_c10.yaml --config config\politica.yaml --dataset data\p5-eval-v1 --weights models\yolox_tiny.onnx --filtro-mediana 3 --output resultados\c1-c10-mediana3
```

`resultados.json` registra `filtro_mediana_detector`. La referencia sin filtro, sobre `8e76180`, está en [c1-c10-sin-filtro/](../evidencias/B1-03-detector/c1-c10-sin-filtro/): 8 pasan, 2 fallan (C5 y C7) y 0 pendientes.

## Qué sigue

**Si C1–C7 pasan y la revisión de los tramos libres la acepta:**

1. Aprobar la propuesta con esa evidencia, incluida la decisión sobre `seq06-0025`.
2. Mover el filtro a `src/p5/detector` y activarlo por defecto. Hecho.
3. Generar de nuevo la evidencia de métricas. Hecho: `evidencias/a3-metricas-mediana3/`.
4. Repetir el benchmark, hecho, y la reproducción de #9, pendiente.
5. Revisar #3 con esa evidencia.

**Si C5 o C7 siguen fallando:**

1. Guardar los resultados y las trazas, y documentar la causa.
2. Mantener #3 abierto.
3. No probar otra variante mirando `p5-eval-v1`: cualquier cambio nuevo se elige otra vez con ajuste.
