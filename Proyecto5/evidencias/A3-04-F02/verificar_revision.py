"""Registra integridad y recalculo de F02; no decide el criterio visual ni reanota."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from auditar_a3_04 import digest, indexed, inventory, overlap, read_json, read_lines  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Carpeta nueva.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("la salida debe ser nueva")
    dataset = ROOT / "data/p5-eval-v1"
    historical = ROOT / "evidencias/a3-metricas-v1"
    original_audit = ROOT / "evidencias/A3-04"
    inputs = {
        name: inventory(path)
        for name, path in (
            ("dataset", dataset),
            ("metricas_v1", historical),
            ("auditoria_original", original_audit),
        )
    }
    git = ["git", "-c", f"safe.directory={ROOT.parent.as_posix()}"]
    commit = subprocess.run(
        [*git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    immutable = ["data/p5-eval-v1", "evidencias/a3-metricas-v1", "evidencias/A3-04"]
    subprocess.run(
        [*git, "diff", "--exit-code", "HEAD", "--", *immutable],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    manifest = dataset / "manifiesto.jsonl"
    expected = "5dab9ee3f65cad0a1b31695d6d81c7a50c81fe3934f07572e53f64dc7e2ffeeb"
    assert digest(manifest) == expected, "cambio el manifiesto congelado"
    frame_id = "seq06-0028"
    rows = read_lines(manifest)
    row = indexed(rows)[frame_id]
    assert len(rows) == 128
    assert row["annotations"] == [{"class_name": "person", "bbox_xyxy": [44, 0, 111, 144]}]
    assert digest(dataset / row["image"]) == row["sha256"]
    perception = indexed(read_lines(historical / "predicciones.jsonl"))[frame_id]
    prediction = next(d for d in perception["detections"] if d["class_name"] == "person")
    iou = overlap(prediction["bbox_xyxy"], row["annotations"][0]["bbox_xyxy"])
    assert abs(iou - 0.47284356754785883) < 1e-12
    metrics = read_json(historical / "metricas.json")
    assert metrics["iou_umbral"] == metrics["umbral_confianza"] == 0.5
    published = indexed(read_lines(historical / "resultados_por_cuadro.jsonl"))[frame_id]
    assert (published["tp"], published["fp"], published["fn"]) == (0, 1, 1)
    args.output.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/auditar_a3_04.py"),
            "--output",
            str(args.output / "recalculo"),
            "--laminas",
        ],
        cwd=ROOT,
        check=True,
    )
    audit = read_json(args.output / "recalculo/auditoria.json")
    assert audit["numeric_checks_pass"] and not audit["failures"]
    after = {
        name: inventory(path)
        for name, path in (
            ("dataset", dataset),
            ("metricas_v1", historical),
            ("auditoria_original", original_audit),
        )
    }
    assert inputs == after, "cambiaron las entradas durante la verificacion"
    subprocess.run(
        [*git, "diff", "--exit-code", "HEAD", "--", *immutable],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    report = {
        "seguimiento": "https://github.com/White-eclipse1/Equipo03-Proyecto05/issues/41",
        "commit_base": commit,
        "runtime": f"Python {platform.python_version()}",
        "frame_id": frame_id,
        "imagen_sha256": row["sha256"],
        "manifiesto_sha256": digest(manifest),
        "gt": row["annotations"],
        "prediccion_publicada": prediction,
        "iou_recalculado": iou,
        "umbral_iou": metrics["iou_umbral"],
        "umbral_confianza": metrics["umbral_confianza"],
        "conteo_frame": {key: published[key] for key in ("tp", "fp", "fn")},
        "inventario_entradas_sha256": inputs,
        "inventario_antes_despues_identico": inputs == after,
        "entradas_sin_diferencias_con_commit_base": True,
        "revision_y_criterio_sha256": {
            name: digest(ROOT / name)
            for name in (
                "docs/CRITERIO_ANOTACION.md",
                "docs/A2_DATASET.md",
                "evidencias/A3-04-F02/REVISION.md",
            )
        },
        "verificador_sha256": digest(Path(__file__)),
        "inventario_sha256": hashlib.sha256(
            json.dumps(inputs, sort_keys=True).encode()
        ).hexdigest(),
        "auditoria_numerica_correcta": True,
        "alcance": "Integridad y aritmetica; la inspeccion visual se documenta en REVISION.md",
    }
    (args.output / "verificacion.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("F02: entradas intactas; IoU y FP+FN publicados confirmados")


if __name__ == "__main__":
    main()
