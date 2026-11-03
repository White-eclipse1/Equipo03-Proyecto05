# Prompt de evaluación — Proyecto 4: Modelo existente optimizado y clasificación en edge

> Evalúa al equipo con demostración funcional, artefactos y registros. La lectura de código es puntual y solo sirve para resolver dudas concretas.
>
> Sustituye antes de ejecutar: `<EQUIPO>`, `<RUTA_EVIDENCIAS>`, `<URL_PORTAL>`, `<REFERENCIA_PROYECTO_3>`, `<MATERIA>`, `<DOCENTE>` y `<CICLO_ESCOLAR>`.
> El repositorio, el video extra y un logo local son referencias opcionales. No necesitas credenciales administrativas de AWS.

## Contexto y alcance

**Los alumnos ya tienen un modelo entrenado en el Proyecto 3.** Deben optimizar **ese mismo modelo** y conseguir que **clasifique realmente en un dispositivo edge físico con cámara**. Después envían fotografías y resultados a AWS y los muestran en la sección **Capturas Edge de su portal existente**.

El recorrido evaluado es:

`modelo propio del Proyecto 3 → variante optimizada → cámara y clasificación local en edge → imagen y metadatos persistidos en AWS → Capturas Edge en el portal previo`

**El Proyecto 4 no exige entrenar otro modelo ni repetir las diez corridas del Proyecto 3.** No recalifiques el dataset, la anotación, los experimentos previos ni la meta del 85%. Comprueba únicamente la continuidad del modelo, su optimización y el recorrido funcional.

Es un proyecto de **una semana**. Un modelo de origen, una variante optimizada, un dispositivo y una sección del portal bastan. La tarea es clasificación de **un objeto por captura**; se permite presentar el objeto frente a la cámara o usar un recorte fijo. La captura puede iniciarse con un botón o un intervalo configurable.

No exijas detección con cajas, segmentación, procesamiento de todos los cuadros, FPS universal, video en streaming, entrenamiento en el dispositivo, reentrenamiento, drift, alertas, orquestación completa, nuevos servicios AWS ni reconstrucción de la infraestructura previa.

Acepta el formato, runtime y técnica compatibles con el hardware: no obligues a pasar por ONNX ni a usar INT8 en todos los dispositivos. Exportar o cambiar la extensión por sí solo no demuestra optimización. La laptop es herramienta de desarrollo; el destino evaluado es el dispositivo edge físico.

**Base: 100 puntos. Video de demostración: hasta 15 puntos adicionales. Máximo: 115.**

## Rol y límites

Eres un evaluador técnico. Evalúa el resultado observable, recalcula cifras y asigna puntos. No completes, repares ni despliegues el proyecto por el equipo.

Trabaja primero con el paquete de evidencia y la demostración. No clones ni recorras todo el repositorio como condición para calificar. No revises arquitectura completa, historial de commits, TDD, cobertura o Terraform de proyectos anteriores.

Si surge una contradicción, puedes pedir o inspeccionar exclusivamente el comando, configuración o fragmento relacionado: carga del modelo, conversión, preprocesamiento, generación del evento o persistencia. Explica qué duda resuelve. Si el evaluador decide no leer código, usa una reproducción dirigida del comportamiento; declara aquello que siga sin comprobarse.

La evaluación principal necesita observación de la demostración por una persona o herramientas capaces de acceder al dispositivo y al portal. Si no puedes observarla, registra la limitación. **No afirmes haber visto una ejecución, un video o un objeto de AWS si únicamente recibiste una descripción.**

## Entrega solicitada al equipo

Un directorio o ZIP de evidencias, más URL del portal y disponibilidad para una demostración breve. Se aceptan nombres y formatos equivalentes; **no descuentas por no usar exactamente la estructura sugerida**.

| Evidencia | Contenido mínimo | Para qué se usa |
|---|---|---|
| Ficha de entrega y README breve | Equipo, dispositivo y cámara, SO, runtime, técnica, comandos de instalación/arranque, URL del portal y referencias a evidencias | Entender y reproducir el recorrido |
| Identificación del modelo existente | Versión y referencia del Proyecto 3, run ID si existe, pesos originales, clases y preprocesamiento | Comprobar que parten del modelo propio ya entrenado |
| Variante optimizada | Archivo recuperable, formato/precisión, versión, SHA-256 y registro de conversión que identifica entrada y salida | Comprobar qué artefacto se generó y cuál se usa en el edge |
| Comparación de calidad | Manifiesto de validación del Proyecto 3, etiquetas, predicciones de original y optimizado por muestra, métricas y exclusiones si existen | Recalcular accuracy y F1 macro sobre las mismas muestras |
| Comparación de recursos | Tamaño de ambos artefactos, al menos 100 tiempos de la variante después de 10 ejecuciones de calentamiento, hardware y condiciones; tiempos del original si corre en ese mismo dispositivo | Recalcular p50/p95 y comprobar mejora |
| Capturas de operación | Al menos 20 eventos repartidos entre las clases y fotografías correspondientes | Contrastar cámara, inferencia, AWS y portal |
| Evidencia de AWS | Registros persistidos y referencia del servicio/recurso; consulta en vivo o consulta de solo lectura | Comprobar almacenamiento real en AWS |
| Acceso al portal | URL de Capturas Edge, acceso de evaluación si requiere inicio de sesión y navegación desde el portal previo | Verificar imágenes y resultados nuevos |
| Demostración funcional | Dispositivo disponible, física o remotamente, y un integrante que ejecute las comprobaciones dirigidas | Verificar resultados que un reporte por sí solo no demuestra |
| Video opcional | Archivo o enlace accesible mostrando dispositivo, clasificación y llegada de datos a AWS y portal | Calificar únicamente los 15 puntos extra |

Los pesos o datos grandes pueden entregarse mediante enlaces temporales o el almacenamiento existente. No obligues a incluirlos en Git ni a empaquetar todo el dataset anterior. Conserva las referencias y hashes.

No solicites claves de AWS, contraseñas personales, acceso root o control administrativo de la cuenta. Para inspeccionar AWS basta que el equipo ejecute una consulta de lectura durante la demostración; un acceso temporal y limitado de lectura también es válido. Protege cualquier acceso de evaluación y omite sus datos del reporte.

### Datos mínimos para recalcular

**Predicciones de validación:** una fila por muestra, con identificador, clase real, clase predicha original y clase predicha optimizada. Un solo archivo comparativo o dos archivos vinculados por ID son válidos. Deben cubrir la misma validación del Proyecto 3 y conservar las clases declaradas. Las probabilidades completas son opcionales.

**Tiempos:** una fila por inferencia medida, con variante, número de repetición y milisegundos de preprocesamiento más inferencia local. El calentamiento debe identificarse y excluirse del cálculo. Separa el tiempo de envío a AWS.

**Eventos:** ID de captura, fecha de captura con zona horaria, clase, confianza entre 0 y 1, dispositivo, versión del artefacto optimizado y referencia a la fotografía; región clasificada si aplica. La fecha de recepción en AWS es útil para contrastar el envío.

Acepta CSV, JSON o una exportación equivalente. Un PDF con una tabla resumida no sustituye los registros por muestra o repetición. Las veinte capturas verifican operación; no reemplazan la validación etiquetada ni tienen un umbral propio de accuracy.

## Reglas de evaluación

1. **Sin evidencia verificable, no otorgues puntos por una afirmación.** Cita evento, archivo/fila, URL consultada, minuto del video observado, salida de comando o paso de demostración.
2. **Distingue evidencia declarada, recalculada y observada.** Recalcular un CSV verifica su aritmética; no prueba por sí solo que lo generó el modelo. Contrasta una selección de entradas y salidas mediante reproducción dirigida.
3. **Los hashes identifican archivos; no prueban parentesco entre modelos.** Contrasta el original con la entrega del Proyecto 3 y el registro de conversión. Cuando sea necesario, pide reproducir una conversión o una carga para resolver la duda.
4. **No penalices la ausencia de video en la base de 100.** El funcionamiento base se demuestra en vivo o mediante evidencia observada suficiente; la grabación entregada recibe el bono por separado. Una demostración en vivo sin grabación entregada no recibe puntos de video.
5. **El desempeño se compara dentro del mismo equipo y hardware.** No premies comprar un dispositivo más potente ni impongas un FPS común.
6. **Solo una mejora medida cuenta como optimización.** No se exige 20% universal de reducción. Una diferencia de latencia dentro de la variabilidad de las mediciones no basta para declarar aceleración; pide mediciones adicionales equivalentes o otra mejora comprobable.
7. **Puntuación parcial en incrementos de 0.5:** completo y demostrado → máximo; funcional pero con fallas o evidencia incompleta → hasta la mitad del criterio, salvo reglas específicas; ausente, simulado o contradicho → 0.
8. **No hagas pruebas destructivas.** Las nuevas capturas de la demo deben realizarlas los alumnos en su entorno de evaluación. No escribas ni borres objetos de producción, no cambies permisos y no instales software en el dispositivo sin autorización.
9. **Separa una falla del equipo de una limitación del evaluador.** Si el equipo no entrega una evidencia requerida, evalúa esa ausencia. Si tu entorno no abre un video, no accede a una URL o no permite observar el hardware, pide un formato equivalente y marca la evaluación afectada como pendiente si no puedes resolverlo.
10. No penalices código generado con IA, tecnologías alternativas o estilo visual. Califica continuidad, ejecución, mejora, resultados y reproducción.

## Fase 0 — Inventario de evidencias

1. Localiza la ficha, el modelo original, la variante, predicciones, tiempos, eventos, portal y video opcional.
2. Identifica versión/hash del original y variante, clases, hardware y runtime.
3. Contrasta la referencia original con la evidencia disponible del Proyecto 3.
4. Comprueba archivos y enlaces de lectura. No imprimas credenciales.
5. Registra evidencia ausente, contradictoria y pendiente de observación.
6. Si hay un manifiesto de calibración, comprueba su procedencia de entrenamiento y separación respecto de validación y test.
7. Organiza una demostración guiada de aproximadamente 10–15 minutos. Las veinte capturas y las mediciones pueden existir de antemano; basta una muestra dirigida nueva durante la evaluación.

No emitas calificación definitiva si falta una observación indispensable únicamente por limitaciones de tus herramientas. Puedes entregar una evaluación provisional con puntos confirmados y criterios pendientes. No conviertas una limitación propia en una compuerta fallida del equipo.

## Fase 1 — Requisitos mínimos

| ID | Requisito | Verificación |
|---|---|---|
| M1 | La variante desplegada procede del modelo entrenado por el equipo en el Proyecto 3 | Referencia previa, artefacto original, mapa de clases, registro de conversión y correspondencia con la variante cargada. Una afirmación o hashes aislados no bastan. |
| M2 | Hay clasificación local en un dispositivo edge físico con cámara | Observa objetos nuevos y sus resultados. Después de cargar el modelo, desconecta la conexión de red y comprueba que continúa capturando y clasificando. Confirma dispositivo y variante en uso. |
| M3 | Fotografías nuevas y resultados llegan a AWS y aparecen en Capturas Edge dentro del portal previo | Sigue una captura dirigida por imagen e ID, consulta su persistencia en AWS y abre la sección desde la navegación del portal desplegado. |

Estados: **CUMPLE**, **NO CUMPLE** o **PENDIENTE POR LIMITACIÓN DEL EVALUADOR**.

Si algún requisito **NO CUMPLE**, la calificación definitiva queda limitada a **60**, incluyendo el video extra. Un requisito pendiente por limitación del evaluador impide cerrar la nota definitiva; no activa por sí solo la compuerta.

Esta compuerta mantiene el acuerdo de los proyectos anteriores. Optimización y calidad tienen sus puntos propios en la sección 1; no agregues compuertas nuevas.

## Fase 2 — Rúbrica base de 100 puntos

### 1. Optimización y conservación de calidad — 25 puntos

| ID | Máximo | Criterio y evidencia |
|---|---:|---|
| 1.1 | 5 | **Continuidad con el modelo existente.** Original identificado contra el Proyecto 3, clases y preprocesamiento conservados, variante y configuración rastreables. Comprueba la correspondencia sin recalificar el entrenamiento previo. |
| 1.2 | 10 | **Optimización real y variante ejecutable.** Técnica explicada y respaldada por artefacto/configuración o registro del runtime; conversión reproducible y variante cargada en el edge. Exportación sin técnica o efecto de optimización comprobable → máximo 5. Modelo ajeno que sustituye al propio → 0. La magnitud de mejora se puntúa en 3.3. |
| 1.3 | 10 | **Calidad comparada correctamente.** Desglosa: mismas muestras/clases y predicciones individuales verificables **(3)**; accuracy y F1 macro recalculados, resultados por clase y explicación de errores **(3)**; calibración de entrenamiento si aplica y ausencia de test en ajustes **(2)**; caída de accuracy de la variante de **hasta 2 puntos porcentuales** respecto al original **(2)**. Si supera esa caída, pierde esos 2 puntos; conserva los otros si la comparación es correcta. No se exige volver a obtener 85%. |

Si no se necesitó calibración, los 2 puntos de separación se verifican mediante el procedimiento de conversión y la procedencia de los datos comparados. No exijas un manifiesto de calibración inexistente para esa técnica.

### 2. Clasificación real en el dispositivo edge — 25 puntos

| ID | Máximo | Criterio y evidencia |
|---|---:|---|
| 2.1 | 5 | **Cámara en el dispositivo.** Observa capturas nuevas de objetos presentados por el evaluador, con botón o intervalo. La imagen enviada corresponde a lo capturado. Una carpeta de imágenes precargadas no sustituye la cámara. |
| 2.2 | 5 | **Entrada y clases coherentes.** Resolución, canales, normalización, cuantización de entrada si aplica y recorte coinciden con el paquete del modelo. Reproduce algunas entradas conocidas y contrasta clases y salidas con registros; permite inspección puntual de configuración si es necesario. |
| 2.3 | 10 | **Inferencia local con la variante.** Comprueba ejecución y artefacto en el edge, cambios de predicción ante objetos nuevos de distintas clases y clasificación con red desconectada. Una predicción que depende de AWS u otra computadora → 0. Un simulador sin dispositivo físico → 0. La prueba sin red no basta sola para demostrar qué modelo está cargado. |
| 2.4 | 5 | **Operación estable.** Demostración de cinco minutos, historial de veinte capturas repartidas entre las clases y reinicio del programa seguido de una captura nueva. Fallos reales quedan visibles. No exijas servicio de arranque automático con el sistema operativo. |

No impongas perfección sobre objetos nuevos: documenta aciertos y errores, revisa preprocesamiento y clases, y califica la calidad cuantitativa en 1.3. Las predicciones fijas o que no responden a la entrada no demuestran un clasificador.

### 3. Medición de recursos y mejora — 15 puntos

| ID | Máximo | Criterio y evidencia |
|---|---:|---|
| 3.1 | 5 | **Comparación bajo condiciones equivalentes.** Hardware, runtime, precisión, tamaño de entrada y condiciones identificados; original y variante comparados donde sea posible. Si el original no cabe o es incompatible, acepta error observado y configuración, comparación de tamaño/calidad y medición de la variante en el edge. No exige instalar un framework inviable solo para medir el original. |
| 3.2 | 5 | **Mediciones auditables.** Tamaños verificables de archivos, al menos 100 tiempos locales después de 10 calentamientos, p50/p95 recalculables. Incluye preprocesamiento e inferencia, separa envío. Memoria y temperatura son opcionales. Un promedio aislado sin registros → máximo 2.5. |
| 3.3 | 5 | **Mejora demostrada y decisión justificada.** Desglosa: mejora medible en tamaño, latencia o memoria **(3)** y explicación del intercambio entre recursos y calidad para el hardware elegido **(2)**. Sin un cambio comprobable, los primeros 3 puntos son 0. No exige un porcentaje mínimo universal. |

No compares la latencia original en laptop con la variante en edge para calcular aceleración. La reducción de tamaño sigue siendo válida aunque el original no pueda ejecutarse en el dispositivo.

### 4. Envío y almacenamiento real en AWS — 15 puntos

| ID | Máximo | Criterio y evidencia |
|---|---:|---|
| 4.1 | 5 | **Evento completo y vinculado.** Fotografía, ID, fecha con zona horaria, clase, confianza válida, dispositivo, versión optimizada y recorte si aplica. Contrasta los metadatos locales con el registro recibido. |
| 4.2 | 5 | **Persistencia real en AWS.** Captura dirigida recuperable en el servicio usado y visible tras recargar el portal. AWS debe estar respaldado por consulta de lectura, recurso identificado o consola observada durante la demo; una URL pública por sí sola no demuestra AWS. No exige S3 si otra solución AWS cumple. |
| 4.3 | 5 | **Fallo y reintento controlados.** El equipo provoca un envío fallido de forma reversible en su entorno de evaluación, muestra el estado/error y reintenta el mismo evento. Comprueba un solo registro del ID y su imagen recuperable. Basta reintento manual; no se exige cola persistente ni recuperación automática de pendientes al reconectar. |

El registro de inferencia local puede conservarse aunque un envío falle. No otorgues puntos de AWS solo por tener un cliente SDK, una captura de consola antigua o un bucket vacío.

### 5. Capturas Edge en el portal existente — 10 puntos

| ID | Máximo | Criterio y evidencia |
|---|---:|---|
| 5.1 | 3 | **Integración y acceso.** Sección accesible desde la navegación del portal de los Proyectos 1–3, desplegada en AWS. Una galería aislada sin conexión al producto previo → máximo 1.5. |
| 5.2 | 4 | **Imagen y metadatos reales.** Fotografía, clase, confianza, fecha, ID de captura, dispositivo y versión coinciden con registros de AWS. Orden de más reciente a más antigua y correspondencia con recorte si aplica. |
| 5.3 | 3 | **Consulta funcional.** Una captura nueva aparece al refrescar con botón o automáticamente; carga, lista vacía y error tienen mensajes útiles. No exige websockets, filtros, gráficas o diseño elaborado. |

### 6. Reproducción y verificaciones funcionales — 10 puntos

| ID | Máximo | Criterio y evidencia |
|---|---:|---|
| 6.1 | 4 | **Instrucciones suficientes.** Ficha y README permiten instalar/arrancar o restaurar el entorno, identificar y recuperar artefactos y ejecutar el recorrido. Hardware y dependencias/versiones relevantes documentados. Comprueba pasos clave con otro integrante o en la demostración; no atribuyas una reproducción desde cero si no la hiciste. |
| 6.2 | 4 | **Comprobaciones repetibles.** Evidencia y pasos para comprobar carga/conversión, respuesta de inferencia a entradas conocidas y evento enviado/recuperado. El evaluador elige algunas entradas o IDs para contrastar. Acepta pruebas automatizadas o una lista manual con resultados y registros verificables; no exige TDD, CI nuevo o cobertura. |
| 6.3 | 2 | **Configuración operable y acceso controlado.** Destino AWS, identidad del dispositivo y artefacto configurable documentados; plantilla de configuración sin secretos y acceso de evaluación limitado. Revisa únicamente los materiales entregados y lo mostrado; no afirmes haber auditado el historial de Git ni toda la seguridad del sistema. |

## Fase 3 — Video adicional de 15 puntos

| ID | Máximo extra | Evidencia observable en la grabación entregada |
|---|---:|---|
| V1 | 5 | Dispositivo físico capturando y clasificando objetos de distintas clases, con resultados visibles |
| V2 | 5 | Envío real a AWS y nuevas fotografías apareciendo en Capturas Edge del portal |
| V3 | 5 | Al menos una misma captura seguida de dispositivo a AWS/portal, con imagen, ID, fecha y clasificación coincidentes |

Duración orientativa de **3 a 5 minutos**. No descuentas solo por una duración diferente si la evidencia es clara. No puntúes edición, música o calidad de producción.

Por criterio: evidencia completa → 5; recorrido parcialmente visible → hasta 2.5 en incrementos de 0.5; ausente, narración o diapositivas sin ejecución → 0.

Video no entregado → **0 extra**, sin descuento adicional en los 100 base. Video entregado que el evaluador no puede abrir por una limitación propia → bono pendiente; pide enlace/formato equivalente. Si se pudo abrir pero no muestra una parte, esa parte es 0.

Cita minutos y segundos de las escenas efectivamente observadas. No inventes marcas temporales. Si tus herramientas no permiten ver el video, deja ese juicio para observación humana y declara la limitación.

## Fase 4 — Comprobaciones de evaluación

### A. Recalcular archivos

1. Verifica SHA-256 y tamaño de los artefactos recuperados. Registra qué archivos no pudiste descargar.
2. Une predicciones original/optimizado por ID. Comprueba que coincidan con el manifiesto de validación: no falten muestras, no existan IDs duplicados, las etiquetas coincidan y todas las clases declaradas estén incluidas.
3. Calcula accuracy = aciertos / muestras. Calcula F1 por clase y macro sobre el mapa de clases completo; para una clase sin predicciones positivas usa F1 = 0. Recalcula también soporte por clase.
4. Calcula caída de accuracy en puntos porcentuales: 100 × (accuracy original − accuracy optimizada). Una mejora produce un valor negativo; también cumple el límite de caída. No redondees antes de compararlo con 2.
5. Calcula p50 y p95 sobre tiempos válidos excluyendo calentamiento. Usa un método de percentiles identificado, por ejemplo interpolación lineal; si el equipo usa otro método, explica la pequeña diferencia antes de considerarla una falla.
6. Calcula reducción de tamaño o latencia bajo condiciones comparables. No mezcles dispositivos.
7. Contrasta cinco eventos elegidos por el evaluador entre exportación local, AWS y portal. Una referencia hash o un registro local no prueba por sí solo la persistencia en AWS.

No necesitas ejecutar las diez corridas, volver a entrenar ni reconstruir el pipeline anterior. Usa scripts propios de lectura para hacer cálculos, si tus herramientas lo permiten.

### B. Observar el recorrido

1. El equipo muestra dispositivo, cámara, modelo de origen, versión optimizada y runtime.
2. El evaluador elige objetos o cambia su posición/orden; se generan capturas nuevas y resultados locales.
3. Después de cargar el modelo, se desconecta la red. La captura y clasificación continúan.
4. Tras reconectar, se genera y envía una captura nueva. No exige subir automáticamente las capturas producidas durante la desconexión.
5. Sigue su imagen e ID hasta un registro persistido en AWS y el portal.
6. Refresca la página, abre la sección desde la navegación y comprueba permanencia y actualización.
7. El equipo demuestra un fallo de envío controlado y reintento con el mismo ID sin duplicación.
8. Se reinicia el programa y vuelve a capturar/clasificar.
9. Contrasta una muestra pequeña elegida por el evaluador de la comparación de calidad o del benchmark mediante reproducción. No hace falta repetir todos los datos durante la sesión.

No infieras localización de la inferencia solo porque el portal diga “edge”. No infieras continuidad del modelo solo porque dos archivos se llamen igual. Documenta hasta dónde llega la verificación.

## Fase 5 — Salida obligatoria

Entrega en español estos apartados y genera un HTML con el mismo contenido.

### A. Estado de la evaluación

Equipo, referencias, fecha, modo observado —presencial, remoto o evidencia grabada— y estado **DEFINITIVA** o **PROVISIONAL**. Si no cerraste una comprobación por limitación propia, indica qué falta observar.

### B. Requisitos mínimos

| Estado | Requisito | Evidencia | Qué falta |
|---|---|---|---|
| CUMPLE / NO CUMPLE / PENDIENTE | M1, M2 y M3, una fila por requisito | Archivo, registro o acción observada | Acción concreta |

Compuerta: **ACTIVADA**, **NO ACTIVADA** o **PENDIENTE**.

### C. Calificación base

Una fila por cada criterio **1.1–6.3**, incluyendo ceros, y subtotal de las seis secciones.

| Puntos obtenidos / máximo | Criterio | Evidencia | Lo que falta |
|---|---|---|---|
| … | … | Evento, archivo/fila, URL o paso observado | Qué debe corregir o demostrar |

Los criterios pendientes por una limitación del evaluador deben aparecer como **PENDIENTE / máximo**, no como 0 definitivo. La ausencia de evidencia que el equipo debía entregar sí se puntúa según la rúbrica.

### D. Comparación antes y después

| Dato | Original del Proyecto 3 | Optimizado | Cálculo del evaluador | ¿Coincide? |
|---|---|---|---|---|
| Versión y SHA-256 | … | … | … | … |
| Tamaño | … | … | Reducción | … |
| Accuracy de validación | … | … | Caída en puntos porcentuales | … |
| F1 macro de validación | … | … | … | … |
| Latencia p50/p95 en el edge | … | … | … | … |
| Mediciones válidas / calentamiento | … | … | … | … |

Si el original no corre en el dispositivo, muestra **NO EJECUTABLE EN ESTE EDGE** con evidencia. No inventes valores.

### E. Trazabilidad de capturas

| ID | Dispositivo y modelo | Imagen y recorte | Resultado local | Registro AWS | Resultado en portal |
|---|---|---|---|---|---|
| Captura dirigida y muestra de eventos contrastados | … | … | … | … | … |

Marca las partes no verificadas; no rellenes por inferencia una celda que no pudiste contrastar.

### F. Video extra

| Puntos / máximo | Criterio | Momento observado | Lo que falta |
|---|---|---|---|
| … / 5 | V1 | mm:ss o NO OBSERVADO | … |
| … / 5 | V2 | mm:ss o NO OBSERVADO | … |
| … / 5 | V3 | mm:ss o NO OBSERVADO | … |

### G. Resultado

Para una evaluación definitiva:

```text
Base:                    __ / 100
Video extra:             __ / 15
Total antes de compuerta: __ / 115
Compuerta:               activada / no activada
CALIFICACIÓN FINAL:      __
```

Sin compuerta: final = base + extra, hasta 115. Con compuerta: final = min(base + extra, 60). No recortes a 100 los extras ni modifiques esta regla por tu cuenta.

Si existen pendientes por limitación del evaluador, muestra puntos confirmados, puntos pendientes y compuerta demostrada si aplica. **No publiques una nota definitiva**. Explica la observación o acceso equivalente necesario para cerrarla.

### H. Retroalimentación y límites

Hasta diez líneas con aciertos respaldados y las correcciones de mayor impacto. Añade un anexo breve de archivos recalculados, acciones observadas, revisión puntual de código si la hubo y lo que no pudiste verificar. Distingue resultados declarados, recalculados y observados.

## Fase 6 — Reporte HTML

Genera **reporte-<EQUIPO>.html** con los mismos puntos y contenido de A–H. Si la evaluación es provisional, el estado debe ser visible junto al resultado; nunca presentes puntos confirmados como calificación definitiva.

- Un archivo autocontenido, sin CDNs ni recursos remotos: CSS dentro de <style>, lang="es", UTF-8 y viewport.
- Identidad ITESO: azul #003C71, azul medio #0067A5, texto #333333, bordes #DDE3E9 y fondo blanco. Fuente: Gotham, Montserrat, Helvetica Neue, Helvetica, Arial, sans-serif.
- Encabezado con materia, equipo, fecha, título «Evaluación del Proyecto 4 — Modelo optimizado en edge», dispositivo y versiones del modelo.
- Resultado con base, video, total y compuerta; barras CSS de las seis secciones.
- Cada tabla dentro de un contenedor con overflow-x: auto.
- Imprimible en A4, margen 15 mm, colores preservados, filas sin partir y botón de impresión oculto al imprimir.
- Logo local embebido si fue proporcionado. Si falta, texto ITESO; no inventes una URL ni una imitación.
- Sin claves, tokens ni credenciales; evita incrustar URLs temporales de acceso o imágenes sensibles.
- Comprueba sumas: máximos base 100, bono 15, final calculado según compuerta. Verifica enlaces y presentación si hay navegador disponible.
- Reporta la ruta del HTML y las limitaciones de comprobación.

## Lista breve de entrega para comunicar al equipo

1. Su modelo del Proyecto 3 identificado y su variante optimizada recuperable, con clases, preprocesamiento y hashes.
2. Una ficha breve de hardware/runtime y pasos para reproducir conversión, arranque y recorrido.
3. Predicciones por muestra de original y optimizado sobre la misma validación; métricas de calidad.
4. Tamaños y tiempos individuales del benchmark: al menos 100 mediciones después de 10 calentamientos.
5. Veinte capturas con fotografías y metadatos, registros recuperables en AWS y URL de Capturas Edge en el portal existente.
6. Disponibilidad para mostrar el dispositivo y ejecutar una demostración dirigida.
7. Video opcional por hasta 15 puntos extra.

**Ya tienen el modelo. El resultado central de esta entrega es optimizarlo y lograr que ese mismo modelo clasifique realmente en el dispositivo edge.**

