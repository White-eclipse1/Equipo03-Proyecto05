import argparse
import hashlib
import http.client
import logging
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# Identidad del artefacto. Ver `docs/A1-02_PROCEDENCIA.md`.
WEIGHTS_URL = (
    "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
)
WEIGHTS_SHA256 = "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"
WEIGHTS_SIZE = 20219662
DEFAULT_WEIGHTS_PATH = Path("models") / "yolox_tiny.onnx"

_CHUNK_SIZE = 1024 * 1024
_TIMEOUT_SECONDS = 60


class WeightsError(RuntimeError):
    pass


def _failure(path: Path, detail: object) -> WeightsError:
    logger.error("weights_error path=%s detail=%s", path, detail)
    return WeightsError(f"{path}: {detail}")


def _mismatch(path: Path, sha256: str, size: int) -> str | None:
    actual_size = path.stat().st_size
    if actual_size != size:
        return f"size {actual_size}, expected {size}"

    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK_SIZE):
            digest.update(chunk)
    if digest.hexdigest() != sha256:
        return f"SHA-256 {digest.hexdigest()}, expected {sha256}"
    return None


def verify_weights(
    path: str | Path, *, sha256: str = WEIGHTS_SHA256, size: int = WEIGHTS_SIZE
) -> None:
    target = Path(path)
    if not target.is_file():
        raise _failure(target, "weights file not found")
    if problem := _mismatch(target, sha256, size):
        raise _failure(target, problem)


def download_weights(
    path: str | Path,
    *,
    url: str = WEIGHTS_URL,
    sha256: str = WEIGHTS_SHA256,
    size: int = WEIGHTS_SIZE,
    timeout: float = _TIMEOUT_SECONDS,
) -> bool:
    """Deja en `path` el archivo verificado. Devuelve False si ya estaba y no hizo falta bajarlo.

    Descarga a un temporal y solo lo mueve a `path` si el tamano y el hash coinciden, asi
    que un fallo nunca deja un archivo parcial ni toca el que ya existia.
    """
    target = Path(path)
    if target.is_file():
        problem = _mismatch(target, sha256, size)
        if problem is None:
            return False
        logger.warning("weights_invalid path=%s detail=%s", target, problem)

    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            urllib.request.urlopen(url, timeout=timeout) as response,
            tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=f"{target.name}.", suffix=".part", delete=False
            ) as file,
        ):
            temporary = Path(file.name)
            written = 0
            while chunk := response.read(_CHUNK_SIZE):
                written += len(chunk)
                if written > size:
                    raise _failure(target, f"size above the expected {size}")
                file.write(chunk)

        if problem := _mismatch(temporary, sha256, size):
            raise _failure(target, problem)
        os.replace(temporary, target)
    except (OSError, http.client.HTTPException) as error:
        raise _failure(target, error) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m p5.detector.weights",
        description="Descarga los pesos del detector y verifica su SHA-256.",
    )
    parser.add_argument("--path", default=str(DEFAULT_WEIGHTS_PATH), help="Ruta del modelo .onnx.")
    parser.add_argument("--verify-only", action="store_true", help="Solo verifica, sin descargar.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    try:
        if args.verify_only:
            verify_weights(args.path, sha256=WEIGHTS_SHA256, size=WEIGHTS_SIZE)
        else:
            download_weights(args.path, url=WEIGHTS_URL, sha256=WEIGHTS_SHA256, size=WEIGHTS_SIZE)
    except WeightsError:
        return 1

    print(f"{WEIGHTS_SHA256}  {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
