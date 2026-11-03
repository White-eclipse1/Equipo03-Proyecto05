"""Tablas relacionales (SQLAlchemy 2.0).

Ojo con la palabra "modelo", que aqui significa dos cosas distintas:

  - `dataset_quality.models` son modelos **Pydantic**: contratos que validan
    datos que cruzan la frontera del sistema. Viven en memoria y se descartan.
  - este modulo define modelos **SQLAlchemy**: las tablas donde viven las filas.

El Tier 1 traduce de los primeros a los segundos.

Reparto de responsabilidades entre los dos almacenes:

  - **MariaDB** guarda lo que se consulta y se agrega: que imagenes hay, sus
    dimensiones, que cajas tienen y de que clase.
  - **MinIO** guarda los bytes de las imagenes. En `images.storage_key` queda
    la llave del objeto; el binario nunca entra en una columna.

Meter un JPEG en la base funciona con diez fotos y se derrumba con novecientas:
las copias de seguridad tardan horas y no se puede servir la imagen sin pasarla
entera por el servidor.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Category(Base):
    """Una clase del dataset. El id es el del COCO, no autoincremental."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    supercategory: Mapped[str | None] = mapped_column(String(100), nullable=True)

    annotations: Mapped[list[Annotation]] = relationship(back_populates="category")


class Image(Base):
    """Metadatos de una imagen. Los bytes viven en MinIO, no aqui."""

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    file_name: Mapped[str] = mapped_column(String(255), unique=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)

    # Llave del objeto en el bucket de imagenes, p. ej. `raw/img_0001.jpg`.
    storage_key: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # Huella del contenido: permite saltarse una subida ya hecha y detectar
    # que un archivo cambio sin depender de la fecha de modificacion.
    sha256: Mapped[str] = mapped_column(String(64))

    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    annotations: Mapped[list[Annotation]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_images_sha256", "sha256"),)


class Annotation(Base):
    """Una bounding box. Coordenadas absolutas en pixeles, como exige COCO."""

    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))

    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    area: Mapped[float] = mapped_column(Float)
    iscrowd: Mapped[int] = mapped_column(SmallInteger, default=0)

    image: Mapped[Image] = relationship(back_populates="annotations")
    category: Mapped[Category] = relationship(back_populates="annotations")

    __table_args__ = (
        Index("idx_annotations_image", "image_id"),
        Index("idx_annotations_category", "category_id"),
    )


class Split(Base):
    """La asignacion de una imagen a train/val/test (Frente 5).

    El artefacto canonico es `reports/splits.json`; esta tabla es la misma
    informacion consultable desde SQL para la app web (Frente 7). Una imagen
    tiene como maximo una fila — reflejo del "cero fuga" que ya exige
    `SplitsManifest` en el JSON — y `id` es autoincremental porque, a
    diferencia de images/categories/annotations, no viene de un id de COCO.
    """

    __tablename__ = "splits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), unique=True)
    split: Mapped[str] = mapped_column(String(10))
    seed: Mapped[int] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    image: Mapped[Image] = relationship()

    __table_args__ = (Index("idx_splits_split", "split"),)


class DatasetVersionRow(Base):
    """Una version publicada del dataset (Frente 6, `dq release`).

    El artefacto canonico sigue siendo `reports/versions.json`; esta tabla
    es para consulta desde la app web (Frente 7), igual que `Split`. Se llama
    `DatasetVersionRow` y no `DatasetVersion` para no chocar con el modelo
    Pydantic del mismo nombre en `models.versions` — son dos objetos
    distintos (fila SQL vs. contrato validado) que conviene poder importar
    juntos sin alias.
    """

    __tablename__ = "dataset_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True)
    dataset_fingerprint: Mapped[str] = mapped_column(String(64))
    quality_report_fingerprint: Mapped[str] = mapped_column(String(64))
    splits_fingerprint: Mapped[str] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(String(512))
    quality_status: Mapped[str] = mapped_column(String(10))
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("idx_dataset_versions_created_at", "created_at"),)


class CopilotToolCall(Base):
    """Auditoria de una llamada MCP, sin conservar la conversacion.

    Se registran argumentos saneados y la revision del reporte, pero nunca la
    pregunta, respuesta, payload completo de la herramienta ni secretos.
    """

    __tablename__ = "copilot_tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    call_id: Mapped[str] = mapped_column(String(128), unique=True)
    tool_name: Mapped[str] = mapped_column(String(80))
    arguments: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    duration_ms: Mapped[int] = mapped_column(Integer)
    source_artifact: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_dataset_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("idx_copilot_tool_calls_request_created", "request_id", "created_at"),)
