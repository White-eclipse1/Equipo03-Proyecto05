# F11 — Autoevaluación, demo y congelación

| Campo | Valor |
|---|---|
| Responsable | Diego (PM · datos · evaluación · entrega) |
| Revisor de PRs | Edith |
| Fechas | 30 sep de 2026 |
| Rama | `feat/fase-11-autoevaluacion-cierre` |
| Puntos de rúbrica | 0 (Todas) |
| Depende de | F1–F10 |
| Bloquea a | — |
| Control | Control 3 |

**Nota de calendario:** Miércoles 30 en la tarde: autoevaluación, guion y ensayo de la demo, y tag final. Todo lo inyectado se revierte antes de etiquetar.

> Antes de empezar lee `AGENTS.md` (contexto y reglas) y `docs/contratos.md`. Trabaja los bloques en orden; cada bloque es al menos un PR.

## Bloque T29 — Autoevaluación con el prompt de rúbrica

**Objetivo:** Ejecutar el prompt de evaluación (docs/rubrica.md) sobre el repo como lo haría el docente y corregir lo que falle.

**Criterios de rúbrica:** Todas

**Pasos**

1. Corre el prompt completo con un agente sobre una copia limpia del repo en el commit candidato.
2. Registra la tabla de puntos obtenida y los criterios con puntuación < máximo.
3. Crea tarjetas de corrección en Notion para cada hueco y asígnalas al dueño del área; prioriza compuerta M1–M4 y 4.3.
4. Repite solo las secciones afectadas tras las correcciones.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [ ] Compuerta M1–M4 en CUMPLE
- [ ] Lista de pérdidas de puntos atendida o justificada

**Entregables:** `docs/autoevaluacion.md`; reporte HTML de ensayo

## Bloque T33 — Guion de demo de la cadena completa

**Objetivo:** Preparar una demo en la que, desde una versión del dataset, se siga el mismo trabajo hasta una predicción en el portal, y en la que cada integrante pueda explicar sus cifras.

**Criterios de rúbrica:** Todas (evidencia para la evaluación)

**Pasos**

1. Escribe docs/demo.md con los pasos y enlaces reales: release DVC (ID y hash) → manifiesto 70/20/10 y conteos → run seleccionado en MLflow (curvas, parámetros y selection.json) → evaluación en test (matriz, F1 por clase) → versión del modelo y objeto en S3 (key, VersionId, SHA-256) → predicción en Inference hecha con ese archivo descargado → envío a la cola de anotación.
2. Verifica que todos los enlaces apunten al mismo trabajo (mismos IDs de punta a punta).
3. Asigna quién explica cada tramo: Diego datos y test, Edith entrenamiento y MLflow, Andrés portal e inferencia; cada uno prepara la respuesta a '¿de dónde sale este número?' para sus cifras.
4. Haz un ensayo cronometrado con los tres.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [ ] docs/demo.md con IDs reales y consistentes
- [ ] Ensayo realizado con los tres integrantes

**Entregables:** `docs/demo.md`

## Bloque T30 — Congelamiento, etiqueta de entrega y checklist final

**Objetivo:** Cerrar la entrega con un commit identificable y trazabilidad completa.

**Criterios de rúbrica:** Todas

**Pasos**

1. Rellena docs/trazabilidad.md: release DVC y hash -> manifiesto y hash -> run MLflow elegido -> checkpoint -> versión -> S3 bucket/key y SHA-256 -> predicción de prueba desde el portal.
2. Confirma git status limpio, CI en verde en main y que no hay secretos (gitleaks o similar sobre el historial de P3).
3. Crea el tag git 'p3-entrega' y compártelo con el equipo.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [ ] Tabla de trazabilidad sin celdas vacías
- [ ] Tag creado sobre commit con CI verde

**Entregables:** `docs/trazabilidad.md`; Tag p3-entrega

## Definición de terminado

- [ ] Todas las casillas de aceptación marcadas con evidencia real
- [ ] PRs fusionados con review de Edith
- [ ] CI en verde en `main`
- [ ] Commits red → green visibles en el historial

## Registro de avance

| Fecha | Quién | Bloque | Qué se hizo / PR | Pendiente |
|---|---|---|---|---|
