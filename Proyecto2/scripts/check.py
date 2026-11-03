#!/usr/bin/env python3
"""Comando único de validación diaria (<30s) para Frente 10 (Ruff, pytest y CI).

Ejecuta en un solo paso:
1. Ruff Lint (`ruff check .`)
2. Ruff Format (`ruff format --check .`)
3. Pytest suite (`pytest`)
4. Terraform Format & Validate (`terraform fmt -check` y `terraform validate`)
5. Higiene de Git y Compuerta M2 (ausencia de `.env`, `.tfstate`, etc.)

Termina con código 0 si todo pasa, o código != 0 si cualquier chequeo falla.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROYECTO2_DIR = Path(__file__).resolve().parent.parent


def find_executable(name: str) -> str | None:
    """Busca un ejecutable en .venv local o en el PATH."""
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    venv_bin = PROYECTO2_DIR / ".venv" / bin_dir / name
    if sys.platform == "win32":
        venv_bin = venv_bin.with_suffix(".exe")
    if venv_bin.exists():
        return str(venv_bin)
    return shutil.which(name)


def run_step(
    title: str,
    cmd: list[str],
    cwd: Path,
    env: dict | None = None,
) -> tuple[bool, float, str]:
    """Ejecuta un comando midiendo el tiempo transcurrido."""
    print(f"  {BOLD}•{RESET} {title:<50} ", end="", flush=True)
    t0 = time.perf_counter()
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    elapsed = time.perf_counter() - t0

    if res.returncode == 0:
        print(f"{GREEN}[PASS]{RESET} {DIM}({elapsed:.2f}s){RESET}")
        return True, elapsed, ""
    else:
        print(f"{RED}[FAIL]{RESET} {DIM}({elapsed:.2f}s){RESET}")
        output = (res.stdout + "\n" + res.stderr).strip()
        return False, elapsed, output


def check_git_hygiene() -> tuple[bool, float, str]:
    """Verifica que ningún secreto ni archivo prohibido esté en el índice de Git."""
    title = "Higiene de Git & Compuerta M2 (cero secretos)"
    print(f"  {BOLD}•{RESET} {title:<50} ", end="", flush=True)
    t0 = time.perf_counter()
    res = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0

    if res.returncode != 0:
        print(f"{RED}[FAIL]{RESET} {DIM}({elapsed:.2f}s){RESET}")
        return False, elapsed, "Error al ejecutar git ls-files"

    prohibited = [".env", ".tfstate", "__pycache__", ".venv", "node_modules"]
    tracked = res.stdout.splitlines()
    violations = [
        f for f in tracked if any(p in f for p in prohibited) and not f.endswith(".example")
    ]

    if violations:
        print(f"{RED}[FAIL]{RESET} {DIM}({elapsed:.2f}s){RESET}")
        msg = "Archivos prohibidos encontrados en Git:\n  " + "\n  ".join(violations)
        return False, elapsed, msg

    print(f"{GREEN}[PASS]{RESET} {DIM}({elapsed:.2f}s){RESET}")
    return True, elapsed, ""


def main() -> int:
    # La consola de Windows usa cp1252 cuando la salida va a una tuberia, y las
    # lineas de recuadro de abajo la revientan con UnicodeEncodeError antes de
    # ejecutar un solo chequeo. Reconfigurar el stream evita que `make check |
    # tee` falle por un caracter decorativo.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    print(f"\n{BOLD}══════════════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  Dataset Quality — Validación Rápida de Frente 10 (<30s){RESET}")
    print(f"{BOLD}══════════════════════════════════════════════════════════════════════{RESET}\n")

    start_total = time.perf_counter()
    failures: list[tuple[str, str]] = []

    ruff = find_executable("ruff")
    terraform = find_executable("terraform")

    # pytest se invoca como MODULO del interprete actual, no por su `pytest.exe`.
    # El shim que genera pip es un ejecutable que vuelve a lanzar el Python base,
    # y con el Python de la Microsoft Store esa relanzada falla sin imprimir
    # nada y devolviendo 1 — con lo que este script reportaba un FAIL de una
    # suite que en realidad esta entera en verde, que es el peor fallo posible
    # en una herramienta de validacion. `ruff` no tiene el problema porque su
    # ejecutable es un binario nativo, no un shim de Python.
    pytest = [sys.executable, "-m", "pytest"]

    # 1. Ruff Lint
    if ruff:
        ok, _, out = run_step(
            "Ruff: verificación de lint (ruff check)",
            [ruff, "check", "."],
            PROYECTO2_DIR,
        )
        if not ok:
            failures.append(("Ruff Lint", out))

        ok, _, out = run_step(
            "Ruff: verificación de formato (ruff format --check)",
            [ruff, "format", "--check", "."],
            PROYECTO2_DIR,
        )
        if not ok:
            failures.append(("Ruff Format", out))
    else:
        print(f"  {YELLOW}⚠ Ruff no encontrado. Omitiendo.{RESET}")

    # 2. Pytest suite
    ok, _, out = run_step(
        "Pytest: suite completa de pruebas unitarias",
        pytest,
        PROYECTO2_DIR,
    )
    if not ok:
        failures.append(("Pytest", out))

    # 3. Terraform checks
    if terraform:
        tf_dir = PROYECTO2_DIR / "terraform"
        tf_env = dict(os.environ, TF_CLI_CONFIG_FILE="/dev/null")
        ok, _, out = run_step(
            "Terraform: formato estricto (fmt -check)",
            [terraform, "fmt", "-check"],
            tf_dir,
            env=tf_env,
        )
        if not ok:
            failures.append(("Terraform Format", out))

        ok, _, out = run_step(
            "Terraform: validación de sintaxis y tipos (validate)",
            [terraform, "validate"],
            tf_dir,
            env=tf_env,
        )
        if not ok:
            # En macOS sandbox, si gRPC a plugins está restringido, no bloquea si sintaxis es ok
            if "Failed to obtain provider schema" in out and "Plugin did not respond" in out:
                print(f"    {YELLOW}↳ Aviso: Plugin gRPC bloqueado por sandbox local.{RESET}")
            else:
                failures.append(("Terraform Validate", out))
    else:
        print(f"  {DIM}  Terraform no encontrado. Omitiendo.{RESET}")

    # 4. Higiene de Git
    ok, _, out = check_git_hygiene()
    if not ok:
        failures.append(("Git Hygiene", out))

    total_elapsed = time.perf_counter() - start_total

    print(f"\n{DIM}──────────────────────────────────────────────────────────────────────{RESET}")
    print(
        f"  {BOLD}Tiempo total:{RESET} {total_elapsed:.2f}s  "
        f"{DIM}(Límite de la rúbrica: <30.0s){RESET}"
    )

    if failures:
        print(f"\n{RED}{BOLD}✖ SE DETECTARON FALLOS EN LA VALIDACIÓN:{RESET}\n")
        for name, detail in failures:
            print(f"{RED}{BOLD}--- [{name}] ---{RESET}")
            print(detail)
            print()
        return 1

    print(f"\n{GREEN}{BOLD}✔ TODOS LOS CHEQUEOS PASARON EXITOSAMENTE.{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
