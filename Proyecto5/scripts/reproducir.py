"""B3-03: corre todos los comandos del proyecto y resume lo que quedo reproducido.

Se ejecuta desde Proyecto5, despues de la preparacion del README. No usa la red.
Solo termina con 0 si cada paso se cumple, incluidos los casos C1-C10: un caso que
falla o sigue pendiente deja la reproduccion incompleta, aunque el comando haya corrido.
"""

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST = Path("data/p5-eval-v1/manifiesto.jsonl")
EVALUATION = Path("data/p5-eval-v1")
TUNING = Path("data/p5-ajuste-v1")
POLICY = Path("config/politica.yaml")
CASES = Path("casos/c1_c10.yaml")
IMAGE = Path("../Proyecto4/evidencias/EDGE-01/camara-nueva.jpg")
TRACE_SEQUENCE = "seq02"
TRACE_FRAME = "seq02-0003"

OK = "ok"
FAILED = "falla"
INCOMPLETE = "incompleto"
CASES_NOT_MET = 1


@dataclass(frozen=True)
class Step:
    name: str
    criterion: str
    arguments: tuple[str, ...]
    # Revisa lo que escribio el paso. Devuelve (estado, detalle) cuando el comando corrio.
    check: Callable[[int], tuple[str, str]] | None = None
    env: dict[str, str] = field(default_factory=dict)


def _module(name: str, *arguments: object) -> tuple[str, ...]:
    return ("-m", name, *(str(argument) for argument in arguments))


def check_cases(results: Path) -> Callable[[int], tuple[str, str]]:
    def check(code: int) -> tuple[str, str]:
        report = json.loads(results.read_text(encoding="utf-8"))
        detail = (
            f"{report['pasan']} pasan, {report['fallan']} fallan, {report['pendientes']} pendientes"
        )
        if report["ejecucion"]["salida_fisica"] is not False:
            return FAILED, f"salida fisica activa; {detail}"
        # El runner sale con 1 solo cuando un caso falla o sigue pendiente. Cualquier otra salida
        # distinta de 0 es un error, aunque el archivo diga que todo esta correcto.
        if code != 0 and (report["correcto"] or code != CASES_NOT_MET):
            return FAILED, f"codigo de salida {code}; {detail}"
        return (OK if report["correcto"] else INCOMPLETE), detail

    return check


def check_trace(trace: Path, frame_id: str, summary: Path) -> Callable[[int], tuple[str, str]]:
    def check(code: int) -> tuple[str, str]:
        if code != 0:
            return FAILED, f"codigo de salida {code}"
        lines = trace.read_text(encoding="utf-8").splitlines()
        row = next((json.loads(line) for line in lines if frame_id in line), None)
        if row is None:
            return FAILED, f"{frame_id} no esta en la traza"
        decision, command = row["decision"], row["command"]
        ids = {row["frame_id"], row["perception"]["frame_id"]}
        ids |= {decision["frame_id"], command["frame_id"]}
        if ids != {frame_id}:
            return FAILED, f"frame_id distinto entre etapas: {sorted(ids)}"
        chain = {
            "cuadro": frame_id,
            "detecciones": [d["class_name"] for d in row["perception"]["detections"]],
            "estado": decision["estado"],
            "decision": decision["accion"],
            "comando": command["direction"],
            "velocidad": command["speed"],
            "giro": command["steering"],
        }
        if not chain["detecciones"]:
            return FAILED, f"{frame_id} no trae detecciones reales"
        summary.write_text(json.dumps(chain, indent=2) + "\n", encoding="utf-8", newline="\n")
        return OK, (
            f"{frame_id} -> {chain['detecciones']} -> {chain['estado']} -> "
            f"{chain['decision']} -> {chain['comando']}"
        )

    return check


def check_benchmark(evidence: Path) -> Callable[[int], tuple[str, str]]:
    def check(code: int) -> tuple[str, str]:
        if code != 0:
            return FAILED, f"codigo de salida {code}"
        report = json.loads(evidence.read_text(encoding="utf-8"))
        if report["salida_fisica"] is not False:
            return FAILED, "salida fisica activa"
        total = report["resumen"]["etapas"]["ms_total"]
        return OK, (
            f"{report['resumen']['mediciones_validas']} mediciones validas; "
            f"p50 {total['p50']:.1f} ms, p95 {total['p95']:.1f} ms"
        )

    return check


def build_steps(output: Path, weights: Path) -> list[Step]:
    trace = output / "recorrido" / f"{TRACE_SEQUENCE}.jsonl"
    return [
        Step(
            "detector_hash",
            "El detector se recupera y su hash se verifica",
            _module("p5.detector.weights", "--path", weights, "--verify-only"),
        ),
        Step(
            "dataset_evaluacion",
            "El dataset de evaluacion esta completo y congelado",
            _module("p5.dataset.paquete", "validate", "--dataset", EVALUATION),
        ),
        Step(
            "dataset_ajuste",
            "El dataset de ajuste esta completo y no se cruza con evaluacion",
            _module("p5.dataset.paquete", "validate", "--dataset", TUNING, "--against", EVALUATION),
        ),
        Step(
            "inferencia",
            "Comando de inference",
            _module("p5.detector", "--weights", weights, "--image", IMAGE),
        ),
        Step(
            "recorrido",
            "Comando E2E y trazabilidad: cuadro -> detecciones -> estado -> decision -> comando",
            _module(
                "p5.integration",
                "--manifest",
                MANIFEST,
                "--sequence",
                TRACE_SEQUENCE,
                "--weights",
                weights,
                "--output",
                trace,
            ),
            check_trace(trace, TRACE_FRAME, output / "cuadro_trazado.json"),
        ),
        Step(
            "politica",
            "Decisiones C1-C7 con detecciones sinteticas",
            _module("p5.policy", "--output", output / "politica"),
        ),
        Step(
            "casos",
            "Comando C1-C10",
            _module(
                "p5.casos.runner",
                "--cases",
                CASES,
                "--config",
                POLICY,
                "--dataset",
                EVALUATION,
                "--weights",
                weights,
                "--output",
                output / "casos",
            ),
            check_cases(output / "casos" / "resultados.json"),
        ),
        Step(
            "metricas",
            "Comando de metricas",
            _module(
                "p5.metrics",
                "--dataset",
                EVALUATION,
                "--weights",
                weights,
                "--output",
                output / "metricas",
            ),
        ),
        Step(
            "benchmark",
            "Comando de benchmark",
            _module(
                "p5.benchmark",
                "--manifest",
                MANIFEST,
                "--weights",
                weights,
                "--output",
                output / "benchmark",
            ),
            check_benchmark(output / "benchmark" / "benchmark.json"),
        ),
        Step(
            "pruebas",
            "Pruebas del proyecto con pesos reales",
            _module("pytest", "-q"),
            env={"P5_DETECTOR_WEIGHTS": str(weights)},
        ),
    ]


def run_step(step: Step, logs: Path) -> dict[str, Any]:
    logs.mkdir(parents=True, exist_ok=True)
    print(f"[{step.name}] {step.criterion}", flush=True)
    with (logs / f"{step.name}.log").open("w", encoding="utf-8", newline="\n") as log:
        try:
            code = subprocess.run(
                [sys.executable, *step.arguments],
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, **step.env},
                check=False,
            ).returncode
        except OSError as failure:
            return _result(step, FAILED, f"no se pudo ejecutar: {failure}", None)

    if step.check is None:
        state = OK if code == 0 else FAILED
        return _result(step, state, f"codigo de salida {code}", code)
    try:
        state, detail = step.check(code)
    except (OSError, ValueError, KeyError, TypeError) as failure:
        return _result(step, FAILED, f"resultado no valido: {failure}", code)
    return _result(step, state, detail, code)


def _result(step: Step, state: str, detail: str, code: int | None) -> dict[str, Any]:
    print(f"  {state}: {detail}", flush=True)
    return {
        "paso": step.name,
        "criterio": step.criterion,
        "estado": state,
        "detalle": detail,
        "codigo_salida": code,
    }


def overall(results: list[dict[str, Any]]) -> str:
    states = {result["estado"] for result in results}
    if FAILED in states:
        return FAILED
    return INCOMPLETE if INCOMPLETE in states else OK


def _commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True, help="Carpeta nueva de resultados.")
    parser.add_argument("--weights", type=Path, default=Path("models/yolox_tiny.onnx"))
    args = parser.parse_args(argv)

    if args.output.exists():
        print(f"{args.output} ya existe: usa una carpeta nueva", file=sys.stderr)
        return 1
    args.output.mkdir(parents=True)
    (args.output / "recorrido").mkdir()

    results = [
        run_step(step, args.output / "registros") for step in build_steps(args.output, args.weights)
    ]
    state = overall(results)
    report = {
        "estado": state,
        "commit": _commit(),
        "python": sys.version.split()[0],
        "pasos": results,
    }
    summary = args.output / "reproduccion.json"
    summary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Reproduccion: {state} -> {summary}")
    return 0 if state == OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
