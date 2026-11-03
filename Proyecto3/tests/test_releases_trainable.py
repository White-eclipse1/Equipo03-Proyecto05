"""Que releases aprobados se pueden entrenar (F2 T05; criterios 1.1 y 6.1).

`GET /api/p3/releases` dice por release si se puede entrenar (`trainable`) y,
si no, por que (`blocked_reason`), para que Training deshabilite los demas con
su motivo a la vista. No se puede entrenar un release sin `archive_sha256` (su
archivo no se puede verificar) ni uno sin manifiesto congelado con semilla 42
(el worker solo entrena con los de `p3.data.frozen`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.data import api, releases

PROYECTO2 = Path(__file__).parents[2] / "Proyecto2"
FROZEN = {"m-0.1.3-s42-1": "4" * 64}


def entry(version: str, *, sha: str | None = "a" * 64, status: str = "pass") -> dict[str, Any]:
    return {
        "version": version,
        "created_at": "2026-09-18T04:17:13Z",
        "dataset_fingerprint": "f" * 64,
        "quality_report_fingerprint": "q" * 64,
        "quality_status": status,
        "archive_sha256": sha,
        "counts": {"images": 28, "annotations": 28, "categories": 3},
        "published_in": [],
    }


def client_with(versions: list[dict[str, Any]], frozen: dict[str, str], tmp_path: Path):
    registry = tmp_path / "versions.json"
    registry.write_text(json.dumps({"schema_version": 1, "versions": versions}), encoding="utf-8")
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_releases] = lambda: releases.load_releases(registry)
    app.dependency_overrides[api.get_frozen] = lambda: frozen
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    # La respuesta real de la API: 0.1.1 sin hash, 0.1.2 y 0.1.3, en ese orden.
    versions = [entry("0.1.1", sha=None), entry("0.1.2"), entry("0.1.3")]
    return client_with(versions, FROZEN, tmp_path)


def test_cada_release_aprobado_dice_si_se_puede_entrenar_y_por_que(client: TestClient) -> None:
    body = client.get("/api/p3/releases?approved=true").json()["releases"]
    assert [(r["release_id"], r["trainable"], r["blocked_reason"]) for r in body] == [
        ("0.1.1", False, "no registra archive_sha256"),
        ("0.1.2", False, "sin manifiesto congelado"),
        ("0.1.3", True, None),
    ]


def test_el_detalle_tambien_trae_la_bandera_y_el_motivo(client: TestClient) -> None:
    assert client.get("/api/p3/releases/0.1.3").json()["trainable"] is True
    detail = client.get("/api/p3/releases/0.1.1").json()
    assert (detail["trainable"], detail["blocked_reason"]) == (False, "no registra archive_sha256")


def test_sin_hash_gana_aunque_tenga_manifiesto_congelado(tmp_path: Path) -> None:
    client = client_with([entry("0.1.3", sha=None)], FROZEN, tmp_path)
    [release] = client.get("/api/p3/releases").json()["releases"]
    assert (release["trainable"], release["blocked_reason"]) == (
        False,
        "no registra archive_sha256",
    )


def test_un_congelado_con_otra_semilla_tambien_habilita_el_release(tmp_path: Path) -> None:
    # F12 (1.1): cualquier manifiesto congelado del release sirve, no solo el de seed 42.
    client = client_with([entry("0.1.2")], {"m-0.1.2-s7-1": "7" * 64}, tmp_path)
    [release] = client.get("/api/p3/releases").json()["releases"]
    assert (release["trainable"], release["blocked_reason"]) == (True, None)
    assert release["manifests"] == [{"manifest_id": "m-0.1.2-s7-1", "seed": 7, "sweep": False}]


def test_un_congelado_de_otro_release_no_cuenta(tmp_path: Path) -> None:
    # `m-0.1.3-…` no debe habilitar 0.1.30 ni 0.1 (comparacion exacta del release).
    client = client_with([entry("0.1.30"), entry("0.1")], FROZEN, tmp_path)
    flags = [r["trainable"] for r in client.get("/api/p3/releases").json()["releases"]]
    assert flags == [False, False]


def test_con_el_registro_y_los_congelados_reales_solo_0_1_3_se_entrena(tmp_path: Path) -> None:
    registry = PROYECTO2 / "reports" / "versions.json"
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_releases] = lambda: releases.load_releases(registry)
    body = TestClient(app).get("/api/p3/releases?approved=true").json()["releases"]
    trainable = [r["release_id"] for r in body if r["trainable"]]
    assert trainable == ["0.1.3"]
    reasons = {r["release_id"]: r["blocked_reason"] for r in body}
    assert reasons["0.1.1"] == "no registra archive_sha256"
    assert reasons["0.1.2"] == "sin manifiesto congelado"


def test_congelar_un_manifiesto_habilita_su_release(tmp_path: Path) -> None:
    # La bandera sale de la lista de congelados, no de una lista fija.
    frozen = {**FROZEN, "m-0.1.2-s42-1": "2" * 64}
    client = client_with([entry("0.1.2"), entry("0.1.3")], frozen, tmp_path)
    assert [r["trainable"] for r in client.get("/api/p3/releases").json()["releases"]] == [
        True,
        True,
    ]


def test_con_dos_congelados_del_mismo_release_y_semilla_gana_el_de_mayor_n() -> None:
    from p3.data.frozen import frozen_for

    frozen = {"m-0.1.3-s42-1": "1" * 64, "m-0.1.3-s42-2": "2" * 64, "m-0.1.3-s7-9": "9" * 64}
    assert frozen_for("0.1.3", 42, frozen) == "m-0.1.3-s42-2"
    # El orden de la lista no importa.
    assert frozen_for("0.1.3", 42, dict(reversed(list(frozen.items())))) == "m-0.1.3-s42-2"


def test_cada_release_lista_sus_manifiestos_congelados_con_el_del_barrido_primero(
    tmp_path: Path,
) -> None:
    frozen = {
        "m-0.1.3-s7-1": "7" * 64,
        "m-0.1.3-s42-1": "4" * 64,
        "m-0.1.2-s5-1": "5" * 64,
        "m-0.1.1-s42-1": "1" * 64,
    }
    client = client_with([entry("0.1.1", sha=None), entry("0.1.3")], frozen, tmp_path)
    body = {r["release_id"]: r for r in client.get("/api/p3/releases").json()["releases"]}
    assert body["0.1.3"]["manifests"] == [
        {"manifest_id": "m-0.1.3-s42-1", "seed": 42, "sweep": True},
        {"manifest_id": "m-0.1.3-s7-1", "seed": 7, "sweep": False},
    ]
    assert body["0.1.1"]["manifests"] == []
    assert body["0.1.1"]["blocked_reason"] == "no registra archive_sha256"


def test_con_los_congelados_reales_0_1_3_tiene_dos_manifiestos_entrenables() -> None:
    registry = PROYECTO2 / "reports" / "versions.json"
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_releases] = lambda: releases.load_releases(registry)
    release = TestClient(app).get("/api/p3/releases/0.1.3").json()
    assert release["trainable"] is True
    assert [m["manifest_id"] for m in release["manifests"]] == ["m-0.1.3-s42-1", "m-0.1.3-s7-1"]
