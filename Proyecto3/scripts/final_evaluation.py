"""Evaluacion final en test del candidato de `docs/selection.json` (F6 T15-T16).

Se corre UNA vez (la custodia del test es de Diego). Antes de tocar el test exige:

1. arbol de Git limpio: el `code_commit` de `metrics.json` es exacto;
2. `docs/selection.json` versionado y sin cambios: la seleccion quedo en un commit
   ANTERIOR a esta evaluacion (reglas 8 de AGENTS.md; criterios 3.3 y 4.1);
3. el manifiesto congelado (`p3.data.frozen.verify_frozen`);
4. los recortes con el `crops_jsonl_sha256` que registro la seleccion;
5. el checkpoint del snapshot de MLflow (`dvc pull mlflow_snapshot.dvc`) con el
   SHA-256 seleccionado (lo revisa `run_evaluation`).

Salida versionada en `reports/evaluation/<run_id>/`: `predictions_test.csv`,
`metrics.json` y `errors.json`. Con `--audit` recalcula y compara, sin escribir.

    cd Proyecto3
    .venv/Scripts/python scripts/final_evaluation.py [--audit]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROYECTO3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROYECTO3 / "src"))

from p3.data.frozen import verify_frozen  # noqa: E402
from p3.eval.evaluate import run_evaluation  # noqa: E402

SELECTION = Path("docs/selection.json")
CHECKPOINT_PREFIX = "mlflow-artifacts:/"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=PROYECTO3
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audit", action="store_true", help="recalcular y comparar, sin escribir")
    args = parser.parse_args()

    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Hay cambios sin commit: el code_commit no seria exacto.")
    if not git("ls-files", str(SELECTION)):
        raise SystemExit(f"{SELECTION} no esta versionado: la seleccion no quedo en un commit.")
    selection_commit = git("log", "-1", "--format=%H %cI", "--", str(SELECTION))
    selection = json.loads((PROYECTO3 / SELECTION).read_text(encoding="utf-8"))

    manifest_dir = PROYECTO3 / "data" / "manifests" / selection["manifest_id"]
    verify_frozen(manifest_dir)
    release_id = selection["manifest_id"].split("-")[1]
    crops_dir = PROYECTO3 / "data" / "crops" / release_id
    crops_sha = hashlib.sha256((crops_dir / "crops.jsonl").read_bytes()).hexdigest()
    if crops_sha != selection["crops_jsonl_sha256"]:
        raise SystemExit(
            f"crops.jsonl tiene hash {crops_sha}; la seleccion se entreno con "
            f"{selection['crops_jsonl_sha256']}. Regenera los recortes."
        )
    uri = selection["checkpoint_uri"]
    if not uri.startswith(CHECKPOINT_PREFIX):
        raise SystemExit(f"checkpoint_uri inesperado: {uri}")
    checkpoint = PROYECTO3 / "mlflow_snapshot" / "artifacts" / uri.removeprefix(CHECKPOINT_PREFIX)
    if not checkpoint.is_file():
        raise SystemExit(f"No esta {checkpoint}: corre `dvc pull mlflow_snapshot.dvc`.")

    result = run_evaluation(
        selection_path=PROYECTO3 / SELECTION,
        checkpoint_path=checkpoint,
        manifest_dir=manifest_dir,
        crops_dir=crops_dir,
        out_dir=PROYECTO3 / "reports" / "evaluation" / selection["run_id"],
        audit=args.audit,
        provenance={
            "code_commit": git("rev-parse", "HEAD"),
            "selection_commit": selection_commit,
            "crops_jsonl_sha256": crops_sha,
        },
    )
    shown = {k: result[k] for k in result if k not in ("per_class",)}
    print(json.dumps(shown, indent=2, ensure_ascii=False))
    for row in result["per_class"]:
        print(
            f"  {row['class']:>7}: precision {row['precision']:.4f}  recall {row['recall']:.4f}"
            f"  f1 {row['f1']:.4f}  support {row['support']}"
        )


if __name__ == "__main__":
    main()
