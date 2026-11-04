# B1-03: validación de C1–C7 y ajuste con `p5-ajuste-v1` (E5)

Responsables: Andrés Quiroz Valdovinos (@AndresQuiVal) y Omar Ramirez (@OmarCTMX). Fase 3, prioridad P0. Depende de [B1-02](B1-02_TEMPORAL.md) y de [B3-01](B3-01_RECORRIDO.md).

## Estado

**B1-03 no está cerrado.** La definición de terminado exige que C1–C7 pasen, y con el detector real C5 y C7 fallan. Este documento reúne la evidencia y explica por qué ajustar la política no basta para cerrarlo.

| Criterio de #3 | Estado | Evidencia |
|---|---|---|
| C1–C4 y C6 | Pasan con detector real y en replay sintético | `B3-02_RUNNER.md`, `evidencias/B1-02/` |
| C5 considera todas las detecciones | Falla con detector real en `seq05` 8–10 | [`Proyecto3/docs/politica.md`](../../Proyecto3/docs/politica.md), «C5 y C7 con el detector real» |
| C7 clear → blocked → clear | Pasa en sintético; falla con detector real en `seq06` 30/31, 36 y 38 | Misma sección |
| Expectativas antes del resultado | Sintéticas sí (commit red `5695701`). Reales: `B3-02_RUNNER.md` declara que se escribieron durante la captura | `B3-02_RUNNER.md`, «Límites conocidos» |
| Cada fallo produce salida verificable | Sí | `resultados.json` y `decisiones.jsonl` del runner |

Con detector perfecto (las etiquetas como detecciones), la misma política pasa C5 y C7 (`test_expectations_are_consistent_with_a_perfect_detector`). La causa principal es la recuperación del detector: deja de ver a la persona durante varios cuadros seguidos.

## Ajuste con `p5-ajuste-v1`

La política solo se ajusta con el paquete de ajuste. `p5.policy.ajuste` rechaza cualquier paquete que no declare `"package": "ajuste"`.

```powershell
$env:PYTHONPATH = "src;../Proyecto3/src"
.venv\Scripts\python -m p5.policy.ajuste --output resultados\b1-03-ajuste.json
```

- **Funcionamiento:** el detector corre una vez por cuadro con los umbrales del recorrido. Después se repite la política por candidato, reiniciada en cada secuencia.
- **Rejilla:** `umbral_bajo` ∈ {0.30, 0.25, 0.20, 0.15, 0.10}, `cuadros_para_bloquear` ∈ {1, 2} y `cuadros_para_liberar` ∈ {3, 4, 5}. Zonas, clases, `umbral_alto` y comandos no cambian.
- **Métricas:**
  - *no permitidas*: acción fuera de `allowed_actions` del manifiesto.
  - *sin avance*: ni FORWARD ni SLOW con el centro libre (`libre` o lateral). STOP siempre está permitido, así que sin esta métrica detenerse siempre saldría perfecto.
- **Criterio:** primero menos *no permitidas*, después menos *sin avance* y después el cambio más pequeño respecto a la configuración actual.

Resultado, en `evidencias/B1-03/ajuste.json` (manifiesto `b4029c40…`, modelo `427cc366…`), sobre 70 cuadros (aj05, aj06 y aju01):

| Configuración | No permitidas | Sin avance |
|---|---|---|
| Actual: 0.30, bloquear 2, liberar 3 | 13 | 0 |
| **Seleccionada:** 0.15, bloquear 2, liberar 5 | **8** | 1 |

Las 8 restantes están en `aj06` 6–12 y 14. En esos cuadros ninguna caja `person` del detector, que entrega desde 0.10, se solapa con la persona anotada en el centro (IoU 0), así que ninguna configuración de la política puede verla. La selección se commiteó (`1b59eb2`) antes de cambiar la configuración y de medir `p5-eval-v1`.

## Medición única en `p5-eval-v1`

Con la configuración seleccionada (archivo modificado sin commitear sobre `1b59eb2`, `config_sha256` `5a4d3f20…`), el runner de B3-02 da **4 pasan, 4 fallan y 2 pendientes**, frente a 6, 2 y 2 con la configuración actual. Está en `evidencias/B1-03/eval-config-ajustada.json`.

| Caso | Actual | Seleccionada |
|---|---|---|
| C5 | Falla en 8, 9 y 10 | Falla en 10 |
| C7 | Falla en 30/31, 36 y 38 | Falla en 30/31 y 38 |
| C6 (sintético) | Pasa | Falla: arranque de 5 cuadros contra expectativas escritas para 3 |
| C8 (watchdog) | Pasa | Falla: la política no llega a FORWARD antes del corte |

**Decisión: no se adopta.** Reduce las acciones inseguras en ajuste (13 → 8) y en eval (5 → 2 cuadros), pero tiene tres problemas:

- no cierra C5 ni C7;
- un arranque de 5 cuadros rompe C6 y C8, y unas 58 pruebas de P3 y P5, de cuatro roles, escritas con «liberar en 3»;
- cambiar esas expectativas para que pasen sería justo lo que pide evitar el equipo.

Si el equipo decide adoptarla, primero hay que desacoplar las pruebas de la configuración desplegada (que fijen su propia configuración) y revisar C6 y C8 con sus responsables.

## Qué falta para cerrar B1-03

1. **Detector (A1/A3):** recuperar a la persona en `seq05` (derecha), `seq06` 30–39 (centro) y `aj06` 6–15 (centro). El ajuste de la política ya no tiene margen ahí.
2. **Política (B1):** con un detector mejor, repetir `p5.policy.ajuste` sobre `p5-ajuste-v1`, congelar la selección y medir eval una sola vez.
3. **Expectativas reales:** dejar constancia, con B3-02, de cuándo se fijaron las expectativas de C1–C5 y C7 respecto a la primera corrida.
