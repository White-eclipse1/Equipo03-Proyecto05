import argparse
import csv
import hashlib
import io
import json
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter_ns
from typing import Any

import numpy as np
import onnxruntime
import yaml
from p3.policy.config import cargar_config
from p3.policy.politica import PoliticaDecision

from p5.benchmark.timing import COLUMNS, MIN_RUNS, MIN_WARMUPS, instrument, measure, summarize
from p5.control.adapter import VirtualControlAdapter
from p5.dataset.paquete import validate_package
from p5.detector.weights import (
    DEFAULT_WEIGHTS_PATH,
    WEIGHTS_SHA256,
    WEIGHTS_SIZE,
    WeightsError,
    verify_weights,
)
from p5.detector.yolox import DetectorError, YoloxDetector
from p5.integration.pipeline import Pipeline, frames_from_manifest

logger = logging.getLogger(__name__)

DEFAULT_POLICY_CONFIG = Path("config") / "politica.yaml"
DEFAULT_RUNS = 200


def check_images(manifest: Path) -> None:
    """Valida el paquete congelado. Asi el disco tampoco pesa mas en la primera vuelta."""
    errors = validate_package(manifest.parent).errors
    if errors:
        raise ValueError(f"paquete no valido ({len(errors)} errores): {errors[0]}")


def _cpu_name() -> str:
    if sys.platform == "win32":
        import winreg

        key = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            return str(winreg.QueryValueEx(handle, "ProcessorNameString")[0]).strip()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            name, _, value = line.partition(":")
            if name.strip() in ("model name", "Model"):
                return value.strip()
    return platform.processor() or "desconocido"


def _memory_bytes() -> int | None:
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total", ctypes.c_ulonglong),
                ("available", ctypes.c_ulonglong),
                ("page_total", ctypes.c_ulonglong),
                ("page_available", ctypes.c_ulonglong),
                ("virtual_total", ctypes.c_ulonglong),
                ("virtual_available", ctypes.c_ulonglong),
                ("virtual_extended", ctypes.c_ulonglong),
            ]

        status = MemoryStatus(length=ctypes.sizeof(MemoryStatus))
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total)
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def hardware() -> dict[str, Any]:
    """Sin nombre del equipo ni de usuario: este archivo se publica."""
    return {
        "cpu": _cpu_name(),
        "nucleos_logicos": os.cpu_count(),
        "memoria_bytes": _memory_bytes(),
        "arquitectura": platform.machine(),
        "sistema_operativo": platform.platform(),
    }


def _git(*arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            # Junto al codigo importado: no importa desde donde se corra el comando.
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def code_version() -> dict[str, Any]:
    tracked = _git("status", "--porcelain", "--untracked-files=no")
    # Un modulo nuevo sin versionar tambien cambia lo que se mide; la evidencia nueva no.
    new_code = _git("status", "--porcelain", "--untracked-files=all", "--", "../..")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "cambios_sin_commit": None
        if tracked is None or new_code is None
        else bool(tracked or new_code),
    }


def runtime(detector: YoloxDetector) -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "onnxruntime": onnxruntime.__version__,
        "providers_sesion": detector._session.get_providers(),
        "numpy": np.__version__,
        "opencv": version("opencv-python-headless"),
        "pydantic": version("pydantic"),
    }


def _timings_csv(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _print_summary(summary: dict[str, Any]) -> None:
    print(
        f"calentamientos={summary['calentamientos']} "
        f"validas={summary['mediciones_validas']}/{summary['mediciones']}"
    )
    for stage, numbers in summary["etapas"].items():
        if numbers["n"]:
            print(
                f"{stage}: p50={numbers['p50']:.2f} p95={numbers['p95']:.2f} "
                f"max={numbers['maximo']:.2f}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m p5.benchmark",
        description="Mide en CPU el recorrido completo por etapas y exporta cada corrida.",
    )
    parser.add_argument("--manifest", type=Path, required=True, help="Manifiesto congelado.")
    parser.add_argument("--output", type=Path, required=True, help="Carpeta nueva de resultados.")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS_PATH)
    parser.add_argument("--policy-config", type=Path, default=DEFAULT_POLICY_CONFIG)
    parser.add_argument("--calentamientos", type=int, default=MIN_WARMUPS)
    parser.add_argument("--repeticiones", type=int, default=DEFAULT_RUNS)
    args = parser.parse_args(argv)
    if args.calentamientos < MIN_WARMUPS:
        parser.error(f"--calentamientos debe ser al menos {MIN_WARMUPS}")
    if args.repeticiones < MIN_RUNS:
        parser.error(f"--repeticiones debe ser al menos {MIN_RUNS}")

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    try:
        if args.output.exists():
            raise ValueError(f"{args.output} ya existe: usa una carpeta nueva")
        verify_weights(args.weights)
        check_images(args.manifest)
        frames = frames_from_manifest(args.manifest)
        config, config_sha256 = cargar_config(args.policy_config)
        policy = PoliticaDecision(config, config_sha256)
        start = perf_counter_ns()
        detector = YoloxDetector.from_weights(args.weights)
        load_ms = (perf_counter_ns() - start) / 1e6
        # Antes de medir: un fallo aqui no debe costar una medicion ya hecha.
        conditions = {
            "hardware": hardware(),
            "runtime": runtime(detector),
            "codigo": code_version(),
        }
    except (
        WeightsError,
        DetectorError,
        OSError,
        ValueError,
        KeyError,
        PackageNotFoundError,
        yaml.YAMLError,
    ) as failure:
        logger.error("benchmark_error stage=startup detail=%s", failure)
        return 1

    adapter = VirtualControlAdapter()
    clock = instrument(detector, policy, adapter)
    pipeline = Pipeline(detector, policy, adapter)

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = measure(pipeline, clock, frames, warmups=args.calentamientos, runs=args.repeticiones)
    summary = summarize(rows)

    timings = _timings_csv(rows)
    evidence = {
        "schema_version": 1,
        "tarea": "A3-03 (#18)",
        "fecha": started_at,
        "hardware": conditions["hardware"],
        "runtime": conditions["runtime"],
        "detector": {
            "nombre": "YOLOX-Tiny",
            "archivo": args.weights.name,
            "sha256": WEIGHTS_SHA256,
            "bytes": WEIGHTS_SIZE,
            "ms_carga": load_ms,
        },
        "dataset": {
            "nombre": args.manifest.resolve().parent.name,
            "manifiesto_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            "cuadros": len(frames),
        },
        "politica": {"config_sha256": config_sha256},
        "codigo": conditions["codigo"],
        "medicion": {
            "incluye": "Pipeline.process: leer y decodificar la imagen, preprocesar, inferir, "
            "posprocesar, decidir y generar el comando virtual",
            "excluye": "carga del modelo (ms_carga aparte), captura de la camara, escritura de "
            "resultados y motores: no hace llamadas de red",
            "reloj": "time.perf_counter_ns, en milisegundos",
            "percentil": "interpolacion lineal, numpy.percentile por defecto",
            "hilos": "opciones por defecto de onnxruntime, como la aplicacion",
            "calentamientos": args.calentamientos,
            "repeticiones": args.repeticiones,
        },
        "salida_fisica": adapter.physical_output_enabled,
        "resumen": summary,
        "tiempos": {
            "archivo": "tiempos.csv",
            "sha256": hashlib.sha256(timings).hexdigest(),
            "filas": len(rows),
        },
    }

    try:
        args.output.mkdir(parents=True)
        (args.output / "tiempos.csv").write_bytes(timings)
        with (args.output / "benchmark.json").open("x", encoding="utf-8", newline="\n") as output:
            json.dump(evidence, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
    except OSError as failure:
        logger.error("benchmark_error stage=output detail=%s", failure)
        return 1

    _print_summary(summary)
    print(f"output={args.output}")
    return 0 if summary["cumple_minimos"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
