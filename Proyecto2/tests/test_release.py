"""Frente 6 — versionado con DVC: `dq release` publica `versions.json`.

Ninguna prueba toca MinIO de verdad: `upload_archive` se sustituye por un
doble, igual que `test_ingest.py` hace con `upload_images`. Lo que se prueba
es la parte que no depende de la red: el auto-incremento de semver, el orden
cronologico que ya exige `VersionsManifest`, y que el archivo empaquetado sea
byte a byte el mismo para el mismo contenido.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset_quality.models.coco import load_coco
from dataset_quality.models.versions import VersionsManifest
from dataset_quality.storage import file_sha256
from dataset_quality.tiers import release as release_module
from dataset_quality.tiers.gate import dataset_fingerprint

FIXTURES = Path(__file__).parent / "fixtures"


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    coco_path = tmp_path / "annotations.coco.json"
    quality_path = tmp_path / "quality.json"
    splits_path = tmp_path / "splits.json"

    coco_path.write_text(
        json.dumps(
            {
                "images": [{"id": 1, "file_name": "a.jpg", "width": 10, "height": 10}],
                "annotations": [],
                "categories": [{"id": 1, "name": "car"}],
            }
        ),
        encoding="utf-8",
    )
    quality_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-16T00:00:00Z",
                "dataset_fingerprint": dataset_fingerprint(load_coco(coco_path)),
                "config_version": 1,
                "status": "pass",
                "exit_code": 0,
                "totals": {"images": 1, "annotations": 0, "categories": 1},
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    splits_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-16T00:00:00Z",
                "seed": 42,
                "ratios": {"train": 0.7, "val": 0.15, "test": 0.15},
                "counts": {"train": 1, "val": 0, "test": 0},
                "stratified_by": "category_id",
                "assignments": [{"image_id": 1, "split": "train"}],
            }
        ),
        encoding="utf-8",
    )
    return coco_path, quality_path, splits_path


# --------------------------------------------------------------------------
# Auto-incremento de semver
# --------------------------------------------------------------------------
def test_sin_historial_arranca_en_0_1_0() -> None:
    assert release_module.next_version(VersionsManifest(versions=[])) == "0.1.0"


def test_patch_bump_por_defecto() -> None:
    manifest = VersionsManifest.model_validate_json(
        (FIXTURES / "versions.json").read_text(encoding="utf-8")
    )
    assert release_module.next_version(manifest) == "0.1.1"


def test_minor_y_major_bump() -> None:
    manifest = VersionsManifest.model_validate_json(
        (FIXTURES / "versions.json").read_text(encoding="utf-8")
    )
    assert release_module.next_version(manifest, "minor") == "0.2.0"
    assert release_module.next_version(manifest, "major") == "1.0.0"


# --------------------------------------------------------------------------
# Empaquetado deterministico
# --------------------------------------------------------------------------
def test_el_mismo_contenido_da_el_mismo_archivo(tmp_path: Path) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)

    a = release_module.build_archive(
        coco_path=coco_path,
        quality_path=quality_path,
        splits_path=splits_path,
        dest=tmp_path / "a.tar.zst",
    )
    b = release_module.build_archive(
        coco_path=coco_path,
        quality_path=quality_path,
        splits_path=splits_path,
        dest=tmp_path / "b.tar.zst",
    )

    assert file_sha256(a) == file_sha256(b)


def test_los_permisos_locales_no_cambian_el_archivo(tmp_path: Path) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    a = release_module.build_archive(
        coco_path=coco_path,
        quality_path=quality_path,
        splits_path=splits_path,
        dest=tmp_path / "a.tar.zst",
    )
    coco_path.chmod(0o600)
    quality_path.chmod(0o600)
    b = release_module.build_archive(
        coco_path=coco_path,
        quality_path=quality_path,
        splits_path=splits_path,
        dest=tmp_path / "b.tar.zst",
    )
    assert file_sha256(a) == file_sha256(b)


def test_reportes_obsoletos_no_publican_otra_version(tmp_path: Path, monkeypatch) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    report = json.loads(quality_path.read_text())
    report["dataset_fingerprint"] = "0" * 64
    quality_path.write_text(json.dumps(report))
    monkeypatch.setattr(
        release_module, "upload_archive", lambda *a, **k: pytest.fail("no debe subir")
    )
    with pytest.raises(ValueError, match="no corresponden"):
        release_module.run(
            coco_path=coco_path,
            quality_report_path=quality_path,
            splits_path=splits_path,
            dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
            bucket="dataset-releases",
            out=tmp_path / "versions.json",
            archive_dir=tmp_path / "releases",
        )
    assert not (tmp_path / "versions.json").exists()


def test_splits_de_otras_imagenes_no_publican_otra_version(tmp_path: Path, monkeypatch) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    splits = json.loads(splits_path.read_text())
    splits["assignments"][0]["image_id"] = 999
    splits_path.write_text(json.dumps(splits))
    monkeypatch.setattr(
        release_module, "upload_archive", lambda *a, **k: pytest.fail("no debe subir")
    )
    with pytest.raises(ValueError, match="splits no corresponden"):
        release_module.run(
            coco_path=coco_path,
            quality_report_path=quality_path,
            splits_path=splits_path,
            dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
            bucket="dataset-releases",
            out=tmp_path / "versions.json",
            archive_dir=tmp_path / "releases",
        )


def test_contenido_distinto_da_huella_distinta(tmp_path: Path) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    a = release_module.build_archive(
        coco_path=coco_path,
        quality_path=quality_path,
        splits_path=splits_path,
        dest=tmp_path / "a.tar.zst",
    )

    quality_path.write_text(quality_path.read_text(encoding="utf-8").replace("pass", "fail"))
    b = release_module.build_archive(
        coco_path=coco_path,
        quality_path=quality_path,
        splits_path=splits_path,
        dest=tmp_path / "b.tar.zst",
    )

    assert file_sha256(a) != file_sha256(b)


# --------------------------------------------------------------------------
# `storage_uri` y fingerprints
# --------------------------------------------------------------------------
def test_storage_uri_es_s3_y_lleva_la_version() -> None:
    uri = release_module.storage_uri("dataset-releases", "0.2.0")
    assert uri == "s3://dataset-releases/0.2.0/dataset.tar.zst"


def test_run_produce_una_entrada_valida(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    subidas = []
    monkeypatch.setattr(
        release_module,
        "upload_archive",
        lambda path, bucket, version: subidas.append((path, bucket, version)),
    )

    result = release_module.run(
        coco_path=coco_path,
        quality_report_path=quality_path,
        splits_path=splits_path,
        dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
        bucket="dataset-releases",
        out=tmp_path / "versions.json",
        archive_dir=tmp_path / "releases",
    )

    assert result.entry.version == "0.1.0"
    assert result.entry.storage_uri == "s3://dataset-releases/0.1.0/dataset.tar.zst"
    assert result.entry.quality_status == "pass"
    assert len(result.entry.dataset_fingerprint) == 64
    assert len(result.entry.quality_report_fingerprint) == 64
    assert len(result.entry.splits_fingerprint) == 64
    assert result.entry.archive_sha256 == file_sha256(result.archive_path)
    assert result.entry.quality_summary.distinct_images_per_class == {"car": 0}
    assert subidas == [(result.archive_path, "dataset-releases", "0.1.0")]

    # El archivo escrito valida contra su propio contrato congelado.
    on_disk = VersionsManifest.model_validate_json(
        (tmp_path / "versions.json").read_text(encoding="utf-8")
    )
    assert [entry.version for entry in on_disk.versions] == ["0.1.0"]


# --------------------------------------------------------------------------
# En que remotes esta publicada cada version
# --------------------------------------------------------------------------
def test_publicar_registra_el_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`storage_uri` decia a que URI, pero no a que remote.

    Sin el nombre del remote la pantalla no puede distinguir una version que
    solo existe en el MinIO local de una promovida a S3.
    """
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    monkeypatch.setattr(release_module, "upload_archive", lambda *a, **k: None)

    result = release_module.run(
        coco_path=coco_path,
        quality_report_path=quality_path,
        splits_path=splits_path,
        dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
        bucket="dataset-releases",
        out=tmp_path / "versions.json",
        archive_dir=tmp_path / "releases",
    )

    assert [p.remote for p in result.entry.published_in] == ["dev"]
    assert result.entry.published_in[0].storage_uri == result.entry.storage_uri


def test_el_remote_se_puede_elegir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    monkeypatch.setattr(release_module, "upload_archive", lambda *a, **k: None)

    result = release_module.run(
        coco_path=coco_path,
        quality_report_path=quality_path,
        splits_path=splits_path,
        dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
        bucket="dataset-releases-prod",
        remote="prod",
        out=tmp_path / "versions.json",
        archive_dir=tmp_path / "releases",
    )

    assert [p.remote for p in result.entry.published_in] == ["prod"]


def test_si_la_subida_falla_no_queda_registrada_como_publicada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El registro del remote va DESPUES del upload, no antes."""
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)

    def explota(*a: object, **k: object) -> None:
        raise OSError("el bucket no responde")

    monkeypatch.setattr(release_module, "upload_archive", explota)
    out = tmp_path / "versions.json"

    with pytest.raises(OSError, match="el bucket no responde"):
        release_module.run(
            coco_path=coco_path,
            quality_report_path=quality_path,
            splits_path=splits_path,
            dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
            bucket="dataset-releases",
            out=out,
            archive_dir=tmp_path / "releases",
        )

    assert not out.exists()


def test_una_version_no_se_registra_dos_veces_en_el_mismo_remote() -> None:
    from dataset_quality.models.versions import DatasetVersion

    with pytest.raises(ValueError, match="dos veces en el mismo remote"):
        DatasetVersion.model_validate(
            {
                "version": "0.1.0",
                "created_at": "2026-09-16T00:00:00Z",
                "dataset_fingerprint": "a" * 64,
                "quality_report_fingerprint": "b" * 64,
                "splits_fingerprint": "c" * 64,
                "storage_uri": "s3://bucket/0.1.0/dataset.tar.zst",
                "quality_status": "pass",
                "counts": {"images": 1, "annotations": 1, "categories": 1},
                "published_in": [
                    {
                        "remote": "dev",
                        "storage_uri": "s3://bucket/0.1.0/dataset.tar.zst",
                        "published_at": "2026-09-16T00:00:00Z",
                    },
                    {
                        "remote": "dev",
                        "storage_uri": "s3://otro/0.1.0/dataset.tar.zst",
                        "published_at": "2026-09-17T00:00:00Z",
                    },
                ],
            }
        )


def test_las_entradas_viejas_se_leen_como_publicadas_en_dev(tmp_path: Path) -> None:
    """Retrocompatibilidad: un `versions.json` anterior a `published_in`.

    Hasta que existio el campo, `dq release` subia a un unico destino. Leerlas
    como "sin publicar" enseñaria en la pantalla que no estan en ningun lado,
    que es falso.
    """
    antiguo = {
        "schema_version": 1,
        "versions": [
            {
                "schema_version": 1,
                "version": "0.1.0",
                "created_at": "2026-09-16T00:00:00Z",
                "dataset_fingerprint": "a" * 64,
                "quality_report_fingerprint": "b" * 64,
                "splits_fingerprint": "c" * 64,
                "storage_uri": "s3://dataset-releases/0.1.0/dataset.tar.zst",
                "quality_status": "pass",
                "counts": {"images": 10, "annotations": 20, "categories": 2},
                "notes": None,
            }
        ],
    }
    path = tmp_path / "versions.json"
    path.write_text(json.dumps(antiguo), encoding="utf-8")

    manifest = release_module.load_manifest(path)
    publicada = manifest.versions[0].published_in

    assert [p.remote for p in publicada] == ["dev"]
    assert publicada[0].storage_uri == "s3://dataset-releases/0.1.0/dataset.tar.zst"


def test_dry_run_no_sube_ni_escribe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    monkeypatch.setattr(
        release_module,
        "upload_archive",
        lambda *a, **k: pytest.fail("no deberia subir nada en --dry-run"),
    )

    out = tmp_path / "versions.json"
    result = release_module.run(
        coco_path=coco_path,
        quality_report_path=quality_path,
        splits_path=splits_path,
        dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
        bucket="dataset-releases",
        out=out,
        archive_dir=tmp_path / "releases",
        upload=False,
    )

    assert result.entry.version == "0.1.0"
    assert not out.exists()
    # No se subio nada, asi que no hay ningun remote que registrar.
    assert result.entry.published_in == []


def test_segunda_publicacion_incrementa_sobre_el_registro_existente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    monkeypatch.setattr(release_module, "upload_archive", lambda *a, **k: None)
    out = tmp_path / "versions.json"

    first = release_module.run(
        coco_path=coco_path,
        quality_report_path=quality_path,
        splits_path=splits_path,
        dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
        bucket="dataset-releases",
        out=out,
        archive_dir=tmp_path / "releases",
    )
    second = release_module.run(
        coco_path=coco_path,
        quality_report_path=quality_path,
        splits_path=splits_path,
        dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
        bucket="dataset-releases",
        out=out,
        archive_dir=tmp_path / "releases",
    )

    assert first.entry.version == "0.1.0"
    assert second.entry.version == "0.1.1"

    on_disk = VersionsManifest.model_validate_json(out.read_text(encoding="utf-8"))
    assert [entry.version for entry in on_disk.versions] == ["0.1.0", "0.1.1"]


def test_version_explicita_anula_el_auto_incremento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    monkeypatch.setattr(release_module, "upload_archive", lambda *a, **k: None)

    result = release_module.run(
        coco_path=coco_path,
        quality_report_path=quality_path,
        splits_path=splits_path,
        dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
        bucket="dataset-releases",
        version="9.9.9",
        out=tmp_path / "versions.json",
        archive_dir=tmp_path / "releases",
    )

    assert result.entry.version == "9.9.9"


def test_version_duplicada_se_rechaza_al_escribir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)
    monkeypatch.setattr(release_module, "upload_archive", lambda *a, **k: None)
    out = tmp_path / "versions.json"

    release_module.run(
        coco_path=coco_path,
        quality_report_path=quality_path,
        splits_path=splits_path,
        dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
        bucket="dataset-releases",
        version="1.0.0",
        out=out,
        archive_dir=tmp_path / "releases",
    )

    with pytest.raises(ValueError, match="duplicada"):
        release_module.run(
            coco_path=coco_path,
            quality_report_path=quality_path,
            splits_path=splits_path,
            dataset_fingerprint=dataset_fingerprint(load_coco(coco_path)),
            bucket="dataset-releases",
            version="1.0.0",
            out=out,
            archive_dir=tmp_path / "releases",
        )


# --------------------------------------------------------------------------
# La compuerta de calidad bloquea `dq release`
# --------------------------------------------------------------------------
def test_cmd_release_falla_si_no_existe_quality_json(tmp_path: Path, monkeypatch) -> None:
    from dataset_quality import cli

    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["release", "--quality-report", "no_existe.json"])
    assert exit_code == 1


def test_cmd_release_falla_si_la_compuerta_esta_en_fail(tmp_path: Path, monkeypatch) -> None:
    from dataset_quality import cli

    monkeypatch.chdir(tmp_path)
    reporte = {
        "schema_version": 1,
        "generated_at": "2026-09-16T00:00:00Z",
        "dataset_fingerprint": "a" * 64,
        "config_version": 1,
        "status": "fail",
        "exit_code": 1,
        "totals": {"images": 1, "annotations": 1, "categories": 1},
        "checks": [
            {
                "name": "duplicates",
                "status": "fail",
                "severity": "error",
                "observed": 0.5,
                "threshold": 0.01,
                "message": "demasiados duplicados",
                "offenders": [],
            }
        ],
    }
    (tmp_path / "quality.json").write_text(json.dumps(reporte), encoding="utf-8")

    exit_code = cli.main(["release", "--quality-report", str(tmp_path / "quality.json")])
    assert exit_code == 1


def test_cmd_release_falla_si_no_existe_splits_json(tmp_path: Path, monkeypatch, env) -> None:
    from dataset_quality import cli
    from dataset_quality.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    reporte = {
        "schema_version": 1,
        "generated_at": "2026-09-16T00:00:00Z",
        "dataset_fingerprint": "a" * 64,
        "config_version": 1,
        "status": "pass",
        "exit_code": 0,
        "totals": {"images": 1, "annotations": 0, "categories": 1},
        "checks": [],
    }
    (tmp_path / "quality.json").write_text(json.dumps(reporte), encoding="utf-8")

    exit_code = cli.main(
        [
            "release",
            "--quality-report",
            str(tmp_path / "quality.json"),
            "--splits",
            str(tmp_path / "no_existe_splits.json"),
        ]
    )
    assert exit_code == 1


def test_cmd_release_force_ignora_la_compuerta_en_fail(tmp_path: Path, monkeypatch, env) -> None:
    from dataset_quality import cli
    from dataset_quality.settings import get_settings
    from dataset_quality.tiers import ingest as ingest_module
    from dataset_quality.tiers import release as release_cli_module

    get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)

    # `quality.json` en fail: solo debe pasar con --force.
    reporte = json.loads(quality_path.read_text(encoding="utf-8"))
    reporte["status"] = "fail"
    reporte["exit_code"] = 1
    reporte["checks"] = [
        {
            "name": "duplicates",
            "status": "fail",
            "severity": "error",
            "observed": 0.5,
            "threshold": 0.01,
            "message": "demasiados duplicados",
            "offenders": [],
        }
    ]
    quality_path.write_text(json.dumps(reporte), encoding="utf-8")

    images_dir = tmp_path / "raw_images"
    images_dir.mkdir()
    monkeypatch.setattr(ingest_module, "RAW_ANNOTATIONS", coco_path)
    monkeypatch.setattr(ingest_module, "RAW_IMAGES", images_dir)
    monkeypatch.setattr(release_cli_module, "upload_archive", lambda *a, **k: None)

    exit_code = cli.main(
        [
            "release",
            "--quality-report",
            str(quality_path),
            "--splits",
            str(splits_path),
            "--out",
            str(tmp_path / "versions.json"),
            "--force",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "versions.json").is_file()


def test_cmd_release_dry_run_no_escribe_versions_json(tmp_path: Path, monkeypatch, env) -> None:
    from dataset_quality import cli
    from dataset_quality.settings import get_settings
    from dataset_quality.tiers import ingest as ingest_module
    from dataset_quality.tiers import release as release_cli_module

    get_settings.cache_clear()
    monkeypatch.chdir(tmp_path)
    coco_path, quality_path, splits_path = _write_inputs(tmp_path)

    images_dir = tmp_path / "raw_images"
    images_dir.mkdir()
    monkeypatch.setattr(ingest_module, "RAW_ANNOTATIONS", coco_path)
    monkeypatch.setattr(ingest_module, "RAW_IMAGES", images_dir)
    monkeypatch.setattr(
        release_cli_module, "upload_archive", lambda *a, **k: pytest.fail("no deberia subir")
    )

    out = tmp_path / "versions.json"
    exit_code = cli.main(
        [
            "release",
            "--quality-report",
            str(quality_path),
            "--splits",
            str(splits_path),
            "--out",
            str(out),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert not out.exists()
