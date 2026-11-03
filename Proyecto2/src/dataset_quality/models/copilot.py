"""Contratos HTTP y de evidencia del Dataset Copilot."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from dataset_quality.copilot.tools import SourceCitation
from dataset_quality.models import StrictModel


class CopilotChatRequest(StrictModel):
    question: str = Field(min_length=1, max_length=2_000)


class CopilotToolCall(StrictModel):
    id: str
    name: str
    arguments: dict[str, Any]
    status: Literal["success", "failed", "rejected"]
    duration_ms: int = Field(ge=0)
    citation: SourceCitation | None = None
    error: str | None = None


class CopilotAnswer(StrictModel):
    request_id: str
    answer: str
    tool_calls: list[CopilotToolCall]
    citations: list[SourceCitation]
