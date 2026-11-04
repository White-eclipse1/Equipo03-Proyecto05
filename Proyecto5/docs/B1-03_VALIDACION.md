# B1-03 (#3) — Validación C1–C7 contra geometría y expectativas

Owners: Andrés Quiroz Valdovinos (@AndresQuiVal) y Omar Ramirez (@OmarCTMX).
Fase 3; E5. Fecha: 2026-11-04.

**Estado: NO cumple todavía la Definition of Done.** La validación está
implementada y ejecutada, pero el sistema obtiene **6/7 casos**: C7 falla con
el detector real. Este cambio no debe cerrar #3 ni liberar B3-03 como aprobado.
Se conserva el resultado negativo en lugar de cambiar las expectativas.

## Expectativas y origen

Se reutilizan los casos de `casos/c1_c10.yaml` y `allowed_actions` del manifiesto
congelado. Las expectativas históricas ya estaban en el commit
`7d07559e696f28af116f1ae3512389f98322083e`, anterior a esta ejecución.
El código base de esta rama es `fe9f5d5945acf690438b30a7f20ce9c33082ba18`.

Antes de inferir sobre evaluación se guardó
[`protocolo_previo.json`](../evidencias/B1-03/protocolo_previo.json), con fecha,
expectativas y hashes de casos, configuración, manifiestos, selección y código.
El hash permite identificar código nuevo aún sin commit. Los resultados
registran además el commit base, modelo, perfil y fecha previa a inferencia.

| Caso | Expectativa fijada | Entrada | Resultado |
|---|---|---|---|
| C1 | Avance positivo con vía despejada; STOP permanente falla | seq01, detector real | PASA |
| C2 | Bloqueo en ≤2 cuadros; STOP o evasión a destino libre | seq02, detector real | PASA |
| C3 | Avanzar sin dirigir hacia izquierda ocupada | seq03, detector real | PASA |
| C4 | Avanzar sin dirigir hacia derecha ocupada | seq04, detector real | PASA |
| C5 | Considerar todas las detecciones y rechazar destinos ocupados | seq05, detector real | PASA |
| C6 | Distinguir confianza ignorada, débil y firme | Control sintético en torno al perfil | PASA |
| C7 | Avanzar, bloquear en plazo, sostener y recuperar movimiento | seq06 real + control temporal | **FALLA real; PASA control** |

Los casos reales recorren `YoloxDetector → PerceptionFrame → PoliticaDecision →
VirtualControlAdapter`, usando ONNX Runtime CPU y los 128 cuadros originales.
No usan predicciones guardadas para sustituir al detector ni reciben etiquetas
como entrada al recorrido. El control sigue siendo virtual; no se accionan motores.

## Verificación geométrica independiente

`p5.casos.geometry` no llama a `_zonas_de` ni a `evaluar_deteccion` del motor.
Calcula las zonas desde cajas originales, clases, banda de riesgo, área mínima
y solape relativo al menor ancho de caja/zona. Considera todas las cajas.

Después de decidir, el runner comprueba:

- Acción admisible según el manifiesto y comando coherente con velocidad/giro.
- Un giro requiere destino `LIBRE`, racha libre suficiente y ausencia de evidencia
  actual desde `umbral_bajo`. También falla si el GT ocupa ese destino, aunque
  la política lo haya considerado libre por una omisión del detector.
- `FORWARD` no puede dirigirse al centro ocupado por GT; `SLOW` sigue admisible
  en la transición de confirmación, conforme al contrato existente.
- El motor evaluó tantas detecciones como recibió, el avance tiene velocidad
  positiva y `STOP` tiene velocidad y dirección cero.
- Errores del recorrido, plazos de reacción y límites de dirección de cada caso.

Las pruebas con un detector perfecto, que entrega etiquetas **solo como fixture
de prueba**, pasan 7/7 y validan que las expectativas son realizables. Esas
pruebas no se presentan como evidencia de inferencia real.

## Selección usando solo ajuste

La documentación de B3-02 ya registraba fallos reales de C5/C7 con el perfil
histórico. Se exploraron primero 12 combinaciones temporales/evasión sobre
los 70 cuadros de `p5-ajuste-v1`; persistieron 11 infracciones geométricas de
seguridad. Se amplió la búsqueda de confianza usando exclusivamente el mismo
paquete de ajuste, sin consultar predicciones de evaluación para seleccionar.

La búsqueda final reproducible compara 48 perfiles:

- `umbral_alto`: 0.20, 0.30, 0.40, 0.50; bajo = máximo de 0.10 y alto−0.20.
- Bloqueo: 1 o 2 cuadros; liberación: 3, 4 o 5; evasión activada/desactivada.
- Orden de selección: avance en control despejado, menos infracciones de
  seguridad, menos infracciones totales, menos STOP laterales y menos cambios.

El perfil seleccionado **antes** de evaluación está en
`config/politica_b1_03.yaml`: confianza 0.10/0.30, bloqueo 2, liberación 5,
evasión habilitada. La selección final conserva **8 infracciones de seguridad
y 16 comprobaciones fallidas** en ajuste; no se ocultan ni se presenta el perfil
como libre de fallos. Se almacenan todos los candidatos y sus predicciones.

El paquete de ajuste no contiene escenas completamente despejadas; se añadió
un control sintético de avance, pero eso no sustituye negativos reales para
estudiar falsas alarmas. El perfil es experimental, explícito en el comando;
`config/politica.yaml` y los defaults del recorrido permanecen históricos.
No se modificaron pesos, umbral del detector, zonas ni paquetes congelados.

## C6 y C7 deterministas

C6 usa el perfil efectivo: `umbral_bajo/2` se ignora, el punto medio de ambos
umbrales es débil y exactamente `umbral_alto` es firme. Las expectativas se
construyen desde estas fases y los contadores configurados antes de decidir.
Con el perfil seleccionado son 0.05, 0.20 y 0.30. Esto evita asumir que 0.40
siempre es débil para cualquier configuración. La ruta sintética antigua se
conserva para casos sin `confidence_from_config`.

C7 incluye un control sintético separado con ausencia aislada y secuencia
`UNKNOWN → CLEAR → CAUTION → BLOCKED → CLEAR`. Verifica la histéresis de la
misma política y configuración usadas por el recorrido real.

La secuencia real termina con solo dos cuadros completamente despejados
(49–50): el caso histórico admite recuperar `FORWARD` **o** `SLOW`. No exige
que todos los laterales ya hayan completado cinco cuadros libres. El retorno
literal a `CLEAR` se comprueba en el control, sin extender ni editar la secuencia
real para fabricar una liberación. El resultado real no se sustituye por él.

## Desviación real pendiente: C7

Ejecución final sellada: **6 pasan, 1 falla, 0 pendientes; código de salida 1**.
Se mantuvieron intactos perfil y expectativas después de ver este resultado.

| Cuadro | Observado | Violación |
|---|---|---|
| seq06-0030 y seq06-0031 | SLOW / CAUTION, sin BLOCKED | No confirma bloqueo dentro del plazo de dos cuadros |
| seq06-0038 | FORWARD / VIA_LIBRE | Persona central en el GT; avance no admisible |

La traza conserva detecciones, confianza, cajas, evaluación por zona, estados,
razones, comandos y errores. La revisión de estos fallos requiere trabajo de
percepción/continuidad del bloqueo. No hay justificación para reducir el plazo,
permitir ese avance o ajustar de nuevo con `p5-eval-v1` para cerrar el ticket.
La siguiente iteración debe usar ajuste adicional y una validación final
separada; los resultados actuales deben conservarse como historial.

## Evidencia y comandos

| Ruta en evidencias/B1-03 | Contenido |
|---|---|
| ajuste/ | Exploración inicial de 12 perfiles y predicciones de ajuste |
| ajuste_confianza/ | Selección de 48 perfiles, configuración y predicciones de ajuste |
| protocolo_previo.json | Identidad de expectativas y perfil antes de inferencia final |
| evaluacion/resultados.json | Resultados, metadatos, expectativas y control C7 |
| evaluacion/decisiones.jsonl | Decisiones por cuadro, incluyendo percepción real y comandos |
| evaluacion/fallos.jsonl | Cada fallo por caso, regla, cuadro o ventana de reacción |
| evaluacion/controles_temporales.jsonl | Control sintético C7 identificado como tal |

Desde `Proyecto5`, con Python 3.12 y las dependencias fijadas:

```powershell
$env:PYTHONPATH = "src;../Proyecto3/src"
.venv/Scripts/python -m p5.detector.weights
.venv/Scripts/python -m p5.casos.tune --output resultados/b1-03-ajuste
.venv/Scripts/python -m p5.casos.runner --cases casos/c1_c10.yaml --config config/politica_b1_03.yaml --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --output resultados/b1-03-validacion --only C1 C2 C3 C4 C5 C6 C7
$LASTEXITCODE
$env:P5_DETECTOR_WEIGHTS = (Resolve-Path models/yolox_tiny.onnx).Path
.venv/Scripts/python -m pytest tests/test_b1_03_geometry.py tests/test_casos_runner.py
git diff --exit-code -- data/p5-eval-v1 data/p5-ajuste-v1
```

Usar carpetas nuevas; el runner no sobrescribe evidencia. `--only` permite
ejecutar el alcance B1-03 sin que C8–C10 pendientes se confundan con sus resultados.
Sin ese argumento conserva el recorrido completo C1–C10. Un fallo de caso produce
JSON/JSONL y código 1; un fallo de arranque produce stderr y código 1.

Las pruebas del verificador comprueban resultados positivos y fallos deliberados,
incluida la reproducción de la desviación real documentada. Que esas pruebas
pasen acredita al verificador, **no significa que C7 ni la DoD estén aprobados**.

## Análisis incorporado de docs/b1-c7-detector-real

Se incorporaron sin alterar sus contenidos los cambios de `9df9d1d`, `08288af`
y `0608551` de la rama remota, revisada hasta `0608551`. Solo incluyen
[documentación de la política](../../Proyecto3/docs/politica.md) y
[trazas históricas C5/C7](../../Proyecto3/reports/politica/c5-c7-detector-real/resultados.json);
no contienen una corrección del motor ni una configuración nueva.

Se verificaron los hashes del manifiesto y del perfil histórico y se reprodujeron
exactamente todos los campos de las 65 decisiones almacenadas (15 de C5 y 50
de C7) pasando sus percepciones originales por el motor actual. La documentación
remota habla de 14 cuadros en parte de su explicación de C5; la traza y la
secuencia completa contienen 15, que son los usados en esta comprobación.

El análisis separa una pérdida de evidencia del detector de una debilidad de
continuidad en la política: una detección firme central todavía no confirmada
no cambia una zona que ya era `LIBRE` a `OCUPADA`. Al desaparecer en el cuadro
siguiente, el motor puede recuperar crucero sin esperar otra racha libre completa.
Eso explica la contribución de la política al cuadro 38 y ofrece una hipótesis
concreta: exigir evidencia limpia suficiente desde la última detección central
antes de volver a `FORWARD`, incluso si no se confirmó ocupación.

Esa hipótesis aún requiere pruebas y selección con ajuste; no se implementó
ni se presenta como solución verificada en esta incorporación. Tampoco corrige
por sí sola la falta de bloqueo dentro del plazo 30–31. El resultado remoto de
C5/C7 usa el perfil histórico; no reemplaza nuestra ejecución final con el
perfil experimental. Ambas evidencias siguen registrando que #3 está abierto.

Verificación final de la rama: **446 pruebas aprobadas y una omitida**, con
`P5_DETECTOR_WEIGHTS` definido. La omisión corresponde a la comprobación de
paquete instalado, porque se ejecutó desde fuentes. Ruff, formato y
`git diff --check` correctos; ambos paquetes congelados sin cambios. El stash
de la auditoría A3-04 no se aplicó ni modificó durante esta tarea.
