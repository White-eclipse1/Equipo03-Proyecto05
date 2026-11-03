"""Restaura el snapshot de MLflow en su volumen (servicio `mlflow-restore`, M1).

Corre dentro de la imagen de MLflow antes del servidor, solo con la libreria
estandar: `python3 /restore.py /snapshot /mlflow`.

Restaura si el volumen no tiene `mlflow.db` o si la base no tiene ninguna
corrida. Lo segundo pasa cuando `up.py` corre antes que `dvc pull`: el servidor
ya creo su base vacia y, sin este caso, las corridas del barrido no se
cargarian nunca. Una base con corridas nunca se toca.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def _run_count(db: Path) -> int:
    try:
        with closing(sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)) as conn:
            return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    except sqlite3.OperationalError:
        return 0  # base recien creada, sin tablas todavia


def restore(snapshot: Path, volume: Path) -> str:
    if not (snapshot / "mlflow.db").is_file():
        return "sin snapshot"
    target = volume / "mlflow.db"
    if target.is_file() and _run_count(target) > 0:
        return "con datos"
    target.unlink(missing_ok=True)
    shutil.copytree(snapshot, volume, dirs_exist_ok=True)
    return "restaurado"


MESSAGES = {
    "sin snapshot": "Sin snapshot (falta `dvc pull` en Proyecto3): MLflow arranca vacio.",
    "con datos": "MLflow ya tiene corridas; no se restaura.",
    "restaurado": "Snapshot restaurado.",
}

if __name__ == "__main__":
    print(MESSAGES[restore(Path(sys.argv[1]), Path(sys.argv[2]))])
