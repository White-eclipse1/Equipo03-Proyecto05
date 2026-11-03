import hashlib
import json
from pathlib import Path

WIDTH, HEIGHT = 400, 296
BOUNDARY = b"\r\n--123456789000000000000987654321\r\n"
CENTER_BOX = [160.0, 100.0, 240.0, 280.0]
LEFT_BOX = [10.0, 100.0, 90.0, 280.0]
RIGHT_BOX = [310.0, 100.0, 390.0, 280.0]


def make_jpeg(seed: int, width: int = WIDTH, height: int = HEIGHT) -> bytes:
    """Un JPEG minimo para el parser: SOI, SOF0 con dimensiones, datos y EOI."""
    sof = (
        b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2)
        + width.to_bytes(2)
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + sof + b"\xff\xda" + seed.to_bytes(4) + b"\r\n\r\n" + b"\xff\xd9"


def stream_bytes(parts: list[bytes]) -> bytes:
    """Mismo orden que `app_httpd.cpp`: cabecera de la parte, JPEG y luego la frontera."""
    out = b""
    for part in parts:
        header = f"Content-Type: image/jpeg\r\nContent-Length: {len(part)}\r\n\r\n".encode()
        out += header + part + BOUNDARY
    return out


def add_sequence(
    dataset: Path,
    sequence_id: str,
    states: list[str],
    *,
    first_seed: int,
    split: str = "evaluacion",
    scenario: str = "C1",
) -> None:
    directory = dataset / "secuencias" / sequence_id
    directory.mkdir(parents=True)

    boxes = {
        "libre": [],
        "centro": [CENTER_BOX],
        "lateral_izquierda": [LEFT_BOX],
        "lateral_derecha": [RIGHT_BOX],
        "varios": [LEFT_BOX, CENTER_BOX],
    }
    with (
        (directory / "capturas.jsonl").open("w", encoding="utf-8") as captures,
        (dataset / "anotaciones.jsonl").open("a", encoding="utf-8") as annotations,
    ):
        for index, state in enumerate(states):
            data = make_jpeg(first_seed + index)
            frame_id = f"{sequence_id}-{index + 1:04d}"
            (directory / f"{frame_id}.jpg").write_bytes(data)
            record = {
                "sequence_id": sequence_id,
                "frame_id": frame_id,
                "file": f"{frame_id}.jpg",
                "t_capture_ms": index * 500,
                "image_width": WIDTH,
                "image_height": HEIGHT,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            captures.write(json.dumps(record) + "\n")
            objects = [{"class_name": "person", "bbox_xyxy": box} for box in boxes[state]]
            row = {"frame_id": frame_id, "road_state": state, "objects": objects}
            annotations.write(json.dumps(row) + "\n")

    path = dataset / "secuencias.json"
    declared = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"sequences": {}}
    declared["sequences"][sequence_id] = {"split": split, "scenario": scenario}
    path.write_text(json.dumps(declared), encoding="utf-8")


def make_valid_dataset(dataset: Path) -> None:
    """Seis secuencias de evaluacion, con 60 cuadros, que cumplen todos los minimos."""
    add_sequence(dataset, "seq01", ["libre"] * 15, first_seed=100, scenario="C1")
    add_sequence(dataset, "seq02", ["libre"] * 3 + ["centro"] * 7, first_seed=200, scenario="C2")
    add_sequence(dataset, "seq03", ["lateral_izquierda"] * 8, first_seed=300, scenario="C3")
    add_sequence(dataset, "seq04", ["lateral_derecha"] * 8, first_seed=400, scenario="C4")
    add_sequence(dataset, "seq05", ["varios"] * 7, first_seed=500, scenario="C5")
    add_sequence(
        dataset,
        "seq06",
        ["libre"] * 4 + ["centro"] * 4 + ["libre"] * 4,
        first_seed=600,
        scenario="C7",
    )
