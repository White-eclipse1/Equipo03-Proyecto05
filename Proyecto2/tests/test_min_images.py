"""El minimo de imagenes por clase: 300 en al menos 2 clases, severidad error.

Escritas ANTES de la implementacion.

Este check no estaba en `QualityConfig`. Es el requisito del curso (compuerta
M3) y el unico que mide si el dataset tiene volumen suficiente para entrenar
algo; dejarlo en un valor de ejemplo bajo hace que la compuerta pase cuando no
deberia, que es peor que no tenerla.

Hay una prueba que lee el `quality.yaml` real del repositorio y comprueba que
el umbral sea 300 con severidad `error`: un umbral por debajo pone la suite en
rojo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dataset_quality.analyzers import analyze_min_images_per_class
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import MinImagesPerClassCheck, QualityConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK = MinImagesPerClassCheck(min_images=300, min_classes=2)
# El requisito del curso, independiente de lo que diga hoy el quality.yaml.
REQUISITO_MIN_IMAGES = 300


def dataset_con(**imagenes_por_clase: int) -> CocoDataset:
    """Dataset sintetico con un numero exacto de imagenes distintas por clase."""
    images, annotations, categories = [], [], []
    image_id = annotation_id = 1

    for category_id, (name, cuantas) in enumerate(imagenes_por_clase.items(), start=1):
        categories.append({"id": category_id, "name": name})
        for _ in range(cuantas):
            images.append(
                {"id": image_id, "file_name": f"{name}_{image_id}.jpg", "width": 100, "height": 100}
            )
            annotations.append(
                {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": category_id,
                    "bbox": [0.0, 0.0, 10.0, 10.0],
                    "area": 100.0,
                    "iscrowd": 0,
                }
            )
            image_id += 1
            annotation_id += 1

    return CocoDataset.model_validate(
        {"images": images, "annotations": annotations, "categories": categories}
    )


# --------------------------------------------------------------------------
# Comportamiento
# --------------------------------------------------------------------------
def test_dos_clases_con_300_cumplen() -> None:
    result = analyze_min_images_per_class(dataset_con(person=300, dog=300, cat=5), CHECK)

    assert result.status == "pass"
    assert result.observed == pytest.approx(300.0)
    assert result.threshold == pytest.approx(300.0)


def test_una_sola_clase_con_300_no_basta() -> None:
    """El requisito son DOS clases; una sola no cumple por muy poblada que este."""
    result = analyze_min_images_per_class(dataset_con(person=900, dog=10), CHECK)

    assert result.status == "fail"
    assert result.observed == pytest.approx(10.0)


def test_el_valor_observado_es_el_de_la_segunda_clase_mas_poblada() -> None:
    """Con min_classes=2, lo que decide es la 2a clase, no la 1a ni la ultima."""
    result = analyze_min_images_per_class(dataset_con(a=500, b=420, c=3), CHECK)

    assert result.observed == pytest.approx(420.0)
    assert result.status == "pass"


def test_justo_en_300_cumple() -> None:
    """El umbral es inclusivo: 300 es suficiente, 299 no."""
    assert analyze_min_images_per_class(dataset_con(a=300, b=300), CHECK).status == "pass"
    assert analyze_min_images_per_class(dataset_con(a=300, b=299), CHECK).status == "fail"


def test_senala_las_clases_que_no_llegan() -> None:
    result = analyze_min_images_per_class(dataset_con(person=300, dog=300, cat=40), CHECK)

    # `cat` es la categoria 3
    assert result.offenders == [3]


def test_el_mensaje_dice_cuantas_faltan() -> None:
    result = analyze_min_images_per_class(dataset_con(person=288, dog=206), CHECK)

    assert "288" in result.message
    assert result.status == "fail"


def test_menos_clases_que_el_minimo_exigido_falla() -> None:
    result = analyze_min_images_per_class(dataset_con(person=900), CHECK)

    assert result.status == "fail"
    assert result.observed == pytest.approx(0.0)


def test_desactivado_se_salta() -> None:
    disabled = MinImagesPerClassCheck(enabled=False, min_images=300, min_classes=2)

    assert analyze_min_images_per_class(dataset_con(a=1), disabled).status == "skipped"


def test_la_severidad_por_defecto_bloquea() -> None:
    """Este check nace en `error`: sin volumen no hay dataset que entregar."""
    assert MinImagesPerClassCheck(min_images=300, min_classes=2).severity == "error"


# --------------------------------------------------------------------------
# El quality.yaml que se entrega
# --------------------------------------------------------------------------
def test_el_quality_yaml_del_repo_exige_300_con_severidad_error() -> None:
    """Guarda contra el atajo de bajar el umbral para que la compuerta pase."""
    check = QualityConfig.from_yaml(REPO_ROOT / "quality.yaml").min_images_per_class

    assert check.min_images == REQUISITO_MIN_IMAGES, (
        f"quality.yaml exige {check.min_images} imagenes por clase, no "
        f"{REQUISITO_MIN_IMAGES}: la compuerta M3 pasaria con menos volumen "
        f"del que pide el curso (criterio 4.1 de la rubrica)."
    )
    assert check.enabled is True
    assert check.min_classes >= 2
    assert check.severity == "error"


def test_el_check_esta_entre_los_analizadores_activos() -> None:
    config = QualityConfig.from_yaml(REPO_ROOT / "quality.yaml")

    assert "min_images_per_class" in config.enabled_checks()
