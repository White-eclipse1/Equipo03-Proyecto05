# A3-04 (#29) — Auditoría independiente de datos, métricas y benchmark

Fecha: 2026-11-04. Owner: Omar Arenoso (@OmarCTMX). Entregables E3, E6, E7.
Revisión ejecutada con asistencia de IA; no se atribuye una firma humana al owner.

**Resultado:** integridad y cifras publicadas reproducidas sin diferencias numéricas.
Se revisaron visualmente 38 cuadros de las seis secuencias, con 33 cajas GT.
Hay dos observaciones de seguimiento: entorno de métricas fuera de la versión
de Python declarada y holgura de una caja. Los textos de issues están preparados;
su publicación en GitHub sigue pendiente de conexión. No se da por completado
ese requisito externo de #29 mientras no existan sus enlaces.

## Alcance y trazabilidad

| Fuente | Identificador |
|---|---|
| Commit auditado | `a6371279b3163dd7fc5ee697b27fee8865a10492` |
| Base del congelamiento | `54c1aa07d7118e0294b590b85f4f05dd1852098b` |
| Métricas publicadas | `0cf6dd9d35b567c92542681d820a7c9fd79f964c` |
| Ambos benchmarks publicados | `dacaa56b8a3fb0e8b86396104ab15fc0ea17ae58` |
| SHA-256 del manifiesto | `5dab9ee3f65cad0a1b31695d6d81c7a50c81fe3934f07572e53f64dc7e2ffeeb` |
| SHA-256 del modelo declarado por ambas evaluaciones | `427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7` |

Los hashes de cada archivo del paquete, de los ocho artefactos de resultados
y del script auditor quedan en
[`auditoria.json`](../evidencias/A3-04/recalculo/auditoria.json).
El commit identifica el árbol fuente anterior a este cambio; el hash del script
identifica el auditor nuevo, aún no commiteado al generar la evidencia.

El auditor `scripts/auditar_a3_04.py` no importa `p5.metrics`, `p5.benchmark`,
el validador de dataset ni el motor de política. Usa biblioteca estándar para
los cálculos y verificaciones; OpenCV solo para las láminas opcionales.
Es una comprobación de los artefactos, no otro evaluador de producción ni un
benchmark nuevo. No se modificó el paquete ni se ajustaron umbrales con él.

## Muestra visual

La revisión observó imágenes y cajas GT superpuestas; las dos imágenes dirigidas
también se inspeccionaron en su archivo original. La selección base fue temporal,
seis cuadros por secuencia, y se añadieron los dos FP publicados para examinar
sus parejas cercanas a IoU 0.50. No es una muestra aleatoria ni sirve para estimar
una nueva métrica poblacional.

| Secuencia | Frames revisados (sufijo) | Contenido |
|---|---|---|
| seq01 | 0001, 0004, 0007, 0010, 0013, 0015 | Jardín despejado |
| seq02 | 0001, 0006, 0010, 0015, 0020, 0024 | Persona central, lateral y salida |
| seq03 | 0001, 0003, 0005, 0008, 0010, 0012; dirigido 0006 | Persona izquierda, contraluz |
| seq04 | 0001, 0003, 0005, 0008, 0010, 0012 | Persona derecha, contraluz |
| seq05 | 0001, 0004, 0007, 0010, 0013, 0015 | Dos personas, centro y derecha |
| seq06 | 0001, 0026, 0030, 0038, 0045, 0050; dirigido 0028 | Despejado, aparición, centro y desaparición |

[`revision_visual.csv`](../evidencias/A3-04/revision_visual.csv) registra cada
`frame_id`, clases, cajas `xyxy` en píxeles originales, hash de imagen,
lámina, observación y discrepancia concreta. Las láminas están en
[`recalculo/laminas/`](../evidencias/A3-04/recalculo/laminas/).
Los 36 cuadros base no mostraron omisiones evidentes de clase o conteo dentro
de las ocho clases evaluadas. Eso no certifica cada borde de cada caja.

**A3-04-F02:** en `seq06-0028`, GT `person [44,0,111,144]` incluye margen vacío
superior: la cabeza visible comienza aproximadamente en y=12. Es una observación
visual que requiere segunda revisión y criterio de anotación, no una caja nueva
propuesta ni una corrección automática. Hay contraluz en jardín y cabezas fuera
de encuadre en biblioteca; las cajas deben describir la porción visible.

## Integridad del paquete congelado

Se contrastaron los 128 IDs únicos del manifiesto, anotaciones y capturas,
los archivos JPG presentes, los SHA-256 de todas las imágenes y el manifiesto,
las clases/cajas de anotaciones fuente y manifiesto, estados, dimensiones y
tiempos de captura entre metadatos. Las cajas están dentro del cuadro.
El inventario completo de archivos es idéntico antes y después del auditor.

Coinciden seis secuencias: 15, 24, 12, 12, 15 y 50 cuadros respectivamente;
76 cuadros con objetos y 52 negativos. El inventario registra también los
hashes de metadatos auxiliares: no afirma que el congelamiento original firme
cada archivo por separado, sino que el manifiesto y sus referencias coinciden.

## Reproducción independiente de métricas

Umbrales conservados: confianza ≥ 0.50 e IoU ≥ 0.50, emparejamiento por clase,
confianza descendente y una sola predicción y GT por pareja. Se calculó la
intersección/unión directamente desde coordenadas, sin llamar al evaluador.
Las parejas e IoU de la muestra se contrastaron además con los publicados.

| Ámbito | TP | FP | FN | Precisión | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Muestra de 38 cuadros, recálculo desde cajas | 23 | 2 | 10 | — | — | — |
| Global, desde conteos primarios de 128 cuadros | 64 | 2 | 27 | 0.9696969697 | 0.7032967033 | 0.8152866242 |
| person | 64 | 2 | 27 | 0.9696969697 | 0.7032967033 | 0.8152866242 |

Las otras siete clases tienen soporte, TP, FP y FN cero: sus métricas se
reproducen como 0 según la convención publicada, sin evidencia de rendimiento
para esas clases. Se contrastaron JSON y CSV globales y por clase. Fórmulas:
`P=TP/(TP+FP)`, `R=TP/(TP+FN)`, `F1=2TP/(2TP+FP+FN)`; denominador cero da 0.

Los dos FP de la publicación se reproducen como FP+FN, no TP:

- `seq03-0006`: IoU `0.42547619280841187`, GT `[57,110,97,182]`.
- `seq06-0028`: IoU `0.47284356754785883`, GT `[44,0,111,144]`.

El segundo caso motivó F02; su observación visual no cambia el resultado
aritmético sobre el GT congelado. El JSON auditor conserva cajas de ambas
partes, índices únicos, IoU, FP y GT no emparejados de todos los cuadros de muestra.

**A3-04-F01:** la ejecución de métricas declara `Python 3.13.15`, fuera de
`requires-python = ">=3.12,<3.13"`. La documentación original ya menciona esta
limitación. Se reproducen sus números desde los artefactos en Python 3.12,
pero esto no acredita una inferencia nueva en el entorno soportado.

## Reproducción independiente del benchmark

Se verificaron hashes CSV, fases, índices, conteos y percentiles de las siete
etapas de ambos resultados. Solo entran filas `fase=medicion`, `valido=True`
y sin error; se excluyen todos los calentamientos. Se ordenan n valores y se
interpola en la posición `(n-1)*q`, sin usar `numpy.percentile` ni `summarize`.

| Benchmark | Warmups excluidos | Mediciones válidas | p50 total (ms) | p95 total (ms) |
|---|---:|---:|---:|---:|
| A3-03 oficial | 10 | 200 | 62.85785 | 107.876675 |
| A3-03-programas-abiertos | 10 | 200 | 51.19845 | 92.018245 |

Ambos cumplen ≥100 mediciones válidas y ≥10 warmups. No hay diferencias
numéricas con lo publicado dentro de tolerancia absoluta/relativa `1e-10`.
Estos tiempos pertenecen al hardware, configuración y commits históricos
registrados; no acreditan el rendimiento del código actual ni una comparación
causal entre aplicaciones abiertas/cerradas.

## Comandos reproducibles

Desde `Proyecto5`, con Python 3.12 y las dependencias del proyecto:

```powershell
.venv/Scripts/python scripts/auditar_a3_04.py --output resultados/a3-04-verificacion --laminas
.venv/Scripts/python -m pytest tests/test_audit_a3_04.py
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
Get-FileHash data/p5-eval-v1/manifiesto.jsonl -Algorithm SHA256
git diff --exit-code -- data/p5-eval-v1
git rev-parse HEAD
```

La salida debe ser una carpeta nueva. Sin `--laminas`, el recálculo solo necesita
la biblioteca estándar. Código 0 significa consistencia numérica; no cierra las
observaciones visuales/de entorno ni publica issues. El script no sustituye una
revisión visual: el CSV es el registro de la inspección realizada en esta tarea.

Validación de este cambio: nueve pruebas específicas del auditor aprobadas;
suite completa con 410 aprobadas y 15 omitidas (pesos reales no configurados
y paquete no instalado). Ruff, formato y `git diff --check` correctos.

## Seguimiento y límites

- [F01: entorno de métricas](issues/A3-04-F01_ENTORNO.md): solicitar evidencia
  en Python 3.12, preservando la anterior y sin ajustar umbrales.
- [F02: criterio de caja en seq06-0028](issues/A3-04-F02_CAJA.md): segunda revisión;
  cualquier corrección aceptada requiere una versión posterior, nunca editar v1.
- Publicación de ambos issues pendiente: GitHub no conectado en esta sesión.
- No se repitió inferencia ni benchmark; se auditaron las salidas versionadas.
  No se verificaron físicamente los pesos ausentes, solo sus hashes declarados.
- La muestra visual cubre 38/128 cuadros, tiene selección dirigida y no es una
  certificación exhaustiva ni una revisión humana firmada. Solo hay soporte GT
  para `person`, con cuadros correlacionados y condiciones de captura limitadas.
