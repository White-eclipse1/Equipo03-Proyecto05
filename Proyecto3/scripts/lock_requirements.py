"""Regenera `requirements.lock.txt` de Proyecto 3 dentro de `python:3.12-slim`.

Mismo procedimiento que `Proyecto2/scripts/lock_requirements.py`: pip-compile
corre en la imagen del worker (Linux) y parte del lockfile actual, asi que solo
cambia lo que exige `pyproject.toml`; subir versiones es explicito (`--upgrade`).

Diferencia con P2: PyTorch en Linux arrastra CUDA (`nvidia-*`, `cuda-*`,
`triton`), que no existe en Windows ni en macOS. Esas lineas se marcan
`; sys_platform == 'linux' and platform_machine == 'x86_64'` para que el mismo
lockfile instale el worker con GPU y el venv de Windows/Mac del equipo (donde
`torch` de PyPI es de CPU).

    python scripts/lock_requirements.py
    python scripts/lock_requirements.py --check     # falla si esta desactualizado
    python scripts/lock_requirements.py --upgrade   # sube todo a lo ultimo que admiten los rangos
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROYECTO3_DIR = Path(__file__).resolve().parent.parent
LOCKFILE = PROYECTO3_DIR / "requirements.lock.txt"

IMAGEN = "python:3.12-slim"
PIP_TOOLS = "pip-tools==7.4.1"
EXTRAS = ("train", "dev")

CABECERA = """#
# Lockfile de Proyecto 3: la version EXACTA de cada paquete. Se regenera SIEMPRE
# dentro de `python:3.12-slim` (la imagen del worker), nunca desde un venv local:
#
#    python scripts/lock_requirements.py
#
# Los paquetes de CUDA solo existen para Linux x86_64; llevan marcador para que
# este mismo archivo se instale tambien en Windows y macOS (torch de CPU).
#
"""

SOLO_LINUX = re.compile(r"^(nvidia-[\w-]+|cuda-[\w-]+|triton)==\S+$")
MARCADOR = " ; sys_platform == 'linux' and platform_machine == 'x86_64'"


def compilar(upgrade: bool = False) -> str:
    """Devuelve el lockfile que resuelve pip-compile dentro del contenedor."""
    semilla = (
        "grep -v \" ; sys_platform == 'linux'\" requirements.lock.txt "
        "> /salida/requirements.lock.txt; "
        if LOCKFILE.exists() and not upgrade
        else ""
    )
    extras = " ".join(f"--extra {extra}" for extra in EXTRAS)
    guion = (
        f"{semilla}pip install -q --root-user-action=ignore {PIP_TOOLS} && "
        f"pip-compile --quiet --strip-extras {extras} "
        f"{'--upgrade ' if upgrade else ''}"
        # Ruta RELATIVA: pip-compile la copia en los comentarios `# via`.
        "--output-file /salida/requirements.lock.txt pyproject.toml && "
        "cat /salida/requirements.lock.txt"
    )
    resultado = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{PROYECTO3_DIR}:/w:ro",
            "-w",
            "/w",
            "--tmpfs",
            "/salida",
            IMAGEN,
            "bash",
            "-c",
            guion,
        ],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        sys.exit(f"pip-compile fallo dentro de {IMAGEN}:\n{resultado.stderr.strip()}")
    return resultado.stdout


def normalizar(crudo: str) -> str:
    """Cambia la cabecera generada por la nuestra y marca los paquetes solo-Linux."""
    lineas = crudo.splitlines(keepends=True)
    corte = next((i for i, linea in enumerate(lineas) if not linea.startswith("#")), 0)
    cuerpo = []
    for linea in lineas[corte:]:
        paquete = linea.rstrip("\n")
        cuerpo.append(paquete + MARCADOR + "\n" if SOLO_LINUX.match(paquete) else linea)
    return CABECERA + "".join(cuerpo)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="No escribe; falla si no coincide.")
    parser.add_argument("--upgrade", action="store_true", help="Ignora los pines actuales.")
    args = parser.parse_args()
    if args.check and args.upgrade:
        parser.error("--check y --upgrade no se combinan")

    nuevo = normalizar(compilar(upgrade=args.upgrade))

    if args.check:
        actual = LOCKFILE.read_text(encoding="utf-8") if LOCKFILE.exists() else ""
        if actual != nuevo:
            print(
                "requirements.lock.txt no coincide con lo que resuelve pyproject.toml.\n"
                "Corre `python scripts/lock_requirements.py` y commitea el resultado.",
                file=sys.stderr,
            )
            return 1
        print("requirements.lock.txt esta al dia.")
        return 0

    LOCKFILE.write_text(nuevo, encoding="utf-8", newline="\n")
    pines = sum(1 for linea in nuevo.splitlines() if "==" in linea and not linea.startswith("#"))
    print(f"requirements.lock.txt regenerado: {pines} paquetes fijados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
