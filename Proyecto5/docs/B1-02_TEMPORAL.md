# B1-02 — Política temporal y trazabilidad (E4, E5)

Responsable: Andrés Quiroz Valdovinos (@AndresQuiVal). Fase 2, prioridad P0.
Depende de A1-03 y B1-01. Complementa [B1-01](B1-01_POLITICA.md).

## Implementación y contrato

El motor usado por el recorrido, benchmark y runner integral sigue siendo
`p3.policy.politica.PoliticaDecision`: se reutiliza su lógica temporal pura,
sin mantener un algoritmo paralelo en P5. Cada recorrido tiene su propia memoria.
El replay de P5 usa ese mismo motor a través de `decidir_crudo`, validando el
[contrato A → B](A1-03_CONTRATO.md) en cada cuadro.

Una lista vacía explícita con `status: ok` aporta evidencia de vía libre.
Omitir la lista, enviar confianza fuera de [0, 1], una caja inválida o un error
del detector produce `FAULT` y `STOP`, nunca una vía libre implícita.
Se consideran todas las detecciones relevantes, no solo la de mayor confianza.
Varios objetos en un cuadro no suman varias confirmaciones temporales.

## Histéresis configurada

Los valores provienen de `config/politica.yaml`:

- Confianza < 0.30: ignorada. Desde 0.30 hasta menos de 0.50: débil.
  Desde 0.50: firme. Se conservan los filtros de clase y geometría de B1-01.
- Cada zona pasa a `OCUPADA` tras dos cuadros consecutivos con evidencia firme.
  Una evidencia débil interrumpe esa racha, sin ocupar una zona previamente libre.
- Cada zona pasa a `LIBRE` tras tres cuadros consecutivos sin evidencia firme
  ni débil. Una evidencia débil reinicia la liberación y conserva la ocupación.
- Al arrancar, cambiar de secuencia o recuperarse de un fallo, las zonas deben
  volver a confirmarse. Un tiempo no creciente se rechaza con `STOP`.

Los estados de vía son `UNKNOWN`, `CLEAR`, `CAUTION`, `BLOCKED`, `FAULT`.
Con el centro libre, el primer obstáculo firme provoca `CLEAR → CAUTION` y
`SLOW`; el segundo confirma `CAUTION → BLOCKED`. El bloqueo produce `STOP`
o evasión a un lateral confirmado libre según B1-01. Al desaparecer el obstáculo,
el centro conserva `BLOCKED` durante dos cuadros libres y pasa a `CLEAR` en el
tercero si también están libres los laterales. En otro caso puede pasar a
`CAUTION`. Un cuadro vacío aislado no libera un bloqueo.

Las rachas dependen de cuadros consecutivos, no del reloj de pared. La vigencia
del comando y la supervisión sin cuadros pertenecen al consumidor; B1-02 no
acredita los casos de watchdog o emergencia C8–C10.

## C1–C7 reproducibles

`casos/politica_c1_c7.yaml` fija entradas sintéticas y expectativas exactas para
todos los cuadros. Se comparan después de decidir: no se pasan al motor.

| Caso | Evidencia de comportamiento |
|---|---|
| C1 | Lista vacía: arranque seguro y avance positivo |
| C2 | Obstáculo central persistente: precaución y evasión justificada |
| C3 | Obstáculo izquierdo: avance recto a precaución |
| C4 | Obstáculo derecho: avance recto a precaución |
| C5 | Múltiples obstáculos: atender el centro aunque otro tenga mayor confianza |
| C6 | Confianza 0.29, 0.30 y 0.50: ignorar, precaución, bloqueo |
| C7 | Aparición, persistencia, ausencia aislada y desaparición confirmada |

C7 deshabilita explícitamente la evasión para aislar la estabilidad de STOP.
En los cuadros 3, 4, 5 y 12 registra respectivamente `UNKNOWN → CLEAR`,
`CLEAR → CAUTION`, `CAUTION → BLOCKED` y `BLOCKED → CLEAR`.
El cuadro vacío 8 mantiene `STOP`; el obstáculo del 9 reinicia la liberación.
Solo el tercer cuadro libre consecutivo, el 12, reanuda el avance.

Desde `Proyecto5`, con las dependencias instaladas:

```powershell
$env:PYTHONPATH = "src;../Proyecto3/src"
.venv/Scripts/python -m p5.policy --output resultados/b1-02
```

El comando sale con 0 solo si pasan los siete casos; con 1 ante expectativas
fallidas o entradas inválidas. Requiere una carpeta nueva y no sobrescribe
evidencia. Dos ejecuciones con las mismas entradas y configuración generan
archivos idénticos byte a byte. No usa pesos, azar ni fechas de ejecución.

## Registro y evidencia

Se producen `resultados.json`, `decisiones.jsonl` y `transiciones.jsonl`.
Cada decisión contiene estado anterior, estado actual, `cambio_estado`, acción,
velocidad, dirección, `reason_code` y `razon` (texto explicativo).
Cada transición identifica secuencia, cuadro y tiempo de captura.
Se registra el hash del archivo de configuración y la configuración efectiva
de cada caso con su propio hash, incluyendo la desactivación de evasión.

El recorrido integral también emite logs `policy_transition` con los mismos
identificadores y razones; sus trazas JSONL ya conservan cada decisión.
Se registran únicamente cambios reales de estado en el log de transiciones,
mientras el archivo de decisiones mantiene también los cuadros sin cambio.

La evidencia reproducible está en `evidencias/B1-02/`. Acredita la política con
entradas sintéticas, no la precisión del detector. El runner integral B3-02
conserva su evaluación separada con imágenes y pesos reales.

```powershell
.venv/Scripts/python -m pytest tests/test_policy_temporal.py tests/test_policy_acceptance.py tests/test_integration_pipeline.py
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
```
