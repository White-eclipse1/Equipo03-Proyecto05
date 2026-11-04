# Política de decisión — Proyecto 5 (B1)

Responsable: Andrés Quiroz Valdovinos (B1 — Decision Policy Engineer). Tickets: #1 B1-01, #2 B1-02, #3 B1-03. Entregables: E4 (política) y E5 (casos C1–C7).

La política convierte las detecciones de **un cuadro completo** (cero, una o varias cajas con clase y confianza) en una decisión de movimiento. Es lógica pura: no lee `os.environ`, no usa el reloj de pared y no abre la cámara, GPIO ni motores. La aplicación y el recorrido de evaluación importan el mismo `p3.policy.politica.PoliticaDecision` (criterio 2.3).

| Pieza | Archivo |
|---|---|
| Contrato A → B (entrada) | `src/p3/policy/contrato.py` |
| Configuración validada | `config/politica.yaml` + `src/p3/policy/config.py` |
| Política temporal | `src/p3/policy/politica.py` |
| Casos C1–C7 y runner | `casos/politica_c1_c7.yaml` + `src/p3/policy/casos.py` |
| Resultados de la última corrida | `reports/politica/c1-c7/` |
| Pruebas | `tests/test_policy_*.py` |

## Comandos

Desde `Proyecto3/`, con el venv de la sección «Pruebas de Proyecto 3» del README (la política solo necesita `pydantic` y `pyyaml`):

```bash
# Pruebas de la política (contrato, config, casos, runner)
.venv/Scripts/pytest tests/test_policy_contrato.py tests/test_policy_config.py tests/test_policy_casos.py tests/test_policy_runner.py

# Casos C1–C7: escribe resultados.json y decisiones.jsonl en una carpeta NUEVA; exit 1 si falla uno
PYTHONPATH=src .venv/Scripts/python -m p3.policy.casos \
  --casos casos/politica_c1_c7.yaml --config config/politica.yaml --salida <carpeta-nueva>
```

En Linux/macOS cambia `.venv/Scripts/` por `.venv/bin/`.

## Contrato A → B (propuesta de B1 para A1-03)

Un objeto por cuadro (JSON/JSONL). Lo valida `Cuadro`, y un campo extra se rechaza.

```json
{
  "sequence_id": "seq03",
  "frame_id": "seq03-0012",
  "t_capture_ms": 1200,
  "image_width": 640,
  "image_height": 480,
  "status": "ok",
  "detections": [
    {"class_name": "person", "confidence": 0.87, "bbox_xyxy": [261.0, 198.5, 379.2, 461.0]}
  ],
  "error": null
}
```

- `bbox_xyxy`: píxeles del cuadro **original**, no del tensor redimensionado. El origen está en la esquina superior izquierda; x crece a la derecha e y hacia abajo. Se exige `x2 > x1` y `y2 > y1`, dentro del cuadro con una tolerancia de 1 px.
- `confidence`: un valor finito en [0, 1]. NaN e infinito se rechazan.
- **Escena vacía**: `status: "ok"` con `detections: []`. Con `status: "ok"`, el campo `detections` es **obligatorio**: si falta o es `null`, el cuadro se rechaza y `decidir_crudo` lo trata como `SALIDA_MALFORMADA` (STOP), nunca como vía libre.
- **Fallo del detector**: `status: "error"`, sin detecciones y con `error` explicando el motivo. Nunca se confunde con una escena vacía.
- `t_capture_ms`: tiempo relativo al inicio de la secuencia. Tiene que crecer estrictamente dentro de la secuencia.

Si A1 decide otro formato, lo que cambia es este archivo y `contrato.py`; la política no se toca.

## Zonas, banda de riesgo y proximidad

```
x normalizado  0 ─────── 0.35 ─────── 0.65 ─────── 1
               │ izquierda │   centro   │  derecha  │
               └───────────┴────────────┴───────────┘
y  0.40 ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  ← banda_riesgo_y_min
   (solo cuentan cajas cuyo borde inferior y2 queda por debajo de esta línea)
```

- **Tres zonas verticales.** El centro (30 % del ancho) representa la trayectoria del auto si avanza recto; los laterales representan hacia dónde podría evadir. Las zonas tienen que ser contiguas y cubrir [0, 1], o la configuración se rechaza.
- **Una caja ocupa todas las zonas que cubre.** La regla es `solape ≥ cobertura_min_zona (15 %) × min(ancho de la zona, ancho de la caja)`:
  - una caja ancha ocupa una zona si cubre al menos el 15 % de ella, así que puede bloquear centro y lateral a la vez (C5);
  - una caja **angosta** ocupa toda zona donde caiga al menos el 15 % de la caja. Un obstáculo pequeño montado sobre el límite entre izquierda y centro ocupa **las dos**;
  - **ninguna caja dentro del cuadro queda sin zona**. `cobertura_min_zona` está limitada a ≤ 0.5 y la configuración rechaza valores mayores: una caja repartida entre dos zonas siempre deja al menos la mitad de su ancho en una de ellas. Como **respaldo**, si aun así una caja no alcanzara ninguna zona, ocupa **todas las zonas que toca**: el lado seguro es contarla, nunca ignorarla;
  - una caja lateral grande que apenas roza el centro (menos del 15 % de ambos anchos) no lo ocupa.
- **Banda de riesgo** (`y2/alto ≥ 0.40`): con la cámara mirando al frente, un objeto cuya base aparece en la parte alta del cuadro está lejos o fuera del piso. Se registra como `ignorada / fuera_de_banda`.
- **Proximidad**: se usa `area_caja / area_cuadro ≥ area_min` (0.5 %) como **proxy**. **No es una distancia en metros**, porque no hay calibración de la cámara.
- **Clases obstáculo** (`clases_obstaculo`): person, bicycle, car, motorcycle, bus, truck, cat y dog. Cualquier otra clase se registra como `ignorada / clase_no_obstaculo`. Si A1 elige un detector con otras clases, se ajusta esta lista **antes** de calcular métricas.

## Confianza: dos umbrales (histéresis)

| Confianza | Nivel | Efecto |
|---|---|---|
| ≥ `umbral_alto` (0.50) | `firme` | Puede ocupar una zona. |
| [`umbral_bajo`, `umbral_alto`) = [0.30, 0.50) | `debil` | No ocupa una zona libre, pero **impide liberarla**. En el centro baja la velocidad a precaución. |
| < `umbral_bajo` (0.30) | `ignorada` | No afecta la decisión; queda registrada como `bajo_umbral`. |

Con esto, un objeto débil no se convierte sin criterio en un obstáculo cierto, y una persona cuya confianza oscila alrededor de 0.5 no hace que el auto alterne entre parar y avanzar (C6).

## Estados de zona y temporalidad

Cada zona está en `DESCONOCIDA`, `LIBRE` u `OCUPADA`:

- Pasa a **OCUPADA** tras `cuadros_para_bloquear` (2) cuadros seguidos con detección firme.
- Pasa a **LIBRE** tras `cuadros_para_liberar` (3) cuadros seguidos sin detección firme ni débil.
- Vuelve a **DESCONOCIDA** al arrancar, después de un error o salida malformada del detector, y al cambiar de secuencia. Una zona desconocida se trata como no libre: **la vía libre hay que confirmarla**.

La asimetría (2 para bloquear, 3 para liberar) es intencional: reacciona más rápido de lo que reanuda. Además, el primer cuadro con un obstáculo central ya baja a precaución, aunque el bloqueo todavía no esté confirmado.

## Estados de la vía y decisión

El centro tiene prioridad sobre todo lo demás.

| Estado | Condición | Acción | velocidad | dirección | reason_code |
|---|---|---|---:|---:|---|
| `UNKNOWN` | centro DESCONOCIDA | STOP | 0 | 0 | `PERCEPCION_NO_CONFIRMADA` |
| `BLOCKED` | centro OCUPADA y un lateral verificado libre | EVADE_LEFT / EVADE_RIGHT | 0.20 | ∓0.50 | `EVASION_IZQUIERDA` / `EVASION_DERECHA` |
| `BLOCKED` | centro OCUPADA sin lateral libre | STOP | 0 | 0 | `SIN_ZONA_LIBRE` · `CENTRO_BLOQUEADO` (evasión off) · `CENTRO_HISTERESIS` (ya no se ve pero falta liberar) |
| `CAUTION` | centro LIBRE con detección firme aún no confirmada | SLOW | 0.30 | 0 | `CENTRO_POR_CONFIRMAR` |
| `CAUTION` | centro LIBRE con detección débil | SLOW | 0.30 | 0 | `CENTRO_DEBIL` |
| `CAUTION` | centro LIBRE con un lateral no libre o con detecciones | SLOW | 0.30 | 0 | `LATERAL_OCUPADO` |
| `CLEAR` | las tres zonas LIBRES sin detecciones | FORWARD | 0.60 | 0 | `VIA_LIBRE` |
| `FAULT` | `status: "error"` | STOP | 0 | 0 | `ERROR_PERCEPCION` |
| `FAULT` | la salida no cumple el contrato (`decidir_crudo`) | STOP | 0 | 0 | `SALIDA_MALFORMADA` |
| (sin cambio) | `t_capture_ms` no creciente | STOP | 0 | 0 | `CUADRO_FUERA_DE_ORDEN` |

- **Giro.** Solo se elige con el centro OCUPADO y hacia un lateral que esté LIBRE y lleve al menos `cuadros_para_liberar` cuadros sin ninguna detección, ni firme ni débil. Si los dos laterales están libres, decide `lado_preferido`. Con `evasion.habilitada: false` la respuesta al bloqueo central es siempre STOP, y la rúbrica acepta esa respuesta.
- **Con el centro libre se avanza siempre recto.** No se corrige hacia un lateral, así que nunca se dirige movimiento hacia una zona ocupada (C3, C4).

## Comandos hacia B2

`Decision` (en `politica.py`) es lo que recibe el adaptador de B2:

| Campo | Significado |
|---|---|
| `velocidad` | Fracción de la velocidad máxima, en [0, 1]. B2 la traduce al PWM o al controlador. |
| `direccion` | En [-1, 1]: **negativo = izquierda**, positivo = derecha y 0 = recto. |
| `valido_hasta_ms` | `t_capture_ms + vigencia_comando_ms` (500 ms). A partir de ese instante el adaptador debe tratar el comando como STOP, llegue o no un cuadro nuevo; esa es la función del watchdog de B2-02. En STOP vale `null`, porque STOP no vence. |
| `estado_anterior`, `estado`, `cambio_estado` | Bitácora de transiciones. |
| `reason_code`, `razon` | Por qué se tomó la decisión. |
| `zonas`, `detecciones` | Estado de cada zona, y nivel, motivo y zonas de cada caja, enlazados por `indice` con la entrada. |
| `sequence_id`, `frame_id`, `t_capture_ms`, `config_sha256` | Trazabilidad cuadro → decisión → configuración. |

**STOP siempre implica `velocidad = 0` y `direccion = 0`.**

El watchdog por reloj (C8), la emergencia enclavada con rearme (C10) y el cierre seguro son de B2 (#4, #5, #6). La política aporta tres cosas para esos casos:

- No reanuda después de un fallo sin volver a confirmar la vía.
- Rechaza los cuadros fuera de orden.
- Marca la vigencia de cada comando.

## Presupuesto temporal

A *f* cuadros por segundo, el bloqueo central se confirma en el 2.º cuadro con el obstáculo. Desde el 1.º ya no hay crucero. El plazo declarado es entonces 2 periodos más la latencia del detector; a 10 FPS (100 ms) son unos 200 ms más la inferencia. La vigencia de 500 ms cubre hasta 4 cuadros perdidos a 10 FPS antes de que el adaptador detenga el auto. Si el benchmark de A3 da un p95 de inferencia mayor que el periodo de entrada, hay que subir `vigencia_comando_ms` o bajar los FPS, **antes** de correr la evaluación (4.3). Estos plazos verifican el contrato del software, no una distancia de frenado física.

## Casos C1–C7 (B1-03)

Los casos están en `casos/politica_c1_c7.yaml`, con su justificación geométrica y las acciones permitidas por cuadro. Las expectativas se fijaron en el commit red `5695701`, antes de implementar. El runner nunca pasa `esperado` a la política.

| Caso | Escena sintética | Permitido | Observado |
|---|---|---|---|
| C1 | 6 cuadros libres y 3 con objeto fuera de banda | STOP en 1–2; FORWARD en 3–9 | PASA |
| C2 | persona centrada, conf 0.9 | SLOW o STOP en el 1.er cuadro; STOP o evasión verificada desde el 2.º | PASA (EVADE_RIGHT) |
| C2-sin-evasion | igual, con evasión off | STOP desde el 2.º | PASA |
| C3 | persona solo a la izquierda | avance con dirección ≥ 0 | PASA (SLOW, recto) |
| C4 | persona solo a la derecha | avance con dirección ≤ 0 | PASA (SLOW, recto) |
| C5 | izquierda, centro y derecha ocupados | STOP | PASA (`SIN_ZONA_LIBRE`) |
| C5-evasion | centro e izquierda ocupados | STOP o EVADE_RIGHT | PASA (EVADE_RIGHT) |
| C6 | conf 0.40 → 0.55 en el centro | SLOW mientras es débil; STOP al confirmarse firme | PASA |
| C7 | libre → obstáculo → 1 cuadro vacío → obstáculo → libre | STOP de 5 a 11; FORWARD tras 3 libres | PASA |

Con las secuencias reales y el detector real, los casos los corre el runner de B3-02 (`Proyecto5/docs/B3-02_RUNNER.md`).

## C5 y C7 con el detector real (análisis de B1)

Con el detector real, C5 falla en `seq05` 8–10 (EVADE_RIGHT con una persona a la derecha). C7 falla en `seq06` 30/31 (sin BLOCKED en el plazo de 2 cuadros) y 36/38 (FORWARD con la persona al centro). **No se corrigieron cambiando la política ni las expectativas**, porque la causa principal es el detector. Este es el análisis:

**Reproducción**, desde `Proyecto5` en el commit `fe9f5d5` de `main`:

```powershell
.venv\Scripts\python -m p5.casos.runner --cases casos/c1_c10.yaml --config config/politica.yaml --dataset data/p5-eval-v1 --weights models/yolox_tiny.onnx --output <carpeta-nueva>
```

| Dato | Valor |
|---|---|
| Modelo (`yolox_tiny.onnx`) | `427cc366…70b0f7` |
| Manifiesto `p5-eval-v1` | `5dab9ee3…2ffeeb` |
| `Proyecto5/config/politica.yaml` | `171b0632…716054`. Tiene los mismos valores que `Proyecto3/config/politica.yaml` y solo cambian los comentarios |
| Umbral / NMS del detector | 0.10 / 0.45 |
| Resultado | 6 pasan, 2 fallan (C5, C7), 2 pendientes |

Las mismas acciones y razones salieron en tres corridas: dos en `f9b173a` con la configuración de Proyecto3 y una en `fe9f5d5` con la de Proyecto5. Las confianzas difieren desde el 7.º decimal por ONNX Runtime, lejos de cualquier umbral. Las trazas de C5 y C7 están en `reports/politica/c5-c7-detector-real/`.

**Control con detector perfecto:** `test_expectations_are_consistent_with_a_perfect_detector` (Proyecto5) corre la misma política y la misma configuración con las etiquetas como detecciones, y C5 y C7 **pasan**. Las reglas de la política y las expectativas son consistentes entre sí.

### C5: `seq05`, persona al centro y persona a la derecha en los 14 cuadros

| Cuadro | Persona derecha (detector) | Derecha (racha ocupada, libre) | Acción |
|---|---|---|---|
| 1–2 | 0.85 y 0.78 *f* | OCUPADA en el 2 | STOP, `SIN_ZONA_LIBRE` |
| 3 | 0.42 débil | OCUPADA (0, 0) | EVADE_LEFT |
| 4 | 0.15 *i* | OCUPADA (0, 1) | EVADE_LEFT |
| 5 | 0.83 *f* | OCUPADA (1, 0) | EVADE_LEFT |
| 6 | 0.14 *i* | OCUPADA (0, 1) | EVADE_LEFT |
| 7 | 0.12 *i* | OCUPADA (0, 2) | EVADE_LEFT |
| 8 | sin detección | **LIBRE (0, 3)** | **EVADE_RIGHT** |
| 9–10 | sin detección | LIBRE (0, 4–5) | **EVADE_RIGHT** |
| 11–14 | firme en 11 y 14 | LIBRE; racha libre < 3, así que no sirve como destino | EVADE_LEFT |

La persona del centro sale firme en los 14 cuadros, así que el centro siempre está OCUPADO. La de la derecha sale con 0.12–0.15 en los cuadros 4, 6 y 7, por debajo de `umbral_bajo`, y desaparece en los cuadros 8–10. Con 3 cuadros sin evidencia, la regla documentada libera la zona, y la evasión hacia un lateral LIBRE con 3 cuadros limpios queda permitida. **Causa: detector.** La política aplicó sus reglas tal como están escritas.

### C7: `seq06`

**Cuadro a cuadro** (`seq06`, persona anotada al centro de 30 a 44, x ≈ 0.28–0.46, y2/H ≈ 0.48, dentro de la banda). *f* = firme (≥ 0.50), *i* = ignorada (< 0.30):

| Cuadro | Detector (person) | Centro (racha ocupada, libre) | Acción |
|---|---|---|---|
| 30 | 0.86 *f* izq+centro | LIBRE (1, 0) | SLOW, `CENTRO_POR_CONFIRMAR` |
| 31 | 0.26 *i* centro | LIBRE (0, 1) | SLOW, `LATERAL_OCUPADO` |
| 32 | 0.26 *i* | LIBRE (0, 2) | SLOW |
| 33 | 0.69 *f* | LIBRE (1, 0) | SLOW, `CENTRO_POR_CONFIRMAR` |
| 34 | sin detección | LIBRE (0, 1) | SLOW |
| 35 | sin detección | LIBRE (0, 2) | SLOW |
| 36 | 0.15 *i* | LIBRE (0, 3) | **FORWARD** |
| 37 | 0.73 *f* | LIBRE (1, 0) | SLOW, `CENTRO_POR_CONFIRMAR` |
| 38 | 0.11 *i*, caja en la izquierda | LIBRE (0, 1) | **FORWARD** |
| 39 | 0.58 *f* | LIBRE (1, 0) | SLOW |
| 40–44 | firme en 40, 41, 42 y 44 | OCUPADA | EVADE_RIGHT |

Entre 30 y 39 el detector entrega a la persona como firme en **4 de 10 cuadros**, y nunca en dos cuadros seguidos.

**Atribución:**

- **30/31, causa en el detector:** el cuadro 31 llega con 0.26, que está por debajo de `umbral_bajo`. `cuadros_para_bloquear: 2` exige dos cuadros firmes seguidos, así que la vía queda en CAUTION (SLOW, nunca crucero) y no llega a BLOCKED.
- **36, causa en el detector:** 34, 35 y 36 son tres cuadros sin la persona en el centro, y la regla documentada es que la zona se libera tras 3. Con esa entrada, ninguna política que vuelva a avanzar tras 3 cuadros libres, como pide la propia C7 al final de la secuencia, puede evitar este FORWARD.
- **38, mixta:** el detector pierde a la persona; la única caja que entrega está en la izquierda. La política contribuye: como el centro nunca llegó a OCUPADA, una detección firme sin confirmar (la del 37) se olvida tras un solo cuadro vacío y se vuelve a crucero. Es una debilidad de la política. Con la regla «sin FORWARD hasta `cuadros_para_liberar` cuadros limpios en el centro desde la última detección firme», el 38 daría SLOW. El 36 seguiría fallando.

### Qué sigue

**Por qué no se ajustó aquí:** cambiar umbrales o rachas para pasar C5 y C7 sería **ajustar sobre las secuencias de evaluación** (ver la última viñeta de la sección siguiente). Cualquier ajuste se hace y se congela con `p5-ajuste-v1` y después se mide una sola vez en `p5-eval-v1`.

Las trazas sugieren hipótesis para probar en `p5-ajuste-v1`. No están verificadas:

- Bajar `umbral_bajo`. En los dos casos la persona perdida suele seguir detectada a 0.11–0.15, en su zona correcta. Como débil, sostendría la ocupación en C5 y frenaría la liberación en el 36 de C7. El costo es más falsos positivos.
- Agregar la regla «sin FORWARD hasta `cuadros_para_liberar` cuadros limpios en el centro desde la última detección firme», para el 38 de C7.
- 30/31 de C7 solo pasaría con `cuadros_para_bloquear: 1`, que reacciona a un solo cuadro y va contra la estabilidad que pide C7.

La otra vía es mejorar la recuperación del detector en estas escenas (A1/A3).

## Desviaciones y límites conocidos

- Los casos de esta carpeta usan **detecciones sintéticas**: prueban reglas de política, no calidad de detección.
- Las zonas son franjas verticales fijas. No modelan la perspectiva ni la trayectoria al girar, y no hay planificación de ruta, que tampoco se exige.
- La evasión es un comando de una sola decisión. La política no verifica que el auto haya salido del bloqueo: en cada cuadro vuelve a decidir con lo que ve.
- Los umbrales (0.50/0.30) y `area_min` son valores iniciales. Si se ajustan, tiene que ser sobre secuencias de **ajuste**, nunca sobre los 60 cuadros de evaluación, y se congelan antes de medir.
