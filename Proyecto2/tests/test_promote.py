"""Promociones verificadas e idempotentes; ningun test usa AWS real."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import CheckResult, QualityTotals
from dataset_quality.models.versions import VersionsManifest
from dataset_quality.settings import get_settings
from dataset_quality.storage import file_sha256
from dataset_quality.tiers import promote, release
from dataset_quality.tiers.gate import dataset_fingerprint, evaluate


class MemoryS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts = 0
        self.fail_upload = False
        self.corrupt_upload = False

    def get_object(self, *, Bucket, Key):  # noqa: N803
        data = self.objects.get((Bucket, Key))
        if data is None:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(data)}

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch, **kwargs):  # noqa: N803
        assert IfNoneMatch == "*"
        if self.fail_upload:
            raise OSError("upload fallo")
        if (Bucket, Key) in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.puts += 1
        self.objects[Bucket, Key] = b"corrupto" if self.corrupt_upload else Body.read()


@pytest.fixture
def published(tmp_path, monkeypatch, env):
    get_settings.cache_clear()
    monkeypatch.setenv("PROD_BUCKET_RELEASES", "dataset-quality-releases-prod")
    dataset = CocoDataset.model_validate(
        {
            "images": [
                {"id": i, "file_name": f"{i}.jpg", "width": 100, "height": 100}
                for i in range(1, 601)
            ],
            "annotations": [
                {
                    "id": i,
                    "image_id": i,
                    "category_id": 1 if i <= 300 else 2,
                    "bbox": [0, 0, 100, 100],
                    "area": 10000,
                }
                for i in range(1, 601)
            ],
            "categories": [{"id": 1, "name": "dog"}, {"id": 2, "name": "person"}],
        }
    )
    coco = tmp_path / "annotations.coco.json"
    coco.write_text(dataset.model_dump_json())
    report = evaluate(
        [
            CheckResult(
                name="min_images_per_class",
                status="pass",
                severity="error",
                observed=300,
                threshold=300,
                message="dos clases con 300",
            ),
            CheckResult(
                name="small_objects",
                status="pass",
                severity="warning",
                observed=0,
                threshold=0.1,
                message="sin objetos pequenos",
            ),
        ],
        fingerprint=dataset_fingerprint(dataset),
        config_version=1,
        totals=QualityTotals(images=600, annotations=600, categories=2),
    )
    quality = tmp_path / "quality.json"
    quality.write_text(report.model_dump_json())
    splits = tmp_path / "splits.json"
    splits.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": datetime.now(UTC).isoformat(),
                "seed": 42,
                "ratios": {"train": 0.7, "val": 0.15, "test": 0.15},
                "counts": {"train": 600, "val": 0, "test": 0},
                "assignments": [{"image_id": i, "split": "train"} for i in range(1, 601)],
            }
        )
    )
    entry = release.build_entry(
        version="0.1.2",
        dataset_fingerprint=dataset_fingerprint(dataset),
        quality_report=report,
        quality_report_fingerprint=file_sha256(quality),
        splits_fingerprint=file_sha256(splits),
        bucket="dataset-releases",
        notes=None,
        quality_summary=release.summarize_quality(dataset, report),
        published_in=[release.publication("dev", "dataset-releases", "0.1.2")],
    )
    manifest = tmp_path / "versions.json"
    release.write_manifest(VersionsManifest(versions=[entry]), manifest)
    archive = release.build_archive(
        coco_path=coco,
        quality_path=quality,
        splits_path=splits,
        dest=tmp_path / "dataset.tar.zst",
    )
    client = MemoryS3()
    monkeypatch.setattr(release, "get_prod_s3_client", lambda profile=None: client)
    monkeypatch.setattr(release, "get_s3_client", lambda: pytest.fail("PROD no debe usar MinIO"))
    yield manifest, archive, client, entry, coco, quality, splits
    get_settings.cache_clear()


def test_promote_copia_los_mismos_bytes_y_conserva_la_version(published):
    manifest, archive, client, original, *_ = published
    promoted = promote.run("0.1.2", out=manifest, archive_path=archive)
    assert (
        client.objects[("dataset-quality-releases-prod", "0.1.2/dataset.tar.zst")]
        == archive.read_bytes()
    )
    assert [p.remote for p in promoted.published_in] == ["dev", "prod"]
    assert promoted.model_dump(exclude={"published_in"}) == original.model_dump(
        exclude={"published_in"}
    )
    assert len(release.load_manifest(manifest).versions) == 1


def test_repetir_promocion_verifica_y_no_duplica_registro(published):
    manifest, archive, client, *_ = published
    first = promote.run("0.1.2", out=manifest, archive_path=archive)
    before = manifest.read_bytes()
    second = promote.run("0.1.2", out=manifest, archive_path=archive)
    assert first == second
    assert manifest.read_bytes() == before
    assert client.puts == 1


@pytest.mark.parametrize("failure", ["upload", "checksum", "conflict"])
def test_un_fallo_no_registra_prod(published, failure):
    manifest, archive, client, *_ = published
    before = manifest.read_bytes()
    client.fail_upload = failure == "upload"
    client.corrupt_upload = failure == "checksum"
    if failure == "conflict":
        client.objects[("dataset-quality-releases-prod", "0.1.2/dataset.tar.zst")] = b"otro release"
    with pytest.raises((OSError, ValueError)):
        promote.run("0.1.2", out=manifest, archive_path=archive)
    assert manifest.read_bytes() == before


def test_dry_run_valida_sin_credenciales_ni_cambios(published, monkeypatch):
    manifest, archive, _, original, *_ = published
    before = manifest.read_bytes()
    monkeypatch.setattr(
        release, "get_prod_s3_client", lambda *a: pytest.fail("no debe acceder a AWS")
    )
    assert promote.run("0.1.2", out=manifest, archive_path=archive, dry_run=True) == original
    assert manifest.read_bytes() == before


def test_archivo_alterado_se_rechaza_antes_de_subir(published):
    manifest, archive, client, _, coco, quality, splits = published
    document = json.loads(coco.read_text())
    document["annotations"][0]["category_id"] = 2
    coco.write_text(json.dumps(document))
    release.build_archive(coco_path=coco, quality_path=quality, splits_path=splits, dest=archive)
    with pytest.raises(ValueError, match="huellas"):
        promote.run("0.1.2", out=manifest, archive_path=archive)
    assert client.puts == 0


def test_un_pass_con_umbral_temporal_no_es_promovible(published):
    manifest, archive, client, entry, coco, quality, splits = published
    document = json.loads(quality.read_text())
    document["checks"][0]["threshold"] = 150
    quality.write_text(json.dumps(document))
    entry = entry.model_copy(update={"quality_report_fingerprint": file_sha256(quality)})
    release.write_manifest(VersionsManifest(versions=[entry]), manifest)
    release.build_archive(coco_path=coco, quality_path=quality, splits_path=splits, dest=archive)
    with pytest.raises(ValueError, match="minimo de 300"):
        promote.run("0.1.2", out=manifest, archive_path=archive)
    assert client.puts == 0


def test_version_desconocida_no_accede_a_storage(published):
    manifest, _, client, *_ = published
    with pytest.raises(ValueError, match="desconocida"):
        promote.run("9.9.9", out=manifest)
    assert client.puts == 0


def test_el_sha256_del_archivo_completo_se_verifica(published):
    manifest, archive, client, entry, *_ = published
    entry = entry.model_copy(update={"archive_sha256": "0" * 64})
    release.write_manifest(VersionsManifest(versions=[entry]), manifest)
    with pytest.raises(ValueError, match="SHA-256"):
        promote.run("0.1.2", out=manifest, archive_path=archive)
    assert client.puts == 0


def test_299_imagenes_no_cumplen_aunque_el_reporte_diga_pass(published):
    manifest, archive, client, entry, coco, quality, splits = published
    document = json.loads(coco.read_text())
    document["annotations"][299]["category_id"] = 2
    coco.write_text(json.dumps(document))
    dataset = CocoDataset.model_validate(document)
    fingerprint = dataset_fingerprint(dataset)
    report = json.loads(quality.read_text())
    report["dataset_fingerprint"] = fingerprint
    quality.write_text(json.dumps(report))
    entry = entry.model_copy(
        update={
            "dataset_fingerprint": fingerprint,
            "quality_report_fingerprint": file_sha256(quality),
        }
    )
    release.write_manifest(VersionsManifest(versions=[entry]), manifest)
    release.build_archive(coco_path=coco, quality_path=quality, splits_path=splits, dest=archive)
    with pytest.raises(ValueError, match="dos clases"):
        promote.run("0.1.2", out=manifest, archive_path=archive)
    assert client.puts == 0
