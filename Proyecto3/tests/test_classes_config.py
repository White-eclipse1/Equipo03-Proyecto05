"""`config/classes.yaml` versionado: las clases fijadas antes de experimentar (F2 T06).

Protege la decision: si alguien quita o agrega una clase, cambia el release o
reordena los indices despues de ver resultados, esta prueba falla. El mapa
debe ser el de `docs/contratos.md` §1, que usan el entrenador y la inferencia.
"""

from __future__ import annotations

from pathlib import Path

from p3.data.classes import load_classes

CLASSES_YAML = Path(__file__).parents[1] / "config" / "classes.yaml"


def test_classes_yaml_es_el_mapa_del_contrato() -> None:
    config = load_classes(CLASSES_YAML)
    assert [(c.class_index, c.category_name, c.category_id) for c in config.classes] == [
        (0, "cat", 4),
        (1, "dog", 3),
        (2, "person", 2),
    ]
    assert sorted(e.category_name for e in config.excluded) == ["bicycle", "car"]


def test_classes_yaml_cita_el_release_aprobado() -> None:
    config = load_classes(CLASSES_YAML)
    assert config.release_id == "0.1.3"
    assert config.dataset_fingerprint == (
        "2200274dc6bbe6d0bc516e0136ae68651c0040bc6cab64a871794924fa39aa84"
    )


def test_cada_clase_incluida_tiene_al_menos_300_originales() -> None:
    config = load_classes(CLASSES_YAML)
    assert config.min_originals == 300
    assert all(c.originals >= 300 for c in config.classes)
