"""`quality.yaml` (entrada) y `QualityReport` (salida congelada) — Frente 2."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from dataset_quality.models.errors import DatasetValidationError
from dataset_quality.models.quality import CheckResult, QualityConfig, QualityReport, QualityTotals

REPO_QUALITY_YAML = Path(__file__).parents[1] / "quality.yaml"


def test_el_quality_yaml_real_del_repo_carga_y_valida() -> None:
    config = QualityConfig.from_yaml(REPO_QUALITY_YAML)

    assert config.version == 1
    assert config.duplicates.phash_hamming_distance == 5
    assert config.enabled_checks() == (
        "min_images_per_class",
        "small_objects",
        "class_imbalance",
        "duplicates",
        "degenerate_boxes",
        "spatial_bias",
    )


def test_umbral_fuera_de_rango_se_rechaza_nombrando_el_campo(tmp_path: Path) -> None:
    data = yaml.safe_load(REPO_QUALITY_YAML.read_text(encoding="utf-8"))
    data["small_objects"]["max_ratio"] = 1.5  # fuera de [0, 1]
    path = tmp_path / "quality.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(DatasetValidationError) as error:
        QualityConfig.from_yaml(path)

    assert "small_objects.max_ratio" in str(error.value)


def test_campo_requerido_faltante_se_rechaza_nombrando_el_campo(tmp_path: Path) -> None:
    data = yaml.safe_load(REPO_QUALITY_YAML.read_text(encoding="utf-8"))
    del data["duplicates"]["phash_hamming_distance"]
    path = tmp_path / "quality.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(DatasetValidationError) as error:
        QualityConfig.from_yaml(path)

    assert "duplicates.phash_hamming_distance" in str(error.value)


def test_yaml_malformado_no_propaga_un_traceback_de_pyyaml(tmp_path: Path) -> None:
    path = tmp_path / "quality.yaml"
    path.write_text("version: 1\nsmall_objects: [esto, no, cierra", encoding="utf-8")

    with pytest.raises(DatasetValidationError) as error:
        QualityConfig.from_yaml(path)

    assert "YAML malformado" in str(error.value)


def test_archivo_vacio_se_rechaza(tmp_path: Path) -> None:
    path = tmp_path / "quality.yaml"
    path.write_text("", encoding="utf-8")

    with pytest.raises(DatasetValidationError):
        QualityConfig.from_yaml(path)


def _reporte_base(**overrides: object) -> dict:
    base = {
        "generated_at": datetime.now(tz=UTC),
        "dataset_fingerprint": "a" * 64,
        "config_version": 1,
        "status": "pass",
        "exit_code": 0,
        "totals": QualityTotals(images=3, annotations=4, categories=2),
        "checks": [
            CheckResult(
                name="degenerate_boxes",
                status="pass",
                severity="error",
                observed=0.0,
                threshold=0.0,
                message="sin cajas degeneradas",
            )
        ],
    }
    base.update(overrides)
    return base


def test_status_pass_con_exit_code_1_se_rechaza() -> None:
    with pytest.raises(ValueError, match="exit_code"):
        QualityReport(**_reporte_base(status="pass", exit_code=1))


def test_status_fail_con_exit_code_0_se_rechaza() -> None:
    with pytest.raises(ValueError, match="exit_code"):
        QualityReport(**_reporte_base(status="fail", exit_code=0))


def test_reporte_coherente_se_acepta() -> None:
    report = QualityReport(**_reporte_base())

    assert report.schema_version == 1
    assert report.status == "pass"
    assert report.exit_code == 0
