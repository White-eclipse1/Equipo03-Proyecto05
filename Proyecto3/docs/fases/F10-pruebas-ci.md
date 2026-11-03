# F10 — Pruebas, CI y ensayo de arranque

| Campo | Valor |
|---|---|
| Responsable | Andrés (Líder de portal y calidad) |
| Revisor de PRs | Diego |
| Fechas | 24 sep → 30 sep de 2026 |
| Rama | `feat/fase-10-pruebas-ci` |
| Puntos de rúbrica | 8 (7.1, 7.2, 7.3, M1) |
| Depende de | F1 (CI arranca el jueves 24) |
| Bloquea a | F11 |
| Control | Control 1 y 3 |

**Nota de calendario:** La CI se monta el jueves 24 y corre en cada PR; la prueba E2E y el ensayo desde clon limpio son el miércoles 30.

> Antes de empezar lee `AGENTS.md` (contexto y reglas) y `docs/contratos.md`. Trabaja los bloques en orden; cada bloque es al menos un PR.

## Bloque T25 — CI en GitHub Actions, lint y secretos

**Objetivo:** Pipeline que falla ante errores reales de lint, tipos, build o pruebas, y repo protegido contra secretos y archivos pesados.

**Criterios de rúbrica:** 7.3

**Pasos**

1. Workflow: ruff check + ruff format --check, pytest, build y typecheck del frontend, Biome si el portal ya lo usa. Sin continue-on-error.
2. Agrega gitleaks (o equivalente) sobre el diff/historial.
3. Actualiza .gitignore: pesos (*.pt, *.pth, *.onnx), mlruns/, datos, .env; asegura lockfiles commiteados.
4. Demuestra que falla: un PR de prueba con un error de ruff debe quedar en rojo.

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] Workflow en rojo ante un error inyectado y verde tras corregir → `.github/workflows/p3-ci.yml` corre `ruff check`, `ruff format --check` y `pytest` sin `continue-on-error` (commit `f8def1a`). Evidencia local del gate: un `import os` sin usar pone `ruff check` en **exit 1** (`F401`) y al revertir vuelve a **exit 0**; `pytest` local 143 passed / 1 skipped. _Confirmación de rojo→verde en la propia CI: en la primera corrida del PR de F10._
- [ ] gitleaks corre en CI → job `secrets` cableado en `p3-ci.yml` (gitleaks sobre el historial del PR). _Pendiente: evidencia de la primera corrida en CI (no ejecutable localmente)._

Además, atendiendo el feedback del equipo en el PR #10, la CI del portal (`ci.yml`, job `web`) ahora corre `npm run test:unit` junto a `npm test` y `build` (rama F8, commit `ee53384`).

**Entregables:** `.github/workflows/p3-ci.yml`; `.gitignore`

## Bloque T26 — Prueba de integración de extremo a extremo

**Objetivo:** Una prueba automatizada que recorra el flujo completo con IDs trazables, usando el fixture y MinIO/bucket de prueba.

**Criterios de rúbrica:** 7.2, 7.1

**Pasos**

1. Test (pytest o Playwright) que: selecciona release aprobado del fixture -> genera manifiesto -> lanza trabajo corto (1–2 épocas, imagen pequeña) -> verifica run en MLflow -> selección -> evaluación -> publicación en MinIO -> inferencia vía API/portal.
2. Imprime al final la cadena de IDs (release, manifiesto, run, checkpoint, versión, key, id de inferencia).
3. Prueba de mutación manual en rama aparte: permite un grupo duplicado en train y test, o altera una predicción en la matriz; confirma que la suite falla y documenta en docs/mutaciones.md; revierte.
4. Agrega el test al CI como job separado (puede marcarse como lento).

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [x] La prueba E2E pasa en CI → `Proyecto3/tests/test_e2e.py::test_e2e_flujo_completo` recorre el flujo **completo** in-process con F4–F7 ya en `main`: recortes → manifiesto 70/20/10 sin fuga → **10 entrenamientos** cortos en CPU → selección del candidato por validación → **evaluación en test** → publicación en un S3 falso → **inferencia**, imprimiendo la cadena de IDs (commit `8bbdf84`). Cableada como job separado `p3-e2e` en `p3-ci.yml`. Verificado local: `1 passed` en 16.5s; **suite P3 completa 373 passed / 1 skipped**. _Confirmación en la propia CI: primera corrida del PR._
- [x] Las mutaciones documentadas hacen fallar la suite → `docs/mutaciones.md` documenta dos mutaciones reales sobre el split de F3 (M-A: un grupo de casi duplicados se parte entre train y test — la opción que pide T26; M-B: `check_manifest` deja de ver la fuga) con la salida de `pytest` que las detecta; ambas revertidas con `git checkout` (commit `f649a45`).

**Entregables:** `tests/test_e2e.py`; `docs/mutaciones.md`

## Bloque T28 — Ensayo de arranque desde clon limpio (M1)

**Objetivo:** Garantizar que el docente puede levantar todo siguiendo el README literalmente.

**Criterios de rúbrica:** M1, M4

**Pasos**

1. En una máquina/directorio limpio: git clone, seguir el README paso a paso sin conocimiento previo.
2. Recorre las 5 páginas desde la navegación existente, recarga durante un trabajo corto, cambia la versión del modelo y prueba un archivo inválido.
3. Anota cada paso faltante o ambiguo y corrige el README en el momento.
4. Carga el checkpoint publicado en un proceso limpio e infiere una imagen (M4).

**Aceptación** (marca al cumplir, con enlace a la evidencia)

- [ ] Arranque completo sin pasos inventados → **parcial**: `docs/ensayo_arranque.md` registra el ensayo en seco de lo que no depende del stack (pruebas de P3 144/2, portal 31/31, build) y las observaciones del README. El arranque completo con `up.py` se ejecuta en el ensayo del **30** (necesita Docker y el stack).
- [ ] Las 5 páginas funcionan con datos reales → **pendiente**: hoy corren contra el mock/contrato; con datos reales cuando **F4–F7** estén en `main` (Evaluation/Models/Inference además son de F9).

**Entregables:** README corregido; `docs/ensayo_arranque.md`

## Definición de terminado

- [ ] Todas las casillas de aceptación marcadas con evidencia real
- [ ] PRs fusionados con review de Diego
- [ ] CI en verde en `main`
- [ ] Commits red → green visibles en el historial

## Registro de avance

| Fecha | Quién | Bloque | Qué se hizo / PR | Pendiente |
|---|---|---|---|---|
| 27 sep 2026 | Andrés | T25 | Rama `feat/fase-10-pruebas-ci`. Nuevo `.github/workflows/p3-ci.yml`: job `p3-python` (instala el lockfile de Proyecto3 + `ruff check`/`ruff format --check`/`pytest`, sin `continue-on-error`) y job `secrets` (gitleaks sobre el historial del PR). `.gitignore` de P3 agrega `*.onnx`. Verificado local: ruff limpio, pytest 143/1, y un error de ruff inyectado pone el gate en rojo (exit 1). Aparte, en la rama F8 se añadió `npm run test:unit` a `ci.yml` (feedback del PR #10). Commit `f8def1a`. | Confirmar rojo→verde y gitleaks en la primera corrida de CI del PR. |
| 27 sep 2026 | Andrés | T25 | Fix: gitleaks por CLI (binario) en vez de la action, que fallaba en CI con "Resource not accessible by integration"; nuevo `.gitleaks.toml` con allowlist de ejemplos/locks/fixtures. Commit `b1d4177`. | Confirmar verde en la corrida del PR. |
| 27 sep 2026 | Andrés | T26 | `docs/mutaciones.md`: dos mutaciones reales sobre el split (M-A grupo partido, M-B `check_manifest` ciego), verificadas y revertidas (`f649a45`). Tras mergear `origin/main` (F4–F7), **E2E completo** `test_e2e_flujo_completo`: recortes→manifiesto→10 entrenamientos→selección→evaluación→S3 falso→inferencia con cadena de IDs (`8bbdf84`). Verificado local: E2E 1 passed (16.5s); **suite P3 373 passed / 1 skipped**. | Confirmar en la corrida del PR. Extensión opcional: mutación sobre la matriz de F6. |
| 27 sep 2026 | Andrés | T28 | `docs/ensayo_arranque.md`: bitácora del ensayo. Verificado en seco lo que no depende del stack (pytest 144/2, portal 31/31, build) y anotadas observaciones del README. Commit posterior. | Ensayo completo con `up.py` + 5 páginas con datos reales + M4 el miércoles 30 (necesita F4–F7). |
