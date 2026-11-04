"""Ajuste de umbral bajo y rachas de la politica con `p5-ajuste-v1` (B1-03).

Nunca con `p5-eval-v1`: el paquete debe declarar `"package": "ajuste"`. El detector corre una
vez por cuadro y la politica se repite por candidato, reiniciada en cada secuencia. Se elige
por seguridad (acciones fuera de `allowed_actions`), luego por avance con la via libre y
luego por el cambio mas pequeno respecto a la configuracion actual. Ver
`docs/B1-03_VALIDACION.md`.
"""

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path
from typing import Any

from p3.policy.config import ConfigPolitica, cargar_config
from p3.policy.politica import PoliticaDecision

from p5.dataset.paquete import MANIFEST_FILE, SEQUENCES_FILE, load_manifest

GRID = {
    "umbral_bajo": (0.30, 0.25, 0.20, 0.15, 0.10),
    "cuadros_para_bloquear": (1, 2),
    "cuadros_para_liberar": (3, 4, 5),
}
# Estados de via en los que avanzar esta permitido: el centro esta libre.
_PROGRESS_STATES = {"libre", "lateral_izquierda", "lateral_derecha"}
_PROGRESS_ACTIONS = {"FORWARD", "SLOW"}


def check_tuning_package(dataset: Path) -> None:
    declared = json.loads((dataset / SEQUENCES_FILE).read_text(encoding="utf-8")).get("package")
    if declared != "ajuste":
        raise ValueError(f"{dataset}: solo se ajusta con un paquete de ajuste, no {declared!r}")


def _params(config: ConfigPolitica) -> dict[str, Any]:
    return {
        "umbral_bajo": config.confianza.umbral_bajo,
        "cuadros_para_bloquear": config.temporal.cuadros_para_bloquear,
        "cuadros_para_liberar": config.temporal.cuadros_para_liberar,
    }


def candidates(base: ConfigPolitica) -> list[ConfigPolitica]:
    configs = []
    for bajo, bloquear, liberar in itertools.product(*GRID.values()):
        data = base.model_dump()
        data["confianza"]["umbral_bajo"] = bajo
        data["temporal"].update(cuadros_para_bloquear=bloquear, cuadros_para_liberar=liberar)
        configs.append(ConfigPolitica.model_validate(data))
    return configs


def score(
    config: ConfigPolitica, rows: list[dict[str, Any]], frames: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    sequences: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sequences.setdefault(row["sequence_id"], []).append(row)
    detail, stuck = [], 0
    for sequence in sequences.values():
        policy = PoliticaDecision(config)
        for row in sequence:
            decision = policy.decidir_crudo(frames[row["frame_id"]])
            if decision.accion not in row["allowed_actions"]:
                detail.append(
                    {
                        "frame_id": row["frame_id"],
                        "accion": decision.accion,
                        "permitidas": row["allowed_actions"],
                        "reason_code": decision.reason_code,
                    }
                )
            if row["road_state"] in _PROGRESS_STATES and decision.accion not in _PROGRESS_ACTIONS:
                stuck += 1
    return {
        "cuadros": len(rows),
        "no_permitidas": len(detail),
        "sin_avance": stuck,
        "detalle": detail,
    }


def select(results: list[dict[str, Any]], base: ConfigPolitica) -> dict[str, Any]:
    current = _params(base)

    def key(result: dict[str, Any]) -> tuple:
        deltas = [abs(result[name] - value) for name, value in current.items()]
        changed = sum(delta > 1e-9 for delta in deltas)
        return (result["no_permitidas"], result["sin_avance"], changed, *deltas)

    return min(results, key=key)


def tune(
    rows: list[dict[str, Any]], frames: dict[str, dict[str, Any]], base: ConfigPolitica
) -> dict[str, Any]:
    results = []
    for config in candidates(base):
        outcome = score(config, rows, frames)
        results.append({**_params(config), **outcome})
    actual = next(r for r in results if all(r[k] == v for k, v in _params(base).items()))
    return {"actual": actual, "seleccion": select(results, base), "candidatos": results}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ajuste de la politica con p5-ajuste-v1.")
    parser.add_argument("--dataset", type=Path, default=Path("data/p5-ajuste-v1"))
    parser.add_argument("--config", type=Path, default=Path("config/politica.yaml"))
    parser.add_argument("--weights", type=Path, default=Path("models/yolox_tiny.onnx"))
    parser.add_argument("--output", type=Path, required=True, help="Archivo JSON nuevo.")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError(f"la salida ya existe: {args.output}")
        check_tuning_package(args.dataset)
        base, config_sha256 = cargar_config(args.config)
        rows = load_manifest(args.dataset / MANIFEST_FILE)
        # Importado aqui: las pruebas del ajuste no necesitan onnxruntime ni pesos.
        from p5.detector.frame import detect_frame
        from p5.detector.yolox import YoloxDetector

        detector = YoloxDetector.from_weights(args.weights)
        frames = {
            row["frame_id"]: detect_frame(
                detector,
                args.dataset / row["image"],
                sequence_id=row["sequence_id"],
                frame_id=row["frame_id"],
                t_capture_ms=row["t_capture_ms"],
                image_size=(row["image_width"], row["image_height"]),
            ).to_dict()
            for row in rows
        }
        report = {
            "dataset": args.dataset.as_posix(),
            "manifiesto_sha256": _sha256(args.dataset / MANIFEST_FILE),
            "modelo_sha256": _sha256(args.weights),
            "config_sha256": config_sha256,
            "rejilla": GRID,
            "criterio": "min no_permitidas, luego min sin_avance, luego el cambio mas pequeno",
            **tune(rows, frames, base),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, KeyError) as failure:
        print(f"policy_tuning_error: {failure}", file=sys.stderr)
        return 1
    actual, chosen = report["actual"], report["seleccion"]
    print(
        f"actual: {actual['no_permitidas']} no permitidas, {actual['sin_avance']} sin avance; "
        f"seleccion: umbral_bajo={chosen['umbral_bajo']} "
        f"bloquear={chosen['cuadros_para_bloquear']} liberar={chosen['cuadros_para_liberar']} "
        f"({chosen['no_permitidas']} no permitidas, {chosen['sin_avance']} sin avance) "
        f"-> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
