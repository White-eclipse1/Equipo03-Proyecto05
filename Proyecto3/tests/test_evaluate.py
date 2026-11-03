"""Protocolo de la evaluacion final en test (F6 T15, criterios 4.1-4.3).

Todo sobre el fixture de `tests/fixtures/p3/`: sus recortes, un manifiesto con la
semilla 42 y un ResNet-18 sin preentrenar con pesos fijos. El test real nunca se
toca en las pruebas.

Candados que se prueban:
- sin `selection.json` valido no hay evaluacion;
- el checkpoint y el manifiesto deben ser exactamente los de la seleccion;
- solo se predicen filas de `test`, con el preprocesamiento de evaluacion;
- la evaluacion se corre UNA vez: una segunda corrida se rechaza y el modo
  auditoria recalcula y compara sin sobrescribir.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import torch
from PIL import Image

from p3.data import crops as crops_mod
from p3.data import split
from p3.data.transforms import build_eval_transform
from p3.eval import evaluate
from p3.eval.evaluate import EvaluationAlreadyDoneError, EvaluationError
from p3.model.build import build_model, save_checkpoint

FIXTURE = Path(__file__).parent / "fixtures" / "p3"
CLASSES = ("cat", "dog", "person")
CLASS_INDEX = {4: 0, 3: 1, 2: 2}
IMAGE_SIZE = 32
PREPROCESSING = {
    "image_size": IMAGE_SIZE,
    "resize": "resize_to_square",
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
}


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("f6")
    coco = json.loads((FIXTURE / "annotations.coco.json").read_text(encoding="utf-8"))
    sizes = crops_mod.read_image_sizes(coco["images"], FIXTURE / "images")
    valid = crops_mod.validate_annotations(coco, set(CLASS_INDEX), sizes).valid

    crops_dir = root / "crops" / "0.0.0"
    records = crops_mod.generate_crops(valid, FIXTURE / "images", crops_dir, release_id="0.0.0")
    (crops_dir / "crops.jsonl").write_text(
        "".join(json.dumps(r.__dict__, default=list) + "\n" for r in records), encoding="utf-8"
    )

    rows = split.build_manifest(
        valid,
        release=split.ManifestRelease("0.0.0", "f" * 64),
        class_index=CLASS_INDEX,
        dup_groups=split.dup_group_ids({i["id"] for i in coco["images"]}, [{25, 26}]),
        seed=42,
    )
    manifest_dir = root / "manifests" / "m-0.0.0-s42-1"
    manifest_dir.mkdir(parents=True)
    # En bytes: `write_text` convierte los finales de linea en Windows y el hash cambiaria.
    (manifest_dir / "manifest.jsonl").write_bytes(split.manifest_jsonl(rows).encode("utf-8"))
    manifest_hash = split.manifest_hash(rows)
    (manifest_dir / "manifest.meta.json").write_text(
        json.dumps({"manifest_id": "m-0.0.0-s42-1", "manifest_hash": manifest_hash}),
        encoding="utf-8",
    )

    torch.manual_seed(0)
    model = build_model(num_classes=3, hidden_layers=[], dropout=0.0, pretrained=False)
    checkpoint = root / "model.pt"
    save_checkpoint(
        checkpoint,
        model,
        class_names=CLASSES,
        hidden_layers=[],
        dropout=0.0,
        preprocessing=PREPROCESSING,
    )
    selection = root / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "r-prueba",
                "manifest_id": "m-0.0.0-s42-1",
                "manifest_hash": manifest_hash,
                "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return {
        "root": root,
        "rows": rows,
        "crops_dir": crops_dir,
        "manifest_dir": manifest_dir,
        "checkpoint": checkpoint,
        "selection": selection,
    }


def _run(ws: dict[str, Any], out_dir: Path, **overrides: Any) -> dict[str, Any]:
    kwargs = {
        "selection_path": ws["selection"],
        "checkpoint_path": ws["checkpoint"],
        "manifest_dir": ws["manifest_dir"],
        "crops_dir": ws["crops_dir"],
        "out_dir": out_dir,
    }
    kwargs.update(overrides)
    return evaluate.run_evaluation(**kwargs)


# --- Seleccion -------------------------------------------------------------------------------


def test_sin_selection_json_no_hay_evaluacion(workspace, tmp_path: Path) -> None:
    with pytest.raises(EvaluationError, match=r"selection\.json"):
        _run(workspace, tmp_path / "out", selection_path=tmp_path / "no-existe.json")


@pytest.mark.parametrize("campo", ["run_id", "checkpoint_sha256", "manifest_hash"])
def test_selection_json_incompleto_no_hay_evaluacion(workspace, tmp_path: Path, campo) -> None:
    data = json.loads(workspace["selection"].read_text(encoding="utf-8"))
    del data[campo]
    incompleta = tmp_path / "selection.json"
    incompleta.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(EvaluationError, match=campo):
        _run(workspace, tmp_path / "out", selection_path=incompleta)


def test_checkpoint_distinto_al_seleccionado_se_rechaza(workspace, tmp_path: Path) -> None:
    otro = tmp_path / "otro.pt"
    otro.write_bytes(workspace["checkpoint"].read_bytes() + b"x")
    with pytest.raises(EvaluationError, match="SHA-256"):
        _run(workspace, tmp_path / "out", checkpoint_path=otro)
    assert not (tmp_path / "out").exists()


def test_manifiesto_distinto_al_seleccionado_se_rechaza(workspace, tmp_path: Path) -> None:
    copia = tmp_path / "m-0.0.0-s42-1"
    copia.mkdir()
    texto = (workspace["manifest_dir"] / "manifest.jsonl").read_text(encoding="utf-8")
    (copia / "manifest.jsonl").write_text(texto.replace('"test"', '"val"', 1), encoding="utf-8")
    with pytest.raises(EvaluationError, match="manifiesto"):
        _run(workspace, tmp_path / "out", manifest_dir=copia)


# --- Predicciones ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def evaluated(workspace, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("salida")
    report = _run(workspace, out)
    with (out / "predictions_test.csv").open(encoding="utf-8", newline="") as handle:
        predictions = list(csv.DictReader(handle))
    return {"out": out, "report": report, "predictions": predictions}


def test_solo_se_predicen_las_filas_de_test(workspace, evaluated) -> None:
    test_ids = sorted(r["crop_id"] for r in workspace["rows"] if r["split"] == "test")
    assert [p["crop_id"] for p in evaluated["predictions"]] == test_ids
    assert evaluated["report"]["test_size"] == len(test_ids) > 0


def test_csv_con_las_columnas_que_lee_verify_inference(evaluated) -> None:
    first = evaluated["predictions"][0]
    assert list(first) == [
        "crop_id",
        "clase_real",
        "clase_predicha",
        "prob_cat",
        "prob_dog",
        "prob_person",
    ]
    for row in evaluated["predictions"]:
        probs = {c: float(row[f"prob_{c}"]) for c in CLASSES}
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)
        assert row["clase_predicha"] == max(probs, key=probs.__getitem__)
        assert row["clase_real"] in CLASSES


def test_la_clase_real_sale_del_manifiesto(workspace, evaluated) -> None:
    real = {r["crop_id"]: r["category_name"] for r in workspace["rows"]}
    assert all(p["clase_real"] == real[p["crop_id"]] for p in evaluated["predictions"])


def test_probabilidades_con_el_preprocesamiento_de_evaluacion(workspace, evaluated) -> None:
    # Calculo independiente: mismo checkpoint, build_eval_transform y softmax a mano.
    checkpoint = torch.load(workspace["checkpoint"], weights_only=True)
    torch.manual_seed(0)
    model = build_model(num_classes=3, hidden_layers=[], dropout=0.0, pretrained=False)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    index = {
        json.loads(line)["crop_id"]: workspace["crops_dir"] / json.loads(line)["crop_path"]
        for line in (workspace["crops_dir"] / "crops.jsonl").read_text().splitlines()
    }
    transform = build_eval_transform(IMAGE_SIZE)
    row = evaluated["predictions"][0]
    with Image.open(index[row["crop_id"]]) as handle:
        tensor = transform(handle.convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        esperado = torch.softmax(model(tensor), dim=1)[0].tolist()
    assert [float(row[f"prob_{c}"]) for c in CLASSES] == pytest.approx(esperado, abs=1e-6)


def test_metricas_recalculadas_desde_el_csv(evaluated) -> None:
    preds = evaluated["predictions"]
    aciertos = sum(p["clase_real"] == p["clase_predicha"] for p in preds)
    metrics = json.loads((evaluated["out"] / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["accuracy"] == aciertos / len(preds)
    matrix = metrics["confusion_matrix"]["rows_true_cols_pred"]
    assert sum(map(sum, matrix)) == len(preds)
    assert metrics["confusion_matrix"]["labels"] == list(CLASSES)
    assert {"f1_macro", "per_class", "majority_baseline", "most_confused"} <= set(metrics)


def test_metrics_registra_procedencia(workspace, evaluated) -> None:
    metrics = json.loads((evaluated["out"] / "metrics.json").read_text(encoding="utf-8"))
    selection = json.loads(workspace["selection"].read_text(encoding="utf-8"))
    assert metrics["run_id"] == "r-prueba"
    assert metrics["manifest_hash"] == selection["manifest_hash"]
    assert metrics["checkpoint_sha256"] == selection["checkpoint_sha256"]
    assert (
        metrics["selection_sha256"]
        == hashlib.sha256(workspace["selection"].read_bytes()).hexdigest()
    )
    assert metrics["evaluated_at"].endswith("Z")
    assert metrics["passes_threshold"] is (metrics["accuracy"] >= 0.85)


def test_errores_y_aciertos_de_ejemplo_solo_de_test(workspace, evaluated) -> None:
    errors = json.loads((evaluated["out"] / "errors.json").read_text(encoding="utf-8"))
    test_ids = {r["crop_id"] for r in workspace["rows"] if r["split"] == "test"}
    ejemplos = errors["correct"] + errors["errors"]
    assert ejemplos and all(e["crop_id"] in test_ids for e in ejemplos)
    assert all(e["true"] == e["predicted"] for e in errors["correct"])
    assert all(e["true"] != e["predicted"] for e in errors["errors"])
    assert all(
        {"crop_id", "crop_path", "true", "predicted", "probability"} <= set(e) for e in ejemplos
    )


# --- Una sola corrida ------------------------------------------------------------------------


def test_segunda_evaluacion_se_rechaza(workspace, evaluated) -> None:
    with pytest.raises(EvaluationAlreadyDoneError):
        _run(workspace, evaluated["out"])


def test_auditoria_recalcula_y_no_sobrescribe(workspace, evaluated) -> None:
    antes = {p.name: p.read_bytes() for p in evaluated["out"].iterdir()}
    resultado = _run(workspace, evaluated["out"], audit=True)
    assert resultado["audit_matches"] is True
    assert {p.name: p.read_bytes() for p in evaluated["out"].iterdir()} == antes


def test_auditoria_detecta_un_csv_alterado(workspace, evaluated, tmp_path: Path) -> None:
    copia = tmp_path / "alterado"
    copia.mkdir()
    for p in evaluated["out"].iterdir():
        (copia / p.name).write_bytes(p.read_bytes())
    csv_path = copia / "predictions_test.csv"
    lineas = csv_path.read_text(encoding="utf-8").splitlines()
    campos = lineas[1].split(",")
    campos[2] = "dog" if campos[2] != "dog" else "cat"
    lineas[1] = ",".join(campos)
    csv_path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    resultado = _run(workspace, copia, audit=True)
    assert resultado["audit_matches"] is False


def test_procedencia_extra_queda_en_metrics(workspace, tmp_path: Path) -> None:
    record = _run(
        workspace,
        tmp_path / "out",
        provenance={"code_commit": "abc1234", "crops_jsonl_sha256": "d3d61f35"},
    )
    metrics = json.loads((tmp_path / "out" / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["code_commit"] == record["code_commit"] == "abc1234"
    assert metrics["crops_jsonl_sha256"] == "d3d61f35"
