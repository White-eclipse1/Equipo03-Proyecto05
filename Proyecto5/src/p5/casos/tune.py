"""Seleccion reproducible de perfil B1-03 usando SOLO p5-ajuste-v1.

No modifica zonas ni datos. Compara 48 perfiles de confianza, temporalidad y evasion.
La seleccion se guarda antes de autorizar la evaluacion final separada.
"""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import yaml
from p3.policy.config import ConfigPolitica, cargar_config
from p3.policy.politica import PoliticaDecision

from p5.casos.geometry import geometry_failures
from p5.dataset.paquete import load_manifest
from p5.detector.frame import detect_frame
from p5.detector.weights import verify_weights
from p5.detector.yolox import YoloxDetector


def select_profile(rows, perceptions, base):
    if not rows or any(row["split"] != "ajuste" for row in rows):
        raise ValueError("la seleccion solo admite cuadros de ajuste, nunca evaluacion")
    if {row["frame_id"] for row in rows} != set(perceptions):
        raise ValueError("las predicciones no corresponden al paquete de ajuste")
    candidates = []
    for high, block, release, evade in itertools.product(
        (0.2, 0.3, 0.4, 0.5), (1, 2), (3, 4, 5), (False, True)
    ):
        settings = base.model_dump(mode="json")
        settings["confianza"].update(umbral_alto=high, umbral_bajo=max(0.1, round(high - 0.2, 2)))
        settings["temporal"].update(cuadros_para_bloquear=block, cuadros_para_liberar=release)
        settings["evasion"]["habilitada"] = evade
        config = ConfigPolitica.model_validate(settings)
        engine = PoliticaDecision(config)
        failures = []
        idle = 0
        for row in rows:
            perception = perceptions[row["frame_id"]]
            if perception["status"] != "ok":
                raise ValueError(f"fallo de percepcion durante ajuste: {row['frame_id']}")
            decision = engine.decidir_crudo(perception).model_dump(mode="json")
            record = {**decision, "cuadro": perception}
            failures.extend(
                {"frame_id": row["frame_id"], **failure}
                for failure in geometry_failures(record, row, config)
            )
            if decision["accion"] not in row["allowed_actions"]:
                failures.append(
                    {
                        "regla": "acciones",
                        "frame_id": row["frame_id"],
                        "observada": decision["accion"],
                        "permitidas": row["allowed_actions"],
                    }
                )
            if row["road_state"].startswith("lateral_") and decision["accion"] == "STOP":
                idle += 1
        # Control negativo sintetico: un perfil que siempre pare no es elegible.
        clear_engine = PoliticaDecision(config)
        for index in range(release):
            clear_decision = clear_engine.decidir_crudo(
                {
                    "sequence_id": "clear-control",
                    "frame_id": str(index),
                    "t_capture_ms": index * 100,
                    "image_width": 400,
                    "image_height": 296,
                    "status": "ok",
                    "detections": [],
                }
            )
        clear_ok = clear_decision.accion == "FORWARD" and clear_decision.velocidad > 0
        unsafe = sum(
            f["regla"] in ("destino_no_libre", "avance_hacia_centro_ocupado") for f in failures
        )
        changes = (
            (block != base.temporal.cuadros_para_bloquear)
            + (release != base.temporal.cuadros_para_liberar)
            + (evade != base.evasion.habilitada)
            + (high != base.confianza.umbral_alto)
        )
        # Orden fijado antes de medir: seguridad, infracciones, progreso y cambios minimos.
        rank = [not clear_ok, unsafe, len(failures), idle, changes, block, release, evade, -high]
        candidates.append(
            {
                "config": settings,
                "rank": rank,
                "unsafe": unsafe,
                "fallos": failures,
                "stops_laterales": idle,
                "control_libre": clear_ok,
            }
        )
    chosen = min(candidates, key=lambda item: item["rank"])
    return chosen, candidates


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=Path("data/p5-ajuste-v1"))
    parser.add_argument("--config", type=Path, default=Path("config/politica.yaml"))
    parser.add_argument("--weights", type=Path, default=Path("models/yolox_tiny.onnx"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("usa una carpeta nueva; la evidencia no se sobrescribe")
    if args.output.resolve().is_relative_to(args.dataset.resolve()):
        parser.error("la salida no puede estar dentro del dataset")
    rows = load_manifest(args.dataset / "manifiesto.jsonl")
    if not rows or any(row["split"] != "ajuste" for row in rows):
        parser.error("solo se admite el split ajuste; evaluacion no se puede seleccionar")
    verify_weights(args.weights)
    base, base_sha256 = cargar_config(args.config)
    detector = YoloxDetector.from_weights(args.weights)
    perceptions = {}
    for row in rows:
        perceptions[row["frame_id"]] = detect_frame(
            detector,
            args.dataset / row["image"],
            sequence_id=row["sequence_id"],
            frame_id=row["frame_id"],
            t_capture_ms=row["t_capture_ms"],
            image_size=(row["image_width"], row["image_height"]),
        ).to_dict()
    chosen, candidates = select_profile(rows, perceptions, base)
    args.output.mkdir(parents=True)
    profile = yaml.safe_dump(chosen["config"], sort_keys=False)
    (args.output / "politica_seleccionada.yaml").write_text(profile, encoding="utf-8", newline="\n")
    report = {
        "dataset": str(args.dataset),
        "split": "ajuste",
        "cuadros": len(rows),
        "manifiesto_sha256": hashlib.sha256(
            (args.dataset / "manifiesto.jsonl").read_bytes()
        ).hexdigest(),
        "base_config_sha256": base_sha256,
        "modelo_sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "seleccion_sha256": hashlib.sha256(profile.encode()).hexdigest(),
        "criterio": [
            "control_libre",
            "unsafe",
            "fallos",
            "stops_laterales",
            "cambios",
            "bloqueo",
            "liberacion",
            "evasion",
            "confianza_descendente",
        ],
        "seleccion": chosen,
        "candidatos": candidates,
    }
    (args.output / "seleccion.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    with (args.output / "predicciones.jsonl").open("x", encoding="utf-8", newline="\n") as output:
        for frame in perceptions.values():
            output.write(json.dumps(frame) + "\n")
    print(f"48 perfiles; seleccion {chosen['rank']}; fallos de ajuste: {len(chosen['fallos'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
