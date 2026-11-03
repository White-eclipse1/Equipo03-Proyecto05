r"""Los artefactos del pipeline se escriben con LF en cualquier plataforma.

Por que esto merece una prueba propia
-------------------------------------
Es un fallo que no se ve. El JSON queda bien formado, se relee sin problema y
todas las demas pruebas pasan en verde. Lo unico que cambia son los bytes del
final de cada linea — y DVC hashea bytes, no contenido.

La consecuencia real, que ya ocurrio: un `dvc repro` corrido en Windows graba
en `dvc.lock` los md5 de la version CRLF. En CI, que es Linux, esos mismos
archivos tienen LF, ningun hash coincide, las cuatro etapas salen como
"modified" y `dvc repro` reejecuta el pipeline entero. El lock, que existe
precisamente para evitar eso, pasa a garantizar lo contrario.

En Linux estas pruebas pasan sin hacer nada — `write_text` ya usa LF alli. El
valor esta en Windows, que es donde el `newline="\n"` de cada escritor es lo
unico que separa un lock portable de uno que solo sirve en la maquina que lo
genero.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset_quality.models.quality import CheckResult, QualityReport, QualityTotals
from dataset_quality.models.splits import SplitsManifest
from dataset_quality.models.versions import VersionsManifest
from dataset_quality.tiers import gate, release, splits

FIXTURES = Path(__file__).parent / "fixtures"


def sin_crlf(path: Path) -> None:
    """Falla nombrando el archivo y cuantos CRLF tiene, no solo `assert False`."""
    crudo = path.read_bytes()
    cuantos = crudo.count(b"\r\n")
    assert cuantos == 0, (
        f"{path.name} se escribio con {cuantos} CRLF. En Linux el mismo artefacto "
        f"tendria LF y otro md5, asi que `dvc.lock` dejaria de ser portable. "
        f'Falta `newline="\\n"` en quien lo escribe.'
    )


def test_quality_json_se_escribe_con_lf(tmp_path: Path) -> None:
    destino = tmp_path / "quality.json"
    report = QualityReport(
        generated_at="2026-09-18T00:00:00Z",
        dataset_fingerprint="a" * 64,
        config_version=1,
        status="pass",
        exit_code=0,
        totals=QualityTotals(images=3, annotations=4, categories=2),
        checks=[
            CheckResult(
                name="duplicates",
                status="pass",
                severity="error",
                observed=0.0,
                threshold=0.01,
                message="sin duplicados",
            )
        ],
    )

    gate.write_report(report, destino)

    sin_crlf(destino)
    # Y sigue siendo JSON valido que su propio modelo puede releer: forzar el
    # separador no puede haber roto el contrato.
    QualityReport.model_validate_json(destino.read_text(encoding="utf-8"))


def test_splits_json_se_escribe_con_lf(tmp_path: Path) -> None:
    destino = tmp_path / "splits.json"
    manifest = SplitsManifest.model_validate_json(
        (FIXTURES / "splits.json").read_text(encoding="utf-8")
    )

    splits.write_manifest(manifest, destino)

    sin_crlf(destino)
    SplitsManifest.model_validate_json(destino.read_text(encoding="utf-8"))


def test_versions_json_se_escribe_con_lf(tmp_path: Path) -> None:
    destino = tmp_path / "versions.json"
    manifest = VersionsManifest.model_validate_json(
        (FIXTURES / "versions.json").read_text(encoding="utf-8")
    )

    release.write_manifest(manifest, destino)

    sin_crlf(destino)
    VersionsManifest.model_validate_json(destino.read_text(encoding="utf-8"))


def test_el_artefacto_descriptivo_se_escribe_con_lf(tmp_path: Path) -> None:
    """`stats.json`, que sale de `dq analyze` por `tiers/pipeline.write_stats`."""
    from dataset_quality.models.coco import load_coco
    from dataset_quality.tiers import pipeline

    dataset = load_coco(FIXTURES / "coco_valido.json")
    destino = tmp_path / "stats.json"

    pipeline.write_stats(dataset, [], destino)

    sin_crlf(destino)
    json.loads(destino.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "artefacto",
    ["quality.json", "splits.json", "stats.json", "versions.json", "exploration.json"],
)
def test_los_reportes_del_repositorio_no_tienen_crlf(artefacto: str) -> None:
    """Los artefactos COMMITEADOS, que son los que `dvc.lock` referencia.

    Esta es la que habria atrapado el fallo de verdad: las de arriba prueban a
    los escritores sobre archivos temporales, pero lo que rompio CI fueron los
    `reports/*.json` que estaban en el arbol de trabajo con CRLF cuando se
    regenero el lock.
    """
    ruta = Path(__file__).resolve().parent.parent / "reports" / artefacto
    if not ruta.is_file():
        pytest.skip(f"{artefacto} todavia no se ha generado en este clon")

    sin_crlf(ruta)
