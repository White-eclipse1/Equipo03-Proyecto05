"""Persistencia minima de auditoria para llamadas MCP."""

from __future__ import annotations

from threading import Lock

from dataset_quality.db import get_engine, session_scope
from dataset_quality.models.copilot import CopilotToolCall
from dataset_quality.tables import CopilotToolCall as CopilotToolCallRow

_schema_lock = Lock()
_schema_ready = False


def _ensure_table() -> None:
    """Crea solo la nueva tabla de auditoria, sin migrar tablas ajenas."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if not _schema_ready:
            CopilotToolCallRow.__table__.create(get_engine(), checkfirst=True)
            _schema_ready = True


def record_tool_call(request_id: str, call: CopilotToolCall) -> None:
    """Guarda una llamada ya saneada; el payload de la herramienta se descarta."""
    _ensure_table()
    citation = call.citation
    with session_scope() as session:
        session.add(
            CopilotToolCallRow(
                request_id=request_id,
                call_id=call.id,
                tool_name=call.name,
                arguments=call.arguments,
                status=call.status,
                duration_ms=call.duration_ms,
                source_artifact=citation.artifact if citation else None,
                source_revision=citation.artifact_revision if citation else None,
                source_dataset_fingerprint=citation.dataset_fingerprint if citation else None,
                error_code=call.error,
            )
        )
