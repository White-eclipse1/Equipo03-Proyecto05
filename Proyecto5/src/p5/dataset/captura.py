"""Guarda una secuencia de cuadros desde el stream MJPEG del carro.

Solo lee `/stream`: nunca llama a las rutas de motores. El firmware atiende un solo cliente del
stream a la vez, asi que la pagina del carro debe estar cerrada mientras se captura.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.request import urlopen

logger = logging.getLogger(__name__)

CAPTURES_FILE = "capturas.jsonl"
SEQUENCES_DIR = "secuencias"
DEFAULT_INTERVAL_MS = 500
_TIMEOUT_S = 10
_MAX_HEADER_LINE = 1024
_SEQUENCE_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
# Marcadores SOF: todos los C0-CF salvo DHT (C4), JPG (C8) y DAC (CC).
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


class CaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class FrameRecord:
    sequence_id: str
    frame_id: str
    file: str
    t_capture_ms: int
    image_width: int
    image_height: int
    sha256: str


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Devuelve (ancho, alto) de un JPEG completo, o None si esta truncado o no es JPEG."""
    if len(data) < 4 or data[:2] != b"\xff\xd8" or b"\xff\xd9" not in data[-16:]:
        return None
    position = 2
    while position + 9 <= len(data):
        if data[position] != 0xFF:
            return None
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker in _SOF_MARKERS:
            height = int.from_bytes(data[position + 5 : position + 7])
            width = int.from_bytes(data[position + 7 : position + 9])
            return (width, height) if width and height else None
        position += 2 + int.from_bytes(data[position + 2 : position + 4])
    return None


def iter_stream_parts(stream: BinaryIO) -> Iterator[bytes]:
    """Separa las partes del multipart usando su Content-Length, como las envia el firmware."""
    length = None
    while True:
        line = stream.readline(_MAX_HEADER_LINE)
        if not line:
            return
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            try:
                length = int(value)
            except ValueError as error:
                raise CaptureError(f"invalid Content-Length: {value!r}") from error
        elif not line.strip() and length is not None:
            data = stream.read(length)
            if len(data) < length:
                raise CaptureError(f"stream ended inside a frame: {len(data)}/{length} bytes")
            yield data
            length = None


def capture_sequence(
    stream: BinaryIO,
    sequence_id: str,
    dataset: Path,
    *,
    frames: int,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    clock: Callable[[], float] = time.monotonic,
) -> list[FrameRecord]:
    """Guarda `frames` cuadros distintos, separados al menos `interval_ms`.

    Una secuencia ya existente no se sobrescribe: el dataset solo crece con secuencias nuevas.
    """
    if not _SEQUENCE_ID.fullmatch(sequence_id):
        raise CaptureError(f"invalid sequence id: {sequence_id!r}")
    if frames < 1 or interval_ms < 0:
        raise CaptureError("frames must be positive and interval_ms not negative")

    directory = dataset / SEQUENCES_DIR / sequence_id
    try:
        directory.mkdir(parents=True)
    except FileExistsError as error:
        raise CaptureError(f"sequence already exists: {directory}") from error

    records: list[FrameRecord] = []
    seen: set[str] = set()
    start = last = None
    with (directory / CAPTURES_FILE).open("w", encoding="utf-8", newline="\n") as captures:
        for data in iter_stream_parts(stream):
            now = clock()
            if last is not None and (now - last) * 1000 < interval_ms:
                continue
            size = jpeg_size(data)
            if size is None:
                logger.warning("skipped_frame sequence=%s reason=invalid_jpeg", sequence_id)
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                logger.warning("skipped_frame sequence=%s reason=duplicate", sequence_id)
                continue

            start = now if start is None else start
            last = now
            seen.add(digest)
            frame_id = f"{sequence_id}-{len(records) + 1:04d}"
            (directory / f"{frame_id}.jpg").write_bytes(data)
            record = FrameRecord(
                sequence_id=sequence_id,
                frame_id=frame_id,
                file=f"{frame_id}.jpg",
                t_capture_ms=round((now - start) * 1000),
                image_width=size[0],
                image_height=size[1],
                sha256=digest,
            )
            records.append(record)
            # Se escribe cuadro a cuadro para conservar lo capturado si se corta el WiFi.
            captures.write(json.dumps(asdict(record), sort_keys=True) + "\n")
            captures.flush()
            print(f"{frame_id}  t={record.t_capture_ms} ms", file=sys.stderr)
            if len(records) == frames:
                return records

    raise CaptureError(f"stream ended after {len(records)}/{frames} frames")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m p5.dataset.captura",
        description="Guarda una secuencia de cuadros del stream del carro. No mueve los motores.",
    )
    parser.add_argument("--url", required=True, help="Ej. http://172.20.10.13:81/stream")
    parser.add_argument("--dataset", required=True, type=Path, help="Carpeta del dataset.")
    parser.add_argument("--sequence", required=True, help="ID nuevo de secuencia. Ej. seq01")
    parser.add_argument("--frames", required=True, type=int, help="Cuadros distintos a guardar.")
    parser.add_argument("--interval-ms", type=int, default=DEFAULT_INTERVAL_MS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    try:
        with urlopen(args.url, timeout=_TIMEOUT_S) as stream:
            records = capture_sequence(
                stream,
                args.sequence,
                args.dataset,
                frames=args.frames,
                interval_ms=args.interval_ms,
            )
    except (CaptureError, OSError) as error:
        print(f"captura fallida: {error}", file=sys.stderr)
        return 1

    print(json.dumps({"sequence_id": args.sequence, "frames": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
