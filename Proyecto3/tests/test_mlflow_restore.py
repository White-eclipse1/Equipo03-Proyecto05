"""Restaurar el snapshot de MLflow sin depender del orden de arranque (M1, F1).

Con el README, `up.py` puede correr antes que `dvc pull`: el servidor crea un
`mlflow.db` vacio y, si la restauracion solo mirara si el archivo existe, las
12 corridas del barrido no se cargarian nunca. Se restaura si el volumen no
tiene base o si la base no tiene ninguna corrida; nunca se pisa una base con
corridas.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from p3 import mlflow_restore


def _db(path: Path, runs: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE runs (run_uuid TEXT)")
        conn.executemany("INSERT INTO runs VALUES (?)", [(f"r{i}",) for i in range(runs)])


def _snapshot(tmp_path: Path) -> Path:
    snapshot = tmp_path / "snapshot"
    _db(snapshot / "mlflow.db", runs=12)
    (snapshot / "artifacts" / "3").mkdir(parents=True)
    (snapshot / "artifacts" / "3" / "curves.png").write_bytes(b"png")
    return snapshot


def _runs(path: Path) -> int:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def test_volumen_vacio_restaura(tmp_path: Path) -> None:
    volume = tmp_path / "mlflow"
    volume.mkdir()
    assert mlflow_restore.restore(_snapshot(tmp_path), volume) == "restaurado"
    assert _runs(volume / "mlflow.db") == 12
    assert (volume / "artifacts" / "3" / "curves.png").read_bytes() == b"png"


def test_base_creada_por_el_servidor_sin_corridas_restaura(tmp_path: Path) -> None:
    # up.py antes de dvc pull: MLflow ya creo su mlflow.db, pero sin corridas.
    volume = tmp_path / "mlflow"
    _db(volume / "mlflow.db", runs=0)
    assert mlflow_restore.restore(_snapshot(tmp_path), volume) == "restaurado"
    assert _runs(volume / "mlflow.db") == 12


def test_base_sin_tabla_de_corridas_restaura(tmp_path: Path) -> None:
    volume = tmp_path / "mlflow"
    volume.mkdir()
    sqlite3.connect(volume / "mlflow.db").close()
    assert mlflow_restore.restore(_snapshot(tmp_path), volume) == "restaurado"
    assert _runs(volume / "mlflow.db") == 12


def test_nunca_pisa_una_base_con_corridas(tmp_path: Path) -> None:
    volume = tmp_path / "mlflow"
    _db(volume / "mlflow.db", runs=13)
    assert mlflow_restore.restore(_snapshot(tmp_path), volume) == "con datos"
    assert _runs(volume / "mlflow.db") == 13
    assert not (volume / "artifacts").exists()


def test_sin_snapshot_no_toca_nada(tmp_path: Path) -> None:
    volume = tmp_path / "mlflow"
    volume.mkdir()
    (tmp_path / "snapshot").mkdir()  # Docker crea la carpeta vacia si falta dvc pull
    assert mlflow_restore.restore(tmp_path / "snapshot", volume) == "sin snapshot"
    assert list(volume.iterdir()) == []
