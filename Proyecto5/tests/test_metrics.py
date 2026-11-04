import csv
import json
import os
from pathlib import Path

import numpy as np
import pytest
import yaml

from p5.dataset.paquete import OBSTACLE_CLASSES, load_manifest
from p5.detector.models import Detection
from p5.metrics import __main__ as cli
from p5.metrics.detection import (
    EVALUATED_CLASSES,
    IOU_THRESHOLD,
    SCORE_THRESHOLD,
    evaluate,
    iou,
    match_frame,
    score,
)

PROJECT = Path(__file__).resolve().parents[1]
DATASET = PROJECT / "data" / "p5-eval-v1"
POLICY = PROJECT.parent / "Proyecto3" / "config" / "politica.yaml"
WEIGHTS = os.environ.get("P5_DETECTOR_WEIGHTS")

BOX = [0.0, 0.0, 10.0, 10.0]


def pred(box=BOX, confidence=0.9, class_name="person"):
    return {"class_name": class_name, "confidence": confidence, "bbox_xyxy": box}


def gt(box=BOX, class_name="person"):
    return {"class_name": class_name, "bbox_xyxy": box}


def row(frame_id, annotations, split="evaluacion"):
    return {
        "sequence_id": frame_id.split("-")[0],
        "frame_id": frame_id,
        "split": split,
        "annotations": annotations,
    }


def ok(detections):
    return {"status": "ok", "detections": detections, "error": None}


# IoU


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (BOX, BOX, 1.0),
        (BOX, [20.0, 20.0, 30.0, 30.0], 0.0),
        (BOX, [10.0, 0.0, 20.0, 10.0], 0.0),  # Solo se tocan en un borde.
        (BOX, [0.0, 0.0, 10.0, 5.0], 0.5),
        (BOX, [5.0, 0.0, 15.0, 10.0], 50.0 / 150.0),
    ],
)
def test_iou(a, b, expected):
    assert iou(a, b) == pytest.approx(expected)
    assert iou(b, a) == pytest.approx(expected)


def test_evaluation_thresholds_are_the_required_ones():
    assert IOU_THRESHOLD == 0.50
    assert EVALUATED_CLASSES == OBSTACLE_CLASSES


def test_score_threshold_was_not_chosen_from_results_it_is_the_policy_threshold():
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))

    assert policy["confianza"]["umbral_alto"] == SCORE_THRESHOLD


# Emparejamiento


def test_exact_match_is_a_true_positive():
    result = match_frame([pred()], [gt()])

    assert len(result["matches"]) == 1
    assert result["false_positives"] == []
    assert result["false_negatives"] == []
    assert result["matches"][0]["iou"] == 1.0


def test_iou_exactly_at_the_threshold_matches():
    result = match_frame([pred([0.0, 0.0, 10.0, 5.0])], [gt()])

    assert len(result["matches"]) == 1


def test_iou_below_the_threshold_is_a_false_positive_and_a_false_negative():
    result = match_frame([pred([0.0, 0.0, 10.0, 4.9])], [gt()])

    assert result["matches"] == []
    assert len(result["false_positives"]) == 1
    assert result["false_positives"][0]["best_iou"] == pytest.approx(0.49)
    assert len(result["false_negatives"]) == 1


def test_duplicate_prediction_is_a_false_positive():
    result = match_frame([pred(confidence=0.9), pred(confidence=0.8)], [gt()])

    assert len(result["matches"]) == 1
    assert result["matches"][0]["confidence"] == 0.9
    assert [p["confidence"] for p in result["false_positives"]] == [0.8]


def test_wrong_class_is_a_false_positive_and_a_false_negative():
    result = match_frame([pred(class_name="cat")], [gt(class_name="dog")])

    assert result["matches"] == []
    assert result["false_positives"][0]["class_name"] == "cat"
    assert result["false_negatives"][0]["class_name"] == "dog"


def test_each_annotation_is_used_only_once_and_gets_its_best_prediction():
    near = [0.0, 0.0, 10.0, 9.0]
    other = [0.0, 0.0, 10.0, 6.0]

    result = match_frame([pred(near, 0.9), pred(other, 0.5)], [gt()])

    assert [m["bbox_xyxy"] for m in result["matches"]] == [near]
    assert [p["bbox_xyxy"] for p in result["false_positives"]] == [other]


def test_most_confident_prediction_chooses_first_even_with_worse_iou():
    # El orden es por confianza, como pide la evaluacion, no por el mejor IoU global.
    worse = [0.0, 0.0, 10.0, 6.0]
    better = [0.0, 0.0, 10.0, 9.5]

    result = match_frame([pred(better, 0.5), pred(worse, 0.9)], [gt()])

    assert [m["confidence"] for m in result["matches"]] == [0.9]
    assert [p["confidence"] for p in result["false_positives"]] == [0.5]


def test_prediction_takes_the_annotation_with_the_highest_iou():
    left = [0.0, 0.0, 10.0, 10.0]
    right = [2.0, 0.0, 12.0, 10.0]

    result = match_frame([pred([2.0, 0.0, 12.0, 9.0])], [gt(left), gt(right)])

    assert result["matches"][0]["annotation_index"] == 1
    assert [fn["annotation_index"] for fn in result["false_negatives"]] == [0]


def test_several_objects_in_a_frame_match_independently():
    second = [50.0, 50.0, 60.0, 60.0]

    result = match_frame([pred(second, 0.6), pred(BOX, 0.7)], [gt(BOX), gt(second)])

    assert len(result["matches"]) == 2
    assert result["false_positives"] == []
    assert result["false_negatives"] == []


def test_negative_frame_with_a_prediction_is_only_a_false_positive():
    result = match_frame([pred()], [])

    assert len(result["false_positives"]) == 1
    assert result["false_negatives"] == []


def test_input_is_not_modified():
    predictions, annotations = [pred()], [gt()]

    match_frame(predictions, annotations)

    assert predictions == [pred()]
    assert annotations == [gt()]


# Metricas


def test_score_formulas():
    result = score(tp=6, fp=2, fn=4)

    assert result["precision"] == pytest.approx(6 / 8)
    assert result["recall"] == pytest.approx(6 / 10)
    assert result["f1"] == pytest.approx(12 / 18)


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ((0, 0, 0), (0.0, 0.0, 0.0)),
        ((0, 3, 0), (0.0, 0.0, 0.0)),
        ((0, 0, 3), (0.0, 0.0, 0.0)),
    ],
)
def test_zero_denominators_give_zero(counts, expected):
    result = score(*counts)

    assert (result["precision"], result["recall"], result["f1"]) == expected


def test_evaluate_aggregates_every_frame_including_negatives():
    rows = [row("a-1", [gt()]), row("a-2", []), row("a-3", [gt()])]
    perceptions = {
        "a-1": ok([pred()]),
        "a-2": ok([pred()]),  # Falso positivo en un cuadro negativo.
        "a-3": ok([]),  # Objeto no detectado.
    }

    frames, metrics = evaluate(rows, perceptions)

    assert [(f["tp"], f["fp"], f["fn"]) for f in frames] == [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    micro = metrics["micro"]
    assert (micro["tp"], micro["fp"], micro["fn"], micro["support"]) == (1, 1, 1, 2)
    assert micro["f1"] == pytest.approx(0.5)
    assert metrics["cuadros"] == 3
    assert metrics["cuadros_negativos"] == 1
    assert metrics["cuadros_con_objetos"] == 2


def test_score_threshold_is_inclusive_and_recorded():
    rows = [row("a-1", [gt()]), row("a-2", [gt()])]
    perceptions = {
        "a-1": ok([pred(confidence=SCORE_THRESHOLD)]),
        "a-2": ok([pred(confidence=SCORE_THRESHOLD - 0.01)]),
    }

    frames, metrics = evaluate(rows, perceptions)

    assert [f["tp"] for f in frames] == [1, 0]
    assert [f["bajo_umbral"] for f in frames] == [0, 1]
    assert metrics["detecciones_bajo_umbral"] == 1
    assert metrics["umbral_confianza"] == SCORE_THRESHOLD


def test_classes_outside_the_evaluation_are_not_false_positives_but_are_counted():
    rows = [row("a-1", [])]

    frames, metrics = evaluate(rows, {"a-1": ok([pred(class_name="refrigerator")])})

    assert frames[0]["fp"] == 0
    assert frames[0]["otras_clases"] == {"refrigerator": 1}
    assert metrics["detecciones_de_otras_clases"] == {"refrigerator": 1}


def test_results_per_class_and_classes_without_support():
    rows = [row("a-1", [gt(), gt([20.0, 20.0, 30.0, 30.0], "dog")])]
    perceptions = {"a-1": ok([pred(), pred([50.0, 50.0, 60.0, 60.0], class_name="cat")])}

    _, metrics = evaluate(rows, perceptions)

    per_class = metrics["por_clase"]
    assert (per_class["person"]["tp"], per_class["person"]["f1"]) == (1, 1.0)
    assert (per_class["dog"]["support"], per_class["dog"]["fn"]) == (1, 1)
    assert (per_class["cat"]["support"], per_class["cat"]["fp"], per_class["cat"]["f1"]) == (
        0,
        1,
        0.0,
    )
    assert "cat" in metrics["clases_sin_soporte"]
    assert "person" not in metrics["clases_sin_soporte"]
    assert set(per_class) == set(EVALUATED_CLASSES)


def test_frame_with_an_error_keeps_its_objects_as_false_negatives_and_is_listed():
    rows = [row("a-1", [gt()])]
    perceptions = {"a-1": {"status": "error", "detections": [], "error": "ilegible"}}

    frames, metrics = evaluate(rows, perceptions)

    assert frames[0]["fn"] == 1
    assert metrics["cuadros_con_error"] == [{"frame_id": "a-1", "error": "ilegible"}]


def test_tuning_frames_do_not_count():
    rows = [row("a-1", [gt()]), row("b-1", [gt()], split="ajuste")]

    frames, metrics = evaluate(rows, {"a-1": ok([pred()])})

    assert [f["frame_id"] for f in frames] == ["a-1"]
    assert metrics["micro"]["support"] == 1


def test_package_without_evaluation_frames_is_rejected():
    with pytest.raises(ValueError, match="evaluacion"):
        evaluate([row("b-1", [], split="ajuste")], {})


def test_missing_predictions_are_rejected():
    with pytest.raises(ValueError, match="faltan predicciones"):
        evaluate([row("a-1", []), row("a-2", [])], {"a-1": ok([])})


def test_predictions_of_other_frames_are_rejected():
    with pytest.raises(ValueError, match="fuera de"):
        evaluate([row("a-1", [])], {"a-1": ok([]), "z-9": ok([])})


@pytest.mark.parametrize(
    "bad",
    [pred(confidence=float("nan")), pred([0.0, 0.0, float("inf"), 10.0])],
)
def test_non_finite_detection_is_rejected(bad):
    with pytest.raises(ValueError, match="no finitos"):
        evaluate([row("a-1", [])], {"a-1": ok([bad])})


# Comando


class ScriptedDetector:
    def __init__(self, detections_for):
        self.detections_for = detections_for
        self.sources = []

    def read_image(self, source):
        return np.zeros((296, 400, 3), dtype=np.uint8)

    def detect_image(self, image, *, source):
        self.sources.append(source)
        return self.detections_for(Path(source).stem)


@pytest.fixture(scope="module")
def rows():
    return load_manifest(DATASET / "manifiesto.jsonl")


def perfect_detector(rows):
    by_frame = {r["frame_id"]: r for r in rows}

    def detections_for(frame_id):
        return tuple(
            Detection(o["class_name"], 0.99, tuple(o["bbox_xyxy"]))
            for o in by_frame[frame_id]["annotations"]
        )

    return ScriptedDetector(detections_for)


def run_cli(monkeypatch, tmp_path, detector, *extra, name="salida"):
    weights = tmp_path / "pesos.onnx"
    weights.write_bytes(b"pesos")
    monkeypatch.setattr(cli, "load_detector", lambda path: detector)
    target = tmp_path / name
    code = cli.main(
        ["--dataset", str(DATASET), "--weights", str(weights), "--output", str(target), *extra]
    )
    return code, target


def test_cli_with_a_perfect_detector_gives_f1_one_and_stores_the_evidence(
    monkeypatch, tmp_path, rows, capsys
):
    code, target = run_cli(monkeypatch, tmp_path, perfect_detector(rows))

    assert code == 0
    metrics = json.loads((target / "metricas.json").read_text(encoding="utf-8"))
    assert metrics["micro"]["f1"] == 1.0
    assert metrics["micro"]["support"] == sum(len(r["annotations"]) for r in rows)
    assert metrics["cuadros"] == len(rows)
    assert metrics["ejecucion"]["modelo_sha256"]
    assert metrics["ejecucion"]["manifiesto_sha256"]
    assert metrics["ejecucion"]["predicciones_sha256"]
    assert "f1=1.0000" in capsys.readouterr().out
    assert len((target / "predicciones.jsonl").read_text(encoding="utf-8").splitlines()) == len(
        rows
    )
    per_frame = (target / "resultados_por_cuadro.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(per_frame[0])["frame_id"] == rows[0]["frame_id"]
    with (target / "metricas.csv").open(encoding="utf-8", newline="") as output:
        table = list(csv.DictReader(output))
    assert table[0]["clase"] == "micro"
    assert float(table[0]["f1"]) == 1.0
    assert {line["clase"] for line in table} >= {"person", "dog"}


def test_cli_recalculates_the_same_numbers_from_saved_predictions(monkeypatch, tmp_path, rows):
    # Pierde una detección de cada cuadro impar, para que los numeros no sean triviales.
    by_frame = {r["frame_id"]: r for r in rows}

    def some_detections(frame_id):
        objects = by_frame[frame_id]["annotations"]
        kept = objects if int(frame_id[-4:]) % 2 else objects[1:]
        return tuple(Detection(o["class_name"], 0.8, tuple(o["bbox_xyxy"])) for o in kept)

    _, first = run_cli(monkeypatch, tmp_path, ScriptedDetector(some_detections))
    second = tmp_path / "recalculo"

    code = cli.main(
        [
            "--dataset",
            str(DATASET),
            "--predictions",
            str(first / "predicciones.jsonl"),
            "--output",
            str(second),
        ]
    )

    assert code == 0
    assert (first / "resultados_por_cuadro.jsonl").read_bytes() == (
        second / "resultados_por_cuadro.jsonl"
    ).read_bytes()
    assert (first / "metricas.csv").read_bytes() == (second / "metricas.csv").read_bytes()
    assert (
        json.loads((second / "metricas.json").read_text(encoding="utf-8"))["ejecucion"][
            "modelo_sha256"
        ]
        is None
    )


def test_detector_only_receives_image_paths(monkeypatch, tmp_path, rows):
    # Con etiquetas alteradas en disco no se podria correr: aqui basta ver que abre solo imagenes.
    detector = ScriptedDetector(lambda frame_id: ())

    run_cli(monkeypatch, tmp_path, detector)

    assert len(detector.sources) == len(rows)
    assert all(Path(source).suffix == ".jpg" for source in detector.sources)


def test_cli_with_a_blind_detector_reports_zero_without_failing(monkeypatch, tmp_path):
    code, target = run_cli(monkeypatch, tmp_path, ScriptedDetector(lambda frame_id: ()))

    assert code == 0
    metrics = json.loads((target / "metricas.json").read_text(encoding="utf-8"))
    assert metrics["micro"]["tp"] == 0
    assert metrics["micro"]["f1"] == 0.0


def test_cli_exits_non_zero_when_a_frame_fails_and_keeps_the_evidence(monkeypatch, tmp_path, rows):
    class BrokenDetector(ScriptedDetector):
        def read_image(self, source):
            raise RuntimeError("detector roto")

    code, target = run_cli(monkeypatch, tmp_path, BrokenDetector(lambda frame_id: ()))

    assert code == 1
    metrics = json.loads((target / "metricas.json").read_text(encoding="utf-8"))
    assert len(metrics["cuadros_con_error"]) == len(rows)
    assert metrics["micro"]["fn"] == metrics["micro"]["support"]


def test_cli_records_a_different_threshold(monkeypatch, tmp_path, rows):
    _, target = run_cli(monkeypatch, tmp_path, perfect_detector(rows), "--score-threshold", "0.3")

    metrics = json.loads((target / "metricas.json").read_text(encoding="utf-8"))
    assert metrics["umbral_confianza"] == 0.3


def test_cli_refuses_an_existing_output_folder(monkeypatch, tmp_path, rows):
    (tmp_path / "salida").mkdir()

    with pytest.raises(SystemExit):
        run_cli(monkeypatch, tmp_path, perfect_detector(rows))


def test_cli_reports_weights_that_do_not_load(tmp_path, capsys):
    target = tmp_path / "salida"

    code = cli.main(
        [
            "--dataset",
            str(DATASET),
            "--weights",
            str(tmp_path / "no-existe.onnx"),
            "--output",
            str(target),
        ]
    )

    assert code == 1
    assert "no se pudieron calcular" in capsys.readouterr().err
    assert not target.exists()


def test_cli_rejects_incomplete_predictions(tmp_path, rows, capsys):
    partial = tmp_path / "predicciones.jsonl"
    partial.write_text(
        json.dumps({"frame_id": rows[0]["frame_id"], "status": "ok", "detections": []}) + "\n",
        encoding="utf-8",
    )

    code = cli.main(
        ["--dataset", str(DATASET), "--predictions", str(partial), "--output", str(tmp_path / "s")]
    )

    assert code == 1
    assert "faltan predicciones" in capsys.readouterr().err


@pytest.mark.skipif(not WEIGHTS, reason="P5_DETECTOR_WEIGHTS not set")
def test_real_detector_produces_consistent_counts(tmp_path, rows):
    target = tmp_path / "salida"

    code = cli.main(["--dataset", str(DATASET), "--weights", WEIGHTS, "--output", str(target)])

    assert code == 0
    metrics = json.loads((target / "metricas.json").read_text(encoding="utf-8"))
    micro = metrics["micro"]
    assert micro["support"] == sum(len(r["annotations"]) for r in rows)
    assert micro["tp"] + micro["fn"] == micro["support"]
    assert metrics["cuadros_con_error"] == []
