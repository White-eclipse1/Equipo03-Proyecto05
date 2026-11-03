"""API de manifiestos para la pagina Training (F3, contratos §4; criterios 3.1, 6.1 y M3).

`POST /api/p3/manifests` no crea manifiestos nuevos: el worker solo entrena con
los congelados (`p3.data.frozen`), asi que devuelve el congelado de ese release y
esa semilla tras comprobar sus bytes. Es idempotente. Generar uno nuevo es
`scripts/generate_manifest.py` y congelarlo entra por PR.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.data import api as releases_api
from p3.data import manifests_api, releases

PROYECTO3 = Path(__file__).parents[1]
COUNTS = {
    "crops": {
        "train": {"cat": 7, "dog": 6, "person": 6},
        "val": {"cat": 2, "dog": 2, "person": 2},
        "test": {"cat": 1, "dog": 1, "person": 1},
    },
    "originals": {
        "train": {"cat": 7, "dog": 6, "person": 5},
        "val": {"cat": 2, "dog": 2, "person": 2},
        "test": {"cat": 1, "dog": 1, "person": 1},
    },
}


def release_entry(version: str, status: str = "pass") -> dict[str, Any]:
    return {
        "version": version,
        "created_at": "2026-09-18T04:17:13Z",
        "dataset_fingerprint": "f" * 64,
        "quality_report_fingerprint": "q" * 64,
        "quality_status": status,
        "archive_sha256": "a" * 64,
        "counts": {"images": 28, "annotations": 28, "categories": 3},
        "published_in": [],
    }


def write_manifest(
    folder: Path, manifest_id: str, release_id: str, seed: int, body: bytes = b'{"crop_id": 1}\n'
) -> str:
    """Escribe `manifest.jsonl` y su meta como `scripts/generate_manifest.py`; devuelve el hash."""
    target = folder / manifest_id
    target.mkdir(parents=True)
    (target / "manifest.jsonl").write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    meta = {
        "schema_version": 1,
        "manifest_id": manifest_id,
        "manifest_hash": digest,
        "release": {"release_id": release_id},
        "seed": seed,
        "counts": COUNTS,
    }
    (target / "manifest.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return digest


@pytest.fixture
def setup(tmp_path: Path):
    versions = {
        "schema_version": 1,
        "versions": [
            release_entry("0.9.0", status="fail"),
            release_entry("1.0.0"),
            release_entry("1.1.0"),
            release_entry("1.2.0"),
        ],
    }
    registry = tmp_path / "versions.json"
    registry.write_text(json.dumps(versions), encoding="utf-8")
    folder = tmp_path / "manifests"
    folder.mkdir()
    frozen = {"m-1.0.0-s42-1": write_manifest(folder, "m-1.0.0-s42-1", "1.0.0", 42)}
    # Congelado pero sin `dvc pull`: esta en la lista, no en disco.
    frozen["m-1.2.0-s42-1"] = "b" * 64
    # En disco pero NO congelado (un manifiesto de prueba generado a mano).
    write_manifest(folder, "m-1.1.0-s42-1", "1.1.0", 42)

    app = FastAPI()
    app.include_router(manifests_api.router)
    app.dependency_overrides[releases_api.get_releases] = lambda: releases.load_releases(registry)
    app.dependency_overrides[manifests_api.get_manifests_dir] = lambda: folder
    app.dependency_overrides[manifests_api.get_frozen] = lambda: frozen
    return TestClient(app), folder, frozen


# --- POST /api/p3/manifests ----------------------------------------------------------------


def test_devuelve_el_manifiesto_congelado_con_la_forma_del_contrato(setup) -> None:
    client, _, frozen = setup
    answer = client.post("/api/p3/manifests", json={"release_id": "1.0.0", "seed": 42})
    assert answer.status_code == 201
    assert answer.json() == {
        "manifest_id": "m-1.0.0-s42-1",
        "manifest_hash": frozen["m-1.0.0-s42-1"],
        "counts": COUNTS,
    }


def test_es_idempotente_y_no_escribe_nada(setup) -> None:
    client, folder, _ = setup
    before = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))
    first = client.post("/api/p3/manifests", json={"release_id": "1.0.0", "seed": 42}).json()
    second = client.post("/api/p3/manifests", json={"release_id": "1.0.0", "seed": 42}).json()
    assert first == second
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) == before


def test_release_con_compuerta_fallida_responde_409(setup) -> None:
    client, _, _ = setup
    answer = client.post("/api/p3/manifests", json={"release_id": "0.9.0", "seed": 42})
    assert answer.status_code == 409
    assert "compuerta" in answer.json()["detail"]


def test_release_inexistente_responde_404(setup) -> None:
    client, _, _ = setup
    answer = client.post("/api/p3/manifests", json={"release_id": "7.7.7", "seed": 42})
    assert answer.status_code == 404


def test_sin_manifiesto_congelado_para_esa_semilla_responde_409(setup) -> None:
    client, _, _ = setup
    answer = client.post("/api/p3/manifests", json={"release_id": "1.0.0", "seed": 7})
    assert answer.status_code == 409
    assert "congelado" in answer.json()["detail"]


def test_un_manifiesto_en_disco_pero_no_congelado_no_se_ofrece(setup) -> None:
    client, _, _ = setup
    answer = client.post("/api/p3/manifests", json={"release_id": "1.1.0", "seed": 42})
    assert answer.status_code == 409
    assert "congelado" in answer.json()["detail"]


def test_congelado_sin_descargar_responde_503_con_dvc_pull(setup) -> None:
    client, _, _ = setup
    answer = client.post("/api/p3/manifests", json={"release_id": "1.2.0", "seed": 42})
    assert answer.status_code == 503
    assert "dvc pull" in answer.json()["detail"]


def test_bytes_distintos_al_congelado_responde_409(setup) -> None:
    client, folder, _ = setup
    (folder / "m-1.0.0-s42-1" / "manifest.jsonl").write_bytes(b'{"crop_id": 2}\n')
    answer = client.post("/api/p3/manifests", json={"release_id": "1.0.0", "seed": 42})
    assert answer.status_code == 409
    assert "SHA-256" in answer.json()["detail"]


def test_meta_de_otro_release_no_se_acepta(setup) -> None:
    # El id dice 1.0.0 pero el meta dice otro release: no se sirve.
    client, folder, _ = setup
    meta_path = folder / "m-1.0.0-s42-1" / "manifest.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["release"]["release_id"] = "1.1.0"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    answer = client.post("/api/p3/manifests", json={"release_id": "1.0.0", "seed": 42})
    assert answer.status_code == 409


@pytest.mark.parametrize(
    "body", [{"release_id": "1.0.0"}, {"seed": 42}, {"release_id": "1.0.0", "seed": "x"}]
)
def test_cuerpo_invalido_responde_422(setup, body: dict[str, Any]) -> None:
    client, _, _ = setup
    assert client.post("/api/p3/manifests", json=body).status_code == 422


# --- GET /api/p3/manifests/{manifest_id} ---------------------------------------------------


def test_get_devuelve_el_meta_completo(setup) -> None:
    client, folder, _ = setup
    answer = client.get("/api/p3/manifests/m-1.0.0-s42-1")
    assert answer.status_code == 200
    expected = json.loads((folder / "m-1.0.0-s42-1" / "manifest.meta.json").read_text("utf-8"))
    assert answer.json() == expected


def test_get_inexistente_responde_404(setup) -> None:
    client, _, _ = setup
    assert client.get("/api/p3/manifests/m-3.0.0-s42-1").status_code == 404


def test_get_no_sale_de_la_carpeta_de_manifiestos(setup) -> None:
    client, _, _ = setup
    assert client.get("/api/p3/manifests/..%2Fversions.json").status_code in (404, 422)
    assert client.get("/api/p3/manifests/..").status_code in (404, 422)


# --- El manifiesto real ---------------------------------------------------------------------


def test_el_manifiesto_real_congelado_se_sirve_para_0_1_3_y_semilla_42() -> None:
    folder = PROYECTO3 / "data" / "manifests"
    if not (folder / "m-0.1.3-s42-1" / "manifest.jsonl").is_file():
        pytest.skip("manifiesto no descargado (dvc pull)")
    app = FastAPI()
    app.include_router(manifests_api.router)
    app.dependency_overrides[releases_api.get_releases] = lambda: [
        releases.Release.model_validate(release_entry("0.1.3"))
    ]
    app.dependency_overrides[manifests_api.get_manifests_dir] = lambda: folder
    answer = TestClient(app).post("/api/p3/manifests", json={"release_id": "0.1.3", "seed": 42})
    assert answer.status_code == 201
    body = answer.json()
    assert body["manifest_id"] == "m-0.1.3-s42-1"
    assert body["manifest_hash"].startswith("45600f29")
    assert sum(sum(c.values()) for c in body["counts"]["crops"].values()) == 1459
