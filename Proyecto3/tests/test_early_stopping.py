"""Early stopping con restauracion de la mejor epoca (F4 T12, criterio 2.4)."""

from __future__ import annotations

import pytest
import torch

from p3.train import trainer
from p3.train.early_stopping import EarlyStopping

SECUENCIA = [0.5, 0.6, 0.7, 0.65, 0.64, 0.63]


def _pesos(valor: float) -> dict[str, torch.Tensor]:
    return {"w": torch.full((2,), valor)}


def test_secuencia_controlada_para_en_la_6_y_se_queda_con_la_3() -> None:
    es = EarlyStopping(monitor="val_accuracy", patience=3, min_delta=0.0)
    paradas = [es.step(epoca, valor, _pesos(epoca)) for epoca, valor in enumerate(SECUENCIA, 1)]
    assert paradas == [False, False, False, False, False, True]
    assert es.best_epoch == 3
    assert es.best_value == 0.7
    assert es.stopped_epoch == 6
    assert torch.equal(es.best_state["w"], torch.full((2,), 3.0))


def test_min_delta_exige_una_mejora_real() -> None:
    es = EarlyStopping(monitor="val_accuracy", patience=2, min_delta=0.05)
    assert not es.step(1, 0.50, _pesos(1))
    assert not es.step(2, 0.53, _pesos(2))  # +0.03 < min_delta: no cuenta como mejora
    assert es.step(3, 0.54, _pesos(3))
    assert es.best_epoch == 1


def test_val_loss_se_minimiza() -> None:
    es = EarlyStopping(monitor="val_loss", patience=2, min_delta=0.0)
    for epoca, valor in enumerate([1.0, 0.8, 0.9, 0.95], 1):
        es.step(epoca, valor, _pesos(epoca))
    assert es.best_epoch == 2
    assert es.stopped_epoch == 4


def test_el_estado_guardado_no_cambia_si_el_modelo_sigue_entrenando() -> None:
    es = EarlyStopping(monitor="val_accuracy", patience=3, min_delta=0.0)
    pesos = _pesos(1.0)
    es.step(1, 0.9, pesos)
    pesos["w"].add_(100)
    assert torch.equal(es.best_state["w"], torch.full((2,), 1.0))


def test_monitor_desconocido_se_rechaza() -> None:
    with pytest.raises(ValueError, match="monitor"):
        EarlyStopping(monitor="test_accuracy", patience=3, min_delta=0.0)


def test_el_entrenador_para_y_restaura_la_mejor_epoca(monkeypatch, tmp_path) -> None:
    """Secuencia de validacion forzada: el modelo final debe ser el de la epoca 3."""
    from PIL import Image

    from p3.data import dataset
    from p3.train.config import TrainingConfig

    rows, index = [], {}
    for i in range(8):
        path = tmp_path / f"c{i}.png"
        Image.new("RGB", (34, 34), (i * 30, 90, 140)).save(path)
        index[f"x:a{i}"] = path
        rows.append(
            {
                "crop_id": f"x:a{i}",
                "source_image_id": i,
                "dup_group_id": f"g{i}",
                "class_index": i % 3,
                "split": "train" if i < 6 else "val",
            }
        )
    datasets = dataset.build_datasets(rows, index, image_size=32)

    valores = iter(SECUENCIA + [0.1] * 10)
    monkeypatch.setattr(trainer, "evaluate", lambda *a, **k: (1.0, next(valores)))
    por_epoca: dict[int, dict[str, torch.Tensor]] = {}

    def guardar(modelo_por_epoca):
        def on_epoch(metrics):
            por_epoca[int(metrics["epoch"])] = {
                k: v.detach().clone() for k, v in modelo_por_epoca().state_dict().items()
            }

        return on_epoch

    config = TrainingConfig.model_validate(
        {
            "optimizer": "sgd",
            "batch_size": 3,
            "max_epochs": 20,
            "learning_rate": 0.05,
            "image_size": 32,
            "hidden_layers": [],
            "dropout": 0.0,
            "patience": 3,
            "min_delta": 0.0,
        }
    )
    holder: dict[str, torch.nn.Module] = {}
    result = trainer.train(
        config,
        train_set=datasets["train"],
        val_set=datasets["val"],
        num_classes=3,
        pretrained=False,
        device="cpu",
        on_model=lambda m: holder.setdefault("m", m),
        on_epoch=guardar(lambda: holder["m"]),
    )

    assert len(result.history) == 6
    assert result.best_epoch == 3
    assert result.stopped_epoch == 6
    final = result.model.state_dict()
    for k, v in final.items():
        assert torch.equal(v, por_epoca[3][k]), k
    assert not torch.equal(final["fc.1.weight"], por_epoca[6]["fc.1.weight"])
