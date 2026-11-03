"""Prueba de integracion de extremo a extremo (F10 T26).

Recorre el flujo completo con IDs trazables sobre el fixture de 3 clases, todo
in-process (sin Docker/MLflow/MinIO reales): release -> recortes -> manifiesto
70/20/10 sin fuga -> entrenamiento corto (>=10 corridas) -> seleccion del
candidato por validacion -> evaluacion en test -> publicacion en un S3 falso ->
inferencia con la version activa. Al final imprime la cadena de IDs.

`test_e2e_release_a_manifiesto_sin_fuga` no necesita torch y corre siempre.
`test_e2e_flujo_completo` entrena de verdad: usa `importorskip('torch')`, asi que
en un entorno sin torch se salta y en CI (con el lockfile) corre. Es el job
`p3-e2e` de `p3-ci.yml`, separado por si conviene marcarlo lento.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from p3.data import crops as crops_mod
from p3.data.split import (
    ManifestRelease,
    build_manifest,
    check_manifest,
    dup_group_ids,
    manifest_counts,
    manifest_hash,
    manifest_jsonl,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p3"
# contratos section 1: category_id de COCO -> nombre y class_index (alfabetico).
NAMES = {2: "person", 3: "dog", 4: "cat"}
CLASS_INDEX = {4: 0, 3: 1, 2: 2}
CLASSES = ("cat", "dog", "person")
RELEASE_ID = "0.1.3"
RELEASE = ManifestRelease(release_id=RELEASE_ID, dataset_fingerprint="2200274d" + "0" * 56)
IMAGE_SIZE = 32
PREPROCESSING = {
    "image_size": IMAGE_SIZE,
    "resize": "resize_to_square",
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
}


def _valid_and_coco() -> tuple[list, dict]:
    coco = json.loads((FIXTURE / "annotations.coco.json").read_text(encoding="utf-8"))
    sizes = crops_mod.read_image_sizes(coco["images"], FIXTURE / "images")
    valid = crops_mod.validate_annotations(coco, set(NAMES), sizes).valid
    return valid, coco


def _manifest_rows(valid: list, coco: dict, seed: int = 42) -> list[dict]:
    dup = dup_group_ids({img["id"] for img in coco["images"]}, [{25, 26}])
    return build_manifest(
        valid, release=RELEASE, class_index=CLASS_INDEX, dup_groups=dup, seed=seed
    )


def test_e2e_release_a_manifiesto_sin_fuga(capsys: pytest.CaptureFixture[str]) -> None:
    valid, coco = _valid_and_coco()
    rows = _manifest_rows(valid, coco)

    assert check_manifest(rows) == []
    assert len(rows) == 28  # 10 cat + 9 dog + 9 person (contratos section 7)

    counts = manifest_counts(rows)
    with capsys.disabled():
        print("\nCadena de IDs E2E (release -> manifiesto):")
        print(f"  release_id: {RELEASE_ID}")
        print(f"  manifest_hash: {manifest_hash(rows)}")
        print(f"  recortes: {sum(sum(c.values()) for c in counts['crops'].values())}")

    # Reproducible: misma semilla y mismo release -> mismo hash (M3).
    assert manifest_hash(_manifest_rows(valid, coco)) == manifest_hash(rows)


def test_e2e_flujo_completo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("torch")

    from p3.data import dataset
    from p3.eval import evaluate
    from p3.inference import service
    from p3.model.build import save_checkpoint
    from p3.train import selection, trainer
    from p3.train.config import TrainingConfig

    # 1) Release -> recortes (imagenes reales) -> manifiesto sin fuga.
    valid, coco = _valid_and_coco()
    crops_dir = tmp_path / "crops" / RELEASE_ID
    records = crops_mod.generate_crops(valid, FIXTURE / "images", crops_dir, release_id=RELEASE_ID)
    (crops_dir / "crops.jsonl").write_text(
        "".join(json.dumps(r.__dict__, default=list) + "\n" for r in records), encoding="utf-8"
    )
    rows = _manifest_rows(valid, coco)
    assert check_manifest(rows) == []

    manifest_dir = tmp_path / "manifests" / "m-0.1.3-s42-1"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.jsonl").write_bytes(manifest_jsonl(rows).encode("utf-8"))
    m_hash = manifest_hash(rows)
    (manifest_dir / "manifest.meta.json").write_text(
        json.dumps({"manifest_id": "m-0.1.3-s42-1", "manifest_hash": m_hash}), encoding="utf-8"
    )

    # 2) Entrenamiento: >=10 corridas cortas en CPU sobre los recortes reales.
    crop_index = dataset.load_crop_index(crops_dir)
    datasets = dataset.build_datasets(rows, crop_index, image_size=IMAGE_SIZE)
    ckpts_dir = tmp_path / "ckpts"
    ckpts_dir.mkdir()
    runs: list[selection.RunSummary] = []
    for i in range(10):
        config = TrainingConfig.model_validate(
            {
                "optimizer": "adam",
                "batch_size": 4,
                "max_epochs": 1,
                "learning_rate": 0.01,
                "image_size": IMAGE_SIZE,
                "hidden_layers": [8],
                "dropout": 0.0,
                "seed": i + 1,
            }
        )
        result = trainer.train(
            config,
            train_set=datasets["train"],
            val_set=datasets["val"],
            num_classes=3,
            pretrained=False,
            device="cpu",
        )
        best = max(result.history, key=lambda h: (h["val_accuracy"], -h["val_loss"]))
        run_id = f"e2e-r{i}"
        ckpt = ckpts_dir / f"{run_id}.pt"
        save_checkpoint(
            ckpt,
            result.model,
            class_names=CLASSES,
            hidden_layers=config.hidden_layers,
            dropout=config.dropout,
            preprocessing=PREPROCESSING,
        )
        runs.append(
            selection.RunSummary(
                run_id=run_id,
                experiment_id="1",
                status="FINISHED",
                end_time=1000 + i,
                best_val_accuracy=best["val_accuracy"],
                best_val_loss=best["val_loss"],
                best_epoch=best["epoch"],
                stopped_epoch=len(result.history),
                manifest_id="m-0.1.3-s42-1",
                manifest_hash=m_hash,
                artifact_uri=f"mlflow-artifacts:/1/{run_id}/artifacts",
                params={"optimizer": "adam"},
                tags={},
            )
        )

    # 3) Seleccion del candidato por validacion (>=10 FINISHED sobre el manifiesto).
    winner = selection.select(runs, manifest_hash=m_hash)
    winner_ckpt = ckpts_dir / f"{winner.run_id}.pt"
    checkpoint_sha256 = hashlib.sha256(winner_ckpt.read_bytes()).hexdigest()

    selection_path = tmp_path / "selection.json"
    selection_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": winner.run_id,
                "manifest_id": "m-0.1.3-s42-1",
                "manifest_hash": m_hash,
                "checkpoint_sha256": checkpoint_sha256,
            }
        ),
        encoding="utf-8",
    )

    # 4) Evaluacion UNICA en el test congelado.
    report = evaluate.run_evaluation(
        selection_path=selection_path,
        checkpoint_path=winner_ckpt,
        manifest_dir=manifest_dir,
        crops_dir=crops_dir,
        out_dir=tmp_path / "evaluation",
    )
    assert report["test_size"] > 0
    metrics = json.loads((tmp_path / "evaluation" / "metrics.json").read_text(encoding="utf-8"))
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert metrics["manifest_hash"] == m_hash  # trazabilidad: mismo manifiesto

    # 5) Publicacion en un S3 falso (misma interfaz que el bucket real).
    class FakeStore:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], bytes] = {}

        def put(self, key: str, data: bytes) -> None:
            self.objects[("bucket-e2e", key)] = data

        def get_bytes(self, bucket: str, key: str, version_id: str | None = None) -> bytes:
            return self.objects[(bucket, key)]

    store = FakeStore()
    prefix = "models/clasificador"
    version = "1.0.0"
    model_bytes = winner_ckpt.read_bytes()
    store.put(f"{prefix}/{version}/model.pt", model_bytes)
    store.put(
        f"{prefix}/registry.json",
        json.dumps(
            {
                "schema_version": 1,
                "active_version": version,
                "versions": [
                    {
                        "version": version,
                        "run_id": winner.run_id,
                        "manifest_id": "m-0.1.3-s42-1",
                        "key": f"{prefix}/{version}/model.pt",
                        "sha256": hashlib.sha256(model_bytes).hexdigest(),
                        "s3_version_id": None,
                    }
                ],
            }
        ).encode(),
    )

    # 6) Inferencia con la version activa: probabilidades validas.
    import io

    from PIL import Image

    inference = service.InferenceService(store, bucket="bucket-e2e", prefix=prefix)
    buffer = io.BytesIO()
    Image.new("RGB", (48, 40), (200, 30, 30)).save(buffer, format="PNG")
    prediction = inference.predict(buffer.getvalue(), "image/png")
    assert prediction.model_version == version
    assert set(prediction.probabilities) == set(CLASSES)
    assert abs(sum(prediction.probabilities.values()) - 1.0) < 1e-4
    assert prediction.predicted_class in CLASSES

    # Cadena de IDs completa, trazable de punta a punta.
    with capsys.disabled():
        print("\nCadena de IDs E2E (flujo completo):")
        print(f"  release_id:        {RELEASE_ID}")
        print(f"  manifest_hash:     {m_hash}")
        print(f"  corridas:          {len(runs)}")
        print(f"  run_id candidato:  {winner.run_id}")
        print(f"  val_accuracy:      {winner.best_val_accuracy:.4f}")
        print(f"  checkpoint_sha256: {checkpoint_sha256[:16]}...")
        print(f"  test_accuracy:     {metrics['accuracy']:.4f} (test_size={report['test_size']})")
        print(f"  model_version:     {version}")
        print(f"  prediccion:        {prediction.predicted_class}")
