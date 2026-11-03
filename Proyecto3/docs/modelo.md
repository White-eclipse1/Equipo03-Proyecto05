# Modelo — clasificador de recortes (F4 T10)

Código: [`src/p3/model/build.py`](../src/p3/model/build.py). Decisión de arquitectura: [decisiones.md §3](decisiones.md#3-framework-y-arquitectura-inicial).

## Arquitectura

| Parte | Detalle |
|---|---|
| Backbone | `torchvision.models.resnet18` (torchvision 0.29.0, PyTorch 2.14.0) |
| Pesos iniciales | `ResNet18_Weights.IMAGENET1K_V1`: preentrenados por el equipo de PyTorch sobre ImageNet-1k (1000 clases); archivo `resnet18-f37072fd.pth`, descargado de `download.pytorch.org` y verificado por torchvision con el hash de su nombre |
| Cabeza | Reemplaza la capa `fc` (512 → 1000) por `Linear → ReLU → Dropout` por cada entrada de `hidden_layers` y una `Linear` final a 3 salidas; con `hidden_layers = []` queda `Dropout → Linear` |
| Salida | 3 logits en el orden de `class_index` de [`config/classes.yaml`](../config/classes.yaml): 0 `cat`, 1 `dog`, 2 `person` |
| Capas entrenables | **Todas** (fine-tuning completo): el backbone se ajusta a nuestras clases, no solo la cabeza |

La cabeza es nueva y se inicializa al azar (con la semilla de la corrida); los pesos del backbone parten de ImageNet y se actualizan en cada paso del optimizador. `tests/test_model.py` comprueba que tres pasos cambian tanto la cabeza como la primera convolución del backbone.

## Por qué ResNet-18 preentrenada

- Hay pocos datos: 1459 recortes en total y unos 1000 de entrenamiento. Entrenar desde cero no llegaría al 85 %.
- ResNet-18 es la más ligera de la familia (11.7 M parámetros): cabe en la RTX 4060 (8 GB) con `image_size` 224 y permite ≥10 corridas en la ventana del barrido.
- La rúbrica permite pesos preentrenados si se declara su origen y se entrenan pesos propios; ambos quedan registrados en cada checkpoint (`architecture.pretrained_weights`) y en MLflow.

## Licencia de los pesos

El código de torchvision es BSD-3-Clause. Los pesos se entrenaron con ImageNet-1k, cuyo uso está sujeto a los términos de ImageNet (investigación y educación, no comercial). Este proyecto es académico.

## Checkpoint

`save_checkpoint` guarda en un solo archivo lo necesario para recargar el modelo en un proceso limpio (M4):

```json
{
  "state_dict": "…",
  "architecture": {"name": "resnet18", "hidden_layers": [256], "dropout": 0.3, "num_classes": 3, "pretrained_weights": "ResNet18_Weights.IMAGENET1K_V1"},
  "class_names": ["cat", "dog", "person"],
  "preprocessing": {"image_size": 224, "resize": "resize_to_square", "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]}
}
```

`load_checkpoint` reconstruye la arquitectura sin descargar nada, carga los pesos con `torch.load(weights_only=True)` y deja el modelo en modo `eval`.

## Preprocesamiento

Definido una sola vez en [`src/p3/data/transforms.py`](../src/p3/data/transforms.py):

- **Evaluación, prueba e inferencia** (`build_eval_transform`): el recorte se lleva a `image_size × image_size` sin recortar bordes (la caja ya encuadra el objeto) y se normaliza con la media y desviación de ImageNet.
- **Entrenamiento** (`build_train_transform`): la misma normalización más aumentación aleatoria (recorte aleatorio del 70–100 % del área, espejo horizontal y variación de color). Solo se aplica a la partición de train.
