"""Loop por minibatches, parametros que cambian el comportamiento y semillas (F4 T11, 2.1-2.3).

Recortes sinteticos de 3 clases a 32 px y ResNet-18 sin pesos preentrenados:
cada prueba corre en segundos en CPU.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import torch
from PIL import Image

from p3.data import dataset
from p3.train import trainer
from p3.train.config import TrainingConfig

N_TRAIN, N_VAL = 10, 6


@pytest.fixture
def datasets(tmp_path: Path) -> dict[str, dataset.CropDataset]:
    rows, index = [], {}
    colores = [(220, 40, 40), (40, 200, 40), (40, 40, 220)]
    for i in range(N_TRAIN + N_VAL):
        label = i % 3
        path = tmp_path / f"c{i}.png"
        Image.new("RGB", (36 + i, 30), colores[label]).save(path)
        crop_id = f"9.9.9:a{i}"
        index[crop_id] = path
        split = "train" if i < N_TRAIN else "val"
        rows.append(
            {
                "crop_id": crop_id,
                "source_image_id": i,
                "dup_group_id": f"g{i}",
                "class_index": label,
                "split": split,
            }
        )
    return dataset.build_datasets(rows, index, image_size=32)


def _config(**cambios: object) -> TrainingConfig:
    base = {
        "optimizer": "sgd",
        "batch_size": 4,
        "max_epochs": 2,
        "learning_rate": 0.01,
        "image_size": 32,
        "hidden_layers": [16],
        "dropout": 0.1,
        "seed": 3,
    }
    return TrainingConfig.model_validate({**base, **cambios})


def _train(datasets, config: TrainingConfig, **kwargs) -> trainer.TrainResult:
    return trainer.train(
        config,
        train_set=datasets["train"],
        val_set=datasets["val"],
        num_classes=3,
        pretrained=False,
        device="cpu",
        **kwargs,
    )


@pytest.mark.parametrize(
    ("nombre", "clase"),
    [("sgd", torch.optim.SGD), ("adam", torch.optim.Adam), ("adamw", torch.optim.AdamW)],
)
def test_el_optimizador_y_el_learning_rate_son_los_de_la_config(nombre, clase) -> None:
    model = torch.nn.Linear(2, 2)
    optimizer = trainer.build_optimizer(_config(optimizer=nombre, learning_rate=0.02), model)
    assert type(optimizer) is clase
    assert optimizer.param_groups[0]["lr"] == 0.02


@pytest.mark.parametrize("batch_size", [2, 4, 5])
def test_un_paso_del_optimizador_por_minibatch(datasets, batch_size) -> None:
    result = _train(datasets, _config(batch_size=batch_size, max_epochs=2))
    assert result.optimizer_steps == 2 * math.ceil(N_TRAIN / batch_size)


def test_un_minibatch_final_de_una_sola_muestra_se_descarta(datasets) -> None:
    # 10 = 3 + 3 + 3 + 1: BatchNorm no puede entrenar con 1 muestra; se omite ese batch.
    result = _train(datasets, _config(batch_size=3, max_epochs=2))
    assert result.optimizer_steps == 2 * 3
    assert len(result.train_order) == 2 * 9


def test_max_epochs_define_cuantas_epocas_se_entrenan(datasets) -> None:
    assert len(_train(datasets, _config(max_epochs=3)).history) == 3


def test_image_size_llega_al_modelo(datasets) -> None:
    formas: list[tuple[int, ...]] = []
    result = _train(
        datasets, _config(max_epochs=1), on_batch=lambda x: formas.append(tuple(x.shape[1:]))
    )
    assert result.history
    assert set(formas) == {(3, 32, 32)}


def test_hidden_layers_y_dropout_construyen_la_cabeza(datasets) -> None:
    model = _train(datasets, _config(max_epochs=1, hidden_layers=[24, 12], dropout=0.4)).model
    lineales = [m.out_features for m in model.fc.modules() if isinstance(m, torch.nn.Linear)]
    assert lineales == [24, 12, 3]
    assert {m.p for m in model.fc.modules() if isinstance(m, torch.nn.Dropout)} == {0.4}


def test_la_historia_tiene_loss_y_accuracy_de_train_y_val_por_epoca(datasets) -> None:
    epocas: list[int] = []
    result = _train(datasets, _config(max_epochs=2), on_epoch=lambda m: epocas.append(m["epoch"]))
    assert epocas == [1, 2]
    for fila in result.history:
        assert set(fila) >= {"epoch", "train_loss", "train_accuracy", "val_loss", "val_accuracy"}
        assert 0.0 <= fila["train_accuracy"] <= 1.0
        assert 0.0 <= fila["val_accuracy"] <= 1.0


def test_entrenar_cambia_los_pesos(datasets) -> None:
    torch.manual_seed(3)
    antes = trainer.build_model_for(_config(), num_classes=3, pretrained=False).state_dict()
    despues = _train(datasets, _config()).model.state_dict()
    assert not torch.equal(antes["fc.0.weight"], despues["fc.0.weight"])
    assert not torch.equal(antes["conv1.weight"], despues["conv1.weight"])


def test_misma_semilla_misma_corrida(datasets) -> None:
    a = _train(datasets, _config(seed=11))
    b = _train(datasets, _config(seed=11))

    def sin_duracion(history):
        # La duracion de cada epoca depende del reloj, no de la semilla.
        return [{k: v for k, v in fila.items() if k != "epoch_seconds"} for fila in history]

    assert sin_duracion(a.history) == sin_duracion(b.history)
    assert a.train_order == b.train_order
    for (k, va), (_, vb) in zip(
        a.model.state_dict().items(), b.model.state_dict().items(), strict=True
    ):
        assert torch.equal(va, vb), k


def test_otra_semilla_cambia_el_orden(datasets) -> None:
    assert (
        _train(datasets, _config(seed=1)).train_order
        != _train(datasets, _config(seed=2)).train_order
    )


def test_el_entorno_queda_registrado() -> None:
    info = trainer.environment_info("cpu")
    assert {"python", "torch", "torchvision", "numpy", "device", "deterministic"} <= set(info)
    assert info["torch"] == torch.__version__
