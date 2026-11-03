"""Escribe `.dvc/config.local` con las credenciales del remote `dev`.

    python scripts/dvc_remote.py

`.dvc/config` (versionado) declara la URL de los dos remotes, `dev` (MinIO
local) y `prod` (S3), pero nunca una credencial: es la misma regla de cero
secretos en el codigo que aplica el Frente 1 a `.env`. Las claves de acceso
salen de `.env` y se escriben en `.dvc/config.local`, que DVC ignora por
defecto (`.dvc/.gitignore` ya trae `/config.local`).

Solo usa la libreria estandar, igual que `scripts/up.py`, para no exigir un
entorno virtual solo para levantar el proyecto.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"


def find_dvc() -> str:
    """Ubica el ejecutable `dvc`, este o no el venv "activado" en el shell.

    `dvc` es una dependencia opcional (`pip install -e ".[pipeline]"`), asi
    que vive en `.venv/bin/dvc` junto al interprete que corre este script
    (`sys.executable`) incluso cuando el shell no tiene el venv activado.
    Buscarlo ahi primero evita el error confuso de "dvc no encontrado" que
    sale si alguien corre `python scripts/dvc_remote.py` con el venv sin
    activar, en vez de `.venv/bin/python scripts/dvc_remote.py`.
    """
    # En Windows el ejecutable es `dvc.exe`; en Linux y macOS, `dvc` a secas.
    for nombre in ("dvc.exe", "dvc"):
        junto_al_interprete = Path(sys.executable).with_name(nombre)
        if junto_al_interprete.is_file():
            return str(junto_al_interprete)

    en_path = shutil.which("dvc")
    if en_path is not None:
        return en_path

    fail(
        "No se encontro el ejecutable `dvc`. Instalalo con "
        '`pip install -e ".[pipeline]"` dentro del entorno virtual.'
    )
    raise AssertionError("unreachable")  # fail() no vuelve, pero mypy no lo sabe


def fail(message: str) -> None:
    print(f"\n\033[31mError:\033[0m {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def read_env() -> dict[str, str]:
    """Mismo parser minimo de `.env` que usa `scripts/up.py`."""
    if not ENV_PATH.is_file():
        fail(f"No existe {ENV_PATH}. Corre `python scripts/up.py` primero (crea el .env).")
    values: dict[str, str] = {}
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def dvc(*args: str) -> None:
    result = subprocess.run(
        [find_dvc(), *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        fail(f"`dvc {' '.join(args)}` fallo:\n{result.stderr}")


def main() -> None:
    env = read_env()
    required = ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD")
    faltantes = [key for key in required if key not in env]
    if faltantes:
        fail(f"Faltan en .env: {', '.join(faltantes)}")

    dvc("remote", "modify", "--local", "dev", "access_key_id", env["MINIO_ROOT_USER"])
    dvc("remote", "modify", "--local", "dev", "secret_access_key", env["MINIO_ROOT_PASSWORD"])

    print(
        "\033[32m.dvc/config.local escrito.\033[0m Remote 'dev' listo para "
        "`dvc push` / `dvc pull` contra MinIO."
    )
    print(
        "\033[90mEl remote 'prod' necesita sus propias credenciales de AWS "
        "reales; configuralas a mano con `dvc remote modify --local prod ...` "
        "cuando haya un bucket de produccion.\033[0m"
    )


if __name__ == "__main__":
    main()
