"""Las cinco herramientas MCP de solo lectura del Dataset Copilot.

Este modulo no conoce Gemini ni transporte MCP. Asi las reglas de evidencia se
prueban sin red y el mismo nucleo sirve a la API, al sidecar y a las pruebas.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import Field

from dataset_quality.api import artifacts
from dataset_quality.api.artifacts import LoadedArtifact
from dataset_quality.models import StrictModel

ALLOWED_TOOL_NAMES = (
    "get_quality_report",
    "get_failed_checks",
    "get_class_distribution",
    "get_split_report",
    "list_versions",
)


class SourceCitation(StrictModel):
    """Revision exacta de un reporte que sustenta una respuesta."""

    artifact: str
    artifact_revision: str
    generated_at: str | None = None
    dataset_fingerprint: str | None = None
    dataset_version: str | None = None


class ToolResult(StrictModel):
    """Salida estructurada, pequena y citable de una herramienta MCP."""

    source: SourceCitation
    data: dict[str, Any]


class FailedChecksArguments(StrictModel):
    severity: Literal["all", "error", "warning"] = "all"


class VersionsArguments(StrictModel):
    limit: int = Field(default=10, ge=1, le=50)


def _dataset_version(dataset_fingerprint: str | None) -> str | None:
    """Resuelve una huella a la version publicada mas reciente, si existe."""
    if dataset_fingerprint is None:
        return None

    try:
        versions = artifacts.read(artifacts.ARTIFACTS["versions"]).data.versions
    except HTTPException:
        # La evidencia del reporte sigue siendo valida aunque el registro de
        # releases aun no exista o ya no cumpla su contrato.
        return None

    for version in reversed(versions):
        if version.dataset_fingerprint == dataset_fingerprint:
            return version.version
    return None


def _result(loaded: LoadedArtifact, data: dict[str, Any]) -> ToolResult:
    source = SourceCitation.model_validate(loaded.source())
    source = source.model_copy(
        update={"dataset_version": _dataset_version(source.dataset_fingerprint)}
    )
    return ToolResult(source=source, data=data)


def get_quality_report() -> ToolResult:
    """Devuelve el veredicto y checks de ``quality.json`` sin recalcularlos."""
    loaded = artifacts.read(artifacts.ARTIFACTS["quality"])
    report = loaded.data
    return _result(
        loaded,
        {
            "status": report.status,
            "exit_code": report.exit_code,
            "config_version": report.config_version,
            "totals": report.totals.model_dump(),
            "checks": [check.model_dump(mode="json") for check in report.checks],
        },
    )


def get_failed_checks(severity: Literal["all", "error", "warning"] = "all") -> ToolResult:
    """Devuelve solo reglas fallidas, opcionalmente filtradas por severidad."""
    args = FailedChecksArguments(severity=severity)
    loaded = artifacts.read(artifacts.ARTIFACTS["quality"])
    report = loaded.data
    checks = [check for check in report.checks if check.status == "fail"]
    if args.severity != "all":
        checks = [check for check in checks if check.severity == args.severity]
    return _result(
        loaded,
        {
            "quality_status": report.status,
            "checks": [check.model_dump(mode="json") for check in checks],
        },
    )


def get_class_distribution() -> ToolResult:
    """Devuelve imagenes y cajas por clase desde ``stats.json`` validado."""
    loaded = artifacts.read(artifacts.ARTIFACTS["stats"])
    stats = loaded.data.stats
    return _result(
        loaded,
        {
            "totals": stats.totals.model_dump(),
            "images_per_class": stats.images_per_class,
            "boxes_per_class": stats.boxes_per_class,
        },
    )


def get_split_report() -> ToolResult:
    """Devuelve el resumen reproducible de splits, no todas las asignaciones."""
    loaded = artifacts.read(artifacts.ARTIFACTS["splits"])
    manifest = loaded.data
    return _result(
        loaded,
        {
            "seed": manifest.seed,
            "ratios": manifest.ratios.model_dump(),
            "counts": dict(manifest.counts),
            "stratified_by": manifest.stratified_by,
        },
    )


def list_versions(limit: int = 10) -> ToolResult:
    """Lista las versiones mas recientes del manifiesto inmutable."""
    args = VersionsArguments(limit=limit)
    loaded = artifacts.read(artifacts.ARTIFACTS["versions"])
    versions = loaded.data.versions[-args.limit :]
    return _result(
        loaded,
        {"versions": [version.model_dump(mode="json") for version in reversed(versions)]},
    )


def execute_tool(name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
    """Despacha exclusivamente la lista cerrada de herramientas permitidas."""
    args = arguments or {}
    if name == "get_quality_report":
        if args:
            raise ValueError("get_quality_report no acepta argumentos")
        return get_quality_report()
    if name == "get_failed_checks":
        return get_failed_checks(**FailedChecksArguments.model_validate(args).model_dump())
    if name == "get_class_distribution":
        if args:
            raise ValueError("get_class_distribution no acepta argumentos")
        return get_class_distribution()
    if name == "get_split_report":
        if args:
            raise ValueError("get_split_report no acepta argumentos")
        return get_split_report()
    if name == "list_versions":
        return list_versions(**VersionsArguments.model_validate(args).model_dump())
    raise ValueError(f"Herramienta no permitida: {name}")
