"""Medicion por etapas del mismo recorrido de la aplicacion. Ver `docs/A3-03_BENCHMARK.md`."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import wraps
from pathlib import Path
from time import perf_counter_ns
from typing import Any

import numpy as np
from p3.policy.politica import PoliticaDecision

from p5.control.adapter import VirtualControlAdapter
from p5.detector.yolox import YoloxDetector
from p5.integration.pipeline import FrameInput, Pipeline

MIN_WARMUPS = 10
MIN_RUNS = 100

WARMUP = "calentamiento"
MEASUREMENT = "medicion"

STAGES = (
    "ms_lectura",
    "ms_preprocesamiento",
    "ms_inferencia",
    "ms_posprocesamiento",
    "ms_politica",
    "ms_control",
)
TOTAL = "ms_total"
COLUMNS = (
    "fase",
    "indice",
    "repeticion",
    "sequence_id",
    "frame_id",
    TOTAL,
    *STAGES,
    "valido",
    "accion",
    "error",
)
# Cuanto separa cada vuelta al dataset: la politica exige tiempos crecientes.
_LAP_GAP_MS = 1000.0


def _timed(owner: Any, method: str, clock: dict[str, float], stage: str) -> None:
    original: Callable[..., Any] = getattr(owner, method)

    @wraps(original)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = perf_counter_ns()
        try:
            return original(*args, **kwargs)
        finally:
            elapsed = (perf_counter_ns() - start) / 1e6
            clock[stage] = clock.get(stage, 0.0) + elapsed

    setattr(owner, method, wrapper)


def instrument(
    detector: YoloxDetector, policy: PoliticaDecision, adapter: VirtualControlAdapter
) -> dict[str, float]:
    """Cronometra cada etapa de estos objetos, sin cambiar lo que hacen.

    Devuelve el reloj compartido: `measure` lo vacia antes de cada corrida.
    """
    clock: dict[str, float] = {}
    _timed(detector, "read_image", clock, "ms_lectura")
    _timed(detector, "_preprocess", clock, "ms_preprocesamiento")
    _timed(detector, "_infer", clock, "ms_inferencia")
    _timed(detector, "_postprocess", clock, "ms_posprocesamiento")
    _timed(policy, "decidir_crudo", clock, "ms_politica")
    _timed(adapter, "apply", clock, "ms_control")
    return clock


def measure(
    pipeline: Pipeline,
    clock: dict[str, float],
    frames: Sequence[FrameInput],
    *,
    warmups: int,
    runs: int,
) -> list[dict[str, Any]]:
    """Una fila por corrida: primero los calentamientos, y un fallo no detiene la medicion."""
    span = max(frame.t_capture_ms for frame in frames) + _LAP_GAP_MS
    rows = []
    for index in range(warmups + runs):
        lap, position = divmod(index, len(frames))
        frame = frames[position]
        clock.clear()
        trace = None
        failure = ""
        start = perf_counter_ns()
        try:
            trace = pipeline.process(replace(frame, t_capture_ms=frame.t_capture_ms + lap * span))
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
        total = (perf_counter_ns() - start) / 1e6

        if trace is not None:
            failure = "; ".join(f"{e['stage']}: {e['detail']}" for e in trace.errors)
        rows.append(
            {
                "fase": WARMUP if index < warmups else MEASUREMENT,
                "indice": index,
                "repeticion": index if index < warmups else index - warmups,
                "sequence_id": frame.sequence_id,
                "frame_id": frame.frame_id,
                TOTAL: total,
                **{stage: clock.get(stage) for stage in STAGES},
                "valido": not failure,
                "accion": trace.decision["accion"] if trace and trace.decision else "",
                "error": _without_local_path(failure, frame.image_path),
            }
        )
    return rows


def _without_local_path(message: str, path: Path) -> str:
    """Los errores citan la ruta, a veces con `repr`, y puede incluir la carpeta personal."""
    for form in (repr(str(path))[1:-1], str(path)):
        message = message.replace(form, path.name)
    return message


def _statistics(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return dict.fromkeys(("p50", "p95", "maximo", "minimo", "media"), None) | {"n": 0}
    # Interpolacion lineal (numpy por defecto), como las metricas del Proyecto 4.
    return {
        "n": len(values),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "maximo": max(values),
        "minimo": min(values),
        "media": float(np.mean(values)),
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Cifras de las mediciones validas. Los calentamientos y los fallos no entran."""
    warmups = [row for row in rows if row["fase"] == WARMUP]
    valid_warmups = sum(row["valido"] for row in warmups)
    measured = [row for row in rows if row["fase"] == MEASUREMENT]
    valid = [row for row in measured if row["valido"]]
    stages = {
        stage: _statistics([row[stage] for row in valid if row[stage] is not None])
        for stage in (TOTAL, *STAGES)
    }
    return {
        "calentamientos": len(warmups),
        "calentamientos_validos": valid_warmups,
        "mediciones": len(measured),
        "mediciones_validas": len(valid),
        "mediciones_con_error": len(measured) - len(valid),
        # Un calentamiento fallido no calienta el modelo, y una etapa sin datos no se midio.
        "cumple_minimos": valid_warmups >= MIN_WARMUPS
        and all(numbers["n"] >= MIN_RUNS for numbers in stages.values()),
        "etapas": stages,
    }
