"""`splits.json`: el contrato de salida congelado de los splits estratificados.

Lo produce el Frente 5 (splits con semilla y sin fuga entre train/val/test);
aqui solo se fija su forma exacta para que los frentes que lo consumen
(Frente 7 y 8) puedan escribirse contra un ejemplo de oro desde hoy.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from dataset_quality.models import StrictModel

SplitName = Literal["train", "val", "test"]


class SplitRatios(StrictModel):
    """Proporciones objetivo de cada split. Deben sumar 1.0."""

    train: float = Field(gt=0.0, lt=1.0)
    val: float = Field(gt=0.0, lt=1.0)
    test: float = Field(gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _suman_uno(self) -> SplitRatios:
        total = self.train + self.val + self.test
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"train + val + test debe sumar 1.0 (suma: {total})")
        return self


class SplitAssignment(StrictModel):
    """La asignacion de una imagen a un split."""

    image_id: int = Field(ge=1)
    split: SplitName


class ClassSplitCounts(StrictModel):
    """Como quedo repartida UNA clase entre las tres particiones.

    Se cuentan imagenes DISTINTAS que contienen al menos una caja de la clase,
    igual que en el resto del proyecto: una foto con siete coches aporta una
    imagen a `car`. Una imagen con cajas de dos clases suma en las dos, asi que
    la suma de los `total` de todas las clases puede superar el numero de
    imagenes del dataset.

    `max_deviation` es la peor diferencia, entre las tres particiones, entre la
    proporcion de la clase dentro de una particion y su proporcion global. Es
    la cifra contra la que se compara `splits.tolerance` de `quality.yaml`, y
    la que decide si el reparto cuenta como estratificado.
    """

    train: int = Field(default=0, ge=0)
    val: int = Field(default=0, ge=0)
    test: int = Field(default=0, ge=0)
    total: int = Field(ge=0)
    max_deviation: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _el_total_es_la_suma(self) -> ClassSplitCounts:
        suma = self.train + self.val + self.test
        if suma != self.total:
            raise ValueError(f"total={self.total} no es la suma de las particiones ({suma})")
        return self


class SplitsManifest(StrictModel):
    """Contrato congelado de `splits.json`."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    seed: int
    ratios: SplitRatios
    counts: dict[SplitName, int]
    stratified_by: str = "category_id"
    assignments: list[SplitAssignment]
    # Anadidos opcionales: un `splits.json` escrito antes de que existieran
    # sigue validando, por eso `schema_version` sigue en 1.
    #
    # Sin esto el manifiesto dice CUANTAS imagenes hay en cada particion pero
    # no de que clases, que es justo lo que hace falta para saber si el reparto
    # es honesto. La alternativa — cruzar `splits.json` con `stats.json` en
    # cada pantalla — obliga a que los dos archivos describan el mismo dataset,
    # y no hay nada que lo garantice.
    per_class: dict[str, ClassSplitCounts] = Field(default_factory=dict)
    # Grupos de casi-duplicados (pHash) que viajaron juntos a una particion.
    # Es la cifra que demuestra que no hubo fuga de copias entre splits: se
    # calculaba al repartir y se perdia al escribir el archivo.
    grouped_near_duplicates: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _sin_fuga_y_conteos_coherentes(self) -> SplitsManifest:
        ids = [assignment.image_id for assignment in self.assignments]
        duplicados = {value for value, count in Counter(ids).items() if count > 1}
        if duplicados:
            raise ValueError(
                f"image_id asignado a mas de un split (fuga entre splits): {sorted(duplicados)}"
            )

        conteo_real = Counter(assignment.split for assignment in self.assignments)
        for split_name in ("train", "val", "test"):
            esperado = self.counts.get(split_name, 0)
            observado = conteo_real.get(split_name, 0)
            if esperado != observado:
                raise ValueError(
                    f"counts.{split_name}={esperado} no coincide con las asignaciones reales "
                    f"({observado})"
                )
        return self
