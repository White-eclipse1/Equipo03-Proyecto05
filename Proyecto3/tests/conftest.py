"""Fixtures compartidas: una BD SQLite en archivo por prueba.

En archivo y no en memoria: asi "reiniciar" es abrir un engine nuevo sobre el
mismo archivo y se prueba que el estado sobrevive, no que quedo en un objeto.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from p3.worker.jobs import create_schema


@pytest.fixture
def make_engine(tmp_path: Path) -> Callable[[], Engine]:
    url = f"sqlite:///{tmp_path / 'jobs.db'}"

    def factory() -> Engine:
        engine = create_engine(url, future=True)
        create_schema(engine)
        return engine

    return factory


@pytest.fixture
def session_factory(make_engine: Callable[[], Engine]) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(), autoflush=False, expire_on_commit=False)
