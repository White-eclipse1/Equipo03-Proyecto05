# B1-03 — Por qué el detector pierde a la persona en C5 y C7

Ticket: #3. Continúa [B1-03_VALIDACION.md](B1-03_VALIDACION.md), que dejó pendiente recuperar a la persona en el detector.

## Estado

**Es una propuesta, no la solución de #3.** Todavía no está medida en `p5-eval-v1`, y #3 sigue abierto. Para aprobarla como solución hace falta la evidencia de [la corrida acordada](#condición-para-aprobarla-como-solución-de-3).

No se cambiaron el modelo, los umbrales, la política, los datos ni las expectativas, y sin `--filtro-mediana` el detector se comporta igual que antes.

## Conclusión

- **Causa:** en casi todos los cuadros que fallan, el modelo no da evidencia de la persona. La pérdida no viene del umbral, de NMS ni de la clase ganadora.
- **Propuesta:** aplicar un filtro de mediana 3×3 a la imagen antes del detector.
- **Resultado en `p5-ajuste-v1`:** las acciones no permitidas bajan de 13 a 0 con la misma política. Las personas firmes suben de 39 a 71 de 85.
- **Falta:** comprobar si C5 y C7 pasan, y si el filtro detiene al carro con la vía libre. El paquete de ajuste no tiene cuadros libres.

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

1. **No se sabe si C5 y C7 pasan.** En particular, `seq06` 30–31 exige dos cuadros firmes seguidos.
2. **El ajuste no prueba la vía libre.** Sus cuadros son `centro`, `lateral_derecha` y `varios`, ninguno `libre`. Un filtro que invente personas no se notaría aquí; se verá en C1 y en `seq06` 1–26 y 49–50.
3. **Falsos positivos:** no se pueden calcular en ajuste, porque `aj05` y `aj06` tienen personas sin etiquetar ([A2_DATASET.md](A2_DATASET.md)).
4. **Muestra pequeña:** son 70 cuadros de 3 escenas, quizá del mismo edificio que la evaluación, y 24 variantes. El resultado de ajuste puede ser optimista.
5. **Se miró `p5-eval-v1`:** este diagnóstico leyó los puntajes del detector actual en `seq05` y `seq06`, pero eso no eligió el filtro.
6. **Medición anterior:** [B1-03_VALIDACION.md](B1-03_VALIDACION.md) ya hizo una medición única en eval con otra configuración de política. Esta sería una segunda, de un cambio distinto.
7. **Alcance del filtro:** solo lo aplica el runner de casos, con `--filtro-mediana`, desde `src/p5/casos/filtro.py`. Las métricas, el benchmark y el recorrido siguen sin filtro, y la evidencia de A3 sigue siendo válida.

## Condición para aprobarla como solución de #3

Hace falta **la única corrida acordada en `p5-eval-v1`**, con el comando de [Medición en evaluación](#medición-en-evaluación). Sus resultados y trazas se guardan en `evidencias/B1-03-detector/c1-c10-mediana3/`: `resultados.json` y `decisiones.jsonl`, sin editar.

| Qué revisar | Dónde | Sin filtro | Qué debe mostrar la corrida |
|---|---|---|---|
| C1 | `seq01`, 15 cuadros libres | 13 FORWARD y 2 STOP de arranque | Si el filtro detiene al carro sin obstáculo |
| C5 | `seq05` | EVADE_RIGHT en 8, 9 y 10 | Ninguna evasión hacia la persona de la derecha |
| C7, bloqueo | `seq06` 30–44 | Sin BLOCKED en 30–31; FORWARD en 36 y 38 | Bloqueo en el plazo y ningún FORWARD con la persona al centro |
| Tramos libres de `seq06` | Cuadros 1–26 y 49–50 | 24 FORWARD y 2 STOP de arranque; 2 FORWARD | Si el filtro detiene al carro sin obstáculo |

**Que C1 y C7 digan `PASA` no basta para la vía libre.** Sus reglas piden al menos un avance en el rango, y STOP siempre está permitido, así que un STOP de más no los hace fallar. Por eso hay que comparar esos tramos cuadro por cuadro en `decisiones.jsonl` contra [c1-c10-sin-filtro/](../evidencias/B1-03-detector/c1-c10-sin-filtro/), y anotar cada diferencia con su detección.

Si la corrida no sale bien, no se repite con otros valores: se aplica [Qué sigue](#qué-sigue).

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

Se corre una sola vez. La selección quedó congelada en `b95612f`, antes de medir:

```powershell
.venv\Scripts\python -m p5.casos.runner --cases casos\c1_c10.yaml --config config\politica.yaml --dataset data\p5-eval-v1 --weights models\yolox_tiny.onnx --filtro-mediana 3 --output resultados\c1-c10-mediana3
```

`resultados.json` registra `filtro_mediana_detector`. La referencia sin filtro, sobre `8e76180`, está en [c1-c10-sin-filtro/](../evidencias/B1-03-detector/c1-c10-sin-filtro/): 8 pasan, 2 fallan (C5 y C7) y 0 pendientes.

## Qué sigue

**Si C1–C7 pasan y la revisión de los tramos libres la acepta:**

1. Aprobar la propuesta con esa evidencia.
2. Mover el filtro a `src/p5/detector` y activarlo por defecto.
3. Generar de nuevo la evidencia de métricas: `verificar_a3_04_f01.py` falla a propósito cuando cambia el detector, y las métricas actuales dejarían de describirlo.
4. Repetir el benchmark y la reproducción de #9.
5. Revisar #3 con esa evidencia.

**Si C5 o C7 siguen fallando:**

1. Guardar los resultados y las trazas, y documentar la causa.
2. Mantener #3 abierto.
3. No probar otra variante mirando `p5-eval-v1`: cualquier cambio nuevo se elige otra vez con ajuste.
