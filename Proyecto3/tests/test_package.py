"""Paquete de la version de modelo y su tarjeta (F7 T17, criterio 5.1; contratos §6).

El paquete se arma a partir de datos, no de texto escrito a mano: el checkpoint
de `selection.json` (los mismos bytes, el mismo SHA-256), las metricas de test
de F6 y la configuracion de la corrida de MLflow. La tarjeta describe
exactamente ese artefacto.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import torch
from PIL import Image

from p3.data.transforms import build_eval_transform
from p3.model.build import build_model, load_checkpoint, save_checkpoint
from p3.registry.package import PackageError, build_package

CLASSES = ("cat", "dog", "person")
PREPROCESSING = {
    "image_size": 32,
    "resize": "resize_to_square",
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
}


@pytest.fixture(scope="module")
def inputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("f7")
    torch.manual_seed(0)
    model = build_model(num_classes=3, hidden_layers=[], dropout=0.5, pretrained=False)
    checkpoint = root / "model.pt"
    save_checkpoint(
        checkpoint,
        model,
        class_names=CLASSES,
        hidden_layers=[],
        dropout=0.5,
        preprocessing=PREPROCESSING,
    )
    data = checkpoint.read_bytes()
    selection = {
        "schema_version": 1,
        "run_id": "r10run",
        "manifest_id": "m-0.1.3-s42-1",
        "manifest_hash": "45600f29" + "0" * 56,
        "checkpoint_sha256": hashlib.sha256(data).hexdigest(),
        "crops_jsonl_sha256": "d3d61f35" + "0" * 56,
        "val_accuracy": 0.9965753424657534,
        "best_epoch": 6,
    }
    metrics = {
        "run_id": "r10run",
        "manifest_id": "m-0.1.3-s42-1",
        "test_size": 145,
        "accuracy": 142 / 145,
        "f1_macro": 0.9743519475145314,
        "passes_threshold": True,
        "per_class": [
            {"class": "cat", "precision": 1.0, "recall": 0.9375, "f1": 0.9677, "support": 32},
            {"class": "dog", "precision": 0.9268, "recall": 1.0, "f1": 0.962, "support": 38},
            {"class": "person", "precision": 1.0, "recall": 0.9867, "f1": 0.9933, "support": 75},
        ],
        "confusion_matrix": {
            "labels": list(CLASSES),
            "rows_true_cols_pred": [[30, 2, 0], [0, 38, 0], [0, 1, 74]],
        },
        "majority_baseline": {"class": "person", "accuracy": 75 / 145},
        "most_confused": {"true": "cat", "predicted": "dog", "count": 2},
        "evaluated_at": "2026-09-28T02:25:07Z",
    }
    run_params = {
        "optimizer": "adamw",
        "batch_size": "64",
        "max_epochs": "15",
        "learning_rate": "0.0001",
        "image_size": "224",
        "hidden_layers": "[]",
        "dropout": "0.5",
        "seed": "42",
        "patience": "5",
        "min_delta": "0.001",
        "monitor_metric": "val_accuracy",
    }
    run_tags = {
        "release_id": "0.1.3",
        "release_hash": "2200274d" + "0" * 56,
        "dvc_md5": "ca56420c9992f8b75fdb10f2ece81704.dir",
        "code_commit": "250bedc",
        "pretrained_weights": "ResNet18_Weights.IMAGENET1K_V1",
    }
    classes_config = [
        {"class_index": 0, "category_id": 4, "category_name": "cat"},
        {"class_index": 1, "category_id": 3, "category_name": "dog"},
        {"class_index": 2, "category_id": 2, "category_name": "person"},
    ]
    return {
        "checkpoint": data,
        "selection": selection,
        "metrics": metrics,
        "run_params": run_params,
        "run_tags": run_tags,
        "classes": classes_config,
    }


def package(inputs: dict[str, Any], **overrides: Any) -> dict[str, bytes]:
    kwargs = {
        "checkpoint": inputs["checkpoint"],
        "run": inputs["selection"],
        "selection": json.dumps(inputs["selection"]).encode("utf-8"),
        "metrics": inputs["metrics"],
        "run_params": inputs["run_params"],
        "run_tags": inputs["run_tags"],
        "classes": inputs["classes"],
        "version": "1.0.0",
        "requirements": "torch==2.14.0\ntorchvision==0.29.0\n",
        "created_at": "2026-09-28T03:00:00Z",
    }
    kwargs.update(overrides)
    return build_package(**kwargs)


def test_el_paquete_trae_los_archivos_del_contrato(inputs) -> None:
    assert set(package(inputs)) == {
        "model.pt",
        "class_map.json",
        "preprocessing.json",
        "config.json",
        "requirements.lock.txt",
        "MODEL_CARD.md",
        "model_version.json",
    }


def test_model_pt_son_los_mismos_bytes_seleccionados(inputs) -> None:
    files = package(inputs)
    assert files["model.pt"] == inputs["checkpoint"]
    assert hashlib.sha256(files["model.pt"]).hexdigest() == inputs["selection"]["checkpoint_sha256"]


def test_checkpoint_distinto_al_seleccionado_se_rechaza(inputs) -> None:
    with pytest.raises(PackageError, match="SHA-256"):
        package(inputs, checkpoint=inputs["checkpoint"] + b"x")


def test_metricas_de_otra_corrida_se_rechazan(inputs) -> None:
    with pytest.raises(PackageError, match="run_id"):
        package(inputs, metrics=inputs["metrics"] | {"run_id": "otra"})


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "1.0.0-rc", ""])
def test_version_semantica_obligatoria(inputs, version: str) -> None:
    with pytest.raises(PackageError, match="version"):
        package(inputs, version=version)


def test_model_version_json_del_contrato(inputs) -> None:
    mv = json.loads(package(inputs)["model_version.json"])
    assert mv["version"] == "1.0.0"
    assert mv["architecture"] == "resnet18"
    assert mv["run_id"] == "r10run"
    assert mv["manifest_id"] == "m-0.1.3-s42-1"
    assert mv["release_id"] == "0.1.3"
    assert mv["pretrained_weights"] == "torchvision ResNet18_Weights.IMAGENET1K_V1"
    assert mv["test_metrics"] == {"accuracy": 142 / 145, "f1_macro": 0.9743519475145314}
    assert mv["preprocessing"] == PREPROCESSING
    assert mv["files"]["model.pt"]["sha256"] == inputs["selection"]["checkpoint_sha256"]
    selection_bytes = json.dumps(inputs["selection"]).encode("utf-8")
    assert mv["selection_sha256"] == hashlib.sha256(selection_bytes).hexdigest()


def test_class_map_y_preprocesamiento_salen_del_checkpoint(inputs) -> None:
    files = package(inputs)
    class_map = json.loads(files["class_map.json"])
    assert [c["category_name"] for c in class_map["classes"]] == list(CLASSES)
    assert [c["category_id"] for c in class_map["classes"]] == [4, 3, 2]
    assert json.loads(files["preprocessing.json"]) == PREPROCESSING


def test_config_con_la_corrida_y_la_arquitectura(inputs) -> None:
    config = json.loads(package(inputs)["config.json"])
    assert config["training"]["optimizer"] == "adamw"
    assert config["training"]["learning_rate"] == 0.0001
    assert config["training"]["hidden_layers"] == []
    assert config["architecture"]["name"] == "resnet18"
    assert config["architecture"]["num_classes"] == 3


def test_la_tarjeta_usa_las_cifras_de_la_evaluacion(inputs) -> None:
    card = package(inputs)["MODEL_CARD.md"].decode("utf-8")
    for texto in (
        "1.0.0",
        "r10run",
        "m-0.1.3-s42-1",
        "0.1.3",
        "2200274d",
        "ca56420c9992f8b75fdb10f2ece81704.dir",
        "0.9793",  # accuracy 142/145
        "142 / 145",
        "0.9744",  # F1 macro
        "0.5172",  # baseline
        "0.9375",  # recall de cat
        "IMAGENET1K_V1",
        "resize_to_square",
        "0.485",
        "load_checkpoint",
        "70/20/10",
    ):
        assert texto in card, texto
    for seccion in (
        "Propósito",
        "Datos",
        "Desempeño en test",
        "Preprocesamiento",
        "Limitaciones",
        "Cómo cargarlo",
    ):
        assert f"## {seccion}" in card, seccion


def test_la_tarjeta_no_inventa_cifras_si_cambian_las_metricas(inputs) -> None:
    otras = inputs["metrics"] | {"accuracy": 0.9, "f1_macro": 0.8}
    card = package(inputs, metrics=otras)["MODEL_CARD.md"].decode("utf-8")
    assert "0.9000" in card and "0.8000" in card
    assert "0.9793" not in card


def test_el_paquete_se_carga_en_un_proceso_nuevo_e_infiere(inputs, tmp_path: Path) -> None:
    files = package(inputs)
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    model, meta = load_checkpoint(tmp_path / "model.pt")
    preprocessing = json.loads((tmp_path / "preprocessing.json").read_text(encoding="utf-8"))
    image = Image.new("RGB", (40, 50), (120, 80, 200))
    tensor = build_eval_transform(preprocessing["image_size"])(image).unsqueeze(0)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    assert meta["class_names"] == list(CLASSES)
    assert float(probs.sum()) == pytest.approx(1.0, abs=1e-6)


# --- Version no seleccionada (0.9.0 = r08): sin metricas de test --------------------------


def test_version_no_seleccionada_sin_metricas_de_test(inputs) -> None:
    run = inputs["selection"] | {"run_id": "r08run", "val_accuracy": 0.9965753424657534}
    files = package(inputs, run=run, selection=None, metrics=None, version="0.9.0")
    mv = json.loads(files["model_version.json"])
    assert mv["selected"] is False
    assert mv["test_metrics"] is None
    assert mv["selection_sha256"] is None
    assert mv["run_id"] == "r08run"
    card = files["MODEL_CARD.md"].decode("utf-8")
    assert "No seleccionada" in card
    assert "sin evaluación en test" in card
    assert "0.9966" in card  # val_accuracy de su corrida
    assert "Accuracy top-1" not in card


def test_metricas_de_test_sin_seleccion_se_rechazan(inputs) -> None:
    run = inputs["selection"] | {"run_id": "r10run"}
    with pytest.raises(PackageError, match="seleccion"):
        package(inputs, run=run, selection=None, version="0.9.0")


def test_la_corrida_debe_ser_la_de_selection_json(inputs) -> None:
    run = inputs["selection"] | {"run_id": "r08run"}
    with pytest.raises(PackageError, match="r08run"):
        package(inputs, run=run)


def test_version_seleccionada_marca_selected(inputs) -> None:
    mv = json.loads(package(inputs)["model_version.json"])
    assert mv["selected"] is True
