"""Punto unico de arranque del entorno local (Frente 1 de la rubrica).

    python scripts/up.py

Orquesta, sin ningun paso manual:

  1. Crea `.env` desde `.env.example` si no existe.
  2. Construye la imagen de la app y levanta MariaDB + MinIO + app.
  3. Crea los buckets de MinIO (job idempotente `minio-init`).
  4. Espera a que los tres servicios reporten `healthy`.
  5. Verifica `/health` y muestra las URLs de trabajo.

Solo usa la libreria estandar: se ejecuta con un Python 3.12 limpio, sin
instalar nada en el host. Esto importa para la compuerta M1 de la rubrica
(clonar y arrancar siguiendo el README, en una maquina ajena).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"


def log(message: str) -> None:
    print(f"\n\033[35m==>\033[0m {message}", flush=True)


def fail(message: str) -> None:
    print(f"\n\033[31mError:\033[0m {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def ensure_env_file() -> None:
    """Si no existe `.env`, lo crea desde la plantilla del entorno local."""
    if ENV_PATH.exists():
        return
    if not ENV_EXAMPLE_PATH.exists():
        fail(f"No existe {ENV_PATH.name} ni {ENV_EXAMPLE_PATH.name}.")
    shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
    print(f"No se encontro .env; se creo una copia desde {ENV_EXAMPLE_PATH.name}.")


def read_env() -> dict[str, str]:
    """Parser minimo de `.env` (solo para saber en que puertos publicar avisos)."""
    values: dict[str, str] = {}
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def export_code_commit() -> None:
    """Commit y estado del arbol para las corridas del worker de P3 (tags de MLflow)."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=REPO_ROOT
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return
    os.environ["P3_CODE_COMMIT"] = commit
    os.environ["P3_CODE_DIRTY"] = "true" if dirty else "false"


def export_aws_dir() -> None:
    """Carpeta `~/.aws` para el servicio de inferencia de P3 (solo lectura, sin copiar llaves)."""
    aws = Path.home() / ".aws"
    if aws.is_dir():
        os.environ.setdefault("P3_AWS_DIR", str(aws))


def export_host_identity() -> None:
    """Le pasa a compose el uid/gid del host, para que la app pueda escribir.

    El contenedor monta el repositorio en `/app` y guarda ahi `quality.yaml` y
    los `reports/*.json`. En un bind mount los permisos se resuelven por UID
    numerico, asi que un contenedor que corre como uid 10001 no puede escribir
    en un arbol que en el host es de otro usuario: en Linux el guardado de la
    politica falla con EACCES.

    `os.getuid` no existe en Windows, y ahi tampoco hace falta: Docker Desktop
    no traslada los permisos POSIX al montaje. Sin estas variables,
    `docker-compose.yml` se queda con el `appuser` de la imagen.
    """
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return
    os.environ.setdefault("DQ_UID", str(getuid()))
    os.environ.setdefault("DQ_GID", str(getgid()))


def require_docker() -> None:
    if shutil.which("docker") is None:
        fail("Docker no esta en el PATH. Instala Docker Desktop y vuelve a intentar.")
    probe = subprocess.run(
        ["docker", "compose", "version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        fail("`docker compose` no responde. Revisa que Docker Desktop este corriendo.")


COMPOSE_FILES: list[str] = []


def use_gpu() -> bool:
    """GPU NVIDIA para el worker de P3: `P3_GPU=1/0` manda; si no, se detecta `nvidia-smi`."""
    forced = os.environ.get("P3_GPU")
    if forced is not None:
        return forced == "1"
    return shutil.which("nvidia-smi") is not None


def compose(*args: str, check: bool = True) -> int:
    """Ejecuta `docker compose ...` mostrando la salida en vivo."""
    files = [flag for name in COMPOSE_FILES for flag in ("-f", name)]
    command = ["docker", "compose", *files, *args]
    print(f"\033[90m$ {' '.join(command)}\033[0m", flush=True)
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if check and result.returncode != 0:
        fail(f"`{' '.join(command)}` termino con codigo {result.returncode}.")
    return result.returncode


def snapshot_restored() -> bool:
    """`mlflow-restore` acaba de cargar el snapshot (ver `p3/mlflow_restore.py`)."""
    files = [flag for name in COMPOSE_FILES for flag in ("-f", name)]
    command = ["docker", "compose", *files, "logs", "--no-log-prefix", "mlflow-restore"]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    lines = result.stdout.strip().splitlines()
    return bool(lines) and lines[-1].startswith("Snapshot restaurado")


def wait_for_health(url: str, timeout_seconds: int = 90) -> dict[str, object] | None:
    """Consulta `/health` hasta que responda 200 o se agote el tiempo."""
    deadline = time.monotonic() + timeout_seconds
    last_body: dict[str, object] | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                last_body = json.loads(error.read())
            except (ValueError, OSError):
                last_body = None
        except (urllib.error.URLError, OSError, ValueError):
            last_body = None
        time.sleep(2)
    return last_body


P1_START = (
    "cd ../Proyecto1 && npm install && cp -n .env.example .env && docker compose up -d --wait "
    "&& npm run db:migrate && npm run dev:api"
)


def p1_hint(url: str) -> str | None:
    """`None` si P1 responde; si no, como levantarlo para "Enviar a cola" (Proyecto 3)."""
    try:
        with urllib.request.urlopen(f"{url}/api/images", timeout=3):
            return None
    except urllib.error.HTTPError:
        return None  # responde, aunque sea con error: esta arriba
    except (urllib.error.URLError, OSError):
        return (
            f'P1 (cola de anotacion) no responde en {url}: "Enviar a cola" de Inference '
            f"dara 502. Levantalo en otra terminal, desde Proyecto2/:\n    {P1_START}"
        )


def wait_for_mlflow(url: str, timeout_seconds: int = 90) -> bool:
    """MLflow responde `OK` en texto plano, no JSON: basta con un 200."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Levanta el entorno local completo.")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Borra volumenes (BD y buckets) antes de levantar. Destructivo.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="No reconstruye la imagen de la app (arranque mas rapido).",
    )
    parser.add_argument(
        "--logs",
        action="store_true",
        help="Al terminar, sigue los logs de la app (Ctrl+C solo corta los logs).",
    )
    args = parser.parse_args()

    require_docker()
    export_host_identity()
    export_code_commit()
    export_aws_dir()
    ensure_env_file()
    env = read_env()
    app_port = env.get("APP_PORT", "8000")
    console_port = env.get("MINIO_CONSOLE_PORT", "9101")
    mlflow_port = env.get("MLFLOW_PORT", "5000")

    if args.fresh:
        log("Borrando contenedores y volumenes previos (--fresh)...")
        compose("down", "-v", check=False)

    if use_gpu():
        COMPOSE_FILES.extend(["docker-compose.yml", "docker-compose.gpu.yml"])
        log("GPU NVIDIA detectada: el worker de P3 entrenara con ella.")
    else:
        log("Sin GPU NVIDIA: el worker de P3 entrenara en CPU.")

    log("Levantando MariaDB + MinIO + app + MLflow + worker P3 y esperando healthchecks...")
    up_args = ["up", "-d", "--wait"]
    if not args.no_build:
        up_args.insert(1, "--build")
    compose(*up_args)

    # Si `dvc pull` llego despues del primer `up.py`, MLflow ya estaba corriendo
    # con su base vacia: el restore la reemplaza, pero el servidor no la relee
    # hasta reiniciarse.
    if snapshot_restored():
        log("Snapshot de MLflow restaurado: reiniciando MLflow para cargar las corridas...")
        compose("restart", "mlflow")

    log("Verificando /health (MariaDB + MinIO desde la app)...")
    health = wait_for_health(f"http://localhost:{app_port}/health")
    if health is None or health.get("status") != "ok":
        print(json.dumps(health, indent=2, ensure_ascii=False) if health else "(sin respuesta)")
        fail(
            "La app arranco pero /health no esta OK. "
            "Revisa `docker compose logs app` y los valores de .env."
        )
    print(json.dumps(health, indent=2, ensure_ascii=False))

    log("Verificando MLflow (tracking de Proyecto 3)...")
    if not wait_for_mlflow(f"http://localhost:{mlflow_port}/health"):
        fail("MLflow no responde. Revisa `docker compose logs mlflow`.")

    print(
        f"""
\033[32mEntorno listo.\033[0m

  App / UI          http://localhost:{app_port}
  OpenAPI           http://localhost:{app_port}/docs
  Health            http://localhost:{app_port}/health
  Consola MinIO     http://localhost:{console_port}   (usuario y clave en .env)
  MLflow            http://localhost:{mlflow_port}

  Logs              docker compose logs -f app
  Apagar            python scripts/down.py
"""
    )

    hint = p1_hint(env.get("MP1_BASE_URL", "http://localhost:3000").rstrip("/"))
    if hint:
        log(hint)

    if args.logs:
        log("Siguiendo logs de la app (Ctrl+C corta los logs, no los contenedores)...")
        try:
            compose("logs", "-f", "app", check=False)
        except KeyboardInterrupt:
            print("\nLogs cortados. Los contenedores siguen corriendo.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        raise SystemExit(130) from None
