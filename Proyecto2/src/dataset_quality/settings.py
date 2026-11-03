"""Configuracion tipada del proyecto (Frente 1 de la rubrica).

Toda la configuracion entra por variables de entorno; en local, esas variables
salen de un unico archivo `.env`. No hay ni un solo valor por defecto para
credenciales: si falta una, la aplicacion falla al arrancar con un mensaje
explicito en vez de usar un secreto hardcodeado.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raiz del repositorio: src/dataset_quality/settings.py -> ../../..
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuracion de la aplicacion leida del entorno / `.env`."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Aplicacion ---------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    # Dentro del contenedor la app debe escuchar en todas las interfaces.
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, gt=0, lt=65536)
    log_level: str = "info"

    # URL de la UI de MLflow **alcanzable desde el navegador** (no la de tracking
    # interna del contenedor). La expone /api/config para que el portal enlace a
    # los runs sin hornear el puerto 5000: el despliegue la fija por entorno.
    mlflow_ui_url: str = ""

    # --- Dataset Copilot ---------------------------------------------------
    # No se exige al arranque: calidad, versionado y la UI siguen funcionando
    # aunque el entorno aun no tenga una clave de Gemini. El endpoint del
    # Copilot comprueba esta ausencia y responde 503 sin intentar llamar fuera.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(default="gemini-flash-latest", min_length=1)
    mcp_server_url: str = Field(default="http://127.0.0.1:8001/mcp", min_length=1)

    # --- MariaDB ------------------------------------------------------------
    db_host: str = Field(min_length=1)
    db_port: int = Field(gt=0, lt=65536)
    db_name: str = Field(min_length=1)
    db_user: str = Field(min_length=1)
    db_password: SecretStr

    # --- MinIO / S3 ---------------------------------------------------------
    minio_endpoint: str = Field(min_length=1)
    minio_port: int = Field(gt=0, lt=65536)
    minio_root_user: str = Field(min_length=1)
    minio_root_password: SecretStr
    minio_use_ssl: bool = False
    minio_bucket_releases: str = Field(min_length=1)
    minio_bucket_dvc_cache: str = Field(min_length=1)
    # Binarios del dataset crudo. Una base de datos es pesima guardando
    # JPEGs: los bytes van al almacen de objetos y en MariaDB queda la llave.
    minio_bucket_images: str = Field(min_length=1)

    # AWS usa su cadena de credenciales (perfil explicito u OIDC en CI).
    # Las credenciales de MinIO nunca se reutilizan para PROD.
    prod_bucket_releases: str = Field(default="dataset-quality-releases-750702272375", min_length=1)
    prod_region: str = Field(default="us-east-1", min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """DSN de SQLAlchemy hacia MariaDB (la contrasena se escapa)."""
        password = quote_plus(self.db_password.get_secret_value())
        user = quote_plus(self.db_user)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def minio_endpoint_url(self) -> str:
        """URL base del endpoint S3 de MinIO."""
        scheme = "https" if self.minio_use_ssl else "http"
        return f"{scheme}://{self.minio_endpoint}:{self.minio_port}"

    @property
    def buckets(self) -> tuple[str, ...]:
        """Buckets que el entorno local debe tener creados."""
        return (
            self.minio_bucket_releases,
            self.minio_bucket_dvc_cache,
            self.minio_bucket_images,
        )

    def public_summary(self) -> dict[str, object]:
        """Vista de la configuracion SIN secretos, apta para exponer por HTTP."""
        return {
            "app_env": self.app_env,
            "database": {
                "host": self.db_host,
                "port": self.db_port,
                "name": self.db_name,
                "user": self.db_user,
            },
            "object_storage": {
                "endpoint_url": self.minio_endpoint_url,
                "buckets": list(self.buckets),
            },
            "mlflow_url": self.mlflow_ui_url,
        }


@lru_cache
def get_settings() -> Settings:
    """Instancia unica de configuracion (cacheada por proceso)."""
    return Settings()  # type: ignore[call-arg]
