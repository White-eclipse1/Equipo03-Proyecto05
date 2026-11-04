import csv
import json
import os
import subprocess
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import numpy as np
import pytest
from p3.policy.config import cargar_config
from p3.policy.politica import PoliticaDecision

from p5.benchmark import __main__ as cli
from p5.benchmark.timing import (
    MIN_RUNS,
    MIN_WARMUPS,
    STAGES,
    instrument,
    measure,
    summarize,
)
from p5.control.adapter import VirtualControlAdapter
from p5.dataset.paquete import freeze, load_manifest
from p5.detector.weights import WEIGHTS_SHA256
from p5.detector.yolox import YoloxDetector
from p5.integration.pipeline import FrameInput, Pipeline
from test_detector import PERSON, FakeSession, raw_output, write_png

ROOT = Path(__file__).resolve().parents[2]
POLICY_CONFIG = ROOT / "Proyecto3" / "config" / "politica.yaml"
CENTER = raw_output((0, 208, 300, 100, 200, 1.0, PERSON, 0.9))


def timed_pipeline(session):
    config, sha256 = cargar_config(POLICY_CONFIG)
    detector = YoloxDetector(session)
    policy = PoliticaDecision(config, sha256)
    adapter = VirtualControlAdapter()
    clock = instrument(detector, policy, adapter)
    return Pipeline(detector, policy, adapter), clock


def image_file(tmp_path):
    return write_png(tmp_path / "frame.png", np.zeros((416, 416, 3), dtype=np.uint8))


def frames_for(image, count, sequence="seq01"):
    return [
        FrameInput(
            sequence_id=sequence,
            frame_id=f"{sequence}-{index:04d}",
            t_capture_ms=index * 500.0,
            image_size=(416, 416),
            image_path=image,
        )
        for index in range(count)
    ]


def test_every_stage_of_a_run_is_measured_and_fits_in_the_total(tmp_path):
    pipeline, clock = timed_pipeline(FakeSession(CENTER))

    rows = measure(pipeline, clock, frames_for(image_file(tmp_path), 3), warmups=1, runs=2)

    for row in rows:
        assert row["valido"] is True
        assert row["error"] == ""
        for stage in STAGES:
            assert row[stage] > 0
        assert row["ms_total"] >= sum(row[stage] for stage in STAGES)


def test_warmups_are_recorded_first_and_excluded_from_the_summary(tmp_path):
    pipeline, clock = timed_pipeline(FakeSession())

    rows = measure(pipeline, clock, frames_for(image_file(tmp_path), 5), warmups=2, runs=3)

    assert [row["fase"] for row in rows] == ["calentamiento"] * 2 + ["medicion"] * 3
    assert [row["indice"] for row in rows] == [0, 1, 2, 3, 4]
    assert [row["repeticion"] for row in rows] == [0, 1, 0, 1, 2]
    # Un calentamiento lentisimo no puede mover las cifras.
    rows[0]["ms_total"] = 1e9
    summary = summarize(rows)
    assert summary["calentamientos"] == 2
    assert summary["mediciones"] == 3
    assert summary["mediciones_validas"] == 3
    assert summary["etapas"]["ms_total"]["maximo"] < 1e9


def test_summary_can_be_recalculated_from_the_individual_runs():
    rows = [
        {
            "fase": "medicion",
            "valido": True,
            "ms_total": float(value),
            **dict.fromkeys(STAGES, float(value) / 10),
        }
        for value in range(1, 101)
    ]

    total = summarize(rows)["etapas"]["ms_total"]

    assert total["n"] == 100
    assert total["p50"] == pytest.approx(50.5)
    assert total["p95"] == pytest.approx(95.05)
    assert total["maximo"] == 100.0
    assert total["minimo"] == 1.0
    assert total["media"] == pytest.approx(50.5)


def fake_rows(warmups, runs, *, valid_warmups=None):
    valid_warmups = warmups if valid_warmups is None else valid_warmups
    rows = []
    for index in range(warmups):
        rows.append(
            {
                "fase": "calentamiento",
                "valido": index < valid_warmups,
                "ms_total": 1.0,
                **dict.fromkeys(STAGES, 0.1),
            }
        )
    for _ in range(runs):
        rows.append(
            {"fase": "medicion", "valido": True, "ms_total": 1.0, **dict.fromkeys(STAGES, 0.1)}
        )
    return rows


def test_minimums_hold_with_valid_warmups_and_data_in_every_stage():
    assert summarize(fake_rows(MIN_WARMUPS, MIN_RUNS))["cumple_minimos"] is True


def test_failed_warmups_do_not_count_for_the_minimum():
    summary = summarize(fake_rows(MIN_WARMUPS, MIN_RUNS, valid_warmups=MIN_WARMUPS - 1))

    assert summary["calentamientos"] == MIN_WARMUPS
    assert summary["calentamientos_validos"] == MIN_WARMUPS - 1
    assert summary["cumple_minimos"] is False


@pytest.mark.parametrize("stage", STAGES)
def test_a_stage_without_data_does_not_meet_the_minimums(stage):
    rows = fake_rows(MIN_WARMUPS, MIN_RUNS)
    for row in rows:
        row[stage] = None

    summary = summarize(rows)

    assert summary["etapas"][stage]["n"] == 0
    assert summary["cumple_minimos"] is False


def test_failures_are_kept_apart_from_valid_runs(tmp_path):
    image = image_file(tmp_path)
    frames = frames_for(image, 4)
    frames[2] = FrameInput(
        sequence_id="seq01",
        frame_id="seq01-0002",
        t_capture_ms=1000.0,
        image_size=(416, 416),
        image_path=tmp_path / "missing.png",
    )
    pipeline, clock = timed_pipeline(FakeSession())

    rows = measure(pipeline, clock, frames, warmups=0, runs=4)

    assert [row["valido"] for row in rows] == [True, True, False, True]
    assert "detector" in rows[2]["error"]
    assert "missing.png" in rows[2]["error"]
    assert str(tmp_path) not in rows[2]["error"]
    assert rows[2]["accion"] == "STOP"
    # No llego a inferir: esa etapa queda sin dato, no en cero.
    assert rows[2]["ms_inferencia"] is None
    summary = summarize(rows)
    assert summary["mediciones"] == 4
    assert summary["mediciones_validas"] == 3
    assert summary["mediciones_con_error"] == 1
    assert summary["etapas"]["ms_total"]["n"] == 3


def test_error_messages_never_expose_the_folder_of_the_image(tmp_path):
    # El mensaje de un OSError de Windows trae la ruta con `repr`, con barras dobles.
    missing = tmp_path / "missing.png"
    pipeline, clock = timed_pipeline(FakeSession())
    frame = FrameInput(
        sequence_id="seq01",
        frame_id="seq01-0000",
        t_capture_ms=0.0,
        image_size=(416, 416),
        image_path=missing,
    )
    real = pipeline.process

    def fail_with_repr(_frame):
        raise OSError(f"[Errno 2] No such file: {str(missing)!r} y {missing}")

    pipeline.process = fail_with_repr
    rows = measure(pipeline, clock, [frame], warmups=0, runs=1)
    pipeline.process = real

    assert "missing.png" in rows[0]["error"]
    assert str(tmp_path) not in rows[0]["error"]
    assert repr(str(tmp_path))[1:-1] not in rows[0]["error"]


def test_unexpected_exception_is_a_failed_run_and_the_benchmark_goes_on(tmp_path):
    pipeline, clock = timed_pipeline(FakeSession())
    frames = frames_for(image_file(tmp_path), 2)
    real = pipeline.process
    calls = []

    def explode_once(frame):
        calls.append(frame)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(frame)

    pipeline.process = explode_once

    rows = measure(pipeline, clock, frames, warmups=0, runs=2)

    assert [row["valido"] for row in rows] == [False, True]
    assert "boom" in rows[0]["error"]


@pytest.mark.parametrize("count", [1, 3])
def test_going_through_the_frames_again_is_not_a_failure(tmp_path, count):
    pipeline, clock = timed_pipeline(FakeSession())

    rows = measure(pipeline, clock, frames_for(image_file(tmp_path), count), warmups=2, runs=8)

    assert all(row["valido"] for row in rows)
    assert rows[count]["frame_id"] == rows[0]["frame_id"]


def test_measuring_does_not_change_the_decisions(tmp_path):
    image = image_file(tmp_path)
    frames = frames_for(image, 6)
    config, sha256 = cargar_config(POLICY_CONFIG)
    plain = Pipeline(
        YoloxDetector(FakeSession(CENTER)),
        PoliticaDecision(config, sha256),
        VirtualControlAdapter(),
    )
    expected = [plain.process(frame).decision["accion"] for frame in frames]

    pipeline, clock = timed_pipeline(FakeSession(CENTER))
    rows = measure(pipeline, clock, frames, warmups=0, runs=6)

    assert [row["accion"] for row in rows] == expected
    assert len(pipeline.adapter.history) == 6


def small_dataset(tmp_path):
    """Paquete congelado de imagenes reales, con cuadros suficientes para el minimo."""
    from dataset_helpers import make_valid_dataset

    dataset = tmp_path / "dataset"
    make_valid_dataset(dataset)
    freeze(dataset, "v1")
    # Las imagenes del paquete de prueba son JPEG minimos sin pixeles que decodificar.
    real = cv2_jpeg()
    manifest = dataset / "manifiesto.jsonl"
    rows = load_manifest(manifest)
    for row in rows:
        (dataset / row["image"]).write_bytes(real)
    return manifest


def cv2_jpeg():
    import cv2

    ok, encoded = cv2.imencode(".jpg", np.zeros((296, 400, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


@pytest.fixture
def fake_weights(tmp_path, monkeypatch):
    def install(session):
        monkeypatch.setattr(YoloxDetector, "from_weights", lambda *_a, **_k: YoloxDetector(session))
        monkeypatch.setattr(cli, "verify_weights", lambda *_a, **_k: None)
        monkeypatch.setattr(cli, "check_images", lambda *_a, **_k: None)

    return install


def arguments(manifest, output, *extra):
    return [
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--weights",
        "unused.onnx",
        "--policy-config",
        str(POLICY_CONFIG),
        *extra,
    ]


def test_cli_exports_raw_timings_and_conditions(tmp_path, fake_weights, capsys):
    manifest = small_dataset(tmp_path)
    output = tmp_path / "nueva" / "carpeta"
    fake_weights(FakeSession())

    code = cli.main(arguments(manifest, output, "--repeticiones", "100"))

    assert code == 0
    with (output / "tiempos.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == MIN_WARMUPS + 100
    assert rows[0]["fase"] == "calentamiento"
    assert rows[MIN_WARMUPS]["fase"] == "medicion"
    assert b"\r" not in (output / "tiempos.csv").read_bytes()

    evidence = json.loads(
        (output / "benchmark.json").read_text(encoding="utf-8"), parse_constant=pytest.fail
    )
    assert evidence["resumen"]["mediciones_validas"] == 100
    assert evidence["salida_fisica"] is False
    assert evidence["detector"]["sha256"] == WEIGHTS_SHA256
    assert evidence["runtime"]["onnxruntime"]
    assert evidence["runtime"]["providers_sesion"] == ["CPUExecutionProvider"]
    assert evidence["hardware"]["nucleos_logicos"] == os.cpu_count()
    assert evidence["hardware"]["sistema_operativo"]
    assert evidence["tiempos"]["filas"] == MIN_WARMUPS + 100
    assert "p50" in evidence["resumen"]["etapas"]["ms_inferencia"]
    assert "ms_total" in capsys.readouterr().out

    # El resumen sale exactamente de las filas exportadas.
    totals = [
        float(row["ms_total"])
        for row in rows
        if row["fase"] == "medicion" and row["valido"] == "True"
    ]
    assert evidence["resumen"]["etapas"]["ms_total"]["p95"] == pytest.approx(
        float(np.percentile(totals, 95))
    )


def test_cli_evidence_does_not_expose_local_paths(tmp_path, fake_weights):
    manifest = small_dataset(tmp_path)
    output = tmp_path / "salida"
    fake_weights(FakeSession())

    assert cli.main(arguments(manifest, output, "--repeticiones", "100")) == 0

    home = str(Path.home())
    for name in ("benchmark.json", "tiempos.csv"):
        text = (output / name).read_text(encoding="utf-8")
        assert str(tmp_path) not in text
        assert home not in text and home.replace("\\", "\\\\") not in text
        assert os.environ.get("USERNAME", "\0") not in text


@pytest.mark.parametrize(
    "extra",
    [
        ("--calentamientos", str(MIN_WARMUPS - 1)),
        ("--repeticiones", str(MIN_RUNS - 1)),
    ],
)
def test_cli_rejects_less_than_the_required_minimum(tmp_path, fake_weights, extra):
    fake_weights(FakeSession())
    output = tmp_path / "salida"

    with pytest.raises(SystemExit):
        cli.main(arguments(small_dataset(tmp_path), output, *extra))

    assert not output.exists()


def test_cli_never_replaces_previous_evidence(tmp_path, fake_weights):
    session = FakeSession()
    fake_weights(session)
    output = tmp_path / "salida"
    output.mkdir()
    (output / "tiempos.csv").write_text("anterior", encoding="utf-8")

    assert cli.main(arguments(small_dataset(tmp_path), output)) == 1

    assert (output / "tiempos.csv").read_text(encoding="utf-8") == "anterior"
    # Lo rechaza antes de medir, no despues de gastar la corrida.
    assert session.tensors == []


def test_cli_fails_without_enough_valid_runs_but_keeps_the_evidence(tmp_path, fake_weights):
    output = tmp_path / "salida"
    fake_weights(FakeSession(error=RuntimeError("boom")))

    code = cli.main(arguments(small_dataset(tmp_path), output, "--repeticiones", "100"))

    assert code == 1
    evidence = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
    assert evidence["resumen"]["mediciones_validas"] == 0
    assert evidence["resumen"]["cumple_minimos"] is False
    assert evidence["resumen"]["etapas"]["ms_total"]["n"] == 0
    assert evidence["resumen"]["etapas"]["ms_total"]["p50"] is None


def test_cli_rejects_weights_that_fail_verification(tmp_path):
    manifest = small_dataset(tmp_path)
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"not the real weights")
    output = tmp_path / "salida"

    code = cli.main(
        [
            "--manifest",
            str(manifest),
            "--output",
            str(output),
            "--weights",
            str(bad),
            "--policy-config",
            str(POLICY_CONFIG),
        ]
    )

    assert code == 1
    assert not output.exists()


def test_cli_checks_the_weights_before_measuring(tmp_path, monkeypatch):
    # El archivo no es el verificado, aunque la sesion pudiera cargarse.
    session = FakeSession()
    monkeypatch.setattr(YoloxDetector, "from_weights", lambda *_a, **_k: YoloxDetector(session))
    monkeypatch.setattr(cli, "check_images", lambda *_a, **_k: None)
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"not the real weights")
    output = tmp_path / "salida"
    args = arguments(small_dataset(tmp_path), output, "--weights", str(bad))

    assert cli.main(args) == 1

    assert not output.exists()
    assert session.tensors == []


def test_cli_checks_the_images_before_measuring(tmp_path, monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(YoloxDetector, "from_weights", lambda *_a, **_k: YoloxDetector(session))
    monkeypatch.setattr(cli, "verify_weights", lambda *_a, **_k: None)
    output = tmp_path / "salida"

    # Las imagenes de `small_dataset` ya no son las del congelamiento.
    assert cli.main(arguments(small_dataset(tmp_path), output)) == 1

    assert not output.exists()
    assert session.tensors == []


def test_cli_reports_a_package_with_missing_fields_at_startup(tmp_path, monkeypatch, caplog):
    session = FakeSession()
    monkeypatch.setattr(YoloxDetector, "from_weights", lambda *_a, **_k: YoloxDetector(session))
    monkeypatch.setattr(cli, "verify_weights", lambda *_a, **_k: None)
    manifest = small_dataset(tmp_path)
    captures = next(manifest.parent.glob("secuencias/*/capturas.jsonl"))
    lines = captures.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    del first["frame_id"]
    captures.write_text("\n".join([json.dumps(first), *lines[1:]]) + "\n", encoding="utf-8")
    output = tmp_path / "salida"

    assert cli.main(arguments(manifest, output)) == 1

    assert "benchmark_error stage=startup" in caplog.text
    assert not output.exists()
    assert session.tensors == []


def test_cli_fails_at_startup_if_the_conditions_cannot_be_collected(
    tmp_path, fake_weights, monkeypatch, caplog
):
    session = FakeSession()
    fake_weights(session)
    output = tmp_path / "salida"

    def missing(_name):
        raise PackageNotFoundError("opencv-python-headless")

    monkeypatch.setattr(cli, "version", missing)

    assert cli.main(arguments(small_dataset(tmp_path), output)) == 1

    assert "benchmark_error stage=startup" in caplog.text
    assert not output.exists()
    assert session.tensors == []


def test_commit_is_the_one_of_the_imported_code(tmp_path, monkeypatch):
    try:
        expected = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("copia sin repositorio de git, por ejemplo un ZIP")
    other = tmp_path / "otro"
    other.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=other, check=True)
    monkeypatch.chdir(other)

    assert cli.code_version()["commit"] == expected


def test_code_version_is_unknown_without_a_repository(monkeypatch):
    def no_repository(command, **_kwargs):
        raise subprocess.CalledProcessError(128, command)

    monkeypatch.setattr(cli.subprocess, "run", no_repository)

    assert cli.code_version() == {"commit": None, "cambios_sin_commit": None}


def test_untracked_code_counts_as_a_change_but_new_evidence_does_not(monkeypatch):
    calls = {}

    def fake_git(*arguments):
        calls[arguments] = True
        if arguments[0] == "rev-parse":
            return "abc"
        return "?? src/p5/nuevo.py" if "--" in arguments else ""

    monkeypatch.setattr(cli, "_git", fake_git)

    assert cli.code_version()["cambios_sin_commit"] is True
    untracked = next(call for call in calls if "--" in call)
    assert untracked[-1] == "../.."
    assert Path(cli.__file__).resolve().parents[2].name == "src"


def test_images_that_differ_from_the_manifest_are_rejected(tmp_path):
    manifest = small_dataset(tmp_path)  # Sus imagenes ya no son las del congelamiento.

    with pytest.raises(ValueError, match="SHA-256"):
        cli.check_images(manifest)
