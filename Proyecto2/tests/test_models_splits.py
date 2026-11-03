"""`splits.json`: ratios coherentes y ninguna imagen filtrada entre splits."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dataset_quality.models.splits import SplitAssignment, SplitRatios, SplitsManifest


def _manifiesto_base(**overrides: object) -> dict:
    base = {
        "generated_at": datetime.now(tz=UTC),
        "seed": 42,
        "ratios": SplitRatios(train=0.7, val=0.15, test=0.15),
        "counts": {"train": 2, "val": 1, "test": 1},
        "assignments": [
            SplitAssignment(image_id=1, split="train"),
            SplitAssignment(image_id=2, split="train"),
            SplitAssignment(image_id=3, split="val"),
            SplitAssignment(image_id=4, split="test"),
        ],
    }
    base.update(overrides)
    return base


def test_manifiesto_coherente_se_acepta() -> None:
    manifest = SplitsManifest(**_manifiesto_base())

    assert manifest.schema_version == 1
    assert len(manifest.assignments) == 4


def test_ratios_que_no_suman_uno_se_rechazan() -> None:
    with pytest.raises(ValueError, match=r"sumar 1\.0"):
        SplitRatios(train=0.5, val=0.3, test=0.3)


def test_imagen_asignada_a_dos_splits_se_rechaza_como_fuga() -> None:
    with pytest.raises(ValueError, match="fuga"):
        SplitsManifest(
            **_manifiesto_base(
                assignments=[
                    SplitAssignment(image_id=1, split="train"),
                    SplitAssignment(image_id=1, split="val"),
                ],
                counts={"train": 1, "val": 1, "test": 0},
            )
        )


def test_counts_incoherente_con_assignments_se_rechaza() -> None:
    with pytest.raises(ValueError, match=r"counts\.train"):
        SplitsManifest(**_manifiesto_base(counts={"train": 99, "val": 1, "test": 1}))
