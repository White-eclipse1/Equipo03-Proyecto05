# B1-01 — Política de decisión (E4)

Responsable: Andrés Quiroz Valdovinos (@AndresQuiVal). Fase 1, prioridad P0.

P5 reutiliza `p3.policy.config.ConfigPolitica` y `p3.policy.politica.PoliticaDecision`,
ya consumidos por el recorrido B3. La configuración oficial de P5 está en
[`config/politica.yaml`](../config/politica.yaml); no hay una segunda implementación
del motor. B1-02 puede extender ese motor conservando el contrato de decisiones.

## Detecciones y zonas

Se usa el cuadro completo: cajas `bbox_xyxy` en píxeles originales, origen arriba
a la izquierda. Se normaliza x dividiendo por el ancho del cuadro.

| Zona | Intervalo horizontal |
|---|---|
| Izquierda | 0.00–0.35 |
| Central | 0.35–0.65 |
| Derecha | 0.65–1.00 |

Una caja pertenece a todas las zonas donde su solape horizontal alcance el 15 %
del menor ancho entre caja y zona. Tocar solamente un límite, sin solape positivo,
no ocupa la zona vecina. Si ninguna zona alcanza el mínimo, se consideran todas
las zonas tocadas; una caja ancha puede bloquear las tres.

Son obstáculos: `person`, `bicycle`, `car`, `motorcycle`, `bus`, `truck`, `cat`, `dog`.
Las demás clases se registran como ignoradas. También se ignoran cajas con área
menor al 0.5 % del cuadro o borde inferior por encima del 40 % de su altura.
Estos filtros son aproximaciones visuales de riesgo, no distancias físicas.

| Confianza | Tratamiento |
|---|---|
| < 0.30 | Ignorada; no aporta evidencia de obstáculo |
| ≥ 0.30 y < 0.50 | Débil; no ocupa una zona libre, pero reinicia su confirmación de liberación |
| ≥ 0.50 | Firme; ocupa tras dos cuadros consecutivos |

Una detección débil central produce precaución si el centro ya estaba libre;
si estaba ocupado, lo mantiene ocupado. Ausencia de detecciones relevantes
durante tres cuadros consecutivos confirma una zona libre. Varias cajas en un
solo cuadro cuentan como un cuadro, no como varias confirmaciones.

## Estados y acciones

| Estado | Condición y decisión |
|---|---|
| `UNKNOWN` | Centro aún no confirmado: `STOP` |
| `CLEAR` | Tres zonas confirmadas libres y sin evidencia firme o débil actual: `FORWARD`, velocidad 0.60, dirección 0 |
| `CAUTION` | Centro libre con evidencia central pendiente/débil o lateral no libre: `SLOW`, velocidad 0.30, dirección 0 |
| `BLOCKED` | Centro confirmado ocupado: `STOP` o evasión justificada |
| `FAULT` | Error de percepción o contrato inválido: `STOP`, reiniciar confirmación |

`STOP` siempre tiene velocidad 0 y dirección 0. Una vía despejada desde el
arranque produce `STOP`, `STOP`, `FORWARD`; no queda detenida indefinidamente.
Un primer obstáculo central sobre una vía ya libre produce `SLOW`; el segundo
cuadro firme consecutivo confirma `BLOCKED`. Hasta entonces existe una demora
de confirmación deliberada; no se afirma frenado físico inmediato.

La evasión requiere centro ocupado, `evasion.habilitada: true` y destino lateral
`LIBRE` con al menos tres cuadros consecutivos sin evidencia firme ni débil.
Nunca se gira hacia una zona desconocida, ocupada o con evidencia reciente.
Si ambos laterales cumplen, se prefiere derecha; si solo uno cumple, se elige ese.
La velocidad es 0.20 y la dirección −0.50 para izquierda o +0.50 para derecha.
Sin destino confirmado, o con evasión deshabilitada, se emite `STOP`.
El centro permanece ocupado hasta tres cuadros libres; una evasión conserva
estado `BLOCKED` y registra `EVASION_IZQUIERDA` o `EVASION_DERECHA` como razón.

Al cambiar de secuencia se reinician las zonas. Un tiempo no creciente se rechaza
con `STOP`. Un error no equivale a una lista vacía. Los comandos de movimiento
declaran vigencia de 500 ms desde la captura; `STOP` no vence. La supervisión de
caducidad corresponde al consumidor del comando, no a un reloj del motor puro.

## Uso y verificación

Desde `Proyecto5`, el recorrido y el benchmark usan `config/politica.yaml` por
defecto. Se puede seleccionar otra configuración con `--policy-config RUTA`.
El runner B3-02 requiere `--config config/politica.yaml`. El esquema rechaza
campos desconocidos, umbrales inconsistentes y zonas inválidas antes de construir
la política. Cada decisión incluye el SHA-256 de la configuración utilizada.

```powershell
python -m pytest tests/test_policy_acceptance.py tests/test_integration_pipeline.py
python -m p5.casos.runner --help
```

Las pruebas de aceptación cubren vía libre, bloqueo central, destinos ocupados
o inciertos, umbrales exactos, filtros geométricos, errores y cambios de secuencia.
El control sigue siendo virtual. Los valores se conservan compatibles con la
política compartida y el dataset congelado; no se ajustaron usando evaluación.
