"""Configuracion del receptor de capturas, leida del entorno.

Todo lo que cambia entre la laptop, el MinIO local y AWS vive aqui; el codigo no
tiene nombres de bucket, llaves ni tokens.

- `P4_ALMACEN`: `s3` (AWS o MinIO) o `memoria` (solo desarrollo: se pierde al
  reiniciar el proceso).
- Credenciales de AWS: `P4_AWS_PROFILE` con un perfil de `~/.aws` en desarrollo;
  vacio, boto3 usa su cadena estandar (rol de la instancia en el despliegue).
  `P4_S3_ENDPOINT` + llaves apuntan al MinIO local.
- `P4_TOKEN_DISPOSITIVO`: token Bearer que manda el dispositivo. Sin token el
  receptor no acepta envios: nunca queda abierto por olvido.
- `P4_MODELOS_ACEPTADOS`: `version=sha256` separados por coma. El receptor solo
  guarda capturas clasificadas por un artefacto declarado aqui.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Orden de salida del modelo del Proyecto 3 (`Proyecto3/config/classes.yaml`).
CLASES_P3 = "cat,dog,person"


class ConfigCapturas(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    almacen: Literal["s3", "memoria"] = Field(default="s3", alias="P4_ALMACEN")
    bucket: str = Field(default="", alias="P4_BUCKET")
    prefijo: str = Field(default="edge-capturas/", alias="P4_PREFIJO")
    aws_profile: str | None = Field(default=None, alias="P4_AWS_PROFILE")
    aws_region: str = Field(default="us-east-1", alias="P4_AWS_REGION")
    s3_endpoint: str | None = Field(default=None, alias="P4_S3_ENDPOINT")
    s3_access_key: str | None = Field(default=None, alias="P4_S3_ACCESS_KEY")
    s3_secret_key: SecretStr | None = Field(default=None, alias="P4_S3_SECRET_KEY")
    token_dispositivo: SecretStr | None = Field(default=None, alias="P4_TOKEN_DISPOSITIVO")
    clases: str = Field(default=CLASES_P3, alias="P4_CLASES")
    modelos_aceptados: str = Field(default="", alias="P4_MODELOS_ACEPTADOS")
    max_foto_bytes: int = Field(default=5 * 1024 * 1024, alias="P4_MAX_FOTO_BYTES")
    # El evento pesa menos de 1 KB; 16 KiB deja margen sin aceptar cuerpos absurdos.
    max_evento_bytes: int = Field(default=16 * 1024, alias="P4_MAX_EVENTO_BYTES")

    @field_validator(
        "aws_profile",
        "s3_endpoint",
        "s3_access_key",
        "s3_secret_key",
        "token_dispositivo",
        mode="before",
    )
    @classmethod
    def _vacio_es_none(cls, valor: object) -> object:
        # En `.env` una variable vacia llega como "": significa "sin valor".
        return None if isinstance(valor, str) and not valor.strip() else valor

    @field_validator("prefijo")
    @classmethod
    def _prefijo_con_diagonal(cls, valor: str) -> str:
        valor = valor.strip().lstrip("/")
        return valor if not valor or valor.endswith("/") else f"{valor}/"

    def lista_clases(self) -> tuple[str, ...]:
        return tuple(c.strip() for c in self.clases.split(",") if c.strip())

    def modelos(self) -> dict[str, str]:
        """`{version: sha256}` de los artefactos aceptados."""
        pares = (p.split("=", 1) for p in self.modelos_aceptados.split(",") if "=" in p)
        return {version.strip(): sha.strip().lower() for version, sha in pares}


@lru_cache
def obtener_config() -> ConfigCapturas:
    return ConfigCapturas()
