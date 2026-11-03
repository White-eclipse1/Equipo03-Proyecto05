"""Frente 5 — splits estratificados: semilla, tolerancia y cero fuga.

Las tres propiedades de la tarjeta, en el orden en que importan: primero que
un grupo de casi-duplicados nunca se separe (es lo que distingue este frente
de un `train_test_split` generico), despues reproducibilidad, y por ultimo
que la estratificacion quede dentro de tolerancia.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from dataset_quality.analyzers.duplicates import duplicate_groups
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import (
    ClassImbalanceCheck,
    DegenerateBoxesCheck,
    DuplicatesCheck,
    MinImagesPerClassCheck,
    QualityConfig,
    SmallObjectsCheck,
    SpatialBiasCheck,
    SplitsConfig,
)
from dataset_quality.models.splits import SplitAssignment, SplitRatios, SplitsManifest
from dataset_quality.tiers import splits as splits_module
from dataset_quality.tiers.splits import Unit, assign, build_units, deviation, stratum_labels

RATIOS = SplitRatios(train=0.7, val=0.15, test=0.15)


def coco(
    images: list[tuple[int, str, int, int]],
    boxes: list[tuple[int, int, int, float, float, float, float]],
    categories: list[tuple[int, str]],
) -> CocoDataset:
    """Construye un COCO valido desde tuplas. Mismo helper que `test_analyzers.py`."""
    return CocoDataset.model_validate(
        {
            "images": [{"id": i, "file_name": n, "width": w, "height": h} for i, n, w, h in images],
            "annotations": [
                {
                    "id": bid,
                    "image_id": img,
                    "category_id": cat,
                    "bbox": [x, y, w, h],
                    "area": w * h,
                    "iscrowd": 0,
                }
                for bid, img, cat, x, y, w, h in boxes
            ],
            "categories": [{"id": i, "name": n} for i, n in categories],
        }
    )


def draw(path, seed: int, size: tuple[int, int] = (256, 192)) -> None:
    """Imagen con estructura reconocible para el pHash. Mismo helper que `test_analyzers.py`."""
    canvas = Image.new("RGB", size, (240, 240, 245))
    painter = ImageDraw.Draw(canvas)
    for index in range(7):
        offset = (index * 31 + seed * 47) % (size[0] - 60)
        painter.rectangle(
            [offset, 15 + index * 22, offset + 52, 58 + index * 22],
            fill=(30 + index * 28, (90 + seed * 40) % 256, 210 - index * 24),
        )
    canvas.save(path, "JPEG", quality=93)


def config(**overrides: object) -> SplitsConfig:
    base = {"ratios": RATIOS, "seed": 42}
    base.update(overrides)
    return SplitsConfig(**base)


def quality_config(**splits_overrides: object) -> QualityConfig:
    return QualityConfig(
        min_images_per_class=MinImagesPerClassCheck(min_images=1, min_classes=1),
        small_objects=SmallObjectsCheck(area_ratio_threshold=0.01, max_ratio=0.5),
        class_imbalance=ClassImbalanceCheck(max_ratio_max_min=1000.0),
        duplicates=DuplicatesCheck(phash_hamming_distance=5, max_ratio=1.0),
        degenerate_boxes=DegenerateBoxesCheck(max_ratio=0.0),
        spatial_bias=SpatialBiasCheck(grid_size=4, max_cell_share=1.0),
        splits=config(**splits_overrides),
    )


def dataset_con_clases(por_clase: dict[str, int]) -> CocoDataset:
    """`n` imagenes por clase, sin solapar entre clases, ids consecutivos."""
    images = []
    boxes = []
    categories = [(index + 1, name) for index, name in enumerate(por_clase)]
    image_id = 1
    box_id = 1
    for category_id, name in categories:
        for _ in range(por_clase[name]):
            images.append((image_id, f"img{image_id}.jpg", 100, 100))
            boxes.append((box_id, image_id, category_id, 0, 0, 10, 10))
            image_id += 1
            box_id += 1
    return coco(images, boxes, categories)


# --------------------------------------------------------------------------
# Cero fuga de near-duplicates
# --------------------------------------------------------------------------
def test_grupo_de_duplicados_byte_a_byte_va_entero_a_un_split(tmp_path: Path) -> None:
    draw(tmp_path / "a.jpg", seed=1)
    (tmp_path / "b.jpg").write_bytes((tmp_path / "a.jpg").read_bytes())
    (tmp_path / "c.jpg").write_bytes((tmp_path / "a.jpg").read_bytes())
    draw(tmp_path / "d.jpg", seed=99)

    dataset = coco(
        images=[
            (1, "a.jpg", 256, 192),
            (2, "b.jpg", 256, 192),
            (3, "c.jpg", 256, 192),
            (4, "d.jpg", 256, 192),
        ],
        boxes=[(1, 1, 1, 0, 0, 10, 10), (2, 4, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )

    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)
    split_by_image = {a.image_id: a.split for a in manifest.assignments}

    assert split_by_image[1] == split_by_image[2] == split_by_image[3]


def test_transitividad_a_c_no_cercanos_entre_si_pero_unidos_por_b() -> None:
    """A~B y B~C (pero A y C no cumplen el umbral entre si): los tres juntos."""
    hashes = {1: 0b0000_0000, 2: 0b0000_0111, 3: 0b0000_1110}
    # hamming(1,2)=3, hamming(2,3)=2, hamming(1,3)=4 (por encima de un umbral de 3)
    groups = duplicate_groups(hashes, max_distance=3)
    assert groups == [{1, 2, 3}]


def test_sin_agrupar_duplicados_cada_imagen_es_su_propia_unidad(tmp_path: Path) -> None:
    draw(tmp_path / "a.jpg", seed=1)
    (tmp_path / "b.jpg").write_bytes((tmp_path / "a.jpg").read_bytes())

    dataset = coco(
        images=[(1, "a.jpg", 256, 192), (2, "b.jpg", 256, 192)],
        boxes=[(1, 1, 1, 0, 0, 10, 10), (2, 2, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    units = build_units(dataset, config(group_near_duplicates=False), tmp_path, 5)

    assert sorted(u.image_ids for u in units) == [(1,), (2,)]


# --------------------------------------------------------------------------
# Reproducibilidad por semilla
# --------------------------------------------------------------------------
def test_misma_semilla_da_el_mismo_reparto() -> None:
    dataset = dataset_con_clases({"car": 20, "dog": 20})
    units = [Unit(image_ids=(i.id,), stratum="car") for i in dataset.images]

    a = assign(units, RATIOS, seed=42)
    b = assign(units, RATIOS, seed=42)

    assert [(x.image_id, x.split) for x in a] == [(x.image_id, x.split) for x in b]


def test_semilla_distinta_da_un_reparto_distinto() -> None:
    dataset = dataset_con_clases({"car": 30})
    units = [Unit(image_ids=(i.id,), stratum="car") for i in dataset.images]

    a = assign(units, RATIOS, seed=42)
    b = assign(units, RATIOS, seed=7)

    assert [(x.image_id, x.split) for x in a] != [(x.image_id, x.split) for x in b]


# --------------------------------------------------------------------------
# Conteos coherentes / manifiesto valido
# --------------------------------------------------------------------------
def test_el_manifiesto_construido_valida_contra_su_propio_contrato(tmp_path: Path) -> None:
    dataset = dataset_con_clases({"car": 10, "dog": 10})
    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)

    # Round-trip: si el contrato se violara, esto lanzaria ValueError.
    SplitsManifest.model_validate_json(manifest.model_dump_json())
    assert sum(manifest.counts.values()) == len(dataset.images)
    assert manifest.seed == 42


def test_ninguna_imagen_se_pierde_ni_se_repite(tmp_path: Path) -> None:
    dataset = dataset_con_clases({"car": 7, "dog": 13, "cat": 1})
    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)

    ids_repartidos = sorted(a.image_id for a in manifest.assignments)
    assert ids_repartidos == sorted(i.id for i in dataset.images)


def test_una_clase_con_una_sola_imagen_no_rompe_el_reparto(tmp_path: Path) -> None:
    dataset = dataset_con_clases({"car": 30, "raro": 1})
    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)

    assert sum(manifest.counts.values()) == 31


def test_imagenes_sin_anotar_forman_su_propio_estrato() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100), (2, "vacia.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    labels = stratum_labels(dataset)

    assert labels[1] == "car"
    assert labels[2] == splits_module.SIN_ANOTAR


def test_estratifica_por_la_clase_minoritaria_de_la_imagen() -> None:
    """Una imagen con `car` (comun) y `raro` (escaso) se etiqueta `raro`."""
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)] + [(i, f"c{i}.jpg", 100, 100) for i in range(2, 22)],
        boxes=[(1, 1, 1, 0, 0, 10, 10), (2, 1, 2, 0, 0, 10, 10)]
        + [(i + 1, i, 1, 0, 0, 10, 10) for i in range(2, 22)],
        categories=[(1, "car"), (2, "raro")],
    )
    labels = stratum_labels(dataset)

    assert labels[1] == "raro"


# --------------------------------------------------------------------------
# Dentro de tolerancia
# --------------------------------------------------------------------------
def test_desviacion_es_cero_con_una_sola_clase(tmp_path: Path) -> None:
    dataset = dataset_con_clases({"car": 40})
    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)

    result = deviation(dataset, manifest.assignments)
    assert result["car"] == pytest.approx(0.0)


def test_desviacion_se_mide_por_clase_no_globalmente(tmp_path: Path) -> None:
    dataset = dataset_con_clases({"car": 100, "dog": 100})
    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)

    result = deviation(dataset, manifest.assignments)
    assert set(result) == {"car", "dog"}
    assert all(value <= 0.10 for value in result.values())


# --------------------------------------------------------------------------
# El desglose por clase viaja DENTRO del manifiesto
# --------------------------------------------------------------------------
def test_el_manifiesto_trae_el_reparto_de_cada_clase(tmp_path: Path) -> None:
    """Sin esto, `splits.json` dice cuantas imagenes hay pero no de que clases.

    La pantalla tendria que cruzarlo con `stats.json`, y nada garantiza que los
    dos archivos describan el mismo dataset.
    """
    dataset = dataset_con_clases({"car": 60, "dog": 40})
    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)

    assert set(manifest.per_class) == {"car", "dog"}
    assert manifest.per_class["car"].total == 60
    assert manifest.per_class["dog"].total == 40


def test_el_reparto_de_cada_clase_suma_su_total(tmp_path: Path) -> None:
    dataset = dataset_con_clases({"car": 60, "dog": 40})
    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)

    for counts in manifest.per_class.values():
        assert counts.train + counts.val + counts.test == counts.total


def test_la_suma_de_las_clases_cuadra_con_los_conteos_del_split() -> None:
    """Una imagen con cajas de dos clases suma en las dos: los totales por
    clase pueden superar el numero de imagenes, pero por particion tienen que
    cuadrar cuando cada imagen tiene una sola clase."""
    dataset = coco(
        images=[(i, f"{i}.jpg", 100, 100) for i in range(1, 5)],
        boxes=[(i, i, 1 if i < 3 else 2, 0, 0, 30, 30) for i in range(1, 5)],
        categories=[(1, "car"), (2, "dog")],
    )
    assignments = [
        SplitAssignment(image_id=1, split="train"),
        SplitAssignment(image_id=2, split="train"),
        SplitAssignment(image_id=3, split="val"),
        SplitAssignment(image_id=4, split="test"),
    ]
    desglose = splits_module.class_breakdown(dataset, assignments)

    assert desglose["car"].train == 2
    assert desglose["car"].val == 0
    assert desglose["dog"].val == 1
    assert desglose["dog"].test == 1


def test_una_imagen_con_dos_clases_suma_en_las_dos() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 30, 30), (2, 1, 2, 40, 40, 30, 30)],
        categories=[(1, "car"), (2, "dog")],
    )
    assignments = [SplitAssignment(image_id=1, split="train")]
    desglose = splits_module.class_breakdown(dataset, assignments)

    assert desglose["car"].total == 1
    assert desglose["dog"].total == 1


def test_el_manifiesto_cuenta_los_grupos_de_casi_duplicados(tmp_path: Path) -> None:
    """La cifra que demuestra que ninguna copia cruzo de particion.

    Se calculaba al repartir y se perdia al escribir el archivo, asi que la
    pantalla no tenia con que dibujar mas que un punto verde fijo.
    """
    draw(tmp_path / "gemela_a.jpg", seed=3)
    (tmp_path / "gemela_b.jpg").write_bytes((tmp_path / "gemela_a.jpg").read_bytes())
    draw(tmp_path / "distinta.jpg", seed=11)
    draw(tmp_path / "otra.jpg", seed=19)
    dataset = coco(
        images=[
            (1, "gemela_a.jpg", 256, 192),
            (2, "gemela_b.jpg", 256, 192),
            (3, "distinta.jpg", 256, 192),
            (4, "otra.jpg", 256, 192),
        ],
        boxes=[(i, i, 1, 0, 0, 60, 60) for i in range(1, 5)],
        categories=[(1, "car")],
    )
    manifest = splits_module.build_manifest(dataset, quality_config(), tmp_path)

    assert manifest.grouped_near_duplicates == 1
    # Y las gemelas cayeron en la misma particion.
    split_de = {a.image_id: a.split for a in manifest.assignments}
    assert split_de[1] == split_de[2]


# --------------------------------------------------------------------------
# La compuerta de calidad bloquea `dq split`
# --------------------------------------------------------------------------
def test_cmd_split_falla_si_no_existe_quality_json(tmp_path: Path, monkeypatch) -> None:
    from dataset_quality import cli

    monkeypatch.chdir(tmp_path)
    (tmp_path / "quality.yaml").write_text(
        Path(__file__).parents[1].joinpath("quality.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    exit_code = cli.main(["split", "--quality-report", "no_existe.json"])
    assert exit_code == 1


def test_cmd_split_falla_si_la_compuerta_esta_en_fail(tmp_path: Path, monkeypatch) -> None:
    import json

    from dataset_quality import cli

    monkeypatch.chdir(tmp_path)
    reporte = {
        "schema_version": 1,
        "generated_at": "2026-09-14T00:00:00Z",
        "dataset_fingerprint": "a" * 64,
        "config_version": 1,
        "status": "fail",
        "exit_code": 1,
        "totals": {"images": 1, "annotations": 1, "categories": 1},
        "checks": [
            {
                "name": "duplicates",
                "status": "fail",
                "severity": "error",
                "observed": 0.5,
                "threshold": 0.01,
                "message": "demasiados duplicados",
                "offenders": [],
            }
        ],
    }
    (tmp_path / "quality.json").write_text(json.dumps(reporte), encoding="utf-8")

    exit_code = cli.main(["split", "--quality-report", str(tmp_path / "quality.json")])
    assert exit_code == 1


def test_cmd_split_force_ignora_la_compuerta_en_fail(tmp_path: Path, monkeypatch) -> None:
    import json

    from dataset_quality import cli
    from dataset_quality.tiers import ingest as ingest_module

    monkeypatch.chdir(tmp_path)
    (tmp_path / "quality.yaml").write_text(
        Path(__file__).parents[1].joinpath("quality.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    images_dir = tmp_path / "raw_images"
    images_dir.mkdir()
    annotations_path = tmp_path / "annotations.coco.json"
    dataset = dataset_con_clases({"car": 10, "dog": 10})
    annotations_path.write_text(dataset.model_dump_json(), encoding="utf-8")

    monkeypatch.setattr(ingest_module, "RAW_ANNOTATIONS", annotations_path)
    monkeypatch.setattr(ingest_module, "RAW_IMAGES", images_dir)

    reporte = {
        "schema_version": 1,
        "generated_at": "2026-09-14T00:00:00Z",
        "dataset_fingerprint": "a" * 64,
        "config_version": 1,
        "status": "fail",
        "exit_code": 1,
        "totals": {"images": 1, "annotations": 1, "categories": 1},
        "checks": [],
    }
    (tmp_path / "quality.json").write_text(json.dumps(reporte), encoding="utf-8")

    exit_code = cli.main(
        [
            "split",
            "--quality-report",
            str(tmp_path / "quality.json"),
            "--out",
            str(tmp_path / "splits.json"),
            "--force",
        ]
    )
    assert exit_code == 0
    assert (tmp_path / "splits.json").is_file()
