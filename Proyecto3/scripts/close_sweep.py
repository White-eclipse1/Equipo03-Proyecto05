"""Cierra el barrido de F5: `docs/corridas.md` (T13) y, con `--select`, `docs/selection.json` (T14).

1. Lee de la API de MLflow todas las corridas del experimento `p3-clasificador`.
2. Con `--tag-crops`, agrega a las corridas que no lo tienen el tag
   `crops_jsonl_sha256` con el SHA-256 del `crops.jsonl` en disco, SOLO si ese
   archivo no cambio desde antes de la primera corrida (fecha de modificacion) y
   coincide con `reports/crops/<release>/summary.json`. Marca el origen del tag.
3. Comprueba 3.1: >=10 corridas FINISHED sobre el manifiesto congelado, con
   resultados distintos y los 7 parametros con >=2 valores. Escribe `docs/corridas.md`.
4. Con `--select`, llama a `POST /api/p3/selection` del portal (la regla vive en
   `p3.train.selection`) y escribe `docs/selection.json`.

No consulta ni calcula nada del test.

    python scripts/close_sweep.py --tag-crops
    python scripts/close_sweep.py --select
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROYECTO3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROYECTO3 / "src"))

from p3.data.frozen import FROZEN_MANIFESTS  # noqa: E402
from p3.train.selection import EXPERIMENT, MIN_RUNS, MlflowRest, valid_runs  # noqa: E402

PARAMETROS = (
    "optimizer",
    "batch_size",
    "max_epochs",
    "learning_rate",
    "image_size",
    "hidden_layers",
    "dropout",
)
MANIFEST_ID = "m-0.1.3-s42-1"


def tag_crops(mlflow: MlflowRest, runs, release_id: str) -> None:
    crops = PROYECTO3 / "data" / "crops" / release_id / "crops.jsonl"
    digest = hashlib.sha256(crops.read_bytes()).hexdigest()
    summary = json.loads(
        (PROYECTO3 / "reports" / "crops" / release_id / "summary.json").read_text()
    )
    if digest != summary["crops_jsonl_sha256"]:
        sys.exit(f"{crops} ({digest}) no coincide con summary.json: no se etiqueta nada.")
    modified_ms = int(crops.stat().st_mtime * 1000)
    first_start = min(r.start_time for r in runs if r.start_time is not None)
    if modified_ms >= first_start:
        sys.exit(
            "crops.jsonl cambio despues de la primera corrida: no se puede afirmar cual se uso."
        )
    origin = (
        "agregado despues de la corrida; crops.jsonl sin cambios desde "
        f"{datetime.fromtimestamp(modified_ms / 1000, UTC):%Y-%m-%dT%H:%M:%SZ}, antes de la "
        "primera corrida del barrido, y igual a reports/crops/0.1.3/summary.json"
    )
    for run in runs:
        if "crops_jsonl_sha256" not in run.tags:
            mlflow.set_tag(run.run_id, "crops_jsonl_sha256", digest)
            mlflow.set_tag(run.run_id, "crops_jsonl_sha256_origen", origin)
            print(f"tag de recortes agregado a {run.run_id}")


def write_corridas(runs, launched: dict) -> list:
    manifest_hash = FROZEN_MANIFESTS[MANIFEST_ID]
    valid = sorted(valid_runs(runs, manifest_hash=manifest_hash), key=lambda r: r.end_time or 0)
    names = {r["job_id"]: r["name"] for r in launched["runs"]}
    failed = [r for r in runs if r.status != "FINISHED"]

    problems = []
    if len(valid) < MIN_RUNS:
        problems.append(f"solo {len(valid)} corridas validas (se exigen {MIN_RUNS})")
    for param in PARAMETROS:
        if len({r.params.get(param) for r in valid}) < 2:
            problems.append(f"{param} no varia")
    if len({(r.best_val_accuracy, r.best_val_loss) for r in valid}) < len(valid):
        problems.append("hay corridas con resultados identicos")
    if {r.manifest_hash for r in valid} != {manifest_hash}:
        problems.append("manifiestos distintos")

    lines = [
        "# Corridas del barrido — F5 T13",
        "",
        f"Experimento `{EXPERIMENT}` en MLflow, manifiesto congelado `{MANIFEST_ID}` "
        f"(`{manifest_hash[:12]}…`), clases `cat`, `dog`, `person`. Configuraciones de "
        "[`config/sweep.yaml`](../config/sweep.yaml), lanzadas por el worker con "
        "`scripts/launch_sweep.py`. Generado por `scripts/close_sweep.py` desde la API de "
        f"MLflow el {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. **Ninguna métrica de test.**",
        "",
        f"## Corridas válidas ({len(valid)} FINISHED)",
        "",
        "| Corrida | run_id | optimizer | batch | max_epochs | lr | image | hidden | dropout "
        "| mejor época | parada | best val_acc | best val_loss |",
        "|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for r in valid:
        p = r.params
        lines.append(
            f"| {names.get(r.tags.get('job_id'), '?')} | `{r.run_id}` | {p['optimizer']} | "
            f"{p['batch_size']} | {p['max_epochs']} | {p['learning_rate']} | {p['image_size']} | "
            f"`{p['hidden_layers']}` | {p['dropout']} | {r.best_epoch} | {r.stopped_epoch} | "
            f"{r.best_val_accuracy:.4f} | {r.best_val_loss:.4f} |"
        )
    lines += [
        "",
        "Valores por parámetro: "
        + "; ".join(f"`{p}` {sorted({r.params[p] for r in valid})}" for p in PARAMETROS),
        "",
        f"## Corridas no válidas ({len(failed)})",
        "",
    ]
    lines += [
        f"- `{r.run_id}` ({names.get(r.tags.get('job_id'), '?')}): {r.status} — "
        f"{r.tags.get('nota', 'sin nota')}"
        for r in failed
    ] or ["- Ninguna."]
    lines += [
        "",
        "## Comprobación 3.1",
        "",
        "- "
        + (
            "OK: "
            + ", ".join(
                [
                    f">= {MIN_RUNS} corridas FINISHED",
                    "los 7 parámetros con >= 2 valores",
                    "resultados distintos",
                    "mismo manifiesto",
                ]
            )
            if not problems
            else "FALLA: " + "; ".join(problems)
        ),
        "",
    ]
    out = PROYECTO3 / "docs" / "corridas.md"
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(
        f"{out}: {len(valid)} validas, {len(failed)} no validas; problemas: {problems or 'ninguno'}"
    )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mlflow", default="http://localhost:5000")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--tag-crops", action="store_true")
    parser.add_argument("--select", action="store_true")
    args = parser.parse_args()

    mlflow = MlflowRest(args.mlflow)
    launched = json.loads((PROYECTO3 / "reports" / "sweep" / "launched.json").read_text())
    runs = mlflow.search_runs(EXPERIMENT)
    if any(r.status == "RUNNING" for r in runs):
        sys.exit("Todavia hay corridas en curso: espera a que termine el barrido.")
    if args.tag_crops:
        tag_crops(mlflow, runs, "0.1.3")
        runs = mlflow.search_runs(EXPERIMENT)
    problems = write_corridas(runs, launched)
    if args.select:
        if problems:
            sys.exit("No se selecciona: el barrido no cumple 3.1.")
        request = urllib.request.Request(
            f"{args.api}/api/p3/selection",
            data=json.dumps({"manifest_id": MANIFEST_ID}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            record = json.loads(response.read())
        out = PROYECTO3 / "docs" / "selection.json"
        out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Seleccionado {record['run_id']} (val_acc {record['val_accuracy']:.4f}); {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
