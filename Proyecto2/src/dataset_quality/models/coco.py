"""Modelos del dataset COCO crudo (entrada de la plataforma de calidad).

Espejan las invariantes que ya aplica el exportador de MP1
(`Proyecto1/src/services/coco-export.service.ts`): ids sin duplicar, cada
`image_id`/`category_id` referenciado debe existir, la bbox son 4 coordenadas
absolutas positivas y el area es coherente con `width * height`. Aqui se
verifican en la ingesta para que ningun analizador (Frente 3) trabaje sobre un
dataset ya inconsistente.

El documento de nivel superior acepta campos extra del estandar COCO (`info`,
`licenses`, `segmentation`, ...) que esta plataforma no usa todavia; las listas
que sí se validan lo hacen con reglas estrictas.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from dataset_quality.models import StrictModel
from dataset_quality.models.errors import from_pydantic, single_issue

_AREA_REL_TOL = 1e-6


class CocoImage(StrictModel):
    """Imagen segun el esquema oficial de COCO."""

    id: int = Field(ge=1)
    file_name: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CocoCategory(StrictModel):
    """Categoria segun el esquema oficial de COCO."""

    id: int = Field(ge=1)
    name: str = Field(min_length=1)
    supercategory: str | None = None


class CocoAnnotation(StrictModel):
    """Anotacion segun el esquema oficial de COCO."""

    id: int = Field(ge=1)
    image_id: int = Field(ge=1)
    category_id: int = Field(ge=1)
    bbox: tuple[float, float, float, float]
    area: float = Field(ge=0)
    iscrowd: Literal[0, 1] = 0

    @field_validator("bbox")
    @classmethod
    def _bbox_valida(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x, y, width, height = value
        if x < 0:
            raise ValueError("la coordenada x debe ser >= 0")
        if y < 0:
            raise ValueError("la coordenada y debe ser >= 0")
        if width <= 0:
            raise ValueError("el ancho debe ser > 0")
        if height <= 0:
            raise ValueError("el alto debe ser > 0")
        return value

    @model_validator(mode="after")
    def _area_coherente_con_bbox(self) -> CocoAnnotation:
        _, _, width, height = self.bbox
        esperado = width * height
        if not math.isclose(self.area, esperado, rel_tol=_AREA_REL_TOL):
            raise ValueError(f"no coincide con width * height de bbox ({esperado})")
        return self


class CocoDataset(StrictModel):
    """Dataset COCO completo: la unidad que consumen los analizadores."""

    model_config = ConfigDict(extra="allow", frozen=True, str_strip_whitespace=True)

    images: list[CocoImage]
    annotations: list[CocoAnnotation]
    categories: list[CocoCategory]

    @model_validator(mode="after")
    def _integridad_referencial(self) -> CocoDataset:
        ids_imagen = [image.id for image in self.images]
        duplicados_imagen = _duplicados(ids_imagen)
        if duplicados_imagen:
            raise ValueError(f"id de imagen duplicado: {sorted(duplicados_imagen)}")

        ids_categoria = [category.id for category in self.categories]
        duplicados_categoria = _duplicados(ids_categoria)
        if duplicados_categoria:
            raise ValueError(f"id de categoria duplicado: {sorted(duplicados_categoria)}")

        ids_anotacion = [annotation.id for annotation in self.annotations]
        duplicados_anotacion = _duplicados(ids_anotacion)
        if duplicados_anotacion:
            raise ValueError(f"id de anotacion duplicado: {sorted(duplicados_anotacion)}")

        imagenes_validas = set(ids_imagen)
        categorias_validas = set(ids_categoria)
        for index, annotation in enumerate(self.annotations):
            if annotation.image_id not in imagenes_validas:
                raise ValueError(
                    f"annotations.{index}: referencia una imagen inexistente "
                    f"(image_id={annotation.image_id})"
                )
            if annotation.category_id not in categorias_validas:
                raise ValueError(
                    f"annotations.{index}: referencia una categoria inexistente "
                    f"(category_id={annotation.category_id})"
                )
        return self

    def bbox_out_of_bounds(self) -> list[int]:
        """Ids de anotacion cuya bbox se sale del tamano de su imagen.

        No es un error de validacion (eso corresponde a los analizadores del
        Frente 3): es un helper puro que estos consumiran.
        """
        images_by_id = {image.id: image for image in self.images}
        offenders: list[int] = []
        for annotation in self.annotations:
            image = images_by_id.get(annotation.image_id)
            if image is None:
                continue
            x, y, width, height = annotation.bbox
            if x + width > image.width or y + height > image.height:
                offenders.append(annotation.id)
        return offenders


def _duplicados(values: list[int]) -> set[int]:
    counts = Counter(values)
    return {value for value, count in counts.items() if count > 1}


def parse_coco(raw: str | bytes, *, source: str = "coco.json") -> CocoDataset:
    """Valida un documento COCO crudo. Es la funcion pura que prueban los tests."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise single_issue(source, "<root>", f"JSON malformado: {error.msg}") from error

    try:
        return CocoDataset.model_validate(data)
    except ValidationError as error:
        raise from_pydantic(source, error) from error


def load_coco(path: Path) -> CocoDataset:
    """Lee y valida un archivo COCO desde disco."""
    return parse_coco(path.read_text(encoding="utf-8"), source=str(path))
