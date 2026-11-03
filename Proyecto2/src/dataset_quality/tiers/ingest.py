"""Tier 1 — ingesta del COCO crudo.

Toma lo que dejo `scripts/export_from_mp1.py` en `data/raw/` y lo reparte entre
los dos almacenes:

    data/raw/annotations.coco.json ──► CocoDataset (Pydantic)
                                            │
                          ┌─────────────────┴─────────────────┐
                          ▼                                   ▼
            MinIO: los bytes de cada imagen        MariaDB: metadatos y cajas
            (bucket de imagenes, `raw/<archivo>`)  (categories/images/annotations)

Tres propiedades que el Tier 1 garantiza:

**Valida antes de escribir.** El COCO pasa entero por los modelos Pydantic. Si
viene roto se rechaza aqui, nombrando el campo, y no a mitad del analisis.

**Sube antes de registrar.** Los objetos van primero y las filas despues, de
modo que nunca queda una fila apuntando a un objeto que no existe. Al reves si
puede pasar (un objeto huerfano), que es el fallo barato de los dos.

**Es idempotente.** Correrla dos veces deja el mismo estado: las imagenes que
ya estan en MinIO no se vuelven a subir, y las tablas se redefinen en vez de
acumular. El Tier 1 *define* el estado, no lo va sumando.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete

from dataset_quality.db import create_schema, session_scope
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.errors import from_pydantic, single_issue
from dataset_quality.settings import get_settings
from dataset_quality.storage import ensure_bucket, file_sha256, image_key, upload_image
from dataset_quality.tables import Annotation, Category, Image

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = REPO_ROOT / "data" / "raw"
RAW_ANNOTATIONS = RAW_DIR / "annotations.coco.json"
RAW_IMAGES = RAW_DIR / "images"

# Subir de a una imagen desaprovecha la red; mas de ocho hilos no mejora contra
# un MinIO local y empieza a competir por el disco.
UPLOAD_WORKERS = 8


@dataclass(frozen=True)
class StoredImage:
    """Donde quedo el binario de una imagen y con que huella."""

    key: str
    size_bytes: int
    sha256: str


@dataclass
class IngestSummary:
    images: int
    annotations: int
    categories: int
    uploaded: int
    already_stored: int
    bucket: str
    missing_files: list[str] = field(default_factory=list)

    @property
    def uploaded_all(self) -> bool:
        return not self.missing_files


def load_raw(path: Path = RAW_ANNOTATIONS) -> CocoDataset:
    """Lee y valida el COCO crudo.

    Los errores de Pydantic se traducen a `DatasetValidationError`, que imprime
    la ruta del campo y el valor recibido en vez de un volcado ilegible.
    """
    if not path.exists():
        raise single_issue(
            source=str(path),
            location="archivo",
            message=(
                "no existe; corre `python scripts/export_from_mp1.py` para traerlo "
                "del portal de anotacion"
            ),
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise single_issue(
            source=str(path),
            location=f"linea {error.lineno}, columna {error.colno}",
            message=f"JSON malformado: {error.msg}",
        ) from error

    try:
        return CocoDataset.model_validate(raw)
    except Exception as error:  # ValidationError de Pydantic
        from pydantic import ValidationError

        if isinstance(error, ValidationError):
            raise from_pydantic(str(path), error) from error
        raise


def check_files_present(dataset: CocoDataset, images_dir: Path) -> list[str]:
    """Nombres del COCO que no tienen archivo en disco.

    Un COCO puede ser valido y aun asi referenciar imagenes que no se
    descargaron: eso no es un error de formato, es una descarga incompleta.
    """
    return [
        image.file_name for image in dataset.images if not (images_dir / image.file_name).is_file()
    ]


def upload_images(
    dataset: CocoDataset,
    images_dir: Path,
    bucket: str,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[int, StoredImage], int]:
    """Sube los binarios a MinIO.

    Devuelve el mapa `image_id -> StoredImage` y cuantas se subieron de verdad
    (el resto ya estaban). Se paraleliza porque son cientos de archivos y cada
    subida es una espera de red: en serie tarda minutos, con ocho hilos son
    segundos.
    """
    ensure_bucket(bucket)

    def put(image: object) -> tuple[int, StoredImage, bool]:
        path = images_dir / image.file_name  # type: ignore[attr-defined]
        key = image_key(image.file_name)  # type: ignore[attr-defined]
        uploaded = upload_image(path, bucket, key)
        record = StoredImage(key=key, size_bytes=path.stat().st_size, sha256=file_sha256(path))
        return image.id, record, uploaded  # type: ignore[attr-defined]

    stored: dict[int, StoredImage] = {}
    uploaded_count = 0
    total = len(dataset.images)

    with ThreadPoolExecutor(max_workers=UPLOAD_WORKERS) as pool:
        for done, (image_id, record, uploaded) in enumerate(pool.map(put, dataset.images), start=1):
            stored[image_id] = record
            uploaded_count += int(uploaded)
            if on_progress is not None:
                on_progress(done, total)

    return stored, uploaded_count


def persist(dataset: CocoDataset, stored: dict[int, StoredImage]) -> None:
    """Vuelca el dataset validado a MariaDB, redefiniendo el estado anterior."""
    create_schema()
    with session_scope() as session:
        # Orden inverso a las claves foraneas: primero lo que depende.
        session.execute(delete(Annotation))
        session.execute(delete(Image))
        session.execute(delete(Category))
        session.flush()

        session.add_all(
            [
                Category(id=item.id, name=item.name, supercategory=item.supercategory)
                for item in dataset.categories
            ]
        )
        session.add_all(
            [
                Image(
                    id=item.id,
                    file_name=item.file_name,
                    width=item.width,
                    height=item.height,
                    storage_key=stored[item.id].key,
                    size_bytes=stored[item.id].size_bytes,
                    sha256=stored[item.id].sha256,
                )
                for item in dataset.images
            ]
        )
        session.flush()

        session.add_all(
            [
                Annotation(
                    id=item.id,
                    image_id=item.image_id,
                    category_id=item.category_id,
                    x=item.bbox[0],
                    y=item.bbox[1],
                    width=item.bbox[2],
                    height=item.bbox[3],
                    area=item.area,
                    iscrowd=item.iscrowd,
                )
                for item in dataset.annotations
            ]
        )


def run(
    path: Path = RAW_ANNOTATIONS,
    images_dir: Path = RAW_IMAGES,
    on_progress: Callable[[int, int], None] | None = None,
) -> IngestSummary:
    """Ejecuta el Tier 1 completo."""
    dataset = load_raw(path)

    missing = check_files_present(dataset, images_dir)
    if missing:
        raise single_issue(
            source=str(images_dir),
            location="images",
            message=(
                f"{len(missing)} imagenes del COCO no estan en disco "
                f"(ej. {', '.join(missing[:3])}). "
                f"Corre `python scripts/export_from_mp1.py` para completarlas."
            ),
        )

    # La configuracion se lee despues de validar: un COCO roto se rechaza
    # igual, aunque el entorno todavia no tenga credenciales (p. ej. en CI).
    bucket = get_settings().minio_bucket_images
    stored, uploaded = upload_images(dataset, images_dir, bucket, on_progress)

    persist(dataset, stored)

    return IngestSummary(
        images=len(dataset.images),
        annotations=len(dataset.annotations),
        categories=len(dataset.categories),
        uploaded=uploaded,
        already_stored=len(dataset.images) - uploaded,
        bucket=bucket,
        missing_files=missing,
    )
