"""Registro de versiones de modelo publicadas (contratos §6; lo escribe F7).

Vive junto a los paquetes: `s3://<bucket>/models/clasificador/registry.json`.
Dice que versiones existen, donde esta el `model.pt` de cada una, su SHA-256 y
cual es la activa para inferencia. Solo depende de Pydantic.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REGISTRY_NAME = "registry.json"


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    run_id: str
    manifest_id: str
    key: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    s3_version_id: str | None = None


class ModelRegistry(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    schema_version: Literal[1]
    active_version: str | None
    versions: list[ModelEntry]

    @model_validator(mode="after")
    def _activa_existe(self) -> ModelRegistry:
        known = [entry.version for entry in self.versions]
        if len(known) != len(set(known)):
            raise ValueError("version repetida en el registro")
        if self.active_version is not None and self.active_version not in known:
            raise ValueError(f"active_version {self.active_version} no esta en versions")
        return self

    def active(self) -> ModelEntry | None:
        return next((e for e in self.versions if e.version == self.active_version), None)
