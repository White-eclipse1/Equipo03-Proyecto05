import argparse
import json
import logging
import sys

from p5.detector.yolox import (
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DetectorError,
    YoloxDetector,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m p5.detector",
        description="Ejecuta YOLOX en CPU sobre una imagen e imprime las detecciones en JSON.",
    )
    parser.add_argument("--weights", required=True, help="Ruta del modelo .onnx.")
    parser.add_argument("--image", required=True, help="Ruta de la imagen completa.")
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    parser.add_argument("--nms-threshold", type=float, default=DEFAULT_NMS_THRESHOLD)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    try:
        detector = YoloxDetector.from_weights(
            args.weights,
            score_threshold=args.score_threshold,
            nms_threshold=args.nms_threshold,
        )
        result = detector.detect_file(args.image)
    except (DetectorError, ValueError):
        return 1

    print(json.dumps(result.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
