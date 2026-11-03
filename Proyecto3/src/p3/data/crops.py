"""Recortes COCO: que cajas del release se convierten en muestras (F2 T07, criterio 1.2).

Cada anotacion termina en exactamente uno de dos lados:

- `CropSource`: caja valida, lista para recortar. Conserva `annotation_id`,
  `source_image_id`, `source_file_name`, `category_id`/`category_name` y la
  bbox original del COCO sin redondear. Un original puede producir varios.
- `Exclusion`: caja descartada con su motivo (`docs/contratos.md` §2).

Las cajas estan en las coordenadas del COCO (`width`/`height` de la imagen),
que P1 tomo de la cabecera del archivo. P1 mostro la foto con la rotacion
EXIF aplicada y llevo cada caja a ese espacio eje por eje. Por eso los
limites se revisan contra el tamano del COCO y, para recortar, la foto se
gira igual que en el navegador y la caja se escala por eje al tamano de la
foto girada (`pixel_scale`). Verificado a ojo en el release 0.1.3.

Si una anotacion cumple varios motivos se registra el primero de este orden:
`excluded_category` (la caja no es de una clase fijada, lo demas no importa),
`missing_image`, `degenerate_bbox`, `bbox_out_of_bounds`, `size_mismatch`.

Se trabaja sobre el COCO como `dict` y no con `dataset_quality.models.coco` de
P2 a proposito: ese modelo rechaza el dataset COMPLETO ante una sola caja
degenerada, y aqui hace falta lo contrario: descartar esa caja, registrar por
que y seguir con las demas.

Despues, `generate_crops` corta cada caja valida en un PNG y devuelve un
`CropRecord` por recorte; `write_exclusions_csv` deja las exclusiones en CSV.

Aqui no se leen variables de entorno ni se crean clientes de S3 o BD: las
rutas de imagenes y de salida las pasa quien llama.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageOps, UnidentifiedImageError

ExclusionReason = Literal[
    "degenerate_bbox",
    "bbox_out_of_bounds",
    "missing_image",
    "excluded_category",
    "size_mismatch",
]

BBox = tuple[float, float, float, float]

# Orientaciones EXIF que giran 90 grados (intercambian ancho y alto al mostrarse).
_SWAPPING_ORIENTATIONS = {5, 6, 7, 8}
_ORIENTATION_TAG = 0x0112
# Deformacion de proporcion maxima entre el archivo y el COCO para escalar la caja
# por eje. Con mas, el archivo no es la imagen que se anoto (`size_mismatch`).
MAX_ASPECT_DISTORTION = 0.10


@dataclass(frozen=True)
class ImageGeometry:
    """Tamano del archivo tal como se muestra: con la rotacion EXIF ya aplicada."""

    width: int
    height: int
    exif_transposed: bool = False


@dataclass(frozen=True)
class CropSource:
    """Caja valida de una clase incluida: una fila futura del manifiesto.

    `bbox_xywh` queda en coordenadas del COCO; `pixel_scale` la lleva al
    archivo real (ya girado) para recortar.
    """

    annotation_id: int
    source_image_id: int
    source_file_name: str
    category_id: int
    category_name: str
    bbox_xywh: BBox
    pixel_scale: tuple[float, float] = (1.0, 1.0)


@dataclass(frozen=True)
class Exclusion:
    """Anotacion descartada; va a `exclusions.csv` y a `manifest.meta.json`."""

    annotation_id: int
    source_image_id: int
    reason: ExclusionReason


@dataclass(frozen=True)
class ValidationResult:
    """Ambas tuplas ordenadas por `annotation_id`."""

    valid: tuple[CropSource, ...]
    exclusions: tuple[Exclusion, ...]


def open_as_displayed(path: Path) -> Image.Image:
    """La imagen en RGB con la rotacion EXIF aplicada, como la mostro P1 al anotar."""
    with Image.open(path) as handle:
        return ImageOps.exif_transpose(handle).convert("RGB")


def read_image_sizes(
    images: Iterable[Mapping[str, Any]], images_dir: Path
) -> dict[int, ImageGeometry]:
    """Geometria de cada imagen del COCO que existe y se puede abrir.

    El tamano es el que se muestra (con la rotacion EXIF aplicada), porque es
    sobre esa imagen donde se dibujaron las cajas en P1. Una imagen ausente o
    ilegible no aparece en el resultado; para la validacion eso es
    `missing_image`.
    """
    sizes: dict[int, ImageGeometry] = {}
    for image in images:
        path = images_dir / image["file_name"]
        try:
            with Image.open(path) as handle:
                width, height = handle.size
                orientation = handle.getexif().get(_ORIENTATION_TAG, 1)
        except (FileNotFoundError, IsADirectoryError, UnidentifiedImageError):
            continue
        if orientation in _SWAPPING_ORIENTATIONS:
            sizes[image["id"]] = ImageGeometry(height, width, exif_transposed=True)
        else:
            sizes[image["id"]] = ImageGeometry(width, height)
    return sizes


def validate_annotations(
    coco: Mapping[str, Any],
    included_category_ids: Collection[int],
    image_sizes: Mapping[int, ImageGeometry],
) -> ValidationResult:
    """Separa las anotaciones del COCO en cajas validas y exclusiones con motivo.

    Los limites se revisan en las coordenadas del COCO; luego `pixel_scale`
    lleva la caja, eje por eje, a la foto girada como la mostro P1.
    `image_sizes` viene de `read_image_sizes`: una imagen sin entrada es una
    imagen faltante. No modifica `coco`.
    """
    images = {image["id"]: image for image in coco["images"]}
    category_names = {category["id"]: category["name"] for category in coco["categories"]}

    valid: list[CropSource] = []
    exclusions: list[Exclusion] = []
    for ann in sorted(coco["annotations"], key=lambda a: a["id"]):
        image_id = ann["image_id"]
        reason, scale = _check(ann, images, included_category_ids, image_sizes)
        if reason is not None:
            exclusions.append(Exclusion(ann["id"], image_id, reason))
            continue
        bbox = _as_bbox(ann.get("bbox"))
        assert bbox is not None and scale is not None  # _check ya descarto lo demas
        valid.append(
            CropSource(
                annotation_id=ann["id"],
                source_image_id=image_id,
                source_file_name=images[image_id]["file_name"],
                category_id=ann["category_id"],
                category_name=category_names[ann["category_id"]],
                bbox_xywh=bbox,
                pixel_scale=scale,
            )
        )
    return ValidationResult(tuple(valid), tuple(exclusions))


def _check(
    ann: Mapping[str, Any],
    images: Mapping[int, Mapping[str, Any]],
    included_category_ids: Collection[int],
    image_sizes: Mapping[int, ImageGeometry],
) -> tuple[ExclusionReason | None, tuple[float, float] | None]:
    if ann["category_id"] not in included_category_ids:
        return "excluded_category", None
    image_id = ann["image_id"]
    if image_id not in images or image_id not in image_sizes:
        return "missing_image", None
    bbox = _as_bbox(ann.get("bbox"))
    if bbox is None or bbox[2] <= 0 or bbox[3] <= 0:
        return "degenerate_bbox", None
    geometry = image_sizes[image_id]
    width, height = float(images[image_id]["width"]), float(images[image_id]["height"])
    x, y, w, h = bbox
    if x < 0 or y < 0 or x + w > width or y + h > height:
        return "bbox_out_of_bounds", None
    # P1 registro el tamano de la cabecera, sin girar: la deformacion se mide contra el.
    stored_w, stored_h = (
        (geometry.height, geometry.width)
        if geometry.exif_transposed
        else (geometry.width, geometry.height)
    )
    distortion = (stored_w / width) / (stored_h / height)
    if max(distortion, 1 / distortion) - 1 > MAX_ASPECT_DISTORTION:
        return "size_mismatch", None
    return None, (geometry.width / width, geometry.height / height)


def _as_bbox(value: Any) -> BBox | None:
    """La bbox como 4 floats finitos, o `None` si esta malformada."""
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value):
        return None
    x, y, w, h = (float(v) for v in value)
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        return None
    return (x, y, w, h)


# --- Recortes ------------------------------------------------------------------------------

EXCLUSIONS_HEADER = ("annotation_id", "image_id", "reason")


@dataclass(frozen=True)
class CropRecord:
    """Un recorte generado: la fila base del manifiesto (F3 agrega grupo y particion)."""

    crop_id: str
    annotation_id: int
    source_image_id: int
    source_file_name: str
    category_id: int
    category_name: str
    bbox_xywh: BBox
    pixel_scale: tuple[float, float]
    crop_box_xyxy: tuple[int, int, int, int]
    crop_path: str
    width: int
    height: int


def crop_id(release_id: str, annotation_id: int) -> str:
    """`"<release_id>:a<annotation_id>"`, unico y estable entre generaciones (contratos §2)."""
    return f"{release_id}:a{annotation_id}"


def crop_box(bbox: BBox, image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Caja en pixeles enteros `(left, top, right, bottom)` para `Image.crop`.

    Regla: piso a la izquierda y arriba, techo a la derecha y abajo, para cubrir
    todo pixel que la caja toca; se limita al lienzo (la validacion ya descarto
    las cajas fuera de la imagen) y se garantiza al menos un pixel.
    """
    x, y, w, h = bbox
    width, height = image_size
    left = min(max(math.floor(x), 0), width - 1)
    top = min(max(math.floor(y), 0), height - 1)
    right = min(max(math.ceil(x + w), left + 1), width)
    bottom = min(max(math.ceil(y + h), top + 1), height)
    return (left, top, right, bottom)


def generate_crops(
    valid: Iterable[CropSource], images_dir: Path, out_dir: Path, *, release_id: str
) -> list[CropRecord]:
    """Corta cada caja valida en `out_dir/<clase>/<release>_a<annotation_id>.png`.

    El original se abre como se mostro al anotar (rotacion EXIF aplicada) y la
    caja del COCO se escala con `pixel_scale` al tamano del archivo. PNG sin
    perdida y en RGB: el recorte conserva los pixeles del original sin una
    segunda compresion JPEG. Cada original se abre una sola vez. El resultado
    va ordenado por `annotation_id` y es determinista.
    """
    by_image: dict[str, list[CropSource]] = defaultdict(list)
    for source in valid:
        by_image[source.source_file_name].append(source)

    records: list[CropRecord] = []
    for file_name in sorted(by_image):
        image = open_as_displayed(images_dir / file_name)
        for source in by_image[file_name]:
            x, y, w, h = source.bbox_xywh
            sx, sy = source.pixel_scale
            box = crop_box((x * sx, y * sy, w * sx, h * sy), image.size)
            relative = f"{source.category_name}/{release_id}_a{source.annotation_id}.png"
            path = out_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            image.crop(box).save(path, format="PNG", optimize=False)
            records.append(
                CropRecord(
                    crop_id=crop_id(release_id, source.annotation_id),
                    annotation_id=source.annotation_id,
                    source_image_id=source.source_image_id,
                    source_file_name=source.source_file_name,
                    category_id=source.category_id,
                    category_name=source.category_name,
                    bbox_xywh=source.bbox_xywh,
                    pixel_scale=source.pixel_scale,
                    crop_box_xyxy=box,
                    crop_path=relative,
                    width=box[2] - box[0],
                    height=box[3] - box[1],
                )
            )
    return sorted(records, key=lambda record: record.annotation_id)


def write_exclusions_csv(exclusions: Iterable[Exclusion], path: Path) -> None:
    """`annotation_id,image_id,reason`, ordenado por `annotation_id`, con fin de linea LF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(EXCLUSIONS_HEADER)
        for exclusion in sorted(exclusions, key=lambda e: e.annotation_id):
            writer.writerow((exclusion.annotation_id, exclusion.source_image_id, exclusion.reason))
