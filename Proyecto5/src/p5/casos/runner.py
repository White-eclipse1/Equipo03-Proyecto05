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

from p5.casos.confidence import run_confidence_case
from p5.casos.geometry import geometry_failures
from p5.casos.temporal import run_temporal_control
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
    expected_states = case.get("estados_en_orden", [])
    progress = 0
    for decision in decisions:
        if progress < len(expected_states) and decision["estado"] == expected_states[progress]:
            progress += 1
    if progress != len(expected_states):
        failures.append(
            {
                "regla": "estados_en_orden",
                "esperados": expected_states,
                "observados": [d["estado"] for d in decisions],
            }
        )

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
            **{
                key: case[key]
                for key in (
                    "alguna",
                    "reaccion",
                    "estados_en_orden",
                    "direccion_min",
                    "direccion_max",
                )
                if key in case
            },
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

        failures.extend(
            {**failure, **where} for failure in geometry_failures(record, row, settings)
        )

    failures.extend(_rule_failures(case, decisions))
    temporal_control = run_temporal_control(config) if case["id"] == "C7" else None
    if temporal_control:
        failures.extend(
            {"origen": "control_temporal", **failure} for failure in temporal_control["fallos"]
        )
    return {
        **result,
        "resultado": FAILED if failures else PASSED,
        "fallos": failures,
        "decisiones": decisions,
        "eventos_watchdog": watchdog_events,
        "control_temporal": temporal_control,
    }


def _run_synthetic_case(case: dict[str, Any], config: Config) -> dict[str, Any]:
    if case.get("confidence_from_config"):
        return run_confidence_case(case, config)
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
            [
                "git",
                "-c",
                f"safe.directory={Path(__file__).resolve().parents[4].as_posix()}",
                "rev-parse",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
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
    with (output / "fallos.jsonl").open("w", encoding="utf-8", newline="\n") as lines:
        for case in report["casos"]:
            for failure in case["fallos"]:
                lines.write(json.dumps({"caso": case["id"], **failure}, ensure_ascii=False) + "\n")
    with (output / "controles_temporales.jsonl").open("w", encoding="utf-8", newline="\n") as lines:
        for case in report["casos"]:
            control = case.get("control_temporal")
            if control:
                for decision in control["decisiones"]:
                    lines.write(
                        json.dumps({"caso": case["id"], **decision}, ensure_ascii=False) + "\n"
                    )


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
    parser.add_argument(
        "--only",
        nargs="+",
        choices=REQUIRED_CASES,
        help="Ejecuta solo estos casos; el archivo debe seguir declarando C1-C10.",
    )
    args = parser.parse_args(argv)

    if args.output.exists():
        parser.error(f"--output ya existe: {args.output}")

    try:
        data = load_cases(args.cases)
        if args.only:
            if len(set(args.only)) != len(args.only):
                parser.error("--only no admite casos repetidos")
            data["casos"] = [case for case in data["casos"] if case["id"] in args.only]
        rows = load_manifest(args.dataset / MANIFEST_FILE)
        config = cargar_config(args.config)
        # Sellar entradas antes de cargar el detector: nunca derivar expectativas del resultado.
        expectations = {
            "fecha_previa_inferencia": datetime.now(UTC).isoformat(),
            "casos_sha256": _sha256(args.cases),
            "config_sha256": config[1],
            "manifiesto_sha256": _sha256(args.dataset / MANIFEST_FILE),
            "casos_ejecutados": [case["id"] for case in data["casos"]],
        }
        synthetic_sources = {case["archivo"] for case in data["casos"] if "archivo" in case}
        expectations["fuentes_sinteticas_sha256"] = {
            str(Path(path).name): _sha256(Path(path)) for path in sorted(synthetic_sources)
        }
        detector = load_detector(args.weights)
        report = run_cases(data, rows, config, detector, args.dataset)
    except (DetectorError, OSError, ValueError, KeyError) as error:
        print(f"no se pudieron correr los casos: {error}", file=sys.stderr)
        return 1

    report["ejecucion"] = {
        "run_id": uuid4().hex,
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": _current_commit(),
        "detector": type(detector).__name__,
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
        "expectativas_previas": expectations,
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
