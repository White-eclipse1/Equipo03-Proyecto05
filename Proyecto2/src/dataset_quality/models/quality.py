"""Configuracion de calidad (`quality.yaml`) y su reporte de salida (`quality.json`).

`QualityConfig` es la entrada que ajusta los cinco analizadores del Frente 3
(objetos pequenos, desbalance de clases, duplicados por pHash, cajas
degeneradas, sesgo espacial). `QualityReport` es el contrato de salida que
escribe la compuerta del Frente 4 y que este modulo congela: su forma exacta
(`schema_version=1`) es lo que permite que los Frentes 7 y 8 arranquen contra
ejemplos escritos a mano sin esperar a que la compuerta exista.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, model_validator
from yaml import YAMLError

from dataset_quality.models import StrictModel
from dataset_quality.models.errors import from_pydantic, single_issue
from dataset_quality.models.splits import SplitRatios

Severity = Literal["error", "warning"]

# Longitud del pHash de `imagehash.phash`: 8x8 bits de bajas frecuencias.
PHASH_BITS = 64


class MinImagesPerClassCheck(StrictModel):
    """Exige volumen suficiente: N imagenes distintas en al menos M clases.

    Es el requisito del curso (compuerta M3) y el unico check que mide si hay
    dataset con el que entrenar algo. Nace en `error` a proposito: sin volumen
    no hay nada que publicar, por bien que salgan los demas analizadores.

    Se cuentan IMAGENES distintas que contienen al menos una caja de la clase,
    no cajas: una foto con siete coches aporta una imagen a `car`, no siete.
    """

    enabled: bool = True
    severity: Severity = "error"
    min_images: int = Field(ge=1)
    min_classes: int = Field(ge=1)


class SmallObjectsCheck(StrictModel):
    """Marca anotaciones demasiado chicas, por proporcion o por pixeles.

    Los dos criterios responden preguntas distintas y ninguno sustituye al
    otro. `area_ratio_threshold` pregunta si el objeto es chico DENTRO DE SU
    IMAGEN, que es lo que determina cuantos pixeles le quedan despues de que el
    detector reescale la foto. `min_area_px` pregunta si es chico en terminos
    absolutos: es el criterio de COCO (32x32 = 1024 px de area) y atrapa el
    caso que el relativo deja pasar — una caja de 20x20 en una foto de 200 px
    es el 1% del area y suena aceptable, pero son 400 pixeles de objeto y ahi
    no hay nada que aprender.

    Una caja es infractora si incumple CUALQUIERA de los dos. `min_area_px: 0`
    apaga el criterio absoluto y deja el comportamiento relativo puro.
    """

    enabled: bool = True
    severity: Severity = "warning"
    area_ratio_threshold: float = Field(ge=0.0, le=1.0)
    max_ratio: float = Field(ge=0.0, le=1.0)
    # 32x32 px, la convencion de COCO para "objeto pequeno".
    min_area_px: int = Field(default=1024, ge=0)


class ClassImbalanceCheck(StrictModel):
    """Marca un desbalance excesivo entre la clase mas y menos frecuente."""

    enabled: bool = True
    severity: Severity = "warning"
    max_ratio_max_min: float = Field(gt=1.0)


class DuplicatesCheck(StrictModel):
    """Marca imagenes casi identicas via distancia de Hamming entre pHash."""

    enabled: bool = True
    severity: Severity = "error"
    phash_hamming_distance: int = Field(ge=0, le=64)
    max_ratio: float = Field(ge=0.0, le=1.0)


class DegenerateBoxesCheck(StrictModel):
    """Marca cajas con area nula o negativa que se colaron en el dataset."""

    enabled: bool = True
    severity: Severity = "error"
    max_ratio: float = Field(ge=0.0, le=1.0)


class SpatialBiasCheck(StrictModel):
    """Marca concentracion espacial anomala de las anotaciones en la imagen."""

    enabled: bool = True
    severity: Severity = "warning"
    grid_size: int = Field(ge=2)
    max_cell_share: float = Field(gt=0.0, le=1.0)


class SplitsConfig(StrictModel):
    """Parametros del reparto estratificado (Frente 5).

    No es un check de la compuerta (no tiene `severity` ni `max_ratio`): es la
    configuracion que consume `tiers/splits.py` para producir `splits.json`.
    Vive aqui, junto a los demas umbrales, para que un solo archivo — rastreado
    por DVC en el Frente 6 — sea la fuente de verdad de todos los parametros.
    """

    seed: int = 42
    ratios: SplitRatios
    # Desviacion maxima tolerada entre la proporcion de una clase en un split
    # y su proporcion global. Por encima de esto el reparto no cuenta como
    # "estratificado dentro de tolerancia".
    tolerance: float = Field(default=0.05, ge=0.0, le=1.0)
    # Los grupos de casi-duplicados (pHash del Frente 3) viajan juntos a un
    # solo split; desactivarlo reparte imagen por imagen y arriesga fuga.
    group_near_duplicates: bool = True


class QualityConfig(StrictModel):
    """Umbrales de calidad. Se carga desde `quality.yaml`."""

    version: int = Field(default=1, ge=1)
    min_images_per_class: MinImagesPerClassCheck
    small_objects: SmallObjectsCheck
    class_imbalance: ClassImbalanceCheck
    duplicates: DuplicatesCheck
    degenerate_boxes: DegenerateBoxesCheck
    spatial_bias: SpatialBiasCheck
    splits: SplitsConfig

    def enabled_checks(self) -> tuple[str, ...]:
        """Nombres de los analizadores activos, en el orden declarado arriba."""
        names = (
            "min_images_per_class",
            "small_objects",
            "class_imbalance",
            "duplicates",
            "degenerate_boxes",
            "spatial_bias",
        )
        return tuple(name for name in names if getattr(self, name).enabled)

    @classmethod
    def from_yaml(cls, path: Path) -> QualityConfig:
        """Carga y valida `quality.yaml`. Nunca usa `yaml.load` sin loader seguro."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except YAMLError as error:
            problem_mark = getattr(error, "problem_mark", None)
            location = f"linea {problem_mark.line + 1}" if problem_mark else "<root>"
            raise single_issue(str(path), location, f"YAML malformado: {error}") from error

        if raw is None:
            raise single_issue(str(path), "<root>", "el archivo esta vacio")

        try:
            return cls.model_validate(raw)
        except ValidationError as error:
            raise from_pydantic(str(path), error) from error


class QualityTotals(StrictModel):
    """Conteos globales del dataset evaluado, para contexto en el reporte."""

    images: int = Field(ge=0)
    annotations: int = Field(ge=0)
    categories: int = Field(ge=0)


class DuplicatePair(StrictModel):
    """Dos imagenes que el pHash considera la misma foto.

    `kept` es el id menor — la que se subio primero y se conserva — y
    `duplicate` la copia sobrante. `similarity` es la distancia de Hamming
    traducida a proporcion de bits iguales (1.0 = pHash identico), que es como
    se lee en pantalla; `distance` se conserva porque es lo que compara el
    umbral de `quality.yaml`.
    """

    kept: int
    duplicate: int
    distance: int = Field(ge=0, le=PHASH_BITS)
    similarity: float = Field(ge=0.0, le=1.0)


class DuplicatesDetail(StrictModel):
    """A que clases afecta el duplicado, no solo cuantos hay.

    El analizador ya calculaba los pares para decidir el veredicto y los tiraba
    al construir el `CheckResult`: lo unico que sobrevivia era la lista de ids
    sobrantes. Con eso no se puede responder "cuantos duplicados hay y a que
    clase afectan" sin volver a abrir todas las imagenes, que es justo lo caro.

    `images_by_class` cuenta las imagenes SOBRANTES que contienen al menos una
    caja de esa clase; una copia con cajas de dos clases suma en las dos, asi
    que la suma de este diccionario puede superar el numero de imagenes
    sobrantes. Es la cifra que dice cuanto bajaria el conteo por clase de la
    compuerta M3 al colapsar los duplicados.
    """

    max_distance: int = Field(ge=0, le=PHASH_BITS)
    pairs: list[DuplicatePair] = Field(default_factory=list)
    # Grupos de casi-duplicados con mas de una imagen: cuantas fotos distintas
    # hay de verdad detras de las copias.
    groups: int = Field(default=0, ge=0)
    images_by_class: dict[str, int] = Field(default_factory=dict)
    boxes_by_class: dict[str, int] = Field(default_factory=dict)
    # Copias que no aportan a ninguna clase porque no tienen ninguna caja.
    images_without_class: int = Field(default=0, ge=0)


class SmallObjectsDetail(StrictModel):
    """A que clases afecta el recorte de objetos pequenos, no solo cuantos hay.

    Mismo problema que tenia `duplicates` antes de `DuplicatesDetail`: la lista
    de ids infractores no responde "y esto a que clase me lo esta rompiendo".
    Con el desglose, un `small_objects` en fail se lee de un vistazo: si las
    cajas diminutas se concentran en una clase, el problema es como se anoto
    esa clase; si estan repartidas, es la resolucion del dataset.

    `boxes_by_class` cuenta CAJAS infractoras e `images_by_class` las imagenes
    DISTINTAS que contienen al menos una; ambos van de mayor a menor, asi que
    la primera clave es la clase mas afectada.

    `below_ratio` y `below_min_area` dicen que criterio marco cada caja. Se
    solapan a proposito — una caja puede incumplir los dos — y por eso su suma
    puede superar el total de infractoras.
    """

    area_ratio_threshold: float = Field(ge=0.0, le=1.0)
    min_area_px: int = Field(ge=0)
    boxes_by_class: dict[str, int] = Field(default_factory=dict)
    images_by_class: dict[str, int] = Field(default_factory=dict)
    below_ratio: int = Field(default=0, ge=0)
    below_min_area: int = Field(default=0, ge=0)


class CheckResult(StrictModel):
    """Resultado de un analizador individual."""

    name: str = Field(min_length=1)
    status: Literal["pass", "fail", "skipped"]
    severity: Severity
    observed: float
    threshold: float
    message: str
    offenders: list[int] = Field(default_factory=list)
    # Detalle especifico de un check; `None` en los demas. Son anadidos
    # opcionales al contrato: un `quality.json` escrito antes de que
    # existieran sigue validando, por eso `schema_version` sigue en 1.
    duplicates: DuplicatesDetail | None = None
    small_objects: SmallObjectsDetail | None = None


class QualityReport(StrictModel):
    """Contrato congelado de `quality.json`."""

    schema_version: Literal[1] = 1
    generated_at: datetime
    dataset_fingerprint: str = Field(min_length=1)
    config_version: int = Field(ge=1)
    status: Literal["pass", "fail"]
    exit_code: Literal[0, 1]
    totals: QualityTotals
    checks: list[CheckResult]

    @model_validator(mode="after")
    def _status_y_exit_code_coherentes(self) -> QualityReport:
        esperado = 0 if self.status == "pass" else 1
        if self.exit_code != esperado:
            raise ValueError(
                f"exit_code={self.exit_code} no es coherente con status={self.status!r} "
                f"(se esperaba {esperado})"
            )
        return self
