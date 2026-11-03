"""`/health` solo dice OK cuando MariaDB y MinIO responden de verdad."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dataset_quality import main
from dataset_quality.settings import get_settings


@pytest.fixture
def client(env) -> TestClient:
    # La configuracion esta cacheada por proceso: se limpia para que lea el
    # entorno de la prueba y no el `.env` del desarrollador.
    get_settings.cache_clear()
    yield TestClient(main.create_app(), raise_server_exceptions=False)
    get_settings.cache_clear()


def test_todo_arriba_devuelve_200(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "check_database", lambda: None)
    monkeypatch.setattr(main, "check_object_storage", lambda: None)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {check["name"]: check["status"] for check in body["checks"]} == {
        "mariadb": "up",
        "minio": "up",
    }


def test_una_dependencia_caida_devuelve_503(client, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(main, "check_database", lambda: None)
    monkeypatch.setattr(main, "check_object_storage", boom)

    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    minio = next(check for check in body["checks"] if check["name"] == "minio")
    assert minio["status"] == "down"
    assert "connection refused" in minio["detail"]


def test_config_no_expone_secretos(client) -> None:
    body = client.get("/api/config").json()

    assert body["database"]["name"] == "test_db"
    assert "test:password" not in str(body)
