# AGENTS.md — Proyecto 3: Clasificador de imágenes integrado al portal

## Contexto

Proyecto 3 = clasificador multiclase de UN objeto por imagen, integrado en la MISMA webapp de los Proyectos 1 (anotación COCO con bounding boxes) y 2 (dataset con controles de calidad y release versionado con DVC, split 70/15/15). Flujo obligatorio: release aprobado de P2 -> recortes de cajas COCO + manifiesto derivado -> nuevo split 70/20/10 -> entrenamiento (PyTorch, versiones fijadas) -> >=10 corridas en MLflow -> selección del candidato por VALIDACIÓN -> evaluación única en TEST congelado -> versión de modelo + tarjeta -> pesos en AWS S3 -> inferencia desde el portal. Páginas nuevas: Training, Experiments, Evaluation, Models, Inference. Meta: accuracy top-1 >= 0.85 en test. La rúbrica completa está en docs/rubrica.md y los contratos entre módulos en docs/contratos.md.

Documentos de referencia (las rutas `docs/...` son relativas a `Proyecto3/`):
- `docs/PLAN.md`: equipo, roles, cronograma, controles y Git.
- `docs/rubrica.md`: rúbrica completa con la que se evalúa.
- `docs/contratos.md`: esquemas congelados entre módulos (manifiesto, config de entrenamiento, API, selección, versión de modelo).
- `docs/fases/`: un archivo por fase con bloques, pasos, criterios de aceptación y registro de avance.

## Cómo trabajar una fase

1. Identifica la fase que te pidieron y abre su archivo en `docs/fases/`. Trabaja solo esa fase.
2. Crea o continúa su rama (indicada en el archivo). Si otra persona empezó la fase, sigue en la misma rama.
3. Ejecuta los bloques en orden. Para cada bloque: prueba en rojo (commit), implementación en verde (commit), refactor si hace falta.
4. Si dependes de trabajo de otra fase que aún no está en `main`, trabaja contra `docs/contratos.md` y `tests/fixtures/p3/`, y anótalo como pendiente en el registro.
5. Al cerrar un bloque: marca sus casillas de aceptación con enlace a la evidencia, agrega una fila en "Registro de avance" y abre el PR para el revisor indicado.
6. Nunca marques una casilla sin evidencia real (salida de comando, run de MLflow, objeto en S3, comportamiento en el portal).

## Mapa de fases

| ID | Fase | Responsable | Fechas | Archivo |
|---|---|---|---|---|
| F1 | Kickoff, arranque del stack y contratos | Edith | 24 sep | `docs/fases/F1-arranque-contratos.md` |
| F2 | Almacenamiento, release y recortes COCO | Diego | 24 sep → 25 sep | `docs/fases/F2-release-recortes.md` |
| F3 | Manifiesto 70/20/10 sin fuga | Diego | 25 sep → 28 sep | `docs/fases/F3-manifiesto.md` |
| F4 | Modelo, entrenador y servicio de inferencia | Edith | 25 sep → 29 sep | `docs/fases/F4-modelo-entrenador.md` |
| F5 | Experimentos MLflow y selección | Edith | 28 sep → 29 sep | `docs/fases/F5-experimentos-seleccion.md` |
| F6 | Evaluación final en test | Diego | 28 sep → 29 sep | `docs/fases/F6-evaluacion-test.md` |
| F7 | Paquete, tarjeta y publicación en S3 | Diego | 29 sep → 30 sep | `docs/fases/F7-paquete-s3.md` |
| F8 | Portal: Training y Experiments | Andrés | 24 sep → 28 sep | `docs/fases/F8-portal-training-experiments.md` |
| F9 | Portal: Evaluation, Models e Inference | Andrés | 28 sep → 30 sep | `docs/fases/F9-portal-evaluation-models-inference.md` |
| F10 | Pruebas, CI y ensayo de arranque | Andrés | 24 sep → 30 sep | `docs/fases/F10-pruebas-ci.md` |
| F11 | Autoevaluación, demo y congelación | Diego | 30 sep | `docs/fases/F11-autoevaluacion-cierre.md` |

## Reglas del equipo

1. **Ramas por fase, no por persona:** `feat/fase-N-*`. Si alguien retoma una fase de otro, sigue en la misma rama.
2. **TDD real:** el commit `red` va antes del `green`. Nunca ambos en un commit ni reconstruidos después; el historial es evidencia (criterio 7.1).
3. **Commits pequeños**, un cambio lógico por commit; no mezclar fases.
4. **Pydantic v2 con sintaxis v2:** `field_validator`, `model_validator`, `ConfigDict`, `model_dump()`. Nada de `pydantic.v1`, `@validator`, `.dict()` ni `class Config:`. La config de entrenamiento inválida se rechaza nombrando el campo, por API y por portal, antes de crear el trabajo (2.2).
5. **`ruff check . && ruff format --check .` en cero** antes de cualquier commit, con reglas elegidas por el equipo.
6. **Lógica pura:** recortes, split, entrenamiento, métricas y evaluación no leen `os.environ` ni crean clientes de S3/MLflow/BD; eso vive en `config`/`settings` y se inyecta.
7. **Python 3.12 fijado** en `pyproject.toml` y en el `Dockerfile`, con lockfile pineado (incluidas las versiones de PyTorch/torchvision).
8. **El test es intocable hasta la selección.** No se usa para aumentación, early stopping ni para elegir hiperparámetros. `selection.json` se commitea antes de correr la evaluación final; romper este orden es 0 en 3.3 y 4.1.
9. **Clases fijadas antes de experimentar:** ≥2 clases con ≥300 originales distintos. Quitar clases después de ver el test para llegar al 85% cuenta como resultado inflado.
10. **Nunca versionar** credenciales de AWS, MinIO o MariaDB, llaves de LLM, pesos (`*.pt`, `*.pth`), `mlruns/` ni datos. El evaluador revisa todo el historial de P3.
11. **Contratos congelados** en `docs/contratos.md`; cualquier cambio de forma va explícito en el PR y se avisa al equipo.
12. **`git config user.name` / `user.email` reales.**
13. **Reporte diario del barrido** en el grupo a partir del lunes 28: corridas FINISHED y mejor `val_accuracy`. Las 10 corridas válidas no se recuperan con un cierre heroico.
14. **Las pruebas destructivas** (datos malos, mutaciones) van en copia o rama aparte; nunca se escribe ni borra en el bucket de producción para probar.
15. **El jueves 1** es exclusivamente revisión y corrección sobre el feedback.
