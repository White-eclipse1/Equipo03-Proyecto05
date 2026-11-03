"""Selector de release aprobado de P2 y lectura verificada de su COCO (F2 T05, 1.1 y M2).

El registro de releases es `Proyecto2/reports/versions.json`, el mismo que
escribe `dq release`. Solo un release con compuerta `pass` se puede usar; su
`dataset.tar.zst` se acepta solo si el SHA-256 del archivo y la huella del
COCO coinciden con lo registrado. Las pruebas arman releases con el fixture
de `tests/fixtures/p3/` empaquetado igual que `dataset_quality.tiers.release`.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
import zstandard
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.data import api, releases
from p3.data.releases import (
    Release,
    ReleaseIntegrityError,
    ReleaseNotApprovedError,
    ReleaseNotFoundError,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p3"
P2_VERSIONS = Path(__file__).parents[2] / "Proyecto2" / "reports" / "versions.json"
BUCKET = "bucket-de-prueba"


def fake_fingerprint(coco_bytes: bytes) -> str:
    """Huella canonica como la de P2 (sha256 del JSON con claves ordenadas)."""
    canonical = json.dumps(json.loads(coco_bytes), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_archive(coco: dict[str, Any], *, quality_status: str = "pass") -> bytes:
    """`dataset.tar.zst` con los tres miembros que empaqueta P2."""
    members = {
        "annotations.coco.json": json.dumps(coco).encode("utf-8"),
        "quality.json": json.dumps({"status": quality_status}).encode("utf-8"),
        "splits.json": b'{"assignments": []}',
    }
    raw = io.BytesIO()
    with (
        zstandard.ZstdCompressor().stream_writer(raw, closefd=False) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for name in sorted(members):
            info = tarfile.TarInfo(name)
            info.size = len(members[name])
            archive.addfile(info, io.BytesIO(members[name]))
    return raw.getvalue()


def entry(
    version: str,
    archive: bytes,
    coco: dict[str, Any],
    *,
    status: str = "pass",
    remotes: tuple[str, ...] = ("dev", "prod"),
) -> dict[str, Any]:
    """Una entrada de `versions.json` con la forma que escribe P2."""
    return {
        "schema_version": 1,
        "version": version,
        "created_at": "2026-09-18T04:17:13.000000Z",
        "dataset_fingerprint": fake_fingerprint(json.dumps(coco).encode("utf-8")),
        "quality_report_fingerprint": "q" * 64,
        "splits_fingerprint": "s" * 64,
        "storage_uri": f"s3://dataset-releases/{version}/dataset.tar.zst",
        "quality_status": status,
        "counts": {
            "images": len(coco["images"]),
            "annotations": len(coco["annotations"]),
            "categories": len(coco["categories"]),
        },
        "notes": None,
        "quality_summary": None,
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "published_in": [
            {
                "remote": remote,
                "storage_uri": f"s3://viejo-{remote}/{version}/dataset.tar.zst",
                "published_at": "2026-09-18T04:17:13.000000Z",
            }
            for remote in remotes
        ],
    }


@pytest.fixture(scope="module")
def coco_full() -> dict[str, Any]:
    return json.loads((FIXTURE / "annotations.coco.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def coco_sin_cat(coco_full: dict[str, Any]) -> dict[str, Any]:
    coco = copy.deepcopy(coco_full)
    coco["annotations"] = [a for a in coco["annotations"] if a["category_id"] != 4]
    return coco


@pytest.fixture
def registry(tmp_path: Path, coco_full: dict[str, Any], coco_sin_cat: dict[str, Any]):
    """versions.json de prueba + los archivos de cada release en un bucket en memoria."""
    full, sin_cat = build_archive(coco_full), build_archive(coco_sin_cat)
    objects = {"1.0.0/dataset.tar.zst": full, "1.1.0/dataset.tar.zst": sin_cat}
    versions = {
        "schema_version": 1,
        "versions": [
            entry("0.9.0", full, coco_full, status="fail", remotes=("dev",)),
            entry("1.0.0", full, coco_full),
            entry("1.1.0", sin_cat, coco_sin_cat),
            entry("1.2.0", full, coco_full, remotes=("dev",)),
        ],
    }
    path = tmp_path / "versions.json"
    path.write_text(json.dumps(versions), encoding="utf-8")
    return path, objects


# --- Registro de releases -------------------------------------------------------------------


def test_lee_el_registro_real_de_p2() -> None:
    loaded = releases.load_releases(P2_VERSIONS)
    by_id = {r.release_id: r for r in loaded}
    assert by_id["0.1.0"].quality_status == "fail"
    assert by_id["0.1.3"].quality_status == "pass"
    assert by_id["0.1.3"].archive_sha256 == (
        "787742988af1df41d9a58573b81b5c9b4fe7ab24a647b25f2e71d3eb323838b5"
    )
    assert "prod" in by_id["0.1.3"].published_in


def test_solo_lista_releases_con_compuerta_aprobada(registry) -> None:
    path, _ = registry
    approved = releases.approved_releases(releases.load_releases(path))
    assert [r.release_id for r in approved] == ["1.0.0", "1.1.0", "1.2.0"]


def test_conserva_version_hash_y_referencia_de_calidad(registry) -> None:
    path, _ = registry
    release = releases.get_approved_release(releases.load_releases(path), "1.0.0")
    assert isinstance(release, Release)
    assert release.release_id == "1.0.0"
    assert len(release.dataset_fingerprint) == 64
    assert release.quality_report_fingerprint == "q" * 64
    assert release.archive_sha256 is not None


def test_release_con_compuerta_fallida_no_se_puede_usar(registry) -> None:
    path, _ = registry
    with pytest.raises(ReleaseNotApprovedError, match=r"0\.9\.0"):
        releases.get_approved_release(releases.load_releases(path), "0.9.0")


def test_release_inexistente(registry) -> None:
    path, _ = registry
    with pytest.raises(ReleaseNotFoundError, match=r"7\.7\.7"):
        releases.get_approved_release(releases.load_releases(path), "7.7.7")


def test_llave_del_archivo_en_el_bucket_de_releases() -> None:
    assert releases.archive_key("0.1.3") == "0.1.3/dataset.tar.zst"
    assert releases.archive_uri(BUCKET, "0.1.3") == f"s3://{BUCKET}/0.1.3/dataset.tar.zst"


# --- Lectura verificada del archivo del release --------------------------------------------


def test_abre_el_coco_del_release_y_verifica_hash_y_huella(registry, coco_full) -> None:
    path, objects = registry
    release = releases.get_approved_release(releases.load_releases(path), "1.0.0")
    content = releases.open_release_archive(
        release, objects["1.0.0/dataset.tar.zst"], fingerprint=fake_fingerprint
    )
    assert content.release == release
    assert content.coco == coco_full
    assert content.quality == {"status": "pass"}


def test_rechaza_un_archivo_con_sha256_distinto(registry) -> None:
    path, objects = registry
    release = releases.get_approved_release(releases.load_releases(path), "1.0.0")
    with pytest.raises(ReleaseIntegrityError, match="SHA-256"):
        releases.open_release_archive(
            release, objects["1.1.0/dataset.tar.zst"], fingerprint=fake_fingerprint
        )


def test_rechaza_un_coco_cuya_huella_no_es_la_del_release(registry) -> None:
    path, objects = registry
    release = releases.get_approved_release(releases.load_releases(path), "1.0.0")
    with pytest.raises(ReleaseIntegrityError, match="huella"):
        releases.open_release_archive(
            release, objects["1.0.0/dataset.tar.zst"], fingerprint=lambda _: "0" * 64
        )


def test_rechaza_un_release_sin_archive_sha256(registry) -> None:
    path, objects = registry
    release = releases.get_approved_release(releases.load_releases(path), "1.0.0")
    sin_hash = release.model_copy(update={"archive_sha256": None})
    with pytest.raises(ReleaseIntegrityError, match="archive_sha256"):
        releases.open_release_archive(
            sin_hash, objects["1.0.0/dataset.tar.zst"], fingerprint=fake_fingerprint
        )


def test_rechaza_un_archivo_cuyo_reporte_de_calidad_no_dice_pass(coco_full) -> None:
    archive = build_archive(coco_full, quality_status="fail")
    release = Release.model_validate(entry("1.0.0", archive, coco_full))
    with pytest.raises(ReleaseIntegrityError, match=r"quality\.json"):
        releases.open_release_archive(release, archive, fingerprint=fake_fingerprint)


def test_cambiar_de_release_cambia_los_conteos(registry) -> None:
    path, objects = registry
    loaded = releases.load_releases(path)
    counts = {}
    for release_id in ("1.0.0", "1.1.0"):
        release = releases.get_approved_release(loaded, release_id)
        content = releases.open_release_archive(
            release, objects[releases.archive_key(release_id)], fingerprint=fake_fingerprint
        )
        counts[release_id] = releases.coco_counts(content.coco)
    assert counts["1.0.0"]["annotations"] == 31
    assert counts["1.1.0"]["annotations"] < counts["1.0.0"]["annotations"]
    assert counts["1.0.0"]["annotations_per_category"]["cat"] > 0
    assert "cat" not in counts["1.1.0"]["annotations_per_category"]


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def client(registry) -> TestClient:
    path, _ = registry
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_releases] = lambda: releases.load_releases(path)
    app.dependency_overrides[api.get_releases_bucket] = lambda: BUCKET
    return TestClient(app)


def test_get_releases_aprobados_con_la_forma_del_contrato(client: TestClient) -> None:
    response = client.get("/api/p3/releases", params={"approved": "true"})
    assert response.status_code == 200
    body = response.json()
    assert [r["release_id"] for r in body["releases"]] == ["1.0.0", "1.1.0", "1.2.0"]
    first = body["releases"][0]
    assert set(first) == {
        "release_id",
        "dataset_fingerprint",
        "quality_status",
        "created_at",
        "counts",
        "storage_uri",
        "published_in",
        "trainable",
        "blocked_reason",
        "manifests",
    }
    assert first["quality_status"] == "pass"
    assert first["counts"] == {"images": 30, "annotations": 31, "categories": 3}


def test_storage_uri_apunta_al_bucket_configurado_si_esta_en_prod(client: TestClient) -> None:
    body = client.get("/api/p3/releases", params={"approved": "true"}).json()
    by_id = {r["release_id"]: r for r in body["releases"]}
    assert by_id["1.0.0"]["storage_uri"] == f"s3://{BUCKET}/1.0.0/dataset.tar.zst"
    assert by_id["1.0.0"]["published_in"] == ["dev", "prod"]
    # Publicado solo en el MinIO local de quien lo genero: no hay URI recuperable.
    assert by_id["1.2.0"]["storage_uri"] is None
    assert by_id["1.2.0"]["published_in"] == ["dev"]


def test_get_releases_sin_filtro_incluye_los_fallidos(client: TestClient) -> None:
    body = client.get("/api/p3/releases").json()
    assert "0.9.0" in [r["release_id"] for r in body["releases"]]


def test_get_release_aprobado_incluye_la_procedencia(client: TestClient) -> None:
    response = client.get("/api/p3/releases/1.0.0")
    assert response.status_code == 200
    body = response.json()
    assert body["quality_report_fingerprint"] == "q" * 64
    assert len(body["archive_sha256"]) == 64


def test_get_release_con_compuerta_fallida_responde_409(client: TestClient) -> None:
    response = client.get("/api/p3/releases/0.9.0")
    assert response.status_code == 409
    assert "0.9.0" in response.json()["detail"]
    assert "compuerta" in response.json()["detail"]


def test_get_release_inexistente_responde_404(client: TestClient) -> None:
    response = client.get("/api/p3/releases/7.7.7")
    assert response.status_code == 404
