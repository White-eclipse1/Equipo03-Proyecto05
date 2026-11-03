#!/usr/bin/env python3
"""Regenera `requirements.lock.txt`: la resolucion exacta de cada dependencia.

`pyproject.toml` declara rangos porque es lo correcto para una libreria, pero
un rango no es reproducible: `pip install -e .` hoy y dentro de un mes pueden
traer arboles distintos sin que nadie haya tocado el repositorio. El lockfile
congela esa resolucion; este script es el unico procedimiento autorizado para
producirlo, para que no dependa de que maquina lo corrio.

Corre SIEMPRE dentro de la imagen `python:3.12-slim`, la misma que usan el
Dockerfile y el runner de CI. Un `pip freeze` desde el venv de Windows del
autor no serviria: la resolucion depende de la plataforma, y el resultado
arrastraria paquetes que en Linux no existen y omitiria los que solo existen
alli (`uvloop` es el ejemplo evidente).

    python scripts/lock_requirements.py
    python scripts/lock_requirements.py --check     # falla si esta desactualizado
    python scripts/lock_requirements.py --upgrade   # sube todo a lo ultimo que admiten los rangos

pip-compile parte del lockfile existente: conserva cada pin que siga cumpliendo
`pyproject.toml` y solo cambia lo que el `pyproject.toml` obliga. Sin eso,
`--check` fallaba cada vez que PyPI publicaba una version nueva de cualquier
dependencia, aunque nadie hubiera tocado el repositorio. Subir versiones es una
decision explicita: `--upgrade`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROYECTO2_DIR = Path(__file__).resolve().parent.parent
LOCKFILE = PROYECTO2_DIR / "requirements.lock.txt"

# La misma etiqueta que `docker/Dockerfile` y `setup-python` de CI.
IMAGEN = "python:3.12-slim"
PIP_TOOLS = "pip-tools==7.4.1"

CABECERA = """#
# Lockfile del entorno Python: la version EXACTA de cada paquete, directo o
# transitivo. `pyproject.toml` declara rangos (`fastapi>=0.115`) porque es lo
# que corresponde a una libreria; este archivo congela la resolucion concreta
# para que un clon limpio instale hoy lo mismo que instalo CI ayer, sin volver
# a resolver rangos y sin que una version nueva de una dependencia indirecta
# rompa el build sin que nadie haya tocado el repositorio.
#
# Se regenera SIEMPRE dentro de la misma imagen que usan CI y el Dockerfile,
# nunca desde el venv de Windows de quien lo corre: la resolucion depende de la
# plataforma, y un `pip freeze` local arrastraria paquetes que en Linux no
# existen (y omitiria los que solo existen alli).
#
#    python scripts/lock_requirements.py
#
# Unica linea editada a mano tras generarlo: el marcador de `uvloop`, mas abajo.
#
"""

# pip-compile resuelve para Linux y por eso emite `uvloop` sin marcador. El
# marcador es el que declara `uvicorn[standard]`; reponerlo no cambia nada en
# CI y evita que el lockfile sea ininstalable en los hosts Windows del equipo.
UVLOOP_CRUDO = "uvloop==0.22.1\n"
UVLOOP_CON_MARCADOR = (
    "# El marcador es el que declara `uvicorn[standard]` y pip-compile pierde al\n"
    "# resolver para Linux: uvloop no publica rueda para Windows, y sin el marcador\n"
    "# este lockfile seria ininstalable en el host de medio equipo.\n"
    "uvloop==0.22.1 ; sys_platform != 'win32' and sys_platform != 'cygwin'"
    " and platform_python_implementation != 'PyPy'\n"
)


def compilar(upgrade: bool = False) -> str:
    """Devuelve el lockfile que resuelve pip-compile dentro del contenedor."""
    # El lockfile actual se copia como punto de partida: pip-compile respeta los
    # pines que ya estan en `--output-file` salvo que se le pida `--upgrade`.
    semilla = (
        "cp requirements.lock.txt /salida/requirements.lock.txt && "
        if LOCKFILE.exists() and not upgrade
        else ""
    )
    guion = (
        f"{semilla}pip install -q --root-user-action=ignore {PIP_TOOLS} && "
        "pip-compile --quiet --strip-extras --extra dev --extra pipeline "
        f"{'--upgrade ' if upgrade else ''}"
        # La ruta va RELATIVA: pip-compile la copia tal cual dentro de los
        # comentarios `# via dataset-quality (...)`, y con una ruta absoluta
        # el lockfile llevaria impresa la ruta del contenedor.
        "--output-file /salida/requirements.lock.txt pyproject.toml && "
        "cat /salida/requirements.lock.txt"
    )
    resultado = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            # El proyecto se monta de solo lectura: este script no puede
            # escribir en el arbol desde dentro del contenedor, y asi el
            # unico camino por el que el lockfile llega al repositorio es el
            # de abajo, que pasa por la normalizacion.
            "-v",
            f"{PROYECTO2_DIR}:/w:ro",
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
    """Cambia la cabecera generada por la nuestra y repone el marcador."""
    # La cabecera de pip-compile son las lineas de comentario iniciales; se
    # descartan todas y se sustituyen por la explicacion del proyecto.
    lineas = crudo.splitlines(keepends=True)
    corte = 0
    for indice, linea in enumerate(lineas):
        if not linea.startswith("#"):
            corte = indice
            break
    cuerpo = "".join(lineas[corte:])

    normalizado = CABECERA + cuerpo
    if UVLOOP_CRUDO in normalizado:
        normalizado = normalizado.replace(UVLOOP_CRUDO, UVLOOP_CON_MARCADOR)
    return normalizado


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="No escribe: sale con codigo 1 si el lockfile del repositorio no coincide.",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Ignora los pines actuales y resuelve lo ultimo que admiten los rangos.",
    )
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
    sys.exit(main())
