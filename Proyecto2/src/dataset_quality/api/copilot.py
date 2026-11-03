"""Endpoint HTTP del Dataset Copilot; la logica vive fuera del router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dataset_quality.copilot.service import CopilotProviderError, CopilotUnavailableError, answer
from dataset_quality.models.copilot import CopilotAnswer, CopilotChatRequest
from dataset_quality.settings import get_settings

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


@router.post("/chat", response_model=CopilotAnswer)
async def chat(request: CopilotChatRequest) -> CopilotAnswer:
    try:
        return await answer(request.question, get_settings())
    except CopilotUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except CopilotProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
