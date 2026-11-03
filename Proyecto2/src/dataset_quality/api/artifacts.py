"""Endpoints que sirven los artefactos del pipeline a la app web.

Cada artefacto se lee de `reports/`, se **valida contra su contrato** y se
devuelve envuelto en un sobre que dice de donde salio:

    {"source": "pipeline", "produced_by": "dq gate", "data": {...}}

Validar antes de servir no es ceremonia: si un archivo en disco dejo de cumplir
su contrato — porque alguien cambio un modelo y no regenero el artefacto — es
mejor un 500 que lo diga que una pantalla pintando basura en silencio.

Ningun endpoint recalcula nada. La app web dibuja lo que el pipeline decidio, y
esa separacion es la que permite construir la UI contra los contratos sin
esperar a que el pipeline termine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from PIL import Image, UnidentifiedImageError

from dataset_quality.models.exploration import ExplorationManifest
from dataset_quality.models.quality import QualityReport
from dataset_quality.models.splits import SplitsManifest
from dataset_quality.models.stats import AnalysisArtifact
from dataset_quality.models.versions import VersionsManifest, backfill_remotes

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS = REPO_ROOT / "reports"

router = APIRouter(prefix="/api", tags=["artefactos"])


@dataclass(frozen=True)
class Artifact:
    """Un artefacto del pipeline: donde vive, que contrato cumple y quien lo crea."""

    name: str
    path: Path
    model: type
    produced_by: str


ARTIFACTS: dict[str, Artifact] = {
    "quality": Artifact("quality", REPORTS / "quality.json", QualityReport, "dq gate"),
    "splits": Artifact("splits", REPORTS / "splits.json", SplitsManifest, "dq split"),
    "versions": Artifact("versions", REPORTS / "versions.json", VersionsManifest, "dq release"),
    "exploration": Artifact(
        "exploration", REPORTS / "exploration.json", ExplorationManifest, "dq analyze"
    ),
    "stats": Artifact("stats", REPORTS / "stats.json", AnalysisArtifact, "dq analyze --json"),
}


@dataclass(frozen=True)
class LoadedArtifact:
    """Artefacto validado y su revision inmutable para consumidores internos."""

    artifact: Artifact
    data: Any
    revision: str

    def source(self) -> dict[str, str | None]:
        generated_at = getattr(self.data, "generated_at", None)
        dataset_fingerprint = getattr(self.data, "dataset_fingerprint", None)
        return {
            "artifact": self.artifact.path.name,
            "artifact_revision": self.revision,
            "generated_at": generated_at.isoformat() if generated_at is not None else None,
            "dataset_fingerprint": dataset_fingerprint,
        }


def read(artifact: Artifact) -> LoadedArtifact:
    """Lee y valida un artefacto; nunca entrega JSON no validado al Copilot."""
    if not artifact.path.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Todavia no existe `{artifact.path.name}`. "
                f"Corre `{artifact.produced_by}` para generarlo."
            ),
        )

    try:
        raw = artifact.path.read_bytes()
        validado = artifact.model.model_validate_json(raw)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=(
                f"`{artifact.path.name}` ya no cumple el contrato de "
                f"{artifact.model.__name__}: {error}"
            ),
        ) from error

    return LoadedArtifact(artifact=artifact, data=validado, revision=sha256(raw).hexdigest())


def load(artifact: Artifact) -> dict[str, Any]:
    """Envuelve un artefacto validado para los endpoints de la SPA."""
    loaded = read(artifact)
    return {
        "source": "pipeline",
        "produced_by": artifact.produced_by,
        "data": json.loads(loaded.data.model_dump_json()),
    }


@router.get("/status")
def status() -> dict[str, Any]:
    """Que artefactos existen. La app lo consulta al arrancar para orientarse."""
    return {
        name: {"available": artifact.path.is_file(), "produced_by": artifact.produced_by}
        for name, artifact in ARTIFACTS.items()
    }


@router.get("/quality")
def quality() -> dict[str, Any]:
    """Overview y Analyzers: el veredicto de la compuerta, valor contra umbral."""
    return load(ARTIFACTS["quality"])


@router.get("/splits")
def splits() -> dict[str, Any]:
    """Splits: reparto train/val/test, su semilla y sus conteos."""
    return load(ARTIFACTS["splits"])


@router.get("/versions")
def versions() -> dict[str, Any]:
    """Versions: historial de releases, sus tres huellas y donde esta cada una.

    Las entradas anteriores a `published_in` pasan por `backfill_remotes`: sin
    eso la pantalla mostraria como "sin publicar" versiones que llevan meses en
    el remote. La migracion se aplica al leer, nunca al escribir.
    """
    loaded = read(ARTIFACTS["versions"])
    migrado = backfill_remotes(loaded.data)
    return {
        "source": "pipeline",
        "produced_by": ARTIFACTS["versions"].produced_by,
        "data": json.loads(migrado.model_dump_json()),
    }


@router.get("/exploration")
def exploration() -> dict[str, Any]:
    """Exploracion: la proyeccion 2D precomputada."""
    return load(ARTIFACTS["exploration"])


# Lado del cuadrado de la miniatura, en pixeles. Suficiente para reconocer la
# foto al pasar el raton y lo bastante chico para que quepan cientos en el
# navegador sin que la pantalla se vuelva un visor de imagenes.
THUMBNAIL_PX = 160


@lru_cache(maxsize=512)
def _thumbnail_bytes(path: str, mtime_ns: int, size: int) -> bytes:
    """Genera el JPEG de la miniatura y lo cachea en memoria.

    `mtime_ns` no se usa dentro: esta en la firma para que el cache se invalide
    solo si el archivo cambia en disco. Sin el, una imagen reemplazada seguiria
    sirviendo la miniatura vieja hasta reiniciar el proceso.
    """
    del mtime_ns
    with Image.open(path) as handle:
        rgb = handle.convert("RGB")
        rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        rgb.save(buffer, "JPEG", quality=78)
    return buffer.getvalue()


@router.get("/exploration/thumbnail/{image_id}", response_class=Response)
def exploration_thumbnail(image_id: int) -> Response:
    """La miniatura de una imagen del dataset, para el hover del grafico.

    El `image_id` se traduce a nombre de archivo mirando el propio manifiesto,
    NO concatenando lo que llegue por la URL: asi la ruta servida solo puede
    ser una de las que el pipeline ya registro, y no hay forma de pedir
    `../../.env` por mucho que se insista.
    """
    from dataset_quality.tiers.ingest import RAW_IMAGES

    manifiesto = read(ARTIFACTS["exploration"]).data
    punto = next((p for p in manifiesto.points if p.image_id == image_id), None)
    if punto is None:
        raise HTTPException(status_code=404, detail=f"image_id {image_id} no esta en la proyeccion")
    if not punto.file_name:
        raise HTTPException(
            status_code=503,
            detail=(
                "La proyeccion es anterior a `file_name`: corre `dq analyze` para regenerarla."
            ),
        )

    # `Path(...).name` descarta cualquier componente de directorio que se haya
    # colado en el COCO; el archivo solo puede salir de `data/raw/images/`.
    ruta = RAW_IMAGES / Path(punto.file_name).name
    if not ruta.is_file():
        raise HTTPException(
            status_code=404, detail=f"`{punto.file_name}` ya no esta en {RAW_IMAGES}"
        )

    try:
        contenido = _thumbnail_bytes(str(ruta), ruta.stat().st_mtime_ns, THUMBNAIL_PX)
    except (UnidentifiedImageError, OSError) as error:
        raise HTTPException(
            status_code=500, detail=f"no se pudo leer `{punto.file_name}`: {error}"
        ) from error

    return Response(
        content=contenido,
        media_type="image/jpeg",
        # Inmutable mientras el archivo no cambie: la pantalla pide la misma
        # miniatura cada vez que el raton vuelve a pasar por el punto.
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/stats")
def stats() -> dict[str, Any]:
    """Descriptiva del Tier 2: el contexto sin el cual un umbral no dice nada."""
    return load(ARTIFACTS["stats"])
