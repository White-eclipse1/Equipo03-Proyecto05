"""Traduccion de errores de validacion a mensajes que nombran el campo.

Un `pydantic.ValidationError` crudo es tecnicamente correcto pero ruidoso para
un humano o un log de CI. Este modulo lo aplana una sola vez a una linea por
campo: ubicacion, motivo y valor recibido cuando esta disponible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError


@dataclass(frozen=True)
class FieldIssue:
    """Un problema de validacion localizado en un campo concreto."""

    location: str
    message: str
    received: Any = None
    has_received: bool = False

    def render(self) -> str:
        if self.has_received:
            return f"{self.location}: {self.message} (recibido: {self.received!r})"
        return f"{self.location}: {self.message}"


class DatasetValidationError(Exception):
    """Error de validacion legible: una linea por campo que fallo.

    `source` identifica el origen (archivo, JSON crudo, etc.) para que el
    mensaje diga siempre a que documento pertenece el error.
    """

    def __init__(self, source: str, issues: list[FieldIssue]) -> None:
        self.source = source
        self.issues = issues
        super().__init__(self._render())

    def _render(self) -> str:
        header = f"{self.source}: {len(self.issues)} error(es) de validacion"
        lines = "\n".join(f"  - {issue.render()}" for issue in self.issues)
        return f"{header}\n{lines}" if self.issues else header

    def __str__(self) -> str:  # pragma: no cover - delega en _render
        return self._render()


def from_pydantic(source: str, error: ValidationError) -> DatasetValidationError:
    """Convierte un `ValidationError` de Pydantic en un `DatasetValidationError`."""
    issues = [
        FieldIssue(
            location=".".join(str(part) for part in item["loc"]) or "<root>",
            message=item["msg"],
            received=item.get("input"),
            has_received="input" in item,
        )
        for item in error.errors(include_url=False)
    ]
    return DatasetValidationError(source, issues)


def single_issue(
    source: str, location: str, message: str, received: Any = None
) -> DatasetValidationError:
    """Construye un `DatasetValidationError` de un solo campo (p. ej. YAML malformado)."""
    issue = FieldIssue(
        location=location, message=message, received=received, has_received=received is not None
    )
    return DatasetValidationError(source, [issue])
