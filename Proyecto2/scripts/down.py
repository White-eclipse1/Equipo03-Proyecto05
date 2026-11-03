"""Apaga el entorno local.

python scripts/down.py            # para los contenedores, conserva los datos
python scripts/down.py --volumes  # borra tambien la BD y los buckets
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Apaga el entorno local.")
    parser.add_argument(
        "--volumes",
        action="store_true",
        help="Borra tambien los volumenes (MariaDB y MinIO). Destructivo.",
    )
    args = parser.parse_args()

    command = ["docker", "compose", "down"]
    if args.volumes:
        confirmation = input("Esto BORRA la base de datos y los buckets. Escribe 'si': ")
        if confirmation.strip().lower() not in {"si", "sí"}:
            print("Cancelado.")
            return
        command.append("-v")

    print(f"$ {' '.join(command)}")
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
