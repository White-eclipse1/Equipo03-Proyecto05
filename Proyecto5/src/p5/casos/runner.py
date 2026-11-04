"""Runner de los casos C1-C10 sobre un paquete congelado (B3-02; E5).

Los casos reales pasan por el mismo recorrido de la aplicacion: detector, politica y adaptador
virtual. El recorrido solo recibe la imagen y sus identificadores. Las etiquetas y las acciones
admisibles se usan despues, para comparar lo que hizo el sistema. Sale con codigo 1 si un caso
falla o sigue pendiente. Ver `docs/B3-02_RUNNER.md`.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from p3.policy.casos import ejecutar_casos
from p3.policy.config import ConfigPolitica, cargar_config
from p3.policy.politica import PoliticaDecision

from p5.control.adapter import VirtualControlAdapter
from p5.dataset.paquete import MANIFEST_FILE, load_manifest
from p5.detector.yolox import (
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DetectorError,
    YoloxDetector,
)
from p5.integration.pipeline import FrameInput, FrameTrace, Pipeline

REQUIRED_CASES = tuple(f"C{number}" for number in range(1, 11))
PASSED = "PASA"
FAILED = "FALLA"
PENDING = "PENDIENTE"

# Se escribe aparte de la conversion del recorrido para comprobarla, no para repetirla.
_COMMAND_DIRECTIONS = {
    "STOP": "stop",
    "FORWARD": "forward",
    "SLOW": "forward",
    "EVADE_LEFT": "left",
    "EVADE_RIGHT": "right",
}

Config = tuple[ConfigPolitica, str]


def load_cases(path: Path) -> dict[str, Any]:
    """Lee los casos y resuelve sus rutas. Rechaza una lista que no sea exactamente la requerida."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    ids = [case["id"] for case in data["casos"]]
    if sorted(ids) != sorted(REQUIRED_CASES):
        raise ValueError(f"se esperan los casos {list(REQUIRED_CASES)}, y hay {ids}")
    for case in data["casos"]:
        if "archivo" in case:
            case["archivo"] = str((Path(path).parent / case["archivo"]).resolve())
    return data


def load_detector(weights: Path) -> YoloxDetector:
    return YoloxDetector.from_weights(weights)


def _frame_input(row: dict[str, Any], dataset: Path) -> FrameInput:
    """Lo unico del manifiesto que llega al recorrido. Nunca las etiquetas ni las expectativas."""
    return FrameInput(
        sequence_id=row["sequence_id"],
        frame_id=row["frame_id"],
        t_capture_ms=row["t_capture_ms"],
        image_size=(row["image_width"], row["image_height"]),
        image_path=dataset / row["image"],
    )


def _frame_record(trace: FrameTrace) -> dict[str, Any]:
    """Decision, percepcion y comando de un cuadro. Sin decision, cuenta el STOP que se emitio."""
    decision = trace.decision or {
        "accion": "STOP",
        "estado": "FAULT",
        "velocidad": 0.0,
        "direccion": 0.0,
        "reason_code": trace.command["reason_code"],
    }
    return {
        **decision,
        "frame_id": trace.frame_id,
        "cuadro": trace.perception,
        "comando": trace.command,
        "errores": list(trace.errors),
    }


def _command_matches(record: dict[str, Any]) -> bool:
    command = record["comando"]
    return (
        command["direction"] == _COMMAND_DIRECTIONS[record["accion"]]
        and command["speed"] == record["velocidad"]
        and command["steering"] == record["direccion"]
    )


def _rule_failures(case: dict[str, Any], decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []

    def window(first: int, last: int) -> list[dict[str, Any]] | None:
        if first < 1 or last > len(decisions):
            return None
        return decisions[first - 1 : last]

    for rule in case.get("alguna", []):
        observed = window(*rule["cuadros"])
        actions = {decision["accion"] for decision in observed or ()}
        if not actions & set(rule["acciones"]):
            failures.append({"regla": "alguna", **rule, "observadas": sorted(actions)})

    reaction = case.get("reaccion")
    if reaction:
        # El plazo cuenta el cuadro `desde`: 2 cuadros desde el 30 son el 30 y el 31.
        observed = window(reaction["desde"], reaction["desde"] + reaction["plazo_cuadros"] - 1)
        # El STOP de arranque, con la via sin confirmar, no cuenta como reaccion al obstaculo.
        reacted = any(
            decision["accion"] in reaction["acciones"] and decision["estado"] == "BLOCKED"
            for decision in observed or ()
        )
        if not reacted:
            seen = sorted({f"{d['accion']}/{d['estado']}" for d in observed or ()})
            failures.append({"regla": "reaccion", **reaction, "observadas": seen})

    low, high = case.get("direccion_min", -1.0), case.get("direccion_max", 1.0)
    for number, decision in enumerate(decisions, start=1):
        if not low <= decision["direccion"] <= high:
            failures.append(
                {
                    "regla": "direccion",
                    "cuadro": number,
                    "frame_id": decision["frame_id"],
                    "direccion": decision["direccion"],
                    "limites": [low, high],
                }
            )
    return failures


def _base_result(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case["id"],
        "tipo": case["tipo"],
        "nombre": case["nombre"],
        "estado_inicial": case.get("estado_inicial"),
        "justificacion": case.get("justificacion"),
    }


def run_real_case(
    case: dict[str, Any],
    rows: list[dict[str, Any]],
    config: Config,
    detector: YoloxDetector,
    dataset: Path,
) -> dict[str, Any]:
    """Corre una secuencia por el recorrido completo y compara cuadro por cuadro."""
    settings, config_sha256 = config
    sequence = [row for row in rows if row["sequence_id"] == case["secuencia"]]
    result = {
        **_base_result(case),
        "entrada": {"secuencia": case["secuencia"], "cuadros": len(sequence)},
        "esperado": {
            "acciones_por_cuadro": "allowed_actions del manifiesto",
            **{key: case[key] for key in ("alguna", "reaccion") if key in case},
        },
    }
    if not sequence:
        missing = {"regla": "entrada", "motivo": f"no existe la secuencia {case['secuencia']}"}
        return {**result, "resultado": FAILED, "fallos": [missing], "decisiones": []}

    # Una secuencia grabada conserva sus timestamps, pero su espaciado no
    # representa el paso del tiempo de una aplicaci?n en vivo. El watchdog
    # temporal se reproduce expl?citamente en C8 con un reloj controlado.
    adapter = VirtualControlAdapter()
    pipeline = Pipeline(
        detector,
        PoliticaDecision(settings, config_sha256=config_sha256),
        adapter,
    )
    decisions = []
    failures = []
    watchdog_events = []
    for number, row in enumerate(sequence, start=1):
        where = {"cuadro": number, "frame_id": row["frame_id"]}
        try:
            trace = pipeline.process(_frame_input(row, dataset))
        except Exception as failure:
            # `process` no deberia lanzar nada: si lo hace, la secuencia ya no es confiable.
            failures.append({"regla": "recorrido", **where, "motivo": repr(failure)})
            break
        record = _frame_record(trace)
        decisions.append(record)
        if record["accion"] not in row["allowed_actions"]:
            failures.append(
                {
                    "regla": "acciones",
                    **where,
                    "observada": record["accion"],
                    "permitidas": row["allowed_actions"],
                    "reason_code": record["reason_code"],
                }
            )
        if record["errores"]:
            failures.append({"regla": "errores", **where, "errores": record["errores"]})
        if not _command_matches(record):
            failures.append(
                {
                    "regla": "comando",
                    **where,
                    "accion": record["accion"],
                    "velocidad": record["velocidad"],
                    "direccion": record["direccion"],
                    "comando": record["comando"],
                }
            )

    failures.extend(_rule_failures(case, decisions))
    return {
        **result,
        "resultado": FAILED if failures else PASSED,
        "fallos": failures,
        "decisiones": decisions,
        "eventos_watchdog": watchdog_events,
    }


def _run_synthetic_case(case: dict[str, Any], config: Config) -> dict[str, Any]:
    settings, config_sha256 = config
    source = yaml.safe_load(Path(case["archivo"]).read_text(encoding="utf-8"))
    source["casos"] = [item for item in source["casos"] if item["id"] == case["caso_origen"]]
    if not source["casos"]:
        missing = {"regla": "entrada", "motivo": f"no existe el caso {case['caso_origen']}"}
        return {**_base_result(case), "resultado": FAILED, "fallos": [missing], "decisiones": []}
    outcome = ejecutar_casos(source, settings, config_sha256)["casos"][0]
    return {
        **_base_result(case),
        "entrada": {"detecciones": "sinteticas", "caso_origen": case["caso_origen"]},
        "esperado": outcome["esperado"],
        "resultado": outcome["resultado"],
        "fallos": outcome["fallos"],
        "decisiones": outcome["decisiones"],
    }


def _pending_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base_result(case),
        "entrada": case["entrada"],
        "esperado": case["esperado"],
        "plazo_ms": case["plazo_ms"],
        "bloqueado_por": case["bloqueado_por"],
        "resultado": PENDING,
        "fallos": [],
        "decisiones": [],
    }


def _run_watchdog_case(case: dict[str, Any], config: Config) -> dict[str, Any]:
    """Reproduce C8 por Pipeline y politica real con reloj y detector deterministas."""
    settings, config_sha256 = config
    now = {"ms": 1000.0}

    class ClearImage:
        shape = (416, 416, 3)

    class ClearDetector:
        @staticmethod
        def read_image(_source):
            return ClearImage()

        @staticmethod
        def detect_image(_image, *, source="array"):
            return ()

    adapter = VirtualControlAdapter(clock_ms=lambda: now["ms"])
    pipeline = Pipeline(
        ClearDetector(),
        PoliticaDecision(settings, config_sha256=config_sha256),
        adapter,
    )

    decisions: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    # Tres cuadros libres confirman la via mediante la politica real.
    for index, capture_ms in enumerate((1000.0, 1100.0, 1200.0), start=1):
        now["ms"] = capture_ms
        trace = pipeline.process(
            FrameInput(
                sequence_id="c8",
                frame_id=f"c8-{index:04d}",
                t_capture_ms=capture_ms,
                image_size=(416, 416),
                image_path=Path("c8-clear.synthetic"),
            )
        )
        decisions.append(_frame_record(trace))

    moving = adapter.last_command

    if moving is None or moving.direction != "forward":
        failures.append(
            {
                "regla": "movimiento_inicial",
                "motivo": "la politica no alcanzo FORWARD antes del corte",
            }
        )
        deadline = now["ms"] + case["plazo_ms"]
    else:
        commands.append(
            {
                "evento": "movimiento_inicial",
                "direction": moving.direction,
                "speed": moving.speed,
                "reason_code": moving.reason_code,
            }
        )
        deadline = moving.valid_until_ms

        if deadline is None:
            failures.append(
                {
                    "regla": "vigencia",
                    "motivo": "el comando de movimiento no tiene valid_until_ms",
                }
            )
            deadline = now["ms"] + case["plazo_ms"]

    expected_deadline = now["ms"] + case["plazo_ms"]
    if deadline != expected_deadline:
        failures.append(
            {
                "regla": "plazo",
                "esperado_ms": expected_deadline,
                "observado_ms": deadline,
            }
        )

    # No llega ningun cuadro nuevo: solo avanza el reloj.
    now["ms"] = deadline
    watchdog_stop = pipeline.check_watchdog()

    if watchdog_stop is None:
        failures.append(
            {
                "regla": "watchdog",
                "motivo": "no genero STOP al vencer sin cuadro nuevo",
            }
        )
    else:
        commands.append(
            {
                "evento": "watchdog",
                "direction": watchdog_stop["direction"],
                "speed": watchdog_stop["speed"],
                "reason_code": watchdog_stop["reason_code"],
            }
        )

    # Luego llega un cuadro cuya captura ya tiene exactamente una vigencia de antiguedad.
    stale_capture_ms = deadline - case["plazo_ms"]
    stale_trace = pipeline.process(
        FrameInput(
            sequence_id="c8",
            frame_id="c8-stale",
            t_capture_ms=stale_capture_ms,
            image_size=(416, 416),
            image_path=Path("c8-stale.synthetic"),
        )
    )
    stale_record = _frame_record(stale_trace)
    decisions.append(stale_record)

    commands.append(
        {
            "evento": "cuadro_vencido",
            "direction": stale_trace.command["direction"],
            "speed": stale_trace.command["speed"],
            "reason_code": stale_trace.command["reason_code"],
        }
    )

    if (
        stale_trace.command["direction"] != "stop"
        or not stale_trace.errors
        or stale_trace.errors[0]["stage"] != "stale"
    ):
        failures.append(
            {
                "regla": "cuadro_vencido",
                "motivo": "el cuadro vencido no fue rechazado antes de percepcion/politica",
            }
        )

    return {
        **_base_result(case),
        "entrada": case["entrada"],
        "esperado": case["esperado"],
        "plazo_ms": case["plazo_ms"],
        "resultado": FAILED if failures else PASSED,
        "fallos": failures,
        "decisiones": decisions,
        "comandos": commands,
    }


def _run_detector_failure_case(case: dict[str, Any], config: Config) -> dict[str, Any]:
    """Reproduce C9 con fallos deterministas de inferencia e imagen ilegible."""
    settings, config_sha256 = config

    class ClearImage:
        shape = (416, 416, 3)

    class C9Detector:
        @staticmethod
        def read_image(source):
            if "unreadable" in str(source):
                raise DetectorError("imagen ilegible")
            return ClearImage()

        @staticmethod
        def detect_image(_image, *, source="array"):
            if "inference" in str(source):
                raise DetectorError("fallo de inferencia")
            return ()

    adapter = VirtualControlAdapter()
    pipeline = Pipeline(
        C9Detector(),
        PoliticaDecision(settings, config_sha256=config_sha256),
        adapter,
    )

    decisions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    # Tres percepciones v?lidas confirman la v?a y alcanzan FORWARD.
    for index, capture_ms in enumerate((0.0, 100.0, 200.0), start=1):
        trace = pipeline.process(
            FrameInput(
                sequence_id="c9",
                frame_id=f"c9-{index:04d}",
                t_capture_ms=capture_ms,
                image_size=(416, 416),
                image_path=Path("c9-clear.synthetic"),
            )
        )
        decisions.append(_frame_record(trace))

    if adapter.last_command is None or adapter.last_command.direction != "forward":
        failures.append(
            {
                "regla": "movimiento_inicial",
                "motivo": "la pol?tica no alcanz? FORWARD antes de provocar el fallo",
            }
        )

    # Fallo de inferencia: no debe dejar avance residual.
    inference = pipeline.process(
        FrameInput(
            sequence_id="c9",
            frame_id="c9-inference-failure",
            t_capture_ms=300.0,
            image_size=(416, 416),
            image_path=Path("c9-inference.synthetic"),
        )
    )
    decisions.append(_frame_record(inference))

    # Imagen ilegible: tambi?n debe quedar en FAULT + STOP.
    unreadable = pipeline.process(
        FrameInput(
            sequence_id="c9",
            frame_id="c9-unreadable",
            t_capture_ms=400.0,
            image_size=(416, 416),
            image_path=Path("c9-unreadable.synthetic"),
        )
    )
    decisions.append(_frame_record(unreadable))

    for name, trace in (
        ("fallo_inferencia", inference),
        ("imagen_ilegible", unreadable),
    ):
        stages = [error["stage"] for error in trace.errors]
        if (
            trace.perception["status"] != "error"
            or trace.decision is None
            or trace.decision["estado"] != "FAULT"
            or trace.decision["reason_code"] != "ERROR_PERCEPCION"
            or trace.command["direction"] != "stop"
            or trace.command["speed"] != 0.0
            or "detector" not in stages
        ):
            failures.append(
                {
                    "regla": name,
                    "motivo": "el fallo del detector no termin? en FAULT + STOP",
                }
            )

    if adapter.last_command is None or adapter.last_command.direction != "stop":
        failures.append(
            {
                "regla": "avance_residual",
                "motivo": "qued? un comando de movimiento despu?s del fallo",
            }
        )

    return {
        **_base_result(case),
        "entrada": case["entrada"],
        "esperado": case["esperado"],
        "plazo_ms": case["plazo_ms"],
        "resultado": FAILED if failures else PASSED,
        "fallos": failures,
        "decisiones": decisions,
    }


def _run_emergency_case(case: dict[str, Any], config: Config) -> dict[str, Any]:
    """Reproduce C10: emergencia enclavada, rearme fresco y cierre seguro."""
    settings, config_sha256 = config
    now = {"ms": 0.0}

    class ClearImage:
        shape = (416, 416, 3)

    class ClearDetector:
        @staticmethod
        def read_image(_source):
            return ClearImage()

        @staticmethod
        def detect_image(_image, *, source="array"):
            return ()

    adapter = VirtualControlAdapter(clock_ms=lambda: now["ms"])
    pipeline = Pipeline(
        ClearDetector(),
        PoliticaDecision(settings, config_sha256=config_sha256),
        adapter,
    )

    failures: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def frame(frame_id: str, capture_ms: float) -> FrameInput:
        return FrameInput(
            sequence_id="c10",
            frame_id=frame_id,
            t_capture_ms=capture_ms,
            image_size=(416, 416),
            image_path=Path(f"{frame_id}.synthetic"),
        )

    # Tres cuadros frescos confirman la v?a.
    for index, capture_ms in enumerate((0.0, 100.0, 200.0), start=1):
        now["ms"] = capture_ms
        trace = pipeline.process(frame(f"c10-{index:04d}", capture_ms))
        decisions.append(_frame_record(trace))

    moving = adapter.last_command
    if moving is None or moving.direction != "forward":
        failures.append(
            {
                "regla": "movimiento_inicial",
                "motivo": "la pol?tica no alcanz? FORWARD antes de la emergencia",
            }
        )
    else:
        events.append(
            {
                "evento": "movimiento_inicial",
                "direction": moving.direction,
                "speed": moving.speed,
                "reason_code": moving.reason_code,
            }
        )

    # Emergencia: STOP inmediato y enclavado.
    emergency = pipeline.trigger_emergency()
    events.append(
        {
            "evento": "emergencia",
            "direction": emergency["direction"],
            "speed": emergency["speed"],
            "reason_code": emergency["reason_code"],
        }
    )

    if emergency["direction"] != "stop" or not pipeline.emergency_latched:
        failures.append(
            {
                "regla": "emergencia",
                "motivo": "la emergencia no produjo STOP enclavado",
            }
        )

    # Un cuadro despejado no rearma autom?ticamente.
    now["ms"] = 300.0
    blocked = pipeline.process(frame("c10-sin-rearme", 300.0))
    decisions.append(_frame_record(blocked))
    events.append(
        {
            "evento": "sin_rearme",
            "direction": blocked.command["direction"],
            "speed": blocked.command["speed"],
            "reason_code": blocked.command["reason_code"],
        }
    )

    if blocked.command["direction"] != "stop" or not pipeline.emergency_latched:
        failures.append(
            {
                "regla": "enclavamiento",
                "motivo": "un cuadro despejado liber? la emergencia sin rearme expl?cito",
            }
        )

    # Se solicita rearme, pero un cuadro vencido no puede completarlo.
    pipeline.request_rearm()
    now["ms"] = 1000.0

    stale = pipeline.process(frame("c10-rearm-stale", 300.0))
    decisions.append(_frame_record(stale))
    events.append(
        {
            "evento": "rearme_con_cuadro_vencido",
            "direction": stale.command["direction"],
            "speed": stale.command["speed"],
            "reason_code": stale.command["reason_code"],
        }
    )

    if stale.command["direction"] != "stop" or not pipeline.emergency_latched:
        failures.append(
            {
                "regla": "rearme_vencido",
                "motivo": "un cuadro vencido complet? el rearme",
            }
        )

    # Una percepci?n fresca v?lida s? libera el latch,
    # pero la pol?tica debe volver a confirmar la v?a.
    fresh = pipeline.process(frame("c10-rearm-fresh", 1000.0))
    decisions.append(_frame_record(fresh))
    events.append(
        {
            "evento": "rearme_fresco",
            "direction": fresh.command["direction"],
            "speed": fresh.command["speed"],
            "reason_code": fresh.command["reason_code"],
        }
    )

    if (
        pipeline.emergency_latched
        or fresh.command["direction"] != "stop"
        or fresh.decision is None
        or fresh.decision["reason_code"] != "PERCEPCION_NO_CONFIRMADA"
    ):
        failures.append(
            {
                "regla": "rearme_fresco",
                "motivo": "la percepci?n fresca no produjo un rearme seguro con reconfirmaci?n",
            }
        )

    # Hacen falta dos cuadros frescos m?s para volver a avanzar.
    now["ms"] = 1100.0
    second = pipeline.process(frame("c10-confirm-2", 1100.0))
    decisions.append(_frame_record(second))

    now["ms"] = 1200.0
    third = pipeline.process(frame("c10-confirm-3", 1200.0))
    decisions.append(_frame_record(third))

    events.append(
        {
            "evento": "movimiento_reanudado",
            "direction": third.command["direction"],
            "speed": third.command["speed"],
            "reason_code": third.command["reason_code"],
        }
    )

    if second.command["direction"] != "stop" or third.command["direction"] != "forward":
        failures.append(
            {
                "regla": "reconfirmacion",
                "motivo": "el movimiento no respet? los cuadros requeridos para reconfirmar",
            }
        )

    # Cierre controlado: el ?ltimo comando siempre debe ser STOP.
    shutdown = pipeline.shutdown()
    events.append(
        {
            "evento": "shutdown",
            "direction": shutdown["direction"],
            "speed": shutdown["speed"],
            "reason_code": shutdown["reason_code"],
        }
    )

    if (
        shutdown["direction"] != "stop"
        or shutdown["reason_code"] != "APPLICATION_SHUTDOWN"
        or adapter.last_command is None
        or adapter.last_command.direction != "stop"
    ):
        failures.append(
            {
                "regla": "shutdown",
                "motivo": "el cierre no dej? STOP como comando final",
            }
        )

    return {
        **_base_result(case),
        "entrada": case["entrada"],
        "esperado": case["esperado"],
        "plazo_ms": case["plazo_ms"],
        "resultado": FAILED if failures else PASSED,
        "fallos": failures,
        "decisiones": decisions,
        "eventos": events,
    }


def run_cases(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    config: Config,
    detector: YoloxDetector,
    dataset: Path,
) -> dict[str, Any]:
    results = []
    for case in data["casos"]:
        if case["tipo"] == "real":
            results.append(run_real_case(case, rows, config, detector, dataset))
        elif case["tipo"] == "sintetico":
            results.append(_run_synthetic_case(case, config))
        elif case["tipo"] == "watchdog":
            results.append(_run_watchdog_case(case, config))
        elif case["tipo"] == "detector_failure":
            results.append(_run_detector_failure_case(case, config))
        elif case["tipo"] == "emergency":
            results.append(_run_emergency_case(case, config))
        else:
            results.append(_pending_case(case))

    count = {status: sum(r["resultado"] == status for r in results) for status in (PASSED, FAILED)}
    pending = sum(r["resultado"] == PENDING for r in results)
    return {
        "total": len(results),
        "pasan": count[PASSED],
        "fallan": count[FAILED],
        "pendientes": pending,
        "correcto": count[PASSED] == len(results),
        "casos": results,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _write_results(output: Path, report: dict[str, Any]) -> None:
    output.mkdir(parents=True)
    (output / "resultados.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    with (output / "decisiones.jsonl").open("w", encoding="utf-8", newline="\n") as lines:
        for case in report["casos"]:
            for decision in case["decisiones"]:
                lines.write(json.dumps({"caso": case["id"], **decision}, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m p5.casos.runner",
        description="Corre los casos C1-C10 en modo virtual, sin hardware.",
    )
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path, help="Paquete congelado.")
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Carpeta nueva.")
    args = parser.parse_args(argv)

    if args.output.exists():
        parser.error(f"--output ya existe: {args.output}")

    try:
        data = load_cases(args.cases)
        rows = load_manifest(args.dataset / MANIFEST_FILE)
        config = cargar_config(args.config)
        detector = load_detector(args.weights)
        report = run_cases(data, rows, config, detector, args.dataset)
    except (DetectorError, OSError, ValueError, KeyError) as error:
        print(f"no se pudieron correr los casos: {error}", file=sys.stderr)
        return 1

    report["ejecucion"] = {
        "run_id": uuid4().hex,
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": _current_commit(),
        "modo": "virtual",
        "salida": "comandos del adaptador virtual; C6 solo evalua decisiones de la politica",
        "salida_fisica": VirtualControlAdapter.physical_output_enabled,
        "casos": str(args.cases),
        "dataset": str(args.dataset),
        "modelo_sha256": _sha256(args.weights),
        "manifiesto_sha256": _sha256(args.dataset / MANIFEST_FILE),
        "config_sha256": config[1],
        "umbral_detector": DEFAULT_SCORE_THRESHOLD,
        "nms_detector": DEFAULT_NMS_THRESHOLD,
        "runtime": f"Python {platform.python_version()}",
        "hardware": f"{platform.system()} {platform.machine()}, CPU",
    }
    _write_results(args.output, report)

    for case in report["casos"]:
        print(f"{case['id']:<4} {case['resultado']:<10} {case['nombre']}")
        for failure in case["fallos"]:
            print(f"     {json.dumps(failure, ensure_ascii=False)}")
    print(
        f"{report['pasan']} pasan, {report['fallan']} fallan, "
        f"{report['pendientes']} pendientes -> {args.output}"
    )
    return 0 if report["correcto"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
