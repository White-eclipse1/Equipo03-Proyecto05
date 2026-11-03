"""Configuracion de la parte de datos de P3, leida del entorno.

Es el unico modulo de `p3.data` que lee el entorno; el resto recibe rutas,
bytes o listas de releases ya construidos.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # El router corre dentro de la app de P2 (cwd `/app` = `Proyecto2/`), asi
    # que por defecto se lee el mismo registro que escribe `dq release`.
    versions_path: Path = Field(default=Path("reports/versions.json"), alias="P3_RELEASES_REGISTRY")
    # Bucket de releases de la cuenta del equipo (docs/almacenamiento.md).
    releases_bucket: str = Field(
        default="dataset-quality-releases-750702272375",
        min_length=3,
        alias="P3_RELEASES_BUCKET",
    )
    # Remote de `published_in` que corresponde a ese bucket.
    releases_remote: str = Field(default="prod", min_length=1, alias="P3_RELEASES_REMOTE")
    # Manifiestos de F3 (`dvc pull`). Relativo a `Proyecto2/`; en Docker,
    # `/opt/p3/data/manifests` (montaje de solo lectura de `Proyecto3/data`).
    manifests_dir: Path = Field(
        default=Path("../Proyecto3/data/manifests"), alias="P3_MANIFESTS_DIR"
    )
    # Recortes de F2 (`generate_crops.py`), para las miniaturas de Evaluation. En
    # Docker, `/opt/p3/data/crops`.
    crops_dir: Path = Field(default=Path("../Proyecto3/data/crops"), alias="P3_CROPS_DIR")


@lru_cache
def get_settings() -> DataSettings:
    return DataSettings()
