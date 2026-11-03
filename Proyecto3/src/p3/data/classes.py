"""Clases del clasificador, fijadas antes de experimentar (F2 T06, criterios 1.2 y 3.1).

Regla unica y predeclarada: una categoria del release entra si tiene al menos
`MIN_ORIGINALS` imagenes ORIGINALES distintas con alguna caja valida (segun
`p3.data.crops.validate_annotations`). Se cuentan originales y no recortes:
una imagen con tres personas cuenta una vez para `person`. La exclusion no
depende de ningun resultado de modelo.

El resultado vive en `config/classes.yaml`. `class_index` es el orden
alfabetico del nombre y es el indice de salida del modelo (contratos §1).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from p3.data.crops import CropSource

MIN_ORIGINALS = 300
MIN_CLASSES = 2


class NotEnoughClassesError(ValueError):
    """Menos de `MIN_CLASSES` categorias llegan al umbral."""


@dataclass(frozen=True)
class ClassDecision:
    category_id: int
    category_name: str
    originals: int
    included: bool
    reason: str | None


def originals_per_category(valid: Iterable[CropSource]) -> dict[int, int]:
    """Imagenes originales distintas por categoria, contando solo cajas validas."""
    images: dict[int, set[int]] = defaultdict(set)
    for crop in valid:
        images[crop.category_id].add(crop.source_image_id)
    return {category_id: len(ids) for category_id, ids in images.items()}


def select_classes(
    originals: Mapping[int, int],
    category_names: Mapping[int, str],
    *,
    min_originals: int = MIN_ORIGINALS,
) -> list[ClassDecision]:
    """Decision por categoria del COCO, ordenada por nombre."""
    decisions = []
    for category_id, name in sorted(category_names.items(), key=lambda item: item[1]):
        count = originals.get(category_id, 0)
        included = count >= min_originals
        reason = None if included else f"{count} originales distintos < {min_originals}"
        decisions.append(ClassDecision(category_id, name, count, included, reason))

    included_names = [d.category_name for d in decisions if d.included]
    if len(included_names) < MIN_CLASSES:
        raise NotEnoughClassesError(
            f"Solo {len(included_names)} categoria(s) llegan a {min_originals} originales "
            f"({included_names}); se necesitan al menos {MIN_CLASSES} clases."
        )
    return decisions


class ClassEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    class_index: int = Field(ge=0)
    category_id: int = Field(ge=1)
    category_name: str = Field(min_length=1)
    originals: int = Field(ge=0)


class ExcludedClass(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category_id: int = Field(ge=1)
    category_name: str = Field(min_length=1)
    originals: int = Field(ge=0)
    reason: str = Field(min_length=1)


class ClassesConfig(BaseModel):
    """Contenido de `config/classes.yaml`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    release_id: str = Field(min_length=1)
    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    min_originals: int = Field(ge=1)
    decided_at: date
    classes: list[ClassEntry] = Field(min_length=MIN_CLASSES)
    excluded: list[ExcludedClass] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherente(self) -> ClassesConfig:
        ids = [c.category_id for c in self.classes] + [e.category_id for e in self.excluded]
        if len(ids) != len(set(ids)):
            raise ValueError("category_id repetido entre classes/excluded")
        names = sorted(c.category_name for c in self.classes)
        for entry in self.classes:
            if entry.class_index != names.index(entry.category_name):
                raise ValueError(
                    f"class_index de {entry.category_name} debe ser "
                    f"{names.index(entry.category_name)} (orden alfabetico del nombre)"
                )
            if entry.originals < self.min_originals:
                raise ValueError(
                    f"originals de {entry.category_name} = {entry.originals} "
                    f"< min_originals {self.min_originals}"
                )
        return self


def build_config(
    decisions: Iterable[ClassDecision],
    *,
    release_id: str,
    dataset_fingerprint: str,
    decided_at: date,
    min_originals: int = MIN_ORIGINALS,
) -> ClassesConfig:
    decisions = list(decisions)
    included = sorted((d for d in decisions if d.included), key=lambda d: d.category_name)
    return ClassesConfig(
        release_id=release_id,
        dataset_fingerprint=dataset_fingerprint,
        min_originals=min_originals,
        decided_at=decided_at,
        classes=[
            ClassEntry(
                class_index=index,
                category_id=d.category_id,
                category_name=d.category_name,
                originals=d.originals,
            )
            for index, d in enumerate(included)
        ],
        excluded=[
            ExcludedClass(
                category_id=d.category_id,
                category_name=d.category_name,
                originals=d.originals,
                reason=d.reason or "",
            )
            for d in decisions
            if not d.included
        ],
    )


def dump_classes(config: ClassesConfig, path: Path) -> None:
    text = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def load_classes(path: Path) -> ClassesConfig:
    return ClassesConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
