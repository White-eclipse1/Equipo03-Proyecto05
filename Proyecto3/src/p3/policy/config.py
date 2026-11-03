"""`ConfigPolitica`: zonas, clases, umbrales, tiempos y comandos (B1-01; E4, criterio 2.1).

Se valida al cargar: una configuracion invalida se rechaza nombrando el campo
ANTES de construir la politica, asi que nunca se emite movimiento con ella.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Fraccion = float
_EPS = 1e-9


class _Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Zonas(_Estricto):
    """Intervalos [ini, fin] de x normalizado; contiguos y cubriendo [0, 1]."""

    izquierda: tuple[Fraccion, Fraccion]
    centro: tuple[Fraccion, Fraccion]
    derecha: tuple[Fraccion, Fraccion]

    @model_validator(mode="after")
    def _cubren_el_cuadro(self) -> Zonas:
        orden = [self.izquierda, self.centro, self.derecha]
        if any(fin - ini <= 0 for ini, fin in orden):
            raise ValueError("cada zona necesita ini < fin")
        cortes_ok = (
            abs(self.izquierda[0]) < _EPS
            and abs(self.izquierda[1] - self.centro[0]) < _EPS
            and abs(self.centro[1] - self.derecha[0]) < _EPS
            and abs(self.derecha[1] - 1) < _EPS
        )
        if not cortes_ok:
            raise ValueError("las zonas deben ser contiguas y cubrir [0, 1] sin huecos")
        return self


class Geometria(_Estricto):
    banda_riesgo_y_min: float = Field(ge=0, lt=1)
    area_min: float = Field(ge=0, lt=1)
    cobertura_min_zona: float = Field(gt=0, le=1)


class Confianza(_Estricto):
    umbral_alto: float = Field(gt=0, le=1)
    umbral_bajo: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _histeresis(self) -> Confianza:
        if self.umbral_bajo >= self.umbral_alto:
            raise ValueError("umbral_bajo debe ser menor que umbral_alto")
        return self


class Temporal(_Estricto):
    cuadros_para_bloquear: int = Field(ge=1, le=30)
    cuadros_para_liberar: int = Field(ge=1, le=30)
    vigencia_comando_ms: int = Field(gt=0, le=10_000)


class Comandos(_Estricto):
    velocidad_crucero: float = Field(gt=0, le=1)
    velocidad_precaucion: float = Field(gt=0, le=1)
    velocidad_evasion: float = Field(gt=0, le=1)
    direccion_evasion: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _escalonadas(self) -> Comandos:
        if not self.velocidad_evasion <= self.velocidad_precaucion <= self.velocidad_crucero:
            raise ValueError("se exige velocidad_evasion <= velocidad_precaucion <= crucero")
        return self


class Evasion(_Estricto):
    habilitada: bool
    lado_preferido: Literal["izquierda", "derecha"]


class ConfigPolitica(_Estricto):
    schema_version: Literal[1]
    clases_obstaculo: tuple[str, ...] = Field(min_length=1)
    zonas: Zonas
    geometria: Geometria
    confianza: Confianza
    temporal: Temporal
    comandos: Comandos
    evasion: Evasion

    @field_validator("clases_obstaculo")
    @classmethod
    def _clases_unicas(cls, clases: tuple[str, ...]) -> tuple[str, ...]:
        if any(not c for c in clases) or len(set(clases)) != len(clases):
            raise ValueError("clases_obstaculo debe tener nombres no vacios y sin repetir")
        return clases


def cargar_config(ruta: Path) -> tuple[ConfigPolitica, str]:
    """Lee y valida la politica; devuelve la config y el SHA-256 de los bytes del archivo."""
    datos = Path(ruta).read_bytes()
    config = ConfigPolitica.model_validate(yaml.safe_load(datos))
    return config, hashlib.sha256(datos).hexdigest()
