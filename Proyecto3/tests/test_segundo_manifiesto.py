"""Segundo manifiesto congelado del release 0.1.3, con semilla 7 (F12; criterio 1.1).

Mismo release, otra semilla: cambian el hash y los conteos por particion, sin
fuga. Asi Training puede demostrar que elegir otro manifiesto cambia el split
(los releases 0.1.2, 0.1.4 y 0.1.5 tienen la misma huella que 0.1.3, asi que
solo la semilla lo cambia). En Git va el puntero de DVC; el contenido, en el
remote `prod`.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.data import api as releases_api
from p3.data import frozen, manifests_api, releases

MANIFESTS = Path(__file__).parents[1] / "data" / "manifests"
SEED_7 = "m-0.1.3-s7-1"
SEED_42 = "m-0.1.3-s42-1"
HASH_7 = "c7319207ae60b636e8ef45cd0a6f904e3c2b07755e9536fd2eded140a5089f01"
POINTER_MD5_7 = "82a38b4019bfecc9c25bcb12e98aa3d4.dir"


def test_el_segundo_manifiesto_esta_congelado_y_el_barrido_sigue_siendo_el_de_seed_42() -> None:
    assert frozen.FROZEN_MANIFESTS[SEED_7] == HASH_7
    assert frozen.FROZEN_MANIFESTS[SEED_42].startswith("45600f29")
    assert frozen.SWEEP_MANIFEST == SEED_42


def test_el_puntero_dvc_del_segundo_manifiesto_no_cambia() -> None:
    pointer = yaml.safe_load((MANIFESTS / f"{SEED_7}.dvc").read_text(encoding="utf-8"))
    [out] = pointer["outs"]
    assert (out["path"], out["md5"], out["nfiles"]) == (SEED_7, POINTER_MD5_7, 2)


def _downloaded(manifest_id: str) -> Path:
    folder = MANIFESTS / manifest_id
    if not (folder / "manifest.jsonl").is_file():
        pytest.skip("manifiestos no descargados (dvc pull)")
    return folder


def test_si_esta_descargado_cambia_el_hash_y_los_conteos_sin_fuga() -> None:
    seven, forty_two = _downloaded(SEED_7), _downloaded(SEED_42)
    assert hashlib.sha256((seven / "manifest.jsonl").read_bytes()).hexdigest() == HASH_7
    meta_7 = json.loads((seven / "manifest.meta.json").read_text(encoding="utf-8"))
    meta_42 = json.loads((forty_two / "manifest.meta.json").read_text(encoding="utf-8"))
    assert meta_7["seed"] == 7
    assert meta_7["release"]["release_id"] == "0.1.3"
    assert meta_7["counts"]["crops"] != meta_42["counts"]["crops"]
    with (seven / "manifest.jsonl").open(encoding="utf-8") as lines:
        rows = [json.loads(line) for line in lines]
    for field in ("crop_id", "source_image_id", "dup_group_id"):
        by_split = defaultdict(set)
        for row in rows:
            by_split[row["split"]].add(row[field])
        for a, b in itertools.combinations(("train", "val", "test"), 2):
            assert not by_split[a] & by_split[b], (field, a, b)


def test_post_manifests_con_semilla_7_devuelve_el_segundo_manifiesto() -> None:
    _downloaded(SEED_7)
    _downloaded(SEED_42)
    release = releases.Release.model_validate(
        {
            "version": "0.1.3",
            "created_at": "2026-09-18T04:17:13Z",
            "dataset_fingerprint": "f" * 64,
            "quality_report_fingerprint": "q" * 64,
            "quality_status": "pass",
            "archive_sha256": "a" * 64,
            "counts": {"images": 1, "annotations": 1, "categories": 1},
        }
    )
    app = FastAPI()
    app.include_router(manifests_api.router)
    app.dependency_overrides[releases_api.get_releases] = lambda: [release]
    app.dependency_overrides[manifests_api.get_manifests_dir] = lambda: MANIFESTS
    client = TestClient(app)
    seven = client.post("/api/p3/manifests", json={"release_id": "0.1.3", "seed": 7}).json()
    forty_two = client.post("/api/p3/manifests", json={"release_id": "0.1.3", "seed": 42}).json()
    assert (seven["manifest_id"], seven["manifest_hash"]) == (SEED_7, HASH_7)
    assert seven["manifest_hash"] != forty_two["manifest_hash"]
    assert seven["counts"] != forty_two["counts"]
