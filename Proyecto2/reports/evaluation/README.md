# Evidencia de evaluación

Todo lo que hay en esta carpeta está **generado por un comando**, no escrito a
mano, y cada comando sale con código `!= 0` si lo que afirma no se sostiene.
Ninguno es un informe que alguien redactó después de mirar los resultados.

Se regenera entera desde `Proyecto2/`:

```bash
python scripts/evidencia_dvc.py            # reproducibilidad del pipeline
python scripts/recalculo_independiente.py  # los números del reporte son ciertos
cd web && npx playwright test              # las siete pantallas, en un navegador
```

| Archivo | Qué demuestra | Cómo se regenera |
| --- | --- | --- |
| `dvc-reproducibilidad.md` / `.json` | Dos `dvc repro` seguidos sin que la segunda rehaga ninguna etapa; los hashes de `dvc.lock` no se mueven; el cache local coincide con DEV **y** con PROD. | `python scripts/evidencia_dvc.py` |
| `recalculo.md` / `.json` | Un programa que **no importa `dataset_quality`** llega a las mismas 17 métricas partiendo del COCO crudo y de las 2045 imágenes. | `python scripts/recalculo_independiente.py` |
| `playwright/index.html` | Las siete pantallas cargando con respuestas `200`, el hover y el filtro de la PCA, y la política persistida tras recargar. Con captura de cada una. | `cd web && npx playwright test` |

## Lo que cada pieza NO demuestra

Vale la pena decirlo, porque una tabla de resultados en verde invita a leer de
más:

- **El recálculo** confirma que los analizadores calculan lo que dicen. No
  confirma que detecten defectos: en este dataset duplicados y cajas
  degeneradas dan cero, y coincidir en un cero es barato. Esa otra mitad la
  cubren las pruebas de mutación (`pytest tests/test_mutaciones.py`), que
  inyectan una copia recomprimida, una bbox negativa, una bbox fuera de la
  imagen y un mínimo inalcanzable, y exigen el hallazgo y el código de salida.

- **La reproducibilidad** dice que el grafo no rehace trabajo y que los remotes
  están sincronizados. No dice que los umbrales sean los correctos: eso es una
  decisión de `quality.yaml`, no un hecho comprobable.

- **El reporte de Playwright** prueba las pantallas contra la app levantada con
  los artefactos de hoy. Un dataset distinto puede pintar otras cifras sin que
  ninguna prueba cambie de color; lo que se verifica es que la pantalla pide,
  recibe y dibuja, no qué números salen.

## Una nota sobre `playwright/`

Son ~2.5 MB de capturas. Están commiteadas a propósito, para que quien clone el
repositorio vea el reporte sin tener que levantar el entorno primero. CI lo
publica además como artefacto (`playwright-report`) en cada corrida del job
*Arranque desde cero + navegador*.

La salida cruda por prueba (`web/test-results/`) sí está en `.gitignore`: son
las mismas capturas otra vez, más las trazas.
