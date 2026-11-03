"""Configuracion del worker y de la API de trabajos, leida del entorno.

Usa las mismas variables `DB_*` que Proyecto2: la cola vive en su MariaDB.
Es el unico modulo de `p3.worker` que lee el entorno; el resto recibe el
engine o la sesion ya construidos.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    db_host: str = Field(min_length=1)
    db_port: int = Field(gt=0, lt=65536)
    db_name: str = Field(min_length=1)
    db_user: str = Field(min_length=1)
    db_password: SecretStr
    poll_seconds: float = Field(default=2.0, gt=0, alias="P3_WORKER_POLL_SECONDS")
    # Manifiestos y recortes (`Proyecto3/data` montado en el contenedor).
    data_dir: Path = Field(default=Path("/data"), alias="P3_DATA_DIR")
    # `cuda` si hay GPU visible, `cpu` si no; `P3_DEVICE` lo fuerza.
    device: str | None = Field(default=None, alias="P3_DEVICE")
    num_workers: int = Field(default=2, ge=0, le=16, alias="P3_NUM_WORKERS")
    mlflow_tracking_uri: str = Field(default="http://mlflow:5000", alias="MLFLOW_TRACKING_URI")
    # Commit del codigo que entrena; lo exporta `Proyecto2/scripts/up.py` al levantar.
    code_commit: str = Field(default="unknown", alias="P3_CODE_COMMIT")
    code_dirty: bool = Field(default=False, alias="P3_CODE_DIRTY")

    def resolved_device(self) -> str:
        if self.device:
            return self.device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    @property
    def database_url(self) -> str:
        password = quote_plus(self.db_password.get_secret_value())
        user = quote_plus(self.db_user)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()  # type: ignore[call-arg]


@lru_cache
def get_engine() -> Engine:
    from p3.worker.jobs import create_schema

    engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
    create_schema(engine)
    return engine


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
