"""Exporta MLflow (registros SQLite + artefactos) a `Proyecto3/mlflow_snapshot/` (F4 T12, 3.2).

Las corridas viven en el volumen `mlflow_data` de la maquina que entreno. Para
que el evaluador las vea desde un clon limpio, se copian a esta carpeta, que se
versiona con DVC; al levantar el stack, el servicio `mlflow-restore` las carga
en un volumen vacio.

MLflow se detiene durante la copia para que la base SQLite quede consistente y
se vuelve a arrancar al terminar. Solo lee del contenedor: no borra corridas.

    python scripts/mlflow_snapshot.py
    cd Proyecto3 && dvc add mlflow_snapshot && dvc push mlflow_snapshot.dvc
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROYECTO3 = Path(__file__).resolve().parents[1]
PROYECTO2 = PROYECTO3.parent / "Proyecto2"
SNAPSHOT = PROYECTO3 / "mlflow_snapshot"
CONTAINER = "p3_mlflow"


def run(*command: str) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=PROYECTO2)


def main() -> int:
    if SNAPSHOT.exists():
        shutil.rmtree(SNAPSHOT)
    SNAPSHOT.mkdir()
    run("docker", "compose", "stop", "mlflow")
    try:
        run("docker", "cp", f"{CONTAINER}:/mlflow/.", str(SNAPSHOT))
    finally:
        run("docker", "compose", "start", "mlflow")
    if not (SNAPSHOT / "mlflow.db").is_file():
        sys.exit("La copia no trae mlflow.db: revisa `docker compose logs mlflow`.")
    size = sum(f.stat().st_size for f in SNAPSHOT.rglob("*") if f.is_file())
    print(f"Snapshot listo en {SNAPSHOT} ({size / 1e6:.1f} MB).")
    print("Siguiente: cd Proyecto3 && dvc add mlflow_snapshot && dvc push mlflow_snapshot.dvc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
