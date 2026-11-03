"""Verificacion de recortes contra el COCO original (F2 T07, criterio 1.2).

La version anterior comparaba cada PNG contra `original.crop(...)` hecho con el
MISMO metodo que lo genero: era circular y no detecto los recortes rotados por
EXIF ni los de imagenes con tamano distinto al del COCO (revision de Edith en el
PR #3). Ahora hay tres comprobaciones independientes del generador:

1. Metadatos, sobre TODOS los recortes: la anotacion existe en el COCO con la
   misma imagen, categoria, nombre y bbox.
2. Geometria por otro camino, sobre TODOS: se toma la foto como la muestra un
   navegador (rotacion EXIF aplicada), se REDIMENSIONA COMPLETA al tamano del
   COCO (estirandola si gira, como hizo P1) y se corta la bbox tal cual;
   ese resultado se compara con el recorte (llevado al mismo tamano). Si el
   generador ignorara la rotacion o el escalado, la diferencia seria grande.
3. Revision visual: TODAS las imagenes con rotacion EXIF o con tamano distinto
   al del COCO (los casos de riesgo), mas una muestra aleatoria con semilla
   fija. Cada miniatura muestra el original con la caja del COCO dibujada
   (escalada a la foto mostrada) y el recorte al lado.

    python scripts/verificar_recortes.py --release 0.1.3 [--n 10 --seed 7]

Lee `Proyecto2/data/raw` (misma huella que el release, la verifica
`generate_crops.py`) y no necesita credenciales.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat

ROOT = Path(__file__).resolve().parents[2]
P3 = ROOT / "Proyecto3"
THUMB_HEIGHT = 240
MAX_MEAN_DIFF = 12.0  # 0-255 por canal; un recorte de la zona equivocada da decenas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release", required=True)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "Proyecto2" / "data" / "raw")
    parser.add_argument("--crops-dir", type=Path, default=P3 / "data" / "crops")
    parser.add_argument("--out-dir", type=Path, default=P3 / "docs" / "verificacion_recortes")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    crops_dir = args.crops_dir / args.release
    records = [
        json.loads(line)
        for line in (crops_dir / "crops.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    coco = json.loads((args.raw_dir / "annotations.coco.json").read_text(encoding="utf-8"))
    annotations = {a["id"]: a for a in coco["annotations"]}
    images = {i["id"]: i for i in coco["images"]}
    names = {c["id"]: c["name"] for c in coco["categories"]}

    by_image: dict[int, list[dict]] = {}
    for record in records:
        ann = annotations[record["annotation_id"]]
        image = images[ann["image_id"]]
        assert ann["image_id"] == record["source_image_id"], record["crop_id"]
        assert ann["category_id"] == record["category_id"], record["crop_id"]
        assert names[ann["category_id"]] == record["category_name"], record["crop_id"]
        assert list(ann["bbox"]) == list(record["bbox_xywh"]), record["crop_id"]
        assert image["file_name"] == record["source_file_name"], record["crop_id"]
        by_image.setdefault(ann["image_id"], []).append(record)

    risky: dict[int, str] = {}
    diffs: list[tuple[float, str]] = []
    for image_id, image_records in by_image.items():
        image = images[image_id]
        shown, reason = _as_browser_shows(args.raw_dir / "images" / image["file_name"], image)
        resized = shown.resize(_coco_space(shown, image), Image.Resampling.BILINEAR)
        for record in image_records:
            if reason:
                risky[record["annotation_id"]] = reason
            with Image.open(crops_dir / record["crop_path"]) as crop:
                diff = _mean_diff(resized, record["bbox_xywh"], crop.convert("RGB"))
            diffs.append((diff, record["crop_id"]))

    worst = sorted(diffs, reverse=True)[:5]
    print(f"{len(records)} recortes: metadatos iguales al COCO")
    print(
        f"geometria por redimension completa: diferencia media maxima {worst[0][0]:.2f} "
        f"(umbral {MAX_MEAN_DIFF}); peores: "
        + ", ".join(f"{crop_id} {d:.2f}" for d, crop_id in worst)
    )
    malos = [crop_id for d, crop_id in diffs if d > MAX_MEAN_DIFF]
    assert not malos, f"recortes que no coinciden con su caja: {malos}"

    by_id = {r["annotation_id"]: r for r in records}
    rng = random.Random(args.seed)
    others = sorted(set(by_id) - set(risky))
    sample = sorted(risky) + rng.sample(others, args.n)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for old in args.out_dir.glob("*.jpg"):
        old.unlink()
    print("crop_id | imagen | clase | motivo de revision | miniatura")
    for annotation_id in sample:
        record = by_id[annotation_id]
        image = images[record["source_image_id"]]
        shown, _ = _as_browser_shows(args.raw_dir / "images" / image["file_name"], image)
        name = f"{args.release}_a{annotation_id}.jpg"
        _thumbnail(shown, image, record, crops_dir).save(args.out_dir / name, quality=80)
        print(
            f"{record['crop_id']} | {record['source_image_id']} | {record['category_name']} | "
            f"{risky.get(annotation_id, 'muestra aleatoria')} | {name}"
        )


def _as_browser_shows(path: Path, image: dict) -> tuple[Image.Image, str | None]:
    """La foto como la muestra un navegador, y por que es un caso de riesgo (o None)."""
    with Image.open(path) as handle:
        raw_size = handle.size
        orientation = handle.getexif().get(0x0112, 1)
        shown = ImageOps.exif_transpose(handle).convert("RGB")
    reasons = []
    if orientation not in (0, 1):
        reasons.append(f"EXIF orientacion {orientation}")
    if shown.size != (image["width"], image["height"]) and raw_size != (
        image["width"],
        image["height"],
    ):
        reasons.append(
            f"archivo {shown.size[0]}x{shown.size[1]} vs COCO {image['width']}x{image['height']}"
        )
    return shown, "; ".join(reasons) or None


def _coco_space(shown: Image.Image, image: dict) -> tuple[int, int]:
    """Tamano del COCO, el espacio de las cajas. P1 lo tomo de la cabecera sin girar y
    llevo cada caja ahi eje por eje, asi que se usa tal cual aunque la foto gire."""
    return (image["width"], image["height"])


def _mean_diff(resized: Image.Image, bbox: list[float], crop: Image.Image) -> float:
    """Diferencia media entre la caja cortada de la foto ya llevada al tamano del COCO
    y el recorte generado (reescalado a ese mismo tamano)."""
    x, y, w, h = bbox
    expected = resized.crop((round(x), round(y), round(x + w), round(y + h)))
    got = crop.resize(expected.size, Image.Resampling.BILINEAR)
    return sum(ImageStat.Stat(ImageChops.difference(expected, got)).mean) / 3


def _thumbnail(shown: Image.Image, image: dict, record: dict, crops_dir: Path) -> Image.Image:
    space_w, space_h = _coco_space(shown, image)
    sx, sy = shown.width / space_w, shown.height / space_h
    x, y, w, h = record["bbox_xywh"]
    left = shown.copy()
    draw = ImageDraw.Draw(left)
    draw.rectangle(
        (x * sx, y * sy, (x + w) * sx, (y + h) * sy),
        outline=(255, 0, 0),
        width=max(3, left.width // 120),
    )
    with Image.open(crops_dir / record["crop_path"]) as crop:
        right = crop.convert("RGB")
    left, right = _to_height(left, THUMB_HEIGHT), _to_height(right, THUMB_HEIGHT)
    canvas = Image.new("RGB", (left.width + 8 + right.width, THUMB_HEIGHT), (255, 255, 255))
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width + 8, 0))
    return canvas


def _to_height(image: Image.Image, height: int) -> Image.Image:
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    main()
