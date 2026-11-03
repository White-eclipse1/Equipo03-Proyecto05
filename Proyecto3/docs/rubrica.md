# Prompt de evaluación — Proyecto 3: Clasificador de imágenes integrado al portal (repo Git)

> Cópialo en un agente con acceso al repositorio entregado. Sustituye `<RUTA_O_URL_DEL_REPO>`, `<EQUIPO>`, `<MATERIA>`, `<DOCENTE>` y `<CICLO_ESCOLAR>` antes de ejecutarlo. `<RUTA_LOGO_ITESO>` es opcional: debe apuntar a un archivo local `.svg` o `.png`; si falta, usa el respaldo tipográfico indicado al final.

---

## CONTEXTO Y ALCANCE

El equipo **ya completó los Proyectos 1 y 2**. El Proyecto 1 produjo imágenes, categorías y anotaciones COCO con *bounding boxes* desde el portal. El Proyecto 2 produjo un dataset sometido a controles de calidad, con release versionado mediante DVC. **No vuelvas a calificar esas entregas.** Comprueba únicamente que el Proyecto 3 consume un release aprobado y que la cadena hasta el modelo publicado es real y trazable.

La tarea del Proyecto 3 es **clasificación multiclase de un objeto por imagen**. Cada muestra de entrenamiento es un recorte obtenido de una caja COCO válida; su etiqueta es la categoría de esa caja. Un original puede producir varios recortes. Antes de los experimentos, el equipo fija y documenta las clases incluidas y las exclusiones; debe incluir al menos dos clases con **≥ 300 imágenes originales distintas por clase** en el release aprobado, como exigía el Proyecto 2. No se permite elegir o eliminar clases después de ver el resultado de prueba para facilitar el 85%.

El flujo esperado dentro de **la misma webapp** es:

`release aprobado del Proyecto 2 → recortes y manifiesto derivado → split 70/20/10 → entrenamiento → ≥10 corridas en MLflow → selección por validación → evaluación final en prueba → versión del modelo y tarjeta → pesos en AWS S3 → inferencia desde el portal`.

El Proyecto 2 usaba un split 70/15/15. El 70/20/10 de este proyecto debe ser un **nuevo manifiesto derivado y versionado**, vinculado al release de origen; no debe sobrescribirlo ni reutilizar un test que se haya empleado para ajustar el modelo. El conjunto de prueba permanece fuera del entrenamiento, la aumentación y la selección de hiperparámetros.

Se permite usar LeNet, AlexNet, ResNet u otra CNN justificada como base, **con o sin pesos preentrenados**. El equipo debe adaptar el clasificador a sus clases, entrenar pesos realmente y declarar el origen de cualquier peso inicial. Una red descargada que solo ejecuta inferencia no es un modelo propio para este proyecto. El framework de entrenamiento puede ser PyTorch o TensorFlow/Keras, con versiones fijadas.

Las cinco páginas nuevas del portal son **Training, Experiments, Evaluation, Models e Inference**. Los diseños visuales son referencias de organización; una captura o interfaz estática no demuestra funcionalidad.

**Meta de desempeño:** accuracy *top-1* **≥ 85.00%** sobre el conjunto de prueba congelado, con el checkpoint elegido por validación. La meta tiene puntos propios en la rúbrica y **no activa por sí sola la compuerta de 60**. También se reportan F1 macro y métricas por clase para detectar un resultado inflado por desbalance.

---

## ROL

Eres un evaluador técnico senior. Califica el repositorio en `<RUTA_O_URL_DEL_REPO>` del equipo `<EQUIPO>`. Tu trabajo es **verificar evidencia y asignar puntos**, no arreglar, completar ni desplegar el proyecto por ellos.

## REGLAS DE EVALUACIÓN

1. **Sin evidencia, no hay puntos.** Cada punto otorgado requiere ruta y línea de código, salida real de comando, registro persistido de MLflow, objeto verificable de S3 o comportamiento observado en la webapp. Si algo no se pudo verificar, puntúa 0 en ese criterio y explica la causa.
2. **Califica la ejecución, no la intención.** README, capturas, mocks, tablas fijas, `TODO`, datos de demostración y tests que no corren no sustituyen un flujo funcional. Si README y código discrepan, prevalece el código.
3. **Respeta el alcance acumulativo.** Verifica la conexión con el dataset y portal existentes; no recalifiques toda la anotación, los analizadores, Terraform o la infraestructura del Proyecto 2.
4. **Recalcula las cifras importantes.** Comprueba el split, las diez corridas válidas, la matriz de confusión y el accuracy con datos primarios. No aceptes un número solo porque aparece en pantalla o en la tarjeta del modelo.
5. **No repitas las diez corridas completas.** Inspecciona sus registros y artefactos persistidos; ejecuta una corrida corta de humo con datos de prueba si el entorno lo permite. Recalcula la evaluación final a partir de predicciones por muestra o vuelve a inferir el test con el checkpoint publicado.
6. **Usa un entorno aislado para pruebas destructivas.** Las mutaciones, datos malos y cambios de configuración van en una copia o directorio temporal. Restaura todo, documenta qué inyectaste y confirma `git status` limpio al terminar. No escribas ni borres objetos de un bucket de producción para probar la rúbrica.
7. **Puntuación parcial:** usa incrementos de 0.5. Completo y demostrado → todos los puntos; implementado con fallas reproducibles → hasta la mitad, salvo topes explícitos; ausente, simulado o no verificable → 0. El criterio del 85% es binario según lo indicado en 4.3.
8. **Código generado con IA no penaliza.** Sí penaliza que las pruebas no detecten fallas, que los números sean inventados o que la interfaz no esté conectada al backend.
9. **Idioma de salida: español.** Tono directo y accionable. No expongas claves, tokens ni datos sensibles en el reporte.

---

## FASE 0 — Inventario y línea base

Ejecuta desde el clon entregado y conserva las salidas. Adapta la sintaxis al shell cuando haga falta; no alteres los pasos documentados por el equipo para que arranque.

```bash
git rev-parse --short HEAD
git status --short
git log --oneline --graph --all | head -60
git shortlog -sne --all
git branch -a
rg --files -g '!node_modules' -g '!.venv' -g '!.git' -g '!.dvc/cache' | head -300
rg -n "mlflow|dvc|train|early.stop|checkpoint|predict|s3|70/20/10|0.7|0.2|0.1" . -g '!node_modules' -g '!.venv' -g '!.git' -g '!.dvc/cache' | head -200
dvc remote list -v
dvc status
```

Identifica: commit evaluado, comando de arranque, release DVC de origen, estado de su compuerta de calidad, manifiesto derivado, código que construye recortes, framework, worker de entrenamiento, URI de MLflow, rutas de las cinco páginas, versión publicada y clave del objeto de S3. Localiza las credenciales **sin imprimir sus valores**.

Si `rg`, DVC, Docker, MLflow, AWS CLI o una GPU no están disponibles, registra el error real y usa código o API equivalente cuando sea posible. Una GPU ausente no invalida las diez corridas ya persistidas; un registro de corridas inexistente sí.

---

## FASE 1 — Requisitos mínimos (compuerta)

Comprueba los cuatro. **Si cualquiera falla, la calificación final se topa en 60**, aunque la suma de secciones sea mayor. El 85% se evalúa por separado en 4.3.

| # | Requisito | Verificación exigida |
|---|---|---|
| M1 | El clon arranca siguiendo el README y muestra el portal existente, el worker de entrenamiento y MLflow | Sigue literalmente los pasos documentados desde un clon limpio. Abre una ruta existente del portal y `Training`; inicia o inspecciona un trabajo. Si tuviste que inventar pasos o conectar servicios a mano, no cumple. |
| M2 | El Proyecto 3 consume un release **aprobado y versionado** del Proyecto 2 | Sigue en código y en una corrida real el ID/hash DVC, la política aprobada, el COCO y las imágenes hasta el manifiesto de entrenamiento. Un dataset de ejemplo copiado a `data/`, una URL no versionada o métricas estáticas no cumplen. |
| M3 | Train, validación y prueba están aislados | Comprueba intersecciones vacías de IDs de recortes, imágenes originales y grupos de duplicados entre particiones; la aumentación queda solo en train. Verifica que el test no haya participado en selección o early stopping. Cualquier fuga demostrada implica no cumple. |
| M4 | Existe un modelo entrenado que se puede volver a cargar para inferencia | Obtén el checkpoint que la aplicación identifica como publicado, cárgalo en un proceso limpio con su mapa de clases y preprocesamiento, e infiere una imagen válida. Un archivo vacío, un modelo fijo o una predicción inventada no cumplen. |

Reporta **CUMPLE / NO CUMPLE** con evidencia concreta. No marques M1 como fallido solo por falta de GPU si el stack inicia y el proyecto ofrece un modo de verificación corto documentado. Separa con claridad un fallo del equipo de una limitación del entorno de evaluación.

---

## FASE 2 — Evaluación por secciones (100 pts)

Para cada criterio, asigna puntos y di **exactamente qué falta** para obtenerlos completos. Incluye una cita de archivo y línea o una prueba ejecutada. Los números entre paréntesis son los máximos; los siete subtotales suman 100.

### 1. Integración y datos de entrenamiento — 14 pts

- **1.1 (4)** **Traspaso real desde Proyecto 2.** `Training` selecciona un release DVC con compuerta aprobada y consume su COCO e imágenes mediante el servicio existente. Conserva versión, hash y referencia de calidad. Cambia la versión seleccionada en un entorno de prueba: el manifiesto y los conteos deben cambiar. Si lee un dataset fijo que solo se parece al release, 0.
- **1.2 (5)** **Recortes COCO correctos y selección de clases previa.** Cada muestra conserva `image_id`, `annotation_id`, categoría y coordenadas de origen. Rechaza cajas degeneradas, fuera de imagen o imágenes faltantes; registra exclusiones. Usa al menos dos clases con ≥ 300 imágenes originales distintas cada una en el release aprobado, elegidas antes de observar el test. Verifica manualmente varios recortes y etiquetas contra el COCO original. Si el modelo clasifica imágenes completas que contienen varias clases como si tuvieran una sola etiqueta, 0.
- **1.3 (5)** **Manifiesto 70/20/10 reproducible y sin fuga.** Los conteos de recortes apuntan a 70/20/10, con desviación global máxima de **±5 puntos porcentuales por partición**, salvo que grupos indivisibles impidan cumplirla y el equipo demuestre la mejor asignación factible. Todos los recortes de una imagen y los grupos de duplicados cercanos quedan juntos; ninguna muestra aumentada aparece en validación o prueba. Dos generaciones con la misma semilla producen los mismos IDs. El manifiesto derivado tiene versión/hash propio vinculado al release 70/15/15 del Proyecto 2. Reporta conteos por clase y partición y presencia de cada clase en validación y prueba, no solo porcentajes globales.

### 2. Modelo, entrenamiento y reproducibilidad — 18 pts

- **2.1 (5)** **Clasificador entrenado por el equipo.** Arquitectura LeNet, AlexNet, ResNet u otra CNN documentada; salida y mapa de clases correctos; pesos actualizados por entrenamiento real. Declara si parte de cero o de pesos preentrenados, su origen y qué capas son entrenables. Infiere una muestra antes y después de una corrida corta y revisa que los pesos cambien. Una llamada a un modelo descargado sin entrenamiento propio → 0.
- **2.2 (4)** **Entrenamiento por minibatches y parámetros configurables.** Evidencia de `batch_size`, pasos de optimizador por lote y configuración validada para optimizador, tamaño de batch, épocas máximas, learning rate, tamaño de imagen, capas ocultas de la cabeza y dropout. Introduce un valor inválido por API y por portal: debe rechazarse con mensaje útil antes de crear un trabajo. Parámetros visibles en la UI pero ignorados por el entrenador → 0.
- **2.3 (4)** **Semillas y aumentación controlada.** La corrida registra semilla para partición, shuffle/DataLoader, aumentación e inicialización de pesos, más versiones de librerías y entorno. Los transforms aleatorios solo afectan train; validación, prueba e inferencia comparten preprocesamiento determinista. Repite una corrida corta con igual semilla y entorno para comprobar mismo orden de muestras y resultados razonablemente reproducibles; documenta cualquier operación no determinista.
- **2.4 (5)** **Curvas, early stopping y mejor checkpoint.** Registra loss y accuracy de train/validación por época; muestra las curvas reales y la época de parada. Configura métrica vigilada, `patience` y `min_delta`; el entrenamiento se detiene cuando corresponde y restaura los pesos de la mejor época, no los de la última. Verifica con una secuencia controlada de métricas de validación y compara el checkpoint final con la mejor época. Sin curvas o sin restauración → máximo 2.5.

### 3. Experimentos y MLflow — 14 pts

- **3.1 (6)** **Diez experimentos válidos.** Hay al menos **10 corridas terminadas**, con entrenamiento real y resultados distintos, sobre la misma versión de manifiesto y definición de clases. La búsqueda varía de forma explícita los siete parámetros solicitados: optimizador, batch size, épocas máximas, learning rate, image size, capas ocultas y dropout; cada uno aparece con al menos dos valores entre las corridas, salvo incompatibilidad técnica explicada y demostrada. Corridas fallidas, duplicados exactos o ejecuciones de un solo batch hechas para inflar el conteo no cuentan. Enumera IDs de las diez válidas.
- **3.2 (5)** **Registro completo en MLflow.** Por corrida: parámetros efectivos, semilla, commit, release DVC, hash del manifiesto, clases, estado, métricas por época y artefactos (curvas y checkpoint). Consulta el servidor/API de MLflow, no solo los archivos de la UI. Si hay datos en la pantalla sin la corrida correspondiente, 0 para ese dato.
- **3.3 (3)** **Comparación y elección reproducible.** `Experiments` ordena y filtra corridas con datos reales; la selección del candidato usa una métrica de validación predeclarada y remite a un run ID y checkpoint inequívocos. Verifica cronología: selección antes de evaluación en test. Elegir el mejor por test o cambiar de candidato tras ver el test → 0.

### 4. Evaluación final y calidad del clasificador — 18 pts

- **4.1 (5)** **Protocolo de prueba congelado.** Evalúa el checkpoint elegido una vez como decisión final sobre el 10% de test, sin entrenar, aumentar ni ajustar umbrales o hiperparámetros con esas etiquetas. Guarda por muestra ID, clase real, clase predicha y, si aplica, probabilidades. La evaluación puede repetirse para auditoría con el mismo artefacto y manifiesto; no puede usarse para elegir otro modelo. Verifica orden temporal y hashes.
- **4.2 (4)** **Matriz y métricas correctas.** Matriz de confusión con filas reales y columnas predichas, todas las clases, conteos que suman el total del test, accuracy, F1 macro, precisión/recall/support por clase. Recalcula independientemente desde las predicciones guardadas y compara con MLflow, API y portal. Una matriz hecha con validación presentada como prueba → 0.
- **4.3 (6)** **Umbral de 85% en test.** Usa `aciertos / número total de recortes de test`, sin redondear antes de comparar con **0.85**. Los IDs deben pertenecer al test congelado y el clasificador debe cubrir las clases declaradas. **≥ 0.85 verificado: 6 pts; < 0.85, cifra no verificable, clases omitidas para inflar el resultado o fuga: 0 pts.** Este criterio no es una compuerta global.
- **4.4 (3)** **Interpretación de errores.** Incluye ejemplos navegables de aciertos y errores con recorte, etiqueta real, predicción y clase; reporta clase más confundida y un baseline de clase mayoritaria calculado sobre el mismo test. Explica si el 85% oculta bajo recall de alguna clase. Ejemplos decorativos o elegidos de train → 0.

### 5. Versión, tarjeta y publicación en S3 — 10 pts

- **5.1 (4)** **Paquete de modelo completo.** Versión semántica propia del modelo, pesos/checkpoint, configuración de arquitectura, mapa de clases, preprocesamiento, dependencias y tarjeta con propósito, datos y release de origen, split, run ID MLflow, métricas de test, limitaciones y origen de pesos preentrenados. La tarjeta debe describir el artefacto publicado, no otro experimento.
- **5.2 (4)** **AWS S3 real y recuperable.** Comprueba bucket y clave de los pesos y la tarjeta mediante API/CLI de solo lectura; registra `VersionId` si existe y hash SHA-256 calculado localmente. Descarga ambos a un entorno limpio y ejecuta inferencia con el modelo descargado. Configuración de S3 sin objeto real → máximo 2; solo MinIO local → máximo 2. Nunca atribuyas al ETag de S3 el significado de SHA-256 sin comprobarlo.
- **5.3 (2)** **Registro y versionado navegables.** `Models` resuelve versiones publicadas a run ID, dataset y artefactos correctos; una versión anterior sigue recuperable. Si se usa MLflow Model Registry, comprueba registro/alias y backend persistente. Cambiar la versión seleccionada debe cambiar el artefacto cargado, no solo el texto en pantalla.

### 6. Portal integrado de extremo a extremo — 18 pts

Las cinco páginas deben vivir en **la misma aplicación** de los Proyectos 1 y 2. Evalúa acciones y datos reales, no fidelidad píxel a píxel con los mockups.

- **6.1 (4)** **Training.** Selección de release aprobado, vista de procedencia y split derivado, formulario de todos los parámetros, validación y lanzamiento de un trabajo. El entrenamiento corre fuera del request HTTP; estado, progreso, logs y error persisten al recargar la página. Rechaza iniciar con quality gate fallido o test mezclado.
- **6.2 (3)** **Experiments.** Tabla de diez corridas reales, filtros/comparación de parámetros y curvas de train/validación alimentadas por MLflow. Abrir un run lleva al mismo ID y artefactos de backend. Cambia un dato de una corrida en un entorno de prueba y comprueba que la UI se actualiza.
- **6.3 (3)** **Evaluation.** Muestra candidato seleccionado, versión de datos, métricas finales, matriz de confusión y ejemplos del test con datos reales. Impide que la pantalla revele resultados de test antes de cerrar la selección del modelo. Exportación o consulta de predicciones por muestra para auditoría.
- **6.4 (4)** **Models.** Lista versiones, muestra la tarjeta y su trazabilidad, estado de publicación S3, acciones de descarga y elección de versión para inferencia. No permite marcar como publicado un objeto inexistente. La página no debe confundir versión de dataset con versión de modelo.
- **6.5 (4)** **Inference.** Acepta imagen nueva y recorte elegido desde el portal, valida tipo/tamaño, usa la versión publicada seleccionada y el mismo preprocesamiento de evaluación; devuelve clase y probabilidades coherentes (suma aproximada a 1). La acción «enviar a cola de anotación» crea un elemento consultable en el flujo existente. Comprueba que la predicción sale de los pesos cargados, no de reglas fijas.

### 7. Pruebas, CI y disciplina de repositorio — 8 pts

- **7.1 (4)** **Pruebas que detectan fallas reales y TDD.** Pruebas para recortes/etiquetas, separación por grupos, ausencia de aumentación en val/test, early stopping y restauración, métricas y carga del modelo. Busca ciclos Red → Green en commits del Proyecto 3. En copia aislada, rompe una regla crítica (por ejemplo permite un grupo duplicado en train y test, o cambia una predicción en la matriz) y verifica que la suite falle; restaura después. Tests que siguen verdes → máximo 2.
- **7.2 (2)** **Prueba de integración del recorrido.** Una prueba automatizada o demostración reproducible cubre release aprobado → trabajo corto → run MLflow → evaluación → registro/publicación de prueba → inferencia desde el portal, con IDs trazables. Puede usar MinIO/bucket de prueba para operaciones de escritura; la publicación en AWS S3 se verifica por separado en 5.2.
- **7.3 (2)** **CI, lint y secretos.** Ruff para el código Python, chequeo de tipos/build del frontend y pruebas corren en GitHub Actions y fallan ante errores; conserva Biome si el portal ya lo usa. No hay `continue-on-error` que esconda el resultado. Lockfile y `.gitignore` excluyen pesos, datos grandes y secretos; busca llaves nuevas en HEAD e historial del Proyecto 3 sin revelar valores. Configuración vacía o workflows que solo imprimen → parcial o 0.

---

## FASE 3 — Protocolo de verificación y salida obligatoria

### Comprobaciones mínimas

1. **Datos:** extrae del manifiesto `crop_id`, `source_image_id`, grupo de duplicados, clase y split. Calcula intersecciones entre particiones por los tres identificadores; cuenta muestras y originales distintos por clase. Comprueba dos generaciones con la misma semilla. Inyecta una caja degenerada y verifica que no entre al manifiesto.
2. **Entrenamiento:** identifica el loop por batches y pasos del optimizador; ejecuta una corrida corta con otro ID de experimento o en entorno aislado. Introduce un parámetro inválido y una secuencia de validación que obligue al early stopping; comprueba restauración del mejor checkpoint.
3. **MLflow:** consulta el tracking server/API y enumera diez run IDs válidos con su manifiesto y commit. Compara registros con la tabla del portal y el candidato seleccionado. Para usar Model Registry en un servidor propio, comprueba que haya almacenamiento persistente para sus metadatos.
4. **Test:** obtiene el archivo de predicciones por muestra o vuelve a inferir el test congelado con el checkpoint publicado. Calcula una matriz propia y `accuracy = suma(diagonal) / total`; calcula F1 macro y resultados por clase. Compara cada cifra con portal, MLflow y tarjeta. Anota si el test fue consultado antes de elegir el candidato.
5. **S3 e inferencia:** usa `head-object`/`get-object` o SDK con permisos de lectura sobre pesos y tarjeta; calcula SHA-256 del archivo descargado, carga el modelo en un proceso limpio e infiere una imagen nueva. Si no hay credenciales de lectura, registra exactamente qué no se pudo verificar. No subas ni borres objetos de producción como parte de la evaluación.
6. **Portal:** recorre las cinco páginas desde la navegación existente. Refresca durante un trabajo, cambia la versión del modelo y prueba un archivo inválido. Verifica que «enviar a cola de anotación» produzca una entrada real.

Ejemplos de comandos; adapta rutas y herramientas al repositorio:

```bash
git rev-parse --short HEAD
git status --short
dvc status
python -m pytest
ruff check .
ruff format --check .
aws s3api head-object --bucket <BUCKET> --key <KEY>
aws s3api get-object --bucket <BUCKET> --key <KEY> <ARCHIVO_TEMPORAL>
```

Si el equipo no conserva predicciones individuales, dilo: sin ellas ni una nueva inferencia del test, la matriz y el 85% **no son verificables**. No inventes cifras para llenar la tabla.

Entrega **exactamente** esta estructura en el chat y luego genera el HTML de la Fase 4 con el mismo contenido:

### A. Requisitos mínimos

| Estado | Requisito | Evidencia |
|---|---|---|
| CUMPLE / NO CUMPLE | M1–M4, una fila cada uno | comando, registro o archivo:línea |

**Compuerta:** `ACTIVADA (máximo 60)` o `NO ACTIVADA`.

### B. Tabla de calificación

Una fila para **cada criterio 1.1–7.3**, incluso los ceros, más una fila de subtotal por cada una de las siete secciones.

| Puntos obtenidos | Requisito | Lo que falta |
|---|---|---|
| 2.5 / 5 | 1.3 Manifiesto 70/20/10 | `src/...:línea`: dos recortes del mismo original quedaron en train y val; agrupar por `source_image_id`. |
| 4 / 4 | 2.2 Minibatches y parámetros | — |
| **__ / 14** | **Subtotal Integración y datos** | |

En la tercera columna, si está completo escribe `—`; si falta algo, indica **qué, dónde y cómo se observó**, en una o dos líneas accionables.

### C. Trazabilidad de extremo a extremo

| Release DVC y hash | Manifiesto 70/20/10 y hash | Run MLflow elegido | Checkpoint | Versión de modelo | S3 bucket/key y hash | Predicción de prueba |
|---|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... | ... |

Cada celda debe provenir de una fuente comprobada. Si la cadena se rompe, marca la celda `NO VERIFICADO` y explica dónde.

### D. Contraste de métricas

| Métrica | Reportado por el equipo | Verificado por el evaluador | ¿Coincide? |
|---|---:|---:|---|
| Corridas válidas de MLflow | ... | ... | ... |
| Train / val / test (recortes y originales) | ... | ... | ... |
| Accuracy top-1 en test | ... | ... | ... |
| F1 macro en test | ... | ... | ... |
| Total de la matriz de confusión | ... | ... | ... |

Incluye además una tabla compacta de las **diez corridas válidas** con run ID, parámetros que cambian, mejor métrica de validación y estado. Si hay menos de diez, lista todas las válidas y el número faltante.

### E. Resultado final

```text
Suma de secciones:      __ / 100
Compuerta aplicada:     sí / no
CALIFICACIÓN FINAL:     __
Meta de 85% en test:    alcanzada / no alcanzada / no verificable
Escala:                 Excelente (90-100) / Bueno (75-89) / Suficiente (60-74) / No aprobable (<60)
```

Si la compuerta se activó, `CALIFICACIÓN FINAL = min(suma de secciones, 60)`; de otro modo, igual a la suma. No redondees el accuracy antes de decidir el umbral.

### F. Comentario para el equipo (máximo 10 líneas)

Tres aciertos sólidos y tres pérdidas de puntos de mayor impacto, con acciones concretas.

### G. Anexo de verificación

Comandos y acciones ejecutadas con resultado resumido; datos malos inyectados y reacción del sistema; diferencias detectadas entre portal, MLflow, DVC, S3 y cálculo independiente; lista explícita de **lo que no pudiste verificar** y por qué. Distingue fallas demostradas de limitaciones del entorno. Confirma el estado final limpio de la copia evaluada.

---

## FASE 4 — Reporte HTML

Genera **`reporte-<EQUIPO>.html`** con todo el contenido de A–G, los mismos puntos, métricas y evidencias; no resumas ni recalcules de otro modo.

- Un solo archivo autocontenido: CSS en `<style>`, sin CDNs ni recursos externos. No uses JavaScript salvo el mínimo para el botón de imprimir.
- `<!DOCTYPE html>`, `lang="es"`, `<meta charset="utf-8">` y viewport responsive. Envuelve cada tabla en un contenedor con `overflow-x: auto`.
- Incluye `@media print`: ocultar botón de impresión, `print-color-adjust: exact`, `break-inside: avoid` en filas y `@page { size: A4; margin: 15mm; }`.
- Barras de progreso por sección hechas con CSS. Encabezados azul ITESO sobre blanco; verde, ámbar y rojo solo en badges de estado.

Define la misma identidad usada en los reportes anteriores:

```css
:root {
  --iteso-azul: #003C71;
  --iteso-azul-medio: #0067A5;
  --iteso-azul-claro: #9BC4E2;
  --gris-texto: #333333;
  --gris-borde: #DDE3E9;
  --fondo: #FFFFFF;
  --ok: #1E7A3C;
  --parcial: #B8860B;
  --fallo: #A32020;
  --fuente: "Gotham", "Montserrat", "Helvetica Neue", Helvetica, Arial, sans-serif;
}
```

**Logotipo:** si `<RUTA_LOGO_ITESO>` existe, embebe el archivo en base64 dentro del HTML, sin deformarlo, recolorearlo ni reducir su contraste; altura aproximada de 48 px. Si no se proporcionó, usa texto `ITESO` en `--iteso-azul`, peso 700 y `letter-spacing: .08em`, con comentario HTML indicando dónde poner el logo. No inventes una URL ni una imitación gráfica.

Estructura del HTML:

1. Encabezado: materia, título **«Evaluación de proyecto 3 — Clasificador de imágenes»**, equipo, repositorio y hash evaluado, release de dataset, versión de modelo y fecha.
2. Tarjeta del resultado con calificación, escala, estado de la compuerta y estado de la meta de 85%.
3. Resumen de las siete secciones con puntos y barras CSS.
4. Requisitos mínimos y sus evidencias.
5. Tablas detalladas de criterios y subtotales, una sección por rubro.
6. Cadena de trazabilidad, contraste de métricas y tabla de corridas.
7. Comentario para el equipo y anexo de verificación; salidas de comandos en `<pre>` con `white-space: pre-wrap`.
8. Pie: `<DOCENTE>`, `<MATERIA>`, `<CICLO_ESCOLAR>` y la leyenda: *«Reporte generado automáticamente a partir del estado del repositorio en el commit indicado. La calificación es revisable a solicitud del equipo.»*

Antes de terminar, abre el HTML, confirma que no tenga recursos rotos ni placeholders sin sustituir, que las siete secciones sumen 100, que los subtotales coincidan con la tabla del chat y que la compuerta se haya aplicado correctamente. Restaura los cambios de verificación y reporta la ruta absoluta del HTML.
