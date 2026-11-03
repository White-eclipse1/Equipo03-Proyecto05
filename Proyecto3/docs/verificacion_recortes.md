# Verificación de recortes — release 0.1.3 (F2 T07)

Comprobación de que cada recorte es la caja COCO correcta, con la etiqueta correcta (criterio 1.2). Se genera con:

```bash
cd Proyecto2
PYTHONPATH=../Proyecto3/src .venv/Scripts/python ../Proyecto3/scripts/generate_crops.py --release 0.1.3 --profile <perfil-aws>
cd ../Proyecto3
.venv/Scripts/python scripts/verificar_recortes.py --release 0.1.3 --n 10 --seed 7
```

## Historia: qué falló y cómo se corrigió

La primera versión (commits `57a8b58` y `361fb42`) tenía dos errores que **encontró Edith en la revisión del PR #3**, viendo los recortes:

1. **Fotos rotadas por EXIF.** 11 fotos de celular traen orientación EXIF 6. P1 las mostró giradas, pero el generador las abría sin girar. Seis recortes de `person` (anotaciones 39, 43, 47, 57, 59 y 61) salían como pavimento, pared o árboles.
2. **Tamaño del archivo distinto al del COCO.** En 7 imágenes el archivo no mide lo que dice el COCO (por ejemplo, la imagen 1 mide 1280×851 y el COCO dice 1024×682). Las cajas están en coordenadas del COCO y se recortaban sobre el archivo sin escalar. Las anotaciones 4, 5, 6 y 12 salían claramente mal, y la 9, 16 y 17 algo desplazadas.

Además, **la verificación era circular**: comparaba cada recorte contra el mismo método que lo generó y reportaba 1459/1459 correctos.

**Modelo de coordenadas corregido**, verificado a ojo en los 13 casos (ver abajo): las cajas están en el espacio `width`×`height` del COCO, que P1 tomó de la cabecera del archivo sin girar. P1 mostró la foto con la rotación EXIF aplicada y llevó cada caja a ese espacio eje por eje. Para recortar, la foto se gira igual y la caja se escala por eje al tamaño de la foto girada. Un primer intento de corrección (`1142a35`) intercambiaba ancho y alto en las fotos rotadas; **la revisión visual mostró que las cajas caían junto al ciclista y no encima**, y se reemplazó por el escalado por eje (`a3d2e59`).

## 1. Verificación automática de todos los recortes

`scripts/verificar_recortes.py` recorre los **1459** recortes de `data/crops/0.1.3/crops.jsonl`:

- **Metadatos:** la anotación existe en el COCO con la misma `image_id`, `category_id`, nombre, `file_name` y bbox.
- **Geometría por otro camino:** toma la foto como la muestra un navegador (rotación EXIF aplicada), la **redimensiona completa** al tamaño del COCO, corta la bbox tal cual y la compara con el recorte llevado al mismo tamaño. El generador, en cambio, escala la caja y corta la foto sin redimensionar.

Resultado (26 sep 2026): `1459 recortes: metadatos iguales al COCO`; diferencia media máxima **7.46** (umbral 12; peor caso `a5`, una caja de 34×133 px reescalada).

Sobre los recortes de la primera versión, esta misma verificación **falla** y marca como incorrectos `a4 a5 a6 a12 a17 a39 a43 a47 a57 a59 a61`. Así se comprobó que ya no es circular.

**Límite:** la verificación automática comparte con el generador el *modelo* de coordenadas. También aprobó el primer intento de corrección, que era incorrecto. Lo que valida el modelo es la revisión visual de los casos de riesgo.

## 2. Revisión visual

Todas las imágenes con rotación EXIF o con tamaño distinto al del COCO (casos de riesgo) más 10 al azar (semilla 7). Cada miniatura muestra el original con la caja del COCO dibujada, escalada a la foto mostrada, y el recorte a la derecha.

### Casos de riesgo (13)

| `crop_id` | Imagen | Etiqueta | Motivo de revisión | ¿Correcto? | Observación |
|---|---:|---|---|---|---|
| `0.1.3:a4` | 1 | person | archivo 1280×851 vs COCO 1024×682 | ✅ | Mujer caminando (antes: una ventana) |
| `0.1.3:a5` | 1 | person | ídem | ✅ | Hombre con niño en la acera |
| `0.1.3:a6` | 1 | person | ídem | ✅ | Personas caminando |
| `0.1.3:a9` | 3 | person | archivo 1249×700 vs COCO 1248×702 | ✅ | Niño al fondo, desenfocado |
| `0.1.3:a12` | 6 | dog | archivo 1200×750 vs COCO 1024×639 | ✅ | Perro echado, completo |
| `0.1.3:a16` | 7 | cat | archivo 800×534 vs COCO 800×533 | ✅ | Gato de frente, completo |
| `0.1.3:a17` | 8 | cat | archivo 726×448 vs COCO 728×425 (5.7 %) | ✅ | Gatito completo; el escalado por eje incluye las patas |
| `0.1.3:a39` | 26 | person | EXIF orientación 6 | ✅ | Niño en bicicleta |
| `0.1.3:a43` | 28 | person | EXIF orientación 6 | ✅ | Hombre en bicicleta (antes: una reja) |
| `0.1.3:a47` | 30 | person | EXIF orientación 6 | ✅ | Hombre en bicicleta (antes: una puerta) |
| `0.1.3:a57` | 38 | person | EXIF orientación 6 | ✅ | Niño en bicicleta (antes: plantas) |
| `0.1.3:a59` | 39 | person | EXIF orientación 6 | ✅ | Hombre en bicicleta, de espaldas |
| `0.1.3:a61` | 40 | person | EXIF orientación 6 | ✅ | Hombre mayor en bicicleta |

### Muestra aleatoria (10, semilla 7)

| `crop_id` | Imagen | Etiqueta | ¿Correcto? | Observación |
|---|---:|---|---|---|
| `0.1.3:a955` | 885 | person | ✅ | Persona en un centro comercial |
| `0.1.3:a600` | 534 | dog | ✅ | Perro de frente |
| `0.1.3:a1109` | 942 | person | ✅ | Mujer en una mesa con varias personas |
| `0.1.3:a1676` | 1622 | cat | ✅ | Cara de gato |
| `0.1.3:a390` | 325 | cat | ✅ | Gato echado |
| `0.1.3:a440` | 375 | cat | ✅ | Gato dormido |
| `0.1.3:a1436` | 1244 | dog | ✅ | El perro de la derecha de dos (el de la izquierda no es esta caja) |
| `0.1.3:a484` | 419 | cat | ✅ | Cara de gato |
| `0.1.3:a1046` | 920 | person | ✅ | Cara pequeña entre una multitud |
| `0.1.3:a1535` | 1491 | cat | ✅ | Gato de frente |

**Resultado: 23 de 23 recortes corresponden a su caja y a su etiqueta.** Revisión hecha por el agente de Diego sobre las miniaturas de `docs/verificacion_recortes/`; se puede repetir con el comando de arriba.

Observación para F4/F6: varios recortes de `person` son sujetos pequeños o lejanos (a9, a1046), coherente con el 10.9 % de cajas diminutas que reporta P2. Se conservan por la regla de [clases.md](clases.md); conviene revisar el recall de `person` en la evaluación.
