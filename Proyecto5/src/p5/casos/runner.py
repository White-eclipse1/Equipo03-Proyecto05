"""Runner de los casos C1-C10 sobre un paquete congelado (B3-02; E5).

La percepcion solo recibe la imagen y sus identificadores. Las etiquetas y las acciones
admisibles se usan despues, para comparar lo que decidio el sistema. Sale con codigo 1 si un
caso falla o sigue pendiente. Ver `docs/B3-02_RUNNER.md`.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from p3.policy.casos import ejecutar_casos
from p3.policy.config import ConfigPolitica, cargar_config
from p3.policy.politica import PoliticaDecision

from p5.control.adapter import VirtualControlAdapter
from p5.control.models import Action, ControlDecision
from p5.dataset.paquete import MANIFEST_FILE, load_manifest
from p5.detector.frame import detect_frame
from p5.detector.yolox import DEFAULT_NMS_THRESHOLD, DEFAULT_SCORE_THRESHOLD, YoloxDetector

REQUIRED_CASES = tuple(f"C{number}" for number in range(1, 11))
PASSED = "PASA"
FAILED = "FALLA"
PENDING = "PENDIENTE"

# Lo unico del manifiesto que llega a la percepcion. Nunca las etiquetas ni las expectativas.
INPUT_FIELDS = ("sequence_id", "frame_id", "image", "t_capture_ms", "image_width", "image_height")

Config = tuple[ConfigPolitica, str]
Perceive = Callable[[dict[str, Any]], dict[str, Any]]


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


def detector_perceive(weights: Path, dataset: Path) -> Perceive:
    """Percepcion real: corre el detector sobre la imagen de cada cuadro."""
    detector = YoloxDetector.from_weights(weights)

    def perceive(row: dict[str, Any]) -> dict[str, Any]:
        return detect_frame(
            detector,
            dataset / row["image"],
            sequence_id=row["sequence_id"],
            frame_id=row["frame_id"],
            t_capture_ms=row["t_capture_ms"],
            image_size=(row["image_width"], row["image_height"]),
        ).to_dict()

    return perceive


def _perceive_safely(perceive: Perceive, row: dict[str, Any]) -> dict[str, Any]:
    visible = {field: row[field] for field in INPUT_FIELDS}
    try:
        return perceive(visible)
    except Exception as failure:
        # Un fallo inesperado de la percepcion nunca se presenta como una escena vacia.
        return {
            "sequence_id": row["sequence_id"],
            "frame_id": row["frame_id"],
            "t_capture_ms": row["t_capture_ms"],
            "image_width": row["image_width"],
            "image_height": row["image_height"],
            "status": "error",
            "detections": [],
            "error": f"{type(failure).__name__}: {failure}",
        }


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
    case: dict[str, Any], rows: list[dict[str, Any]], config: Config, perceive: Perceive
) -> dict[str, Any]:
    """Corre una secuencia por la percepcion y la politica, y compara cuadro por cuadro."""
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

    policy = PoliticaDecision(settings, config_sha256=config_sha256)
    decisions = []
    failures = []
    for number, row in enumerate(sequence, start=1):
        frame = _perceive_safely(perceive, row)
        decision = policy.decidir_crudo(frame).model_dump(mode="json")
        decisions.append({**decision, "cuadro": frame})
        if decision["accion"] not in row["allowed_actions"]:
            failures.append(
                {
                    "regla": "acciones",
                    "cuadro": number,
                    "frame_id": row["frame_id"],
                    "observada": decision["accion"],
                    "permitidas": row["allowed_actions"],
                    "reason_code": decision["reason_code"],
                }
            )
    failures.extend(_rule_failures(case, decisions))
    return {
        **result,
        "resultado": FAILED if failures else PASSED,
        "fallos": failures,
        "decisiones": decisions,
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


def _run_watchdog_case(case: dict[str, Any]) -> dict[str, Any]:
    """Reproduce C8 con reloj falso, sin esperar tiempo real ni recibir otro frame."""
    now = {"ms": 1000.0}
    deadline = now["ms"] + case["plazo_ms"]

    adapter = VirtualControlAdapter(clock_ms=lambda: now["ms"])

    forward = adapter.apply(
        ControlDecision(
            action=Action.FORWARD,
            requested_speed=0.5,
            frame_id="c8-fresh",
            decision_id="c8-forward",
            reason_code="clear_path",
            requested_steering=0.0,
            t_capture_ms=now["ms"],
            valid_until_ms=deadline,
        )
    )

    commands = [
        {
            "evento": "movimiento_inicial",
            "direction": forward.direction,
            "speed": forward.speed,
            "reason_code": forward.reason_code,
        }
    ]
    failures: list[dict[str, Any]] = []

    # Dejan de llegar cuadros y solamente avanza el reloj.
    now["ms"] = deadline
    watchdog_stop = adapter.check_watchdog()

    if watchdog_stop is None:
        failures.append({"regla": "watchdog", "motivo": "no genero STOP al vencer"})
    else:
        commands.append(
            {
                "evento": "watchdog",
                "direction": watchdog_stop.direction,
                "speed": watchdog_stop.speed,
                "reason_code": watchdog_stop.reason_code,
            }
        )

    # Luego llega una decision basada en percepcion ya vencida.
    stale = adapter.apply(
        ControlDecision(
            action=Action.FORWARD,
            requested_speed=0.5,
            frame_id="c8-stale",
            decision_id="c8-stale",
            reason_code="clear_path",
            requested_steering=0.0,
            t_capture_ms=1000.0,
            valid_until_ms=deadline,
        )
    )

    commands.append(
        {
            "evento": "cuadro_vencido",
            "direction": stale.direction,
            "speed": stale.speed,
            "reason_code": stale.reason_code,
        }
    )

    if stale.direction != "stop" or stale.reason_code != "watchdog_timeout":
        failures.append(
            {
                "regla": "cuadro_vencido",
                "motivo": "la percepcion vencida reinicio el movimiento",
            }
        )

    return {
        **_base_result(case),
        "entrada": case["entrada"],
        "esperado": case["esperado"],
        "plazo_ms": case["plazo_ms"],
        "resultado": FAILED if failures else PASSED,
        "fallos": failures,
        "decisiones": [],
        "comandos": commands,
    }


def run_cases(
    data: dict[str, Any], rows: list[dict[str, Any]], config: Config, perceive: Perceive
) -> dict[str, Any]:
    results = []
    for case in data["casos"]:
        if case["tipo"] == "real":
            results.append(run_real_case(case, rows, config, perceive))
        elif case["tipo"] == "sintetico":
            results.append(_run_synthetic_case(case, config))
        elif case["tipo"] == "watchdog":
            results.append(_run_watchdog_case(case))
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
        perceive = detector_perceive(args.weights, args.dataset)
        report = run_cases(data, rows, config, perceive)
    except (OSError, ValueError, KeyError) as error:
        print(f"no se pudieron correr los casos: {error}", file=sys.stderr)
        return 1

    report["ejecucion"] = {
        "run_id": uuid4().hex,
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": _current_commit(),
        "modo": "virtual",
        "salida": "decisiones de la politica; el adaptador se integra en #7",
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
