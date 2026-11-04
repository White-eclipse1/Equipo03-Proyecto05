import argparse
import logging
import sys
from pathlib import Path

import yaml
from p3.policy.config import cargar_config
from p3.policy.politica import PoliticaDecision

from p5.control.adapter import VirtualControlAdapter
from p5.detector.weights import DEFAULT_WEIGHTS_PATH
from p5.detector.yolox import DetectorError, YoloxDetector
from p5.integration.pipeline import FrameInput, Pipeline, frames_from_manifest

logger = logging.getLogger(__name__)

DEFAULT_POLICY_CONFIG = Path("..") / "Proyecto3" / "config" / "politica.yaml"


def _prepare(args: argparse.Namespace) -> tuple[Pipeline, list[FrameInput]]:
    frames = frames_from_manifest(args.manifest, sequence_id=args.sequence)
    config, config_sha256 = cargar_config(args.policy_config)
    detector = YoloxDetector.from_weights(args.weights)
    pipeline = Pipeline(detector, PoliticaDecision(config, config_sha256), VirtualControlAdapter())
    return pipeline, frames


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m p5.integration",
        description="Lleva cada imagen de un manifiesto por el detector, la politica y el "
        "adaptador virtual, y guarda una traza JSONL con una linea por cuadro.",
    )
    parser.add_argument("--manifest", type=Path, required=True, help="Manifiesto congelado.")
    parser.add_argument("--output", type=Path, required=True, help="Archivo JSONL de salida.")
    parser.add_argument("--sequence", help="Solo esta secuencia. Sin ella, todo el manifiesto.")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS_PATH)
    parser.add_argument("--policy-config", type=Path, default=DEFAULT_POLICY_CONFIG)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    try:
        pipeline, frames = _prepare(args)
    except (DetectorError, OSError, ValueError, yaml.YAMLError) as failure:
        logger.error("integration_error stage=startup detail=%s", failure)
        return 1

    failed = 0
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as output:
            for frame in frames:
                trace = pipeline.process(frame)
                # Linea a linea: si el proceso se interrumpe, la evidencia ya esta escrita.
                output.write(trace.to_json() + "\n")
                output.flush()
                failed += bool(trace.errors)
    except OSError as failure:
        logger.error("integration_error stage=output detail=%s", failure)
        return 1

    print(f"frames={len(frames)} errors={failed} output={args.output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
