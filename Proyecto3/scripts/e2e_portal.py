"""Recorrido E2E real del portal contra MinIO + MLflow (F14 / 7.2).

Hace el flujo completo con infraestructura REAL (no en memoria): parte de un
release aprobado, entrena un trabajo corto en el experimento `p3-pruebas`
(queda un run en MLflow), evalua el checkpoint sobre el test en un directorio
temporal, publica la version en un MinIO de prueba, la activa y pide una
inferencia por HTTP a `POST /api/p3/inference`. Al final imprime la cadena de
IDs que ata todo (release -> manifiesto -> run -> version -> inferencia).

Se NIEGA a correr contra AWS: exige `P3_S3_ENDPOINT` apuntando a un MinIO local
y un `P3_MODELS_BUCKET` que no sea el de produccion (regla 14 de AGENTS.md).

Levanta el stack con `docker-compose.e2e.yml` y corre (ver docs/e2e_portal.md):

    cd Proyecto3
    docker compose -f docker-compose.e2e.yml up -d --build
    P3_S3_ENDPOINT=http://localhost:9100 P3_MODELS_BUCKET=p3-e2e \
      P3_MLFLOW_URL=http://localhost:5500 P3_INFERENCE_API=http://localhost:8010 \
      .venv/Scripts/python scripts/e2e_portal.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

PROYECTO3 = Path(__file__).resolve().parents[1]

# --- Guarda anti-AWS (pura e importable: la prueba la ejerce sin stack) -------

PROD_BUCKET = "dataset-quality-releases-750702272375"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "minio"})


class E2ERefusedError(RuntimeError):
    """El recorrido se niega a correr (apunta a AWS o al bucket de produccion)."""


def check_not_aws(endpoint: str | None, bucket: str | None) -> None:
    """Falla si no apunta claramente a un MinIO local con un bucket de prueba."""
    endpoint = (endpoint or "").strip()
    if not endpoint:
        raise E2ERefusedError(
            "P3_S3_ENDPOINT vacio: el recorrido E2E se niega a correr contra AWS. "
            "Apunta P3_S3_ENDPOINT a un MinIO de prueba (p. ej. http://localhost:9100)."
        )
    host = (urlparse(endpoint).hostname or "").lower()
    if host not in LOCAL_HOSTS and not host.endswith(".local"):
        raise E2ERefusedError(
            f"P3_S3_ENDPOINT={endpoint!r} no parece un MinIO local (host {host!r}); "
            "el E2E solo corre contra MinIO de prueba, nunca AWS."
        )
    if (bucket or "") == PROD_BUCKET:
        raise E2ERefusedError(
            f"P3_MODELS_BUCKET={bucket!r} es el bucket de PRODUCCION; "
            "el E2E usa un bucket de prueba (p. ej. p3-e2e)."
        )


def _env_config() -> dict[str, str]:
    return {
        "s3_endpoint": os.environ.get("P3_S3_ENDPOINT", ""),
        "s3_access_key": os.environ.get("P3_S3_ACCESS_KEY", "minioadmin"),
        "s3_secret_key": os.environ.get("P3_S3_SECRET_KEY", "minioadmin"),
        "bucket": os.environ.get("P3_MODELS_BUCKET", "p3-e2e"),
        "prefix": os.environ.get("P3_MODELS_PREFIX", "models/clasificador"),
        "mlflow_uri": os.environ.get("P3_MLFLOW_URL", "http://localhost:5500"),
        "inference_api": os.environ.get("P3_INFERENCE_API", "http://localhost:8010"),
        "region": os.environ.get("P3_AWS_REGION", "us-east-1"),
    }


def _predict(api: str, data: bytes, filename: str) -> dict:
    """POST multipart de una imagen a `/api/p3/inference` (como el navegador)."""
    boundary = uuid.uuid4().hex
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(
        f"{api}/api/p3/inference",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default="1.0.0", help="version del MODELO a publicar")
    parser.add_argument("--max-epochs", type=int, default=1, help="trabajo corto")
    parser.add_argument("--image-size", type=int, default=32)
    args = parser.parse_args()

    cfg = _env_config()
    try:
        check_not_aws(cfg["s3_endpoint"], cfg["bucket"])
    except E2ERefusedError as error:
        print(f"E2E RECHAZADO: {error}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(PROYECTO3 / "src"))
    import tempfile
    from datetime import UTC, datetime

    import boto3
    import yaml

    from p3.data import crops as crops_mod
    from p3.data import dataset
    from p3.data.split import (
        ManifestRelease,
        build_manifest,
        check_manifest,
        dup_group_ids,
        manifest_hash,
        manifest_jsonl,
    )
    from p3.eval import evaluate
    from p3.model.build import save_checkpoint
    from p3.registry.package import build_package
    from p3.registry.publish import publish_version
    from p3.registry.s3 import S3Store
    from p3.train.config import TrainingConfig
    from p3.train.tracking import RunContext, preprocessing_for, run_training

    fixture = PROYECTO3 / "tests" / "fixtures" / "p3"
    names = {2: "person", 3: "dog", 4: "cat"}
    class_index = {4: 0, 3: 1, 2: 2}
    class_names = ("cat", "dog", "person")
    release_id = "0.1.3"
    manifest_id = "m-0.1.3-s42-1"
    class_cfg = yaml.safe_load((PROYECTO3 / "config" / "classes.yaml").read_text("utf-8"))
    release_hash = class_cfg["dataset_fingerprint"]

    print(f"Recorrido E2E del portal contra MinIO ({cfg['s3_endpoint']}, bucket {cfg['bucket']}).")

    with tempfile.TemporaryDirectory(prefix="p3-e2e-") as tmp_str:
        tmp = Path(tmp_str)

        # 1) Release aprobado -> recortes (imagenes reales) -> manifiesto sin fuga.
        coco = json.loads((fixture / "annotations.coco.json").read_text(encoding="utf-8"))
        sizes = crops_mod.read_image_sizes(coco["images"], fixture / "images")
        valid = crops_mod.validate_annotations(coco, set(names), sizes).valid
        crops_dir = tmp / "crops" / release_id
        records = crops_mod.generate_crops(
            valid, fixture / "images", crops_dir, release_id=release_id
        )
        crops_jsonl = "".join(json.dumps(r.__dict__, default=list) + "\n" for r in records)
        (crops_dir / "crops.jsonl").write_text(crops_jsonl, encoding="utf-8")
        crops_sha = hashlib.sha256(crops_jsonl.encode("utf-8")).hexdigest()

        dup = dup_group_ids({img["id"] for img in coco["images"]}, [{25, 26}])
        rows = build_manifest(
            valid,
            release=ManifestRelease(release_id=release_id, dataset_fingerprint=release_hash),
            class_index=class_index,
            dup_groups=dup,
            seed=42,
        )
        if check_manifest(rows):
            raise SystemExit(f"El manifiesto tiene fugas: {check_manifest(rows)}")
        manifest_dir = tmp / "manifests" / manifest_id
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.jsonl").write_bytes(manifest_jsonl(rows).encode("utf-8"))
        m_hash = manifest_hash(rows)
        (manifest_dir / "manifest.meta.json").write_text(
            json.dumps({"manifest_id": manifest_id, "manifest_hash": m_hash}), encoding="utf-8"
        )
        print(f"  [1/6] manifiesto {manifest_id} ({m_hash[:16]}...), {len(rows)} recortes")

        # 2) Trabajo corto en p3-pruebas -> run REAL en MLflow.
        crop_index = dataset.load_crop_index(crops_dir)
        datasets = dataset.build_datasets(rows, crop_index, image_size=args.image_size)
        config = TrainingConfig.model_validate(
            {
                "optimizer": "adam",
                "batch_size": 4,
                "max_epochs": args.max_epochs,
                "learning_rate": 0.01,
                "image_size": args.image_size,
                "hidden_layers": [8],
                "dropout": 0.0,
                "seed": 42,
            }
        )
        context = RunContext(
            manifest_id=manifest_id,
            manifest_hash=m_hash,
            release_id=release_id,
            release_hash=release_hash,
            dvc_md5="e2e",
            crops_sha256=crops_sha,
            class_names=class_names,
            code_commit="e2e",
            code_dirty=True,
            job_id="e2e-portal",
        )
        result, run_id = run_training(
            config,
            datasets=datasets,
            context=context,
            device="cpu",
            pretrained=False,
            tracking_uri=cfg["mlflow_uri"],
            experiment="p3-pruebas",
        )
        print(f"  [2/6] run {run_id} en MLflow (p3-pruebas)")

        # 3) Checkpoint de la mejor epoca + selection.json de ese run.
        checkpoint = tmp / "model.pt"
        save_checkpoint(
            checkpoint,
            result.model.to("cpu"),
            class_names=class_names,
            hidden_layers=config.hidden_layers,
            dropout=config.dropout,
            preprocessing=preprocessing_for(config),
        )
        checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        selection_path = tmp / "selection.json"
        selection_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "manifest_id": manifest_id,
                    "manifest_hash": m_hash,
                    "checkpoint_sha256": checkpoint_sha,
                }
            ),
            encoding="utf-8",
        )

        # 4) Evaluacion del checkpoint sobre el test, en un directorio temporal.
        out_dir = tmp / "evaluation"
        metrics = evaluate.run_evaluation(
            selection_path=selection_path,
            checkpoint_path=checkpoint,
            manifest_dir=manifest_dir,
            crops_dir=crops_dir,
            out_dir=out_dir,
        )
        print(
            f"  [3/6] evaluacion: accuracy {metrics['accuracy']:.4f} "
            f"(test_size {metrics['test_size']})"
        )

        # 5) Publicacion en MinIO + activacion (misma ruta que produccion, otro bucket).
        run = {
            "run_id": run_id,
            "manifest_id": manifest_id,
            "manifest_hash": m_hash,
            "checkpoint_sha256": checkpoint_sha,
            "crops_jsonl_sha256": crops_sha,
            "val_accuracy": result.best_metrics["val_accuracy"],
            "best_epoch": result.best_epoch,
        }
        run_params = {
            key: (json.dumps(value) if isinstance(value, list) else str(value))
            for key, value in config.model_dump().items()
        }
        run_tags = {
            "release_id": release_id,
            "release_hash": release_hash,
            "dvc_md5": "e2e",
            "code_commit": "e2e",
            "crops_jsonl_sha256": crops_sha,
        }
        files = build_package(
            checkpoint=checkpoint.read_bytes(),
            run=run,
            selection=selection_path.read_bytes(),
            metrics=metrics,
            run_params=run_params,
            run_tags=run_tags,
            classes=class_cfg["classes"],
            version=args.version,
            requirements=(PROYECTO3 / "requirements.lock.txt").read_text("utf-8"),
            created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        store = S3Store(
            boto3.client(
                "s3",
                endpoint_url=cfg["s3_endpoint"],
                aws_access_key_id=cfg["s3_access_key"],
                aws_secret_access_key=cfg["s3_secret_key"],
                region_name=cfg["region"],
            )
        )
        registry = publish_version(
            store,
            bucket=cfg["bucket"],
            prefix=cfg["prefix"],
            version=args.version,
            files=files,
            activate=True,
        )
        print(f"  [4/6] publicado {args.version} en MinIO (activa: {registry.active_version})")

        # 6) Inferencia por HTTP contra el servicio p3-inference (lee de MinIO).
        test_rows = sorted((r for r in rows if r["split"] == "test"), key=lambda r: r["crop_id"])
        sample = crop_index[test_rows[0]["crop_id"]]
        answer = _predict(cfg["inference_api"], sample.read_bytes(), sample.name)
        print(f"  [5/6] inferencia {answer['inference_id']} -> {answer['predicted_class']}")
        if answer["model_sha256"] != checkpoint_sha:
            raise SystemExit(
                f"El servicio uso otro modelo ({answer['model_sha256']}), no el publicado "
                f"({checkpoint_sha})."
            )
        print("  [6/6] el servicio uso el modelo publicado (SHA-256 coincide)")

        print("\nCadena de IDs del recorrido E2E del portal:")
        print(f"  release_id:        {release_id}")
        print(f"  manifest_id:       {manifest_id}")
        print(f"  manifest_hash:     {m_hash}")
        print(f"  run_id (MLflow):   {run_id}  [experimento p3-pruebas]")
        print(f"  val_accuracy:      {result.best_metrics['val_accuracy']:.4f}")
        print(f"  checkpoint_sha256: {checkpoint_sha}")
        print(f"  test_accuracy:     {metrics['accuracy']:.4f} (test_size {metrics['test_size']})")
        print(f"  model_version:     {args.version}  [activa]")
        print(f"  inference_id:      {answer['inference_id']} -> {answer['predicted_class']}")
        print(
            f"  almacen:           {cfg['s3_endpoint']}/{cfg['bucket']}/{cfg['prefix']}  "
            "(MinIO de prueba, NO AWS)"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
