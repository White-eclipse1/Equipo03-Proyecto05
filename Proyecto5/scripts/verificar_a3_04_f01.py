"""Verifica y compara la nueva inferencia 3.12 sin ejecutar ni calibrar el detector."""

import argparse
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path

from auditar_a3_04 import ROOT, audit_dataset, audit_metrics, digest, read_json

FILES = ("metricas.json", "metricas.csv", "predicciones.jsonl", "resultados_por_cuadro.jsonl")
MANIFEST = "5dab9ee3f65cad0a1b31695d6d81c7a50c81fe3934f07572e53f64dc7e2ffeeb"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("usa un archivo nuevo; no se sobrescribe evidencia")
    failures = []
    historical = ROOT / "evidencias/a3-metricas-v1"
    old = read_json(historical / "metricas.json")
    new = read_json(args.evidence / "metricas.json")
    rows, package = audit_dataset(ROOT / "data/p5-eval-v1", failures)
    independent = audit_metrics(args.evidence, rows, [row["frame_id"] for row in rows], failures)
    execution = new["ejecucion"]
    checks = {
        "python_soportado": platform.python_version_tuple()[:2] == ("3", "12"),
        "inferencia_real_312": execution["origen"] == "detector"
        and execution["runtime"] == f"Python {platform.python_version()}",
        "manifiesto_conservado": execution["manifiesto_sha256"]
        == package["manifest_sha256"]
        == MANIFEST,
        "modelo_conservado": execution["modelo_sha256"]
        == old["ejecucion"]["modelo_sha256"]
        == digest(ROOT / "models/yolox_tiny.onnx"),
        "umbrales_conservados": all(
            new[key] == old[key] == 0.5 for key in ("iou_umbral", "umbral_confianza")
        )
        and execution["umbral_detector"] == old["ejecucion"]["umbral_detector"] == 0.1
        and execution["nms_detector"] == old["ejecucion"]["nms_detector"] == 0.45,
        "sin_errores_inferencia": not new["cuadros_con_error"],
    }
    versions = {}
    for line in (ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        requirement = line.split(";", 1)[0].strip()
        if not requirement or requirement.startswith("#"):
            continue
        name, expected = requirement.split("==")
        installed = importlib.metadata.version(name)
        versions[name] = {"fijada": expected, "instalada": installed}
        checks[f"version:{name}"] = installed == expected
    git = ["git", "-c", f"safe.directory={ROOT.parent.as_posix()}"]
    historic_hashes = {}
    for name in FILES:
        path = historical / name
        original = subprocess.run(
            [*git, "show", f"HEAD:Proyecto5/evidencias/a3-metricas-v1/{name}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        checks[f"historico_intacto:{name}"] = original == path.read_bytes()
        historic_hashes[name] = digest(path)
    source_paths = [
        "src/p5/metrics",
        "src/p5/detector",
        "src/p5/dataset",
        "pyproject.toml",
        "requirements.lock.txt",
        "data/p5-eval-v1",
    ]
    changes = subprocess.run(
        [*git, "diff", execution["commit"], "--", *source_paths],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    checks["fuente_y_dataset_sin_cambios_desde_commit"] = not changes
    same_metrics = {k: v for k, v in old.items() if k != "ejecucion"} == {
        k: v for k, v in new.items() if k != "ejecucion"
    }
    report = {
        "seguimiento": "https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/40",
        "auditoria": "https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/29",
        "ejecucion_historica": old["ejecucion"],
        "ejecucion_nueva": execution,
        "comprobaciones": checks,
        "dependencias": versions,
        "historico_sha256": historic_hashes,
        "nueva_evidencia_sha256": {name: digest(args.evidence / name) for name in FILES},
        "fuentes_sha256": {
            p.relative_to(ROOT).as_posix(): digest(p)
            for folder in ("metrics", "detector", "dataset")
            for p in sorted((ROOT / "src/p5" / folder).glob("*.py"))
        },
        "entorno_sha256": {
            name: digest(ROOT / name) for name in ("pyproject.toml", "requirements.lock.txt")
        },
        "verificador_sha256": digest(Path(__file__)),
        "metricas_identicas_sin_metadatos": same_metrics,
        "archivos_identicos": {
            name: digest(historical / name) == digest(args.evidence / name) for name in FILES
        },
        "auditoria_independiente_128_cuadros": independent,
        "fallos_auditoria": failures,
        "correcto": all(checks.values()) and not failures,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"correcto={report['correcto']}; metricas_identicas={same_metrics}")
    return 0 if report["correcto"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
