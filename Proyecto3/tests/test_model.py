"""Clasificador ResNet-18 con cabeza propia (F4 T10, criterios 2.1 y M4).

Las pruebas construyen el modelo SIN pesos preentrenados para no descargar
nada; el origen de los pesos reales se prueba por su identificador.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch
from torch import nn
from torchvision.models import ResNet18_Weights

from p3.data import classes
from p3.model import build

CLASSES_YAML = Path(__file__).parents[1] / "config" / "classes.yaml"


@pytest.fixture
def class_names() -> list[str]:
    config = classes.load_classes(CLASSES_YAML)
    return [c.category_name for c in sorted(config.classes, key=lambda c: c.class_index)]


def _model(num_classes: int, hidden: list[int], dropout: float) -> nn.Module:
    torch.manual_seed(0)
    return build.build_model(
        num_classes=num_classes, hidden_layers=hidden, dropout=dropout, pretrained=False
    )


def test_la_salida_tiene_una_neurona_por_clase_de_classes_yaml(class_names) -> None:
    model = _model(len(class_names), [128], 0.2).eval()
    with torch.no_grad():
        out = model(torch.randn(2, 3, 64, 64))
    assert out.shape == (2, len(class_names)) == (2, 3)


@pytest.mark.parametrize(
    ("hidden", "lineales"),
    [
        ([], [(512, 3)]),
        ([256], [(512, 256), (256, 3)]),
        ([512, 128], [(512, 512), (512, 128), (128, 3)]),
    ],
)
def test_hidden_layers_define_la_cabeza(hidden, lineales) -> None:
    head = _model(3, hidden, 0.3).fc
    capas = [(m.in_features, m.out_features) for m in head.modules() if isinstance(m, nn.Linear)]
    assert capas == lineales


def test_dropout_se_aplica_en_la_cabeza() -> None:
    head = _model(3, [64, 32], 0.45).fc
    ps = [m.p for m in head.modules() if isinstance(m, nn.Dropout)]
    assert ps and all(p == 0.45 for p in ps)


def test_tres_pasos_del_optimizador_cambian_los_pesos() -> None:
    model = _model(3, [32], 0.0).train()
    antes_cabeza = [p.detach().clone() for p in model.fc.parameters()]
    antes_backbone = model.conv1.weight.detach().clone()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    x, y = torch.randn(4, 3, 64, 64), torch.tensor([0, 1, 2, 0])
    for _ in range(3):
        optimizer.zero_grad()
        nn.functional.cross_entropy(model(x), y).backward()
        optimizer.step()
    assert all(
        not torch.equal(a, p) for a, p in zip(antes_cabeza, model.fc.parameters(), strict=True)
    )
    assert not torch.equal(antes_backbone, model.conv1.weight)


def test_todas_las_capas_son_entrenables() -> None:
    model = _model(3, [64], 0.1)
    assert all(p.requires_grad for p in model.parameters())


def test_los_pesos_iniciales_son_imagenet1k_v1() -> None:
    assert build.PRETRAINED_WEIGHTS is ResNet18_Weights.IMAGENET1K_V1


def test_guardar_y_recargar_conserva_pesos_mapa_de_clases_y_preprocesamiento(
    tmp_path: Path, class_names
) -> None:
    model = _model(len(class_names), [64], 0.2).eval()
    preprocessing = {"image_size": 64, "resize": "resize_to_square"}
    path = tmp_path / "model.pt"
    build.save_checkpoint(
        path,
        model,
        class_names=class_names,
        hidden_layers=[64],
        dropout=0.2,
        preprocessing=preprocessing,
    )

    recargado, meta = build.load_checkpoint(path)
    x = torch.randn(3, 3, 64, 64)
    with torch.no_grad():
        assert torch.equal(model(x), recargado(x))
    assert meta["class_names"] == class_names
    assert meta["preprocessing"] == preprocessing
    assert meta["architecture"] == {
        "name": "resnet18",
        "hidden_layers": [64],
        "dropout": 0.2,
        "num_classes": 3,
        "pretrained_weights": "ResNet18_Weights.IMAGENET1K_V1",
    }
    assert not recargado.training
