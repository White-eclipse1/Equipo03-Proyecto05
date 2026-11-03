"""Inferencias persistidas: cada prediccion queda con su id (F4 T24, criterio 6.5).

Guarda la imagen tal como llego (hasta 10 MB) para poder mandarla despues a la
cola de anotacion de P1 sin pedirla otra vez, y la version y el SHA-256 del
modelo que predijo, para poder auditar la prediccion.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Engine, Integer, LargeBinary, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Timestamp = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
# BLOB de MariaDB se queda en 64 KB; las fotos llegan hasta 10 MB.
ImageBytes = LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql", "mariadb")


class Base(DeclarativeBase):
    """Metadata propia de la inferencia de P3."""


class Inference(Base):
    __tablename__ = "p3_inferences"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    image: Mapped[bytes] = mapped_column(ImageBytes)
    bbox_xywh: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    model_version: Mapped[str] = mapped_column(String(32))
    model_sha256: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str] = mapped_column(String(64))
    predicted_class: Mapped[str] = mapped_column(String(64))
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Id de la imagen creada en la cola de anotacion de P1 al enviarla.
    annotation_image_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def new_inference(**fields: Any) -> Inference:
    return Inference(id=uuid.uuid4().hex, created_at=datetime.now(UTC), **fields)
