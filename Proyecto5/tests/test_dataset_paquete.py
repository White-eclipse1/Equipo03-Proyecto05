import hashlib
import json

import pytest

from dataset_helpers import (
    CENTER_BOX,
    HEIGHT,
    LEFT_BOX,
    RIGHT_BOX,
    WIDTH,
    add_sequence,
    make_valid_dataset,
)
from p5.dataset import paquete
from p5.dataset.paquete import (
    annotation_errors,
    build_report,
    freeze,
    load_manifest,
    occupied_zones,
    validate_package,
)


def person(box):
    return {"class_name": "person", "bbox_xyxy": box}


@pytest.fixture
def dataset(tmp_path):
    make_valid_dataset(tmp_path)
    return tmp_path


def edit_annotations(dataset, frame_id, **changes):
    path = dataset / "anotaciones.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        if row["frame_id"] == frame_id:
            row.update(changes)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_valid_dataset_passes_and_counts_the_evaluation_set(dataset):
    report = build_report(dataset)

    assert report.errors == []
    summary = report.summary()
    assert summary["secuencias_evaluacion"] == 6
    assert summary["frames_evaluacion"] == 60
    assert summary["con_obstaculo"] == 34
    assert summary["despejados"] == 26


def test_manifest_row_links_image_labels_and_allowed_actions(dataset):
    report = build_report(dataset)

    row = next(r for r in report.rows if r["frame_id"] == "seq02-0004")
    assert row["image"] == "secuencias/seq02/seq02-0004.jpg"
    assert row["sequence_id"] == "seq02"
    assert row["t_capture_ms"] == 1500
    assert row["annotations"] == [person(CENTER_BOX)]
    assert "FORWARD" not in row["allowed_actions"]


def test_clear_frame_keeps_an_explicit_empty_annotation(dataset):
    row = next(r for r in build_report(dataset).rows if r["frame_id"] == "seq01-0001")

    assert row["annotations"] == []
    assert row["road_state"] == "libre"


@pytest.mark.parametrize(
    ("box", "zones"),
    [
        (LEFT_BOX, {"izquierda"}),
        (CENTER_BOX, {"centro"}),
        (RIGHT_BOX, {"derecha"}),
        ([0.0, 0.0, WIDTH, HEIGHT], {"izquierda", "centro", "derecha"}),
        # Una caja angosta sobre el limite 0.35 ocupa las dos zonas, como en la politica.
        ([135.0, 0.0, 145.0, 10.0], {"izquierda", "centro"}),
    ],
)
def test_occupied_zones_follow_the_policy_rule(box, zones):
    assert occupied_zones(box, WIDTH) == zones


@pytest.mark.parametrize(
    ("state", "objects", "expected"),
    [
        ("libre", [person(CENTER_BOX)], "libre no admite"),
        ("centro", [], "exige al menos"),
        ("centro", [person(LEFT_BOX)], "caja en el centro"),
        ("lateral_izquierda", [person(RIGHT_BOX)], "solo izquierda"),
        ("lateral_derecha", [person(LEFT_BOX)], "solo derecha"),
        ("lateral_izquierda", [person([100.0, 0.0, 200.0, 50.0])], "solo izquierda"),
        ("varios", [person(CENTER_BOX)], "varios exige"),
        ("otro", [], "desconocido"),
        ("centro", None, "lista explicita"),
        ("centro", [person([200.0, 10.0, 100.0, 50.0])], "sin ancho"),
        ("centro", [person([100.0, 10.0, 100.0, 50.0])], "sin ancho"),
        ("centro", [person([100.0, 10.0, 500.0, 50.0])], "fuera de la imagen"),
        ("centro", [person([-5.0, 10.0, 200.0, 50.0])], "fuera de la imagen"),
        ("centro", [person([1.0, 2.0, 3.0])], "4 numeros"),
        ("centro", [person([1.0, 2.0, float("nan"), 4.0])], "4 numeros"),
        ("centro", [{"class_name": "bottle", "bbox_xyxy": CENTER_BOX}], "fuera de las evaluadas"),
        ("centro", [{"bbox_xyxy": CENTER_BOX}], "class_name"),
    ],
)
def test_annotation_errors_detect_each_problem(state, objects, expected):
    errors = annotation_errors(state, objects, WIDTH, HEIGHT)

    assert any(expected in error for error in errors), errors


def test_invalid_annotation_is_reported_with_its_frame(dataset):
    edit_annotations(dataset, "seq03-0001", objects=[person(RIGHT_BOX)])

    errors = build_report(dataset).errors

    assert any(e.startswith("seq03-0001") and "solo izquierda" in e for e in errors)


def test_frame_without_annotation_is_an_error(dataset):
    path = dataset / "anotaciones.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line for line in lines if "seq01-0002" not in line) + "\n")

    assert any("seq01-0002: sin anotacion" in e for e in build_report(dataset).errors)


def test_annotation_without_a_frame_is_an_error(dataset):
    with (dataset / "anotaciones.jsonl").open("a", encoding="utf-8") as annotations:
        annotations.write(json.dumps({"frame_id": "x-1", "road_state": "libre", "objects": []}))

    assert any("x-1: anotacion sin cuadro" in e for e in build_report(dataset).errors)


def test_modified_image_breaks_its_hash(dataset):
    (dataset / "secuencias" / "seq01" / "seq01-0001.jpg").write_bytes(b"\xff\xd8 otra")

    errors = build_report(dataset).errors

    assert any("seq01-0001: el SHA-256" in e for e in errors)


def test_missing_image_is_an_error(dataset):
    (dataset / "secuencias" / "seq01" / "seq01-0001.jpg").unlink()

    assert any("seq01-0001: no existe" in e for e in build_report(dataset).errors)


def test_same_image_in_two_sequences_is_a_duplicate(dataset):
    add_sequence(dataset, "seq07", ["libre"], first_seed=100, split="ajuste")

    assert any(
        "seq07-0001: imagen identica a seq01-0001" in e for e in build_report(dataset).errors
    )


def test_time_must_grow_within_a_sequence(dataset):
    path = dataset / "secuencias" / "seq01" / "capturas.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[1]["t_capture_ms"] = rows[0]["t_capture_ms"]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    assert any("seq01-0002: t_capture_ms" in e for e in build_report(dataset).errors)


def test_tuning_frames_do_not_count_towards_the_minimums(tmp_path):
    add_sequence(tmp_path, "aj01", ["libre"] * 30, first_seed=1, split="ajuste")
    add_sequence(tmp_path, "aj02", ["centro"] * 30, first_seed=100, split="ajuste")

    errors = build_report(tmp_path).errors

    assert "evaluacion: 0/6 secuencias" in errors
    assert "evaluacion: 0/60 cuadros" in errors
    assert "evaluacion: 0/20 cuadros con obstaculo" in errors
    assert "evaluacion: 0/20 cuadros despejados" in errors


def test_missing_scenario_is_an_error(dataset):
    path = dataset / "secuencias.json"
    declared = json.loads(path.read_text(encoding="utf-8"))
    declared["sequences"]["seq04"]["scenario"] = "C3"
    path.write_text(json.dumps(declared), encoding="utf-8")

    assert "evaluacion: faltan escenarios ['C4']" in build_report(dataset).errors


def test_undeclared_sequence_and_invalid_split_are_errors(dataset):
    path = dataset / "secuencias.json"
    declared = json.loads(path.read_text(encoding="utf-8"))
    del declared["sequences"]["seq01"]
    declared["sequences"]["seq02"]["split"] = "ambos"
    path.write_text(json.dumps(declared), encoding="utf-8")

    errors = build_report(dataset).errors

    assert any("seq01: no esta declarada" in e for e in errors)
    assert any("seq02: split" in e for e in errors)


def test_freeze_records_the_hash_of_the_written_manifest(dataset):
    record = freeze(dataset, "v1", commit="abc123")

    content = (dataset / "manifiesto.jsonl").read_bytes()
    assert record["manifest_sha256"] == hashlib.sha256(content).hexdigest()
    assert record["version"] == "v1"
    assert record["base_commit"] == "abc123"
    stored = json.loads((dataset / "congelamiento.json").read_text(encoding="utf-8"))
    assert stored == record


def test_manifest_can_be_loaded_for_metrics(dataset):
    freeze(dataset, "v1")

    rows = load_manifest(dataset / "manifiesto.jsonl")

    assert len(rows) == 60
    assert {row["split"] for row in rows} == {"evaluacion"}


def test_freeze_is_idempotent_while_the_content_does_not_change(dataset):
    first = freeze(dataset, "v1")

    assert freeze(dataset, "v1") == first


def test_changes_after_freezing_require_a_new_version(dataset):
    freeze(dataset, "v1")
    edit_annotations(dataset, "seq02-0004", objects=[person([150.0, 100.0, 250.0, 280.0])])

    with pytest.raises(ValueError, match="version nueva"):
        freeze(dataset, "v2")


def test_freeze_refuses_an_invalid_dataset(dataset):
    edit_annotations(dataset, "seq03-0001", objects=[])

    with pytest.raises(ValueError, match="errores"):
        freeze(dataset, "v1")

    assert not (dataset / "congelamiento.json").exists()


def change_one_label(content: bytes) -> bytes:
    lines = content.decode("ascii").splitlines()
    row = json.loads(lines[0])
    row["road_state"] = "centro"
    lines[0] = json.dumps(row, sort_keys=True)
    return "".join(f"{line}\n" for line in lines).encode("ascii")


@pytest.mark.parametrize(
    "alter",
    [change_one_label, lambda content: content + b"\n"],
    ids=["changed-line", "extra-blank-line"],
)
def test_load_manifest_rejects_a_manifest_altered_after_freezing(dataset, alter):
    freeze(dataset, "v1")
    path = dataset / "manifiesto.jsonl"
    path.write_bytes(alter(path.read_bytes()))

    with pytest.raises(ValueError, match="no coincide"):
        load_manifest(path)


def test_load_manifest_rejects_a_manifest_without_its_freeze_record(dataset):
    freeze(dataset, "v1")
    (dataset / "congelamiento.json").unlink()

    with pytest.raises(ValueError, match=r"congelamiento\.json"):
        load_manifest(dataset / "manifiesto.jsonl")


@pytest.mark.parametrize("record", ["{}", '{"manifest_sha256": null}', "no es json", "[]"])
def test_load_manifest_rejects_an_invalid_freeze_record(dataset, record):
    freeze(dataset, "v1")
    (dataset / "congelamiento.json").write_text(record, encoding="utf-8")

    with pytest.raises(ValueError, match=r"congelamiento\.json"):
        load_manifest(dataset / "manifiesto.jsonl")


def test_validate_passes_on_an_untouched_frozen_dataset(dataset):
    freeze(dataset, "v1")

    assert validate_package(dataset).errors == []


def test_validate_fails_when_the_manifest_was_altered(dataset, capsys):
    freeze(dataset, "v1")
    path = dataset / "manifiesto.jsonl"
    path.write_bytes(change_one_label(path.read_bytes()))

    assert any("no coincide" in error for error in validate_package(dataset).errors)
    assert paquete.main(["validate", "--dataset", str(dataset)]) == 1
    assert "no coincide" in capsys.readouterr().err


def test_validate_fails_when_the_manifest_is_missing_after_freezing(dataset):
    freeze(dataset, "v1")
    (dataset / "manifiesto.jsonl").unlink()

    assert any("manifiesto.jsonl" in error for error in validate_package(dataset).errors)


def test_validate_fails_when_the_labels_changed_after_freezing(dataset):
    freeze(dataset, "v1")
    edit_annotations(dataset, "seq02-0004", objects=[person([150.0, 100.0, 250.0, 280.0])])

    errors = validate_package(dataset).errors

    assert any("version nueva" in error for error in errors)


def test_freeze_again_detects_an_altered_manifest(dataset):
    freeze(dataset, "v1")
    path = dataset / "manifiesto.jsonl"
    path.write_bytes(change_one_label(path.read_bytes()))

    with pytest.raises(ValueError, match="no coincide"):
        freeze(dataset, "v1")


def test_cli_validate_exit_codes(dataset, capsys):
    assert paquete.main(["validate", "--dataset", str(dataset)]) == 0
    assert json.loads(capsys.readouterr().out)["errores"] == 0

    edit_annotations(dataset, "seq03-0001", objects=[])

    assert paquete.main(["validate", "--dataset", str(dataset)]) == 1
    assert "seq03-0001" in capsys.readouterr().err


def test_cli_reports_a_dataset_without_declared_sequences(tmp_path, capsys):
    assert paquete.main(["validate", "--dataset", str(tmp_path)]) == 1
    assert "paquete invalido" in capsys.readouterr().err
