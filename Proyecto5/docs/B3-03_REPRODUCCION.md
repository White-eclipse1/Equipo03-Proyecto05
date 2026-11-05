# B3-03 — Reproducción limpia y paquete final

Ticket: #9. Entregables: E1–E7.

## Objetivo

Demostrar que otra persona puede recuperar y ejecutar el proyecto sin intervención del equipo.

**Estado: en curso.** La guía y el comando de reproducción ya funcionan desde una copia limpia, y C1–C10 corre completo. El ticket no se puede cerrar porque C5 y C7 todavía no pasan.

## Componentes

- [README.md](../README.md): preparación, comandos y entregables.
- scripts/reproducir.py: corre todos los comandos y resume el resultado.
- tests/test_reproduccion.py: comprueba el resumen, la guía y que el código no abra conexiones de más.

Los comandos están en el README.

## Último resultado

Sobre `main` en `8e76180`, con #39 y #43 ya fusionados, más los archivos de este ticket, con Python 3.12.16 y dependencias fijadas.

| Paso | Linux, sin red | Windows |
|---|---|---|
| Hash del detector | ok | ok |
| Dataset de evaluación y de ajuste | ok | ok |
| Inferencia | ok | ok |
| Recorrido y traza de un cuadro | ok | ok |
| Decisiones C1–C7, detecciones sintéticas | ok, 7 de 7 | ok, 7 de 7 |
| **C1–C10** | **incompleto:** 8 pasan, 2 fallan y 0 pendientes | **incompleto:** igual |
| Métricas | ok: 64 TP, 2 FP y 27 FN | ok: mismos conteos |
| Benchmark | ok: 200 de 200 válidas | ok: 200 de 200 válidas |
| Pruebas | 494 pasan | 494 pasan |

- **Linux:** contenedor `python:3.12`. La preparación usó la red, y todo lo demás corrió con `--network none`.
- **Windows:** clon limpio con los comandos de PowerShell del README, usando la alternativa a `py -3.12` que indica la guía.
- **Benchmark:** estas corridas solo comprueban que el comando funciona. Sus tiempos no son evidencia.

### Traza de un cuadro

`seq02-0003` → person, backpack y person → BLOCKED → EVADE_LEFT → `left`, velocidad 0.2 y giro −0.5, con el mismo `frame_id` en cada etapa.

### Casos que no pasan

| Caso | Estado | Cuadros | Qué ocurre | Depende de |
|---|---|---|---|---|
| C5 | Falla | seq05 8, 9 y 10 | EVADE_RIGHT con una persona a la derecha | #3 |
| C7 | Falla | seq06 36 y 38 | FORWARD con una persona al centro | #3 |
| C7 | Falla | seq06 30 y 31 | No confirma el bloqueo dentro del plazo de 2 cuadros | #3 |

C9 y C10 ya se ejecutan y pasan. No se cambiaron expectativas, umbrales ni datos para hacer pasar estos casos.

[B1-03_VALIDACION.md](B1-03_VALIDACION.md) probó un ajuste de la política y decidió no adoptarlo. El diagnóstico del detector y su propuesta están en `docs/B1-03_DETECTOR.md`, en la rama `feat/a1-filtro-mediana`. Esta reproducción no incluye esa propuesta.

## Criterios del ticket

| Criterio | Estado |
|---|---|
| Copia limpia del repositorio | Hecho, en Linux y Windows |
| Instalación con dependencias fijadas | Hecho |
| El detector se recupera y su hash se verifica | Hecho |
| El dataset se recupera | Hecho: viene en el repositorio y se valida |
| Comandos de inferencia, recorrido, métricas y benchmark | Hecho |
| Comando C1–C10 | **Corre completo, pero C5 y C7 aún no pasan** |
| Motores desactivados por defecto | Hecho |
| Sin AWS ni servicios externos después de la preparación | Hecho: probado sin red en Linux |
| Trazar un cuadro de principio a fin | Hecho |
| README con todos los comandos | Hecho |
| Sin secretos en el repositorio | gitleaks del CI, en cada push |
| Resultados en una carpeta configurable | Hecho |

## Lo que falta para cerrar

1. **#3:** resolver C5 y C7 con `p5-ajuste-v1`, sin tocar `p5-eval-v1` ni las expectativas.
2. **#8:** C1–C10 ya corre completo, y falta su revisión.
3. **Medición final del benchmark:** la evidencia oficial cita `dacaa56`, anterior al watchdog de #5, a `config/politica.yaml` y a #6. Hay que repetirla cuando termine #3.
4. **Reproducción final:** volver a correr esta guía sobre esa versión de `main`, y actualizar este documento y el estado del README.

## Límites conocidos

- **Carro:** esta guía usa imágenes ya capturadas. No se probó con la cámara en vivo, ni se ha medido el ritmo real de `/stream`.
- **Hardware de la demostración:** falta confirmarlo. El benchmark oficial se midió en un laptop.
- **Sin red:** solo se probó en Linux. En Windows hubo conexión disponible durante la corrida.
- **Política:** Proyecto3/config/politica.yaml y config/politica.yaml tienen los mismos valores, pero distinto hash. Los comandos usan `config/politica.yaml`.
