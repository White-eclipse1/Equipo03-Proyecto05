"""La configuracion es la frontera con el exterior: se valida, no se asume.

Cubre el Frente 1 de la rubrica: config por pydantic-settings, cero
credenciales en codigo.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dataset_quality.settings import Settings


def build() -> Settings:
    # `_env_file=None` evita que el `.env` real del repo contamine la prueba.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_carga_desde_el_entorno(env) -> None:
    settings = build()

    assert settings.app_env == "test"
    assert settings.db_name == "test_db"
    assert settings.buckets == ("dataset-releases", "dvc-cache", "dataset-images")


def test_falta_una_credencial_y_aborta(env) -> None:
    env(DB_PASSWORD=None)

    with pytest.raises(ValidationError) as error:
        build()

    assert "db_password" in str(error.value)


def test_dsn_escapa_caracteres_especiales_de_la_contrasena(env) -> None:
    settings = build()

    assert settings.database_url == (
        "mysql+pymysql://test_user:test%3Apassword@db.test:3307/test_db?charset=utf8mb4"
    )


def test_endpoint_de_minio_respeta_el_flag_de_ssl(env) -> None:
    assert build().minio_endpoint_url == "http://minio.test:9100"

    env(MINIO_USE_SSL="true")
    assert build().minio_endpoint_url == "https://minio.test:9100"


def test_los_secretos_no_se_filtran_en_repr_ni_en_el_resumen_publico(env) -> None:
    settings = build()
    rendered = repr(settings) + str(settings.public_summary())

    assert "test:password" not in rendered
    assert "test_minio_password" not in rendered
