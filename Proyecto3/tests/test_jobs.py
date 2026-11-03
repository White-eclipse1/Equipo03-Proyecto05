"""Cola de trabajos de entrenamiento persistida en BD (F1 T02, criterio 6.1)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from p3.worker import jobs


def test_encolar_deja_el_trabajo_en_queued(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="dummy", config={"steps": 3})

    with session_factory() as session:
        stored = jobs.get_job(session, job.id)

    assert stored is not None
    assert stored.status == jobs.JobStatus.QUEUED
    assert stored.progress == 0.0
    assert stored.config == {"steps": 3}
    assert stored.started_at is None


def test_get_job_de_un_id_inexistente_es_none(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        assert jobs.get_job(session, "no-existe") is None


def test_claim_toma_el_mas_antiguo_y_lo_marca_running(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        primero = jobs.enqueue(session, kind="dummy", config={})
    with session_factory.begin() as session:
        jobs.enqueue(session, kind="dummy", config={})

    with session_factory.begin() as session:
        tomado = jobs.claim_next(session, worker_id="w1")
        assert tomado is not None
        tomado_id = tomado.id

    assert tomado_id == primero.id
    with session_factory() as session:
        stored = jobs.get_job(session, tomado_id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.RUNNING
        assert stored.worker_id == "w1"
        assert stored.started_at is not None


def test_claim_sin_trabajos_pendientes_es_none(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        assert jobs.claim_next(session, worker_id="w1") is None


def test_un_trabajo_tomado_no_se_vuelve_a_tomar(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        jobs.enqueue(session, kind="dummy", config={})
    with session_factory.begin() as session:
        assert jobs.claim_next(session, worker_id="w1") is not None
    with session_factory.begin() as session:
        assert jobs.claim_next(session, worker_id="w2") is None


def test_progreso_logs_y_exito_sobreviven_a_un_reinicio(
    make_engine: Callable[[], Engine],
) -> None:
    antes = sessionmaker(bind=make_engine(), expire_on_commit=False)
    with antes.begin() as session:
        job = jobs.enqueue(session, kind="dummy", config={})
    with antes.begin() as session:
        jobs.claim_next(session, worker_id="w1")
    with antes.begin() as session:
        jobs.report_progress(session, job.id, 0.5, "mitad")
    with antes.begin() as session:
        jobs.mark_succeeded(session, job.id)

    # Engine nuevo sobre el mismo archivo: equivale a reiniciar el backend.
    despues = sessionmaker(bind=make_engine())
    with despues() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.SUCCEEDED
        assert stored.progress == 1.0
        assert stored.finished_at is not None
        assert any("mitad" in linea for linea in jobs.log_lines(stored))


def test_el_error_queda_registrado(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="dummy", config={})
    with session_factory.begin() as session:
        jobs.claim_next(session, worker_id="w1")
    with session_factory.begin() as session:
        jobs.mark_failed(session, job.id, "ValueError: se acabo la memoria")

    with session_factory() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None
        assert stored.status == jobs.JobStatus.FAILED
        assert stored.error == "ValueError: se acabo la memoria"
        assert stored.finished_at is not None


@pytest.mark.parametrize("valor", [-0.1, 1.5])
def test_progreso_fuera_de_rango_se_rechaza(
    session_factory: sessionmaker[Session], valor: float
) -> None:
    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="dummy", config={})
    with session_factory.begin() as session, pytest.raises(ValueError, match="progress"):
        jobs.report_progress(session, job.id, valor)


def test_recuperar_huerfanos_marca_failed_los_running(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        huerfano = jobs.enqueue(session, kind="dummy", config={})
        pendiente = jobs.enqueue(session, kind="dummy", config={})
    with session_factory.begin() as session:
        jobs.claim_next(session, worker_id="w-muerto")

    with session_factory.begin() as session:
        recuperados = jobs.recover_orphans(session)

    assert recuperados == 1
    with session_factory() as session:
        h = jobs.get_job(session, huerfano.id)
        p = jobs.get_job(session, pendiente.id)
        assert h is not None and p is not None
        assert h.status == jobs.JobStatus.FAILED
        assert h.error is not None and "reinici" in h.error
        assert p.status == jobs.JobStatus.QUEUED


def test_el_trabajo_guarda_el_run_de_mlflow(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        job = jobs.enqueue(session, kind="dummy", config={})
    with session_factory.begin() as session:
        jobs.set_mlflow_run_id(session, job.id, "abc123")
    with session_factory() as session:
        stored = jobs.get_job(session, job.id)
        assert stored is not None and stored.mlflow_run_id == "abc123"


def test_create_schema_agrega_la_columna_a_una_tabla_de_t02(tmp_path) -> None:
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(f"sqlite:///{tmp_path / 'viejo.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE p3_training_jobs (id VARCHAR(32) PRIMARY KEY, kind VARCHAR(64), "
                "status VARCHAR(16), progress FLOAT, config JSON, logs TEXT, error TEXT, "
                "worker_id VARCHAR(128), created_at DATETIME, started_at DATETIME, "
                "finished_at DATETIME)"
            )
        )
    jobs.create_schema(engine)
    jobs.create_schema(engine)  # idempotente
    columnas = {c["name"] for c in inspect(engine).get_columns("p3_training_jobs")}
    assert "mlflow_run_id" in columnas
