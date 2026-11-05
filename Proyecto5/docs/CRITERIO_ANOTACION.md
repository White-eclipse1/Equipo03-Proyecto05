# Criterio QA de cajas visibles — A3-04-F02

Registrado el 2026-11-04 para la segunda revisión de
[F02 / #41](issues/A3-04-F02_CAJA.md), seguimiento de #29.
Complementa el paso 5 de [A2_DATASET.md](A2_DATASET.md).

Este criterio explicita la revisión actual. No se presenta como una tolerancia
cuantitativa fijada antes de anotar v1 ni modifica su protocolo congelado.
La documentación y el anotador existentes especifican clases, coordenadas y
estados de vía, pero no fijan una tolerancia numérica de holgura ni una regla
completa de oclusión. El validador comprueba geometría válida, no ajuste visual.

## Caja visible y holgura

- La caja es el rectángulo que contiene las partes visibles del objeto,
  incluidos cabello, ropa y calzado atribuibles a la persona. Sus bordes deben
  aproximar los extremos visibles en la imagen original.
- No se agrega margen de fondo deliberado. La incertidumbre por desenfoque,
  compresión o contraste se registra como tal; no permite inventar una frontera
  exacta ni aceptar cualquier holgura.
- No se fija aquí un corte universal en píxeles a partir de este único caso.
  Una franja de fondo claramente separada del objeto se registra como
  discrepancia justificada, aunque la caja siga siendo geométricamente válida.
- La decisión visual se fundamenta en la imagen y este criterio. No se usa la
  caja del detector, su confianza ni el IoU para dibujar una caja de reemplazo.

## Oclusión y truncamiento

- Se encierra la extensión de las partes visibles; no se extrapolan partes
  ocultas por muebles u otras personas ni se reconstruye un cuerpo completo.
- Si hay varias partes visibles del mismo objeto, una sola caja puede incluir
  fondo entre ellas. Ese fondo interior no justifica extender un borde por
  fuera de todos los extremos visibles.
- Si el objeto sale del encuadre, la caja se limita al borde de la imagen.
  Tocar un borde requiere evidencia visible de ese truncamiento; una cabeza
  separada del borde superior no lo demuestra.
- Se registra la incertidumbre de cada borde. La oclusión inferior no justifica
  una ampliación superior independiente.

## Control de versiones

Una discrepancia de QA no autoriza modificar `p5-eval-v1`, sus anotaciones,
manifiesto, imágenes ni resultados publicados. La revisión puede cerrarse
dejando registrada la discrepancia, sin fabricar una caja corregida.

Si el responsable decide reanotar, debe hacerlo en un paquete posterior con
ID y congelamiento nuevos. Debe revisar la imagen con este criterio, registrar
autoría y cambios, validar el paquete completo y generar métricas nuevas con
el umbral publicado. Se conservan v1 y sus resultados como referencia histórica.
No se sustituye únicamente un borde para conseguir un TP ni se presenta ese
nuevo resultado como una evaluación independiente de un conjunto nunca visto.
