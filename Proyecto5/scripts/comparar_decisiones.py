"""Compara dos corridas de C1-C10 cuadro por cuadro. Ver `docs/B1-03_DETECTOR.md`.

Un caso puede decir PASA con un STOP de mas, asi que los tramos libres se revisan aqui.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT_MANIFEST = Path("data/p5-eval-v1/manifiesto.jsonl")
EVALUATED_CASES = ("C1", "C2", "C3", "C4", "C5", "C7")
MIN_CONFIDENCE = 0.30
# (titulo, caso, primer cuadro, ultimo cuadro)
SECTIONS = (
    ("C1, seq01", "C1", 1, 15),
    ("C5, seq05", "C5", 1, 15),
    ("seq06 libre, 1-26", "C7", 1, 26),
    ("seq06 bloqueo, 30-44", "C7", 30, 44),
    ("seq06 libre, 49-50", "C7", 49, 50),
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def number(frame_id: str) -> int:
    return int(frame_id.rsplit("-", 1)[1])


def seen(row: dict) -> list[str]:
    return [
        f"{item['class_name']}:{item['confidence']:.2f}:{item.get('nivel')}"
        for item in row.get("detecciones", [])
        if item["confidence"] >= MIN_CONFIDENCE
    ]


def compare(new_rows: list[dict], old_rows: list[dict], manifest: list[dict]) -> dict:
    old = {(row["caso"], row["frame_id"]): row for row in old_rows}
    if set(old) != {(row["caso"], row["frame_id"]) for row in new_rows}:
        raise ValueError("las corridas no tienen los mismos casos y cuadros")
    allowed = {row["frame_id"]: row["allowed_actions"] for row in manifest}

    changes = []
    forbidden = {"con": [], "sin": []}
    for row in new_rows:
        key = (row["caso"], row["frame_id"])
        before = old[key]
        if (row["accion"], row["reason_code"]) != (before["accion"], before["reason_code"]):
            changes.append(
                {
                    "caso": row["caso"],
                    "frame_id": row["frame_id"],
                    "antes": f"{before['accion']}/{before['reason_code']}",
                    "ahora": f"{row['accion']}/{row['reason_code']}",
                    "detecciones_antes": seen(before),
                    "detecciones_ahora": seen(row),
                }
            )
        if row["caso"] in EVALUATED_CASES:
            for name, item in (("con", row), ("sin", before)):
                if item["accion"] not in allowed[row["frame_id"]]:
                    forbidden[name].append(f"{row['frame_id']}:{item['accion']}")

    sections = {}
    for title, case, first, last in SECTIONS:
        selected = [
            row
            for row in new_rows
            if row["caso"] == case and first <= number(row["frame_id"]) <= last
        ]
        sections[title] = {
            "cuadros": len(selected),
            "con_filtro": dict(sorted(Counter(row["accion"] for row in selected).items())),
            "sin_filtro": dict(
                sorted(Counter(old[(case, row["frame_id"])]["accion"] for row in selected).items())
            ),
        }
    return {"tramos": sections, "no_permitidas": forbidden, "cambios": changes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--con", type=Path, required=True, help="decisiones.jsonl con filtro.")
    parser.add_argument("--sin", type=Path, required=True, help="decisiones.jsonl sin filtro.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    result = compare(read_jsonl(args.con), read_jsonl(args.sin), read_jsonl(args.manifest))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
