"""El MCP solo puede leer reportes validados y devolver evidencia citable."""

from __future__ import annotations

import asyncio
import inspect
import json
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException

from dataset_quality.api import artifacts
from dataset_quality.copilot import tools
from dataset_quality.mcp_server import create_server


@pytest.fixture
def reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    original = artifacts.REPORTS
    for name in ("quality.json", "stats.json", "splits.json", "versions.json"):
        source = (
            Path(__file__).parent / "fixtures" / name
            if name == "versions.json"
            else original / name
        )
        shutil.copy(source, tmp_path / name)
    monkeypatch.setattr(artifacts, "REPORTS", tmp_path)
    monkeypatch.setattr(
        artifacts,
        "ARTIFACTS",
        {
            name: artifacts.Artifact(
                item.name, tmp_path / item.path.name, item.model, item.produced_by
            )
            for name, item in artifacts.ARTIFACTS.items()
        },
    )
    return tmp_path


def test_las_herramientas_son_cinco_y_solo_lectura(reports: Path) -> None:
    before = {path.name: path.read_bytes() for path in reports.iterdir()}

    results = [
        tools.get_quality_report(),
        tools.get_failed_checks(),
        tools.get_class_distribution(),
        tools.get_split_report(),
        tools.list_versions(),
    ]

    assert tools.ALLOWED_TOOL_NAMES == (
        "get_quality_report",
        "get_failed_checks",
        "get_class_distribution",
        "get_split_report",
        "list_versions",
    )
    assert all(len(result.source.artifact_revision) == 64 for result in results)
    assert {path.name: path.read_bytes() for path in reports.iterdir()} == before


def test_las_citas_resuelven_la_version_publicada_mas_reciente(reports: Path) -> None:
    # La huella sale del propio `quality.json`: que el reporte del repo
    # coincida con el ultimo release es una casualidad del momento, no un
    # contrato. El dataset de trabajo puede ir por delante del ultimo
    # publicado, y entonces la cita no nombra version (el test de abajo).
    huella = json.loads((reports / "quality.json").read_text(encoding="utf-8"))[
        "dataset_fingerprint"
    ]
    versions_path = reports / "versions.json"
    manifest = json.loads(versions_path.read_text(encoding="utf-8"))
    # Dos releases publican la misma huella: la cita debe nombrar el reciente.
    manifest["versions"] += [
        {
            **manifest["versions"][-1],
            "version": "0.1.2",
            "created_at": "2026-09-18T00:00:00Z",
            "dataset_fingerprint": huella,
        },
        {
            **manifest["versions"][-1],
            "version": "0.1.3",
            "created_at": "2026-09-19T00:00:00Z",
            "dataset_fingerprint": huella,
        },
    ]
    versions_path.write_text(json.dumps(manifest), encoding="utf-8")

    citation = tools.get_quality_report().source

    assert citation.dataset_fingerprint == huella
    assert citation.dataset_version == "0.1.3"


def test_las_citas_sin_version_no_inventan_un_release(reports: Path) -> None:
    quality_path = reports / "quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["dataset_fingerprint"] = "c" * 64
    quality_path.write_text(json.dumps(quality), encoding="utf-8")

    assert tools.get_quality_report().source.dataset_version is None

    (reports / "versions.json").unlink()
    assert tools.get_quality_report().source.dataset_version is None

    (reports / "versions.json").write_text("{roto", encoding="utf-8")
    assert tools.get_quality_report().source.dataset_version is None


def test_una_cita_legacy_sigue_siendo_valida() -> None:
    citation = tools.SourceCitation.model_validate(
        {
            "artifact": "quality.json",
            "artifact_revision": "a" * 64,
            "dataset_fingerprint": "b" * 64,
        }
    )

    assert citation.dataset_version is None


def test_las_herramientas_devuelven_resumenes_citables(reports: Path) -> None:
    failed = tools.get_failed_checks(severity="error")
    distribution = tools.get_class_distribution()
    splits = tools.get_split_report()
    versions = tools.list_versions(limit=1)

    assert failed.source.artifact == "quality.json"
    assert all(check["severity"] == "error" for check in failed.data["checks"])
    assert distribution.source.artifact == "stats.json"
    assert distribution.data["images_per_class"]
    assert splits.data["counts"].keys() == {"train", "val", "test"}
    assert len(versions.data["versions"]) == 1


def test_un_reporte_invalido_no_produce_evidencia(reports: Path) -> None:
    (reports / "stats.json").write_text('{"stats": "roto"}', encoding="utf-8")

    with pytest.raises(HTTPException, match=r"stats\.json"):
        tools.get_class_distribution()


def test_el_despachador_rechaza_herramientas_y_argumentos_no_permitidos(reports: Path) -> None:
    with pytest.raises(ValueError, match="no permitida"):
        tools.execute_tool("delete_dataset")
    with pytest.raises(ValueError, match="no acepta argumentos"):
        tools.execute_tool("get_split_report", {"path": "reports/quality.json"})


def test_el_servidor_mcp_descubre_y_ejecuta_las_cinco_herramientas() -> None:
    from mcp import Client

    async def discover() -> tuple[list[str], dict[str, str | None], object]:
        async with Client(create_server()) as client:
            listed = await client.list_tools()
            result = await client.call_tool("get_quality_report", {})
            return (
                [tool.name for tool in listed.tools],
                {tool.name: tool.description for tool in listed.tools},
                result,
            )

    names, descriptions, result = asyncio.run(discover())

    assert names == list(tools.ALLOWED_TOOL_NAMES)
    assert descriptions == {
        name: inspect.getdoc(getattr(tools, name)) for name in tools.ALLOWED_TOOL_NAMES
    }
    assert result.is_error is False
    assert result.content[0].text.startswith("{")
