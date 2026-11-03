"""Contrato de la exploracion 2D precomputada (`exploration.json`).

El cuarto contrato de salida, junto a `quality.json`, `splits.json` y
`versions.json`. Existe porque la pantalla de exploracion necesita una lista de
puntos 2D y ninguno de los otros tres la contiene.

Por que precomputada: extraer los rasgos de ~900 imagenes lleva decenas de
segundos de CPU. El navegador no puede hacer eso en cada carga, asi que el
pipeline lo calcula una vez y la app web solo dibuja puntos.

Que NO es: un embedding semantico. El vector combina histograma de color con
una miniatura en escala de grises, asi que agrupa por color y composicion, no
por significado. Dos bicicletas rosas caen juntas; una bicicleta negra cae
lejos de ellas aunque las tres sean bicicletas. `method_detail` existe para que
la pantalla pueda advertirlo a quien la mira.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from dataset_quality.models import StrictModel

ProjectionMethod = Literal["pca", "tsne"]


class ExplorationPoint(StrictModel):
    """Una imagen, proyectada a dos dimensiones."""

    image_id: int = Field(ge=1)
    x: float
    y: float
    # Clase dominante de la imagen; `None` si no tiene ninguna caja.
    category_id: int | None = None
    # Nombre del archivo, para que la pantalla pueda pedir su miniatura sin
    # cargar antes el COCO entero solo para traducir `image_id` a ruta. Es un
    # anadido opcional: un `exploration.json` anterior sigue validando, por eso
    # `schema_version` sigue en 1.
    file_name: str = ""


class ExplorationManifest(StrictModel):
    """Contrato congelado de `exploration.json`."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    method: ProjectionMethod
    # Fija el resultado cuando el metodo es estocastico (t-SNE). PCA es
    # determinista y lo ignora, pero el campo viaja igual para que el reporte
    # se pueda reproducir sin mirar antes que metodo se uso.
    seed: int = 42
    dimensions: Literal[2] = 2

    # Cuanta informacion del vector original sobreviven los dos ejes. Sin este
    # numero nadie sabe si los racimos significan algo: con un 5% el grafico es
    # ruido con forma de nube y no deberia presentarse como si dijera algo.
    variance_explained: float = Field(ge=0.0, le=1.0)

    # Descripcion legible de los rasgos, para mostrarla junto al grafico.
    method_detail: str = Field(min_length=1)

    points: list[ExplorationPoint]

    @model_validator(mode="after")
    def _puntos_unicos(self) -> ExplorationManifest:
        ids = [point.image_id for point in self.points]
        if len(ids) != len(set(ids)):
            vistos: set[int] = set()
            repetidos = sorted({i for i in ids if i in vistos or vistos.add(i)})  # type: ignore[func-returns-value]
            raise ValueError(f"image_id repetido en los puntos: {repetidos[:5]}")
        return self
