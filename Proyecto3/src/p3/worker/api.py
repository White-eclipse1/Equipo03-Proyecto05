"""API de trabajos de entrenamiento: encolar y consultar.

`POST` solo inserta la fila y responde 202 con el `job_id`; el entrenamiento
corre en el worker, fuera del request HTTP. Un trabajo `train` valida su
`TrainingConfig` aqui: un valor invalido responde 422 nombrando el campo y no
se crea ninguna fila (criterio 2.2). Se monta en la app de Proyecto2
para que las paginas nuevas vivan en el mismo portal.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from p3.data.frozen import FROZEN_MANIFESTS, SWEEP_MANIFEST
from p3.train.config import TrainingConfig
from p3.worker import jobs

router = APIRouter(prefix="/api/p3/training", tags=["p3-training"])


def get_session() -> Iterator[Session]:
    from p3.worker.settings import get_session_factory

    with get_session_factory().begin() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


class DummyJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["dummy"]
    config: dict[str, Any] = Field(default_factory=dict)

    def stored_config(self) -> dict[str, Any]:
        return self.config


class TrainJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["train"]
    # Forma fija: el worker arma una ruta con este id.
    manifest_id: str = Field(pattern=r"^m-[0-9A-Za-z.]+-s[0-9]+-[0-9]+$")
    config: TrainingConfig
    # `p3-pruebas` para corridas de humo: no entran al barrido ni a la seleccion.
    experiment: Literal["p3-clasificador", "p3-pruebas"] = "p3-clasificador"

    def stored_config(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "experiment": self.experiment,
            "training": self.config.model_dump(mode="json"),
        }


JobCreate = Annotated[DummyJobCreate | TrainJobCreate, Field(discriminator="kind")]


class JobCreated(BaseModel):
    job_id: str
    status: jobs.JobStatus


class JobView(BaseModel):
    job_id: str
    kind: str
    status: jobs.JobStatus
    progress: float
    config: dict[str, Any]
    logs: list[str]
    error: str | None
    worker_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    mlflow_run_id: str | None

    @classmethod
    def from_job(cls, job: jobs.TrainingJob) -> JobView:
        return cls(
            job_id=job.id,
            kind=job.kind,
            status=jobs.JobStatus(job.status),
            progress=job.progress,
            config=job.config,
            logs=jobs.log_lines(job),
            error=job.error,
            worker_id=job.worker_id,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            mlflow_run_id=job.mlflow_run_id,
        )


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(body: JobCreate, session: SessionDep) -> JobCreated:
    if isinstance(body, TrainJobCreate) and body.manifest_id not in FROZEN_MANIFESTS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El manifiesto {body.manifest_id} no esta congelado; "
                f"solo se entrena con {sorted(FROZEN_MANIFESTS)}."
            ),
        )
    if (
        isinstance(body, TrainJobCreate)
        and body.experiment == "p3-clasificador"
        and body.manifest_id != SWEEP_MANIFEST
    ):
        # Las corridas de `p3-clasificador` (/runs y la seleccion) son del barrido.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El experimento p3-clasificador es el barrido sobre {SWEEP_MANIFEST}; "
                f"entrena {body.manifest_id} en p3-pruebas."
            ),
        )
    job = jobs.enqueue(session, kind=body.kind, config=body.stored_config())
    return JobCreated(job_id=job.id, status=jobs.JobStatus.QUEUED)


@router.get("/jobs/{job_id}")
def read_job(job_id: str, session: SessionDep) -> JobView:
    job = jobs.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No existe el trabajo {job_id}")
    return JobView.from_job(job)
