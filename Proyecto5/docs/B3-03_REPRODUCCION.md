# B3-03 — Reproducción limpia y paquete final

Ticket: #9. Entregables: E1–E7.

## Objetivo

Demostrar que otra persona puede recuperar y ejecutar el proyecto sin intervención del equipo.

**Estado: reproducción completa.** Desde una copia limpia de `main` en `2265d60`, todos los pasos dan `ok` en Linux y en Windows, incluidos los 10 casos C1–C10.

## Componentes

- [README.md](../README.md): preparación, comandos y entregables.
- scripts/reproducir.py: corre todos los comandos y resume el resultado.
- tests/test_reproduccion.py: comprueba el resumen, la guía, la evidencia y que el código no abra conexiones de más.
- evidencias/B3-03/: resumen de cada corrida y el cuadro trazado.

Los comandos están en el README.

## Resultado final

Sobre `2265d60`, sin cambios locales, con Python 3.12.16 y dependencias fijadas.

| Paso | Linux, sin red | Windows |
|---|---|---|
| Hash del detector | ok | ok |
| Dataset de evaluación y de ajuste | ok | ok |
| Inferencia | ok | ok |
| Recorrido y traza de un cuadro | ok | ok |
| Decisiones C1–C7, detecciones sintéticas | ok, 7 de 7 | ok, 7 de 7 |
| C1–C10 | ok: 10 pasan, 0 fallan y 0 pendientes | ok: igual |
| Métricas | ok: 83 TP, 1 FP y 8 FN | ok: mismos conteos |
| Benchmark | ok: 200 de 200 válidas | ok: 200 de 200 válidas |
| Pruebas | 530 pasan | 530 pasan |

- **Linux:** contenedor `python:3.12`. La preparación usó la red, y todo lo demás corrió con `--network none`.
- **Windows:** clon limpio con los comandos de PowerShell del README, usando la alternativa a `py -3.12` que indica la guía.
- **Benchmark:** estas corridas solo comprueban que el comando funciona. Sus tiempos no son evidencia; la medición oficial está en [A3-03_BENCHMARK.md](A3-03_BENCHMARK.md).
- **Este documento:** el commit que agrega esta evidencia no cambia código, datos ni configuración.

### Traza de un cuadro

`seq02-0003` → person, backpack y car → BLOCKED → EVADE_LEFT → `left`, velocidad 0.2 y giro −0.5, con el mismo `frame_id` en cada etapa.

## Criterios del ticket

| Criterio | Estado | Cómo se comprobó |
|---|---|---|
| Copia limpia del repositorio | Hecho | Clones limpios en Linux y Windows |
| Instalación con dependencias fijadas | Hecho | `requirements.lock.txt` |
| El detector se recupera y su hash se verifica | Hecho | Descarga real y `--verify-only` |
| El dataset se recupera | Hecho | Viene en el repositorio y se valida |
| Comandos de inferencia, recorrido y C1–C10 | Hecho | `reproducir.py` |
| Comandos de métricas y benchmark | Hecho | `reproducir.py` |
| Motores desactivados por defecto | Hecho | `salida_fisica: false` y una prueba |
| Sin AWS | Hecho | Una prueba revisa las conexiones del código |
| Sin servicios externos después de la preparación | Hecho | Linux con `--network none` |
| Trazar un cuadro de principio a fin | Hecho | evidencias/B3-03/linux/cuadro_trazado.json |
| README con todos los comandos | Hecho | Se ejecutaron tal cual, y una prueba compara PowerShell con Linux |
| Sin secretos en el repositorio | Hecho | gitleaks del CI en `2265d60` |
| Resultados en una carpeta configurable | Hecho | `--output`, sin reemplazar resultados anteriores |

## Límites conocidos

- **Carro:** esta guía usa imágenes ya capturadas. No se probó con la cámara en vivo, ni se ha medido el ritmo real de `/stream`.
- **Hardware de la demostración:** falta confirmarlo. La medición oficial se hizo en un laptop con Intel i9-12900H.
- **Filtro de mediana:** los 10 casos pasan con el filtro 3×3, activo por defecto. Con `--filtro-mediana 0`, C5 y C7 fallan.
- **Limitación aceptada:** en `seq06-0025` aparece un `truck` falso que causa un SLOW con la vía libre. El PR 50 lo aceptó como limitación documentada.
- **F1:** 0.9486 puede ser optimista, porque se revisaron puntajes de la evaluación durante el diagnóstico. Ver [B1-03_DETECTOR.md](B1-03_DETECTOR.md).
- **Sin red:** solo se probó en Linux. En Windows hubo conexión disponible durante la corrida.
- **Política:** Proyecto3/config/politica.yaml y config/politica.yaml tienen los mismos valores, pero distinto hash. Los comandos usan `config/politica.yaml`.
