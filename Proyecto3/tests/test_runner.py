"""El worker procesa trabajos fuera del request HTTP (F1 T02, criterio 6.1)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from p3.worker import jobs, runner

Report = Callable[[float, str], None]


def test_sin_trabajos_run_once_devuelve_false(session_factory: sessionmaker[Session]) -> None:
    assert runner.run_once(session_factory, "w1", runner.HANDLERS) is False


def test_dummy_termina_en_succeeded_con_progreso_completo(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="dummy", config={"steps": 3, "seconds": 0})

    assert runner.run_once(session_factory, "w1", runner.HANDLERS) is True

    with session_factory() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.SUCCEEDED
        assert stored.progress == 1.0
        assert len(jobs.log_lines(stored)) >= 3


def test_un_handler_que_falla_deja_el_error_y_no_tumba_al_worker(
    session_factory: sessionmaker[Session],
) -> None:
    def explota(config: dict[str, Any], report: Report) -> None:
        report(0.25, "empezando")
        raise RuntimeError("boom")

    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="explota", config={})

    assert runner.run_once(session_factory, "w1", {"explota": explota}) is True

    with session_factory() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.FAILED
        assert stored.error == "RuntimeError: boom"
        assert stored.progress == 0.25


def test_un_tipo_sin_handler_falla_con_mensaje(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="desconocido", config={})

    runner.run_once(session_factory, "w1", runner.HANDLERS)

    with session_factory() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.FAILED
        assert stored.error is not None and "desconocido" in stored.error


def test_dummy_con_fail_simula_un_error(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="dummy", config={"steps": 2, "seconds": 0, "fail": True})

    runner.run_once(session_factory, "w1", runner.HANDLERS)

    with session_factory() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.FAILED
        assert stored.error is not None and "simulado" in stored.error


def test_un_trabajo_train_reporta_progreso_por_epoca(
    session_factory: sessionmaker[Session], tmp_path, monkeypatch
) -> None:
    import hashlib
    import json

    from PIL import Image

    crops = tmp_path / "crops" / "9.9.9"
    manifest = tmp_path / "manifests" / "m-prueba"
    crops.mkdir(parents=True)
    manifest.mkdir(parents=True)
    rows, index = [], []
    for i in range(9):
        Image.new("RGB", (40, 32), ((i % 3) * 100, 50, 200)).save(crops / f"c{i}.png")
        rows.append(
            {
                "crop_id": f"9.9.9:a{i}",
                "source_image_id": i,
                "dup_group_id": f"g{i}",
                "class_index": i % 3,
                "release_id": "9.9.9",
                "split": "train" if i < 6 else "val",
            }
        )
        index.append({"crop_id": f"9.9.9:a{i}", "crop_path": f"c{i}.png"})
    contenido = "".join(json.dumps(r) + "\n" for r in rows)
    (manifest / "manifest.jsonl").write_text(contenido, newline="\n")
    digest = hashlib.sha256(contenido.encode("utf-8")).hexdigest()
    meta = {
        "manifest_id": "m-prueba",
        "manifest_hash": digest,
        "release": {
            "release_id": "9.9.9",
            "dataset_fingerprint": "f" * 64,
            "dvc_pointer": {"md5": "e" * 32 + ".dir"},
        },
        "classes": [
            {"class_index": 0, "category_name": "cat"},
            {"class_index": 1, "category_name": "dog"},
            {"class_index": 2, "category_name": "person"},
        ],
    }
    (manifest / "manifest.meta.json").write_text(json.dumps(meta))
    (crops / "crops.jsonl").write_text("".join(json.dumps(r) + "\n" for r in index))
    training = {
        "optimizer": "sgd",
        "batch_size": 3,
        "max_epochs": 2,
        "learning_rate": 0.01,
        "image_size": 32,
        "hidden_layers": [],
        "dropout": 0.0,
    }
    with session_factory.begin() as session:
        job = jobs.enqueue(
            session, kind="train", config={"manifest_id": "m-prueba", "training": training}
        )

    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    handler = runner.make_train_handler(
        data_dir=tmp_path,
        device="cpu",
        pretrained=False,
        tracking_uri=(tmp_path / "mlruns").as_uri(),
        code_commit="0" * 40,
        frozen={"m-prueba": digest},
    )
    runner.run_once(session_factory, "w1", {"train": handler})

    with session_factory() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.SUCCEEDED, stored.error
        logs = " ".join(jobs.log_lines(stored))
        assert "epoca 1/2" in logs and "epoca 2/2" in logs
        assert stored.mlflow_run_id is not None
        assert stored.mlflow_run_id in logs

    from mlflow.tracking import MlflowClient

    run = MlflowClient((tmp_path / "mlruns").as_uri()).get_run(stored.mlflow_run_id)
    esperado = hashlib.sha256((crops / "crops.jsonl").read_bytes()).hexdigest()
    assert run.data.tags["crops_jsonl_sha256"] == esperado


def test_train_con_manifiesto_no_congelado_falla_sin_entrenar(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    (tmp_path / "manifests" / "m-otro").mkdir(parents=True)
    (tmp_path / "manifests" / "m-otro" / "manifest.jsonl").write_text("{}\n")
    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="train", config={"manifest_id": "m-otro", "training": {}})

    handler = runner.make_train_handler(
        data_dir=tmp_path, device="cpu", pretrained=False, tracking_uri="", frozen={}
    )
    runner.run_once(session_factory, "w1", {"train": handler})

    with session_factory() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.FAILED
        assert "no esta congelado" in (stored.error or "")
