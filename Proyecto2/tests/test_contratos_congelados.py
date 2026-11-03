"""Protege la forma exacta de `quality.json`, `splits.json` y `versions.json`.

Estos tres son el contrato congelado que la tarjeta de F2 pide fijar el mismo
dia: si alguien cambia su forma en F4/F5 sin actualizar el golden file, esta
prueba de round-trip lo detecta antes de que rompa a F7/F8.
"""

from __future__ import annotations

import json
from pathlib import Path

from dataset_quality.models.quality import QualityReport
from dataset_quality.models.splits import SplitsManifest
from dataset_quality.models.versions import VersionsManifest

FIXTURES = Path(__file__).parent / "fixtures"


def _assert_round_trip(model_cls, fixture_name: str) -> None:
    raw = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    original = json.loads(raw)

    parsed = model_cls.model_validate(original)
    dumped = json.loads(parsed.model_dump_json())

    mensaje = f"{fixture_name}: la forma del modelo ya no coincide con el golden file"
    assert dumped == original, mensaje


def test_quality_json_round_trip() -> None:
    _assert_round_trip(QualityReport, "quality.json")


def test_splits_json_round_trip() -> None:
    _assert_round_trip(SplitsManifest, "splits.json")


def test_versions_json_round_trip() -> None:
    _assert_round_trip(VersionsManifest, "versions.json")


def test_los_tres_contratos_estan_en_schema_version_1() -> None:
    quality = QualityReport.model_validate_json(
        (FIXTURES / "quality.json").read_text(encoding="utf-8")
    )
    splits = SplitsManifest.model_validate_json(
        (FIXTURES / "splits.json").read_text(encoding="utf-8")
    )
    versions = VersionsManifest.model_validate_json(
        (FIXTURES / "versions.json").read_text(encoding="utf-8")
    )

    # Si esto falla porque alguien subio la version, es una ruptura deliberada
    # del contrato: debe ir acompanada de una migracion documentada, no de un
    # cambio silencioso.
    assert quality.schema_version == 1
    assert splits.schema_version == 1
    assert versions.schema_version == 1
