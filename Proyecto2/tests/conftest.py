"""Entorno base de las pruebas: variables completas y sin tocar el `.env` real."""

from __future__ import annotations

import pytest

BASE_ENV = {
    "APP_ENV": "test",
    "APP_PORT": "8000",
    "DB_HOST": "db.test",
    "DB_PORT": "3307",
    "DB_NAME": "test_db",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test:password",
    "MINIO_ENDPOINT": "minio.test",
    "MINIO_PORT": "9100",
    "MINIO_ROOT_USER": "test_minio",
    "MINIO_ROOT_PASSWORD": "test_minio_password",
    "MINIO_USE_SSL": "false",
    "MINIO_BUCKET_RELEASES": "dataset-releases",
    "MINIO_BUCKET_DVC_CACHE": "dvc-cache",
    "MINIO_BUCKET_IMAGES": "dataset-images",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """Aplica un entorno completo y devuelve un helper para modificarlo."""
    for key, value in BASE_ENV.items():
        monkeypatch.setenv(key, value)

    def override(**changes: str | None):
        for key, value in changes.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)

    return override
