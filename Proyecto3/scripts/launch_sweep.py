"""Encola el barrido de F5 (T13) en el worker a traves de la API del portal.

Valida las 12 corridas de `config/sweep.yaml` antes de encolar la primera y
guarda `reports/sweep/launched.json` con el `job_id` de cada una. El
entrenamiento corre en el worker, fuera del request, una corrida tras otra.

    python scripts/launch_sweep.py [--api http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROYECTO3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROYECTO3 / "src"))

from p3.train.sweep import job_bodies  # noqa: E402


def post(api: str, body: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        f"{api}/api/p3/training/jobs",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--sweep", type=Path, default=PROYECTO3 / "config" / "sweep.yaml")
    parser.add_argument(
        "--out", type=Path, default=PROYECTO3 / "reports" / "sweep" / "launched.json"
    )
    args = parser.parse_args()

    bodies = job_bodies(args.sweep)
    launched = []
    for name, body in bodies:
        job = post(args.api, body)
        launched.append({"name": name, "job_id": job["job_id"], "config": body["config"]})
        print(f"{name}: {job['job_id']}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "launched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest_id": bodies[0][1]["manifest_id"],
        "experiment": bodies[0][1]["experiment"],
        "runs": launched,
    }
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(launched)} corridas encoladas; registro en {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
