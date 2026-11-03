"""Orquestador stateless: Gemini decide, MCP aporta evidencia, la API audita."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from dataset_quality.copilot.audit import record_tool_call
from dataset_quality.copilot.tools import ALLOWED_TOOL_NAMES, SourceCitation, ToolResult
from dataset_quality.models.copilot import CopilotAnswer, CopilotToolCall
from dataset_quality.settings import Settings

MAX_TOOL_CALLS = 5
logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTIONS = """Eres Dataset Copilot. Responde en espanol y solo con evidencia
recibida mediante herramientas. La primera iteracion debe consultar una herramienta. No inventes
cifras, versiones ni estados y nunca sugieras que cambiaste el dataset. Si una herramienta
entrega `source.dataset_version`, menciona esa version como `vX.Y.Z` al usar esa evidencia; si
es null, no atribuyas ninguna version publicada. Al terminar responde EXCLUSIVAMENTE JSON con
{"answer": string, "citation_call_ids": string[]}. Cada cifra o version de answer debe estar
respaldada por al menos un ID de llamada incluido en citation_call_ids."""

FINAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "citation_call_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "citation_call_ids"],
}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "get_quality_report",
        "description": "Veredicto de calidad y todos sus checks.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "get_failed_checks",
        "description": "Checks que fallaron; filtra por severidad si hace falta.",
        "parameters": {
            "type": "object",
            "properties": {"severity": {"type": "string", "enum": ["all", "error", "warning"]}},
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_class_distribution",
        "description": "Imagenes y cajas por clase del dataset.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "get_split_report",
        "description": "Conteos, proporciones y semilla de train, val y test.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "list_versions",
        "description": "Versiones inmutables publicadas, mas reciente primero.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            "additionalProperties": False,
        },
    },
]


class CopilotUnavailableError(RuntimeError):
    """No hay configuracion o auditoria disponible para cumplir el contrato."""


class CopilotProviderError(RuntimeError):
    """Gemini no pudo terminar una respuesta util."""


def _value(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _mcp_payload(result: Any) -> dict[str, Any]:
    """Extrae la salida JSON del SDK y la deja lista para validacion Pydantic."""
    payload = _value(result, "structured_content")
    if isinstance(payload, dict):
        return payload
    content = _value(result, "content", [])
    if len(content) == 1:
        text = _value(content[0], "text")
        if isinstance(text, str):
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                return decoded
    raise ValueError("MCP devolvio una respuesta sin JSON estructurado")


@asynccontextmanager
async def open_mcp_client(url: str) -> AsyncIterator[Any]:
    """Abre una sesion Streamable HTTP contra el sidecar interno."""
    try:
        from mcp import Client
    except ImportError as error:  # pragma: no cover - depende de extras instalados
        raise CopilotUnavailableError("El SDK MCP no esta instalado.") from error

    async with Client(url) as client:
        yield client


def gemini_client(settings: Settings) -> Any:
    """Construye el cliente solo cuando existe clave; nunca la expone."""
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
        raise CopilotUnavailableError(
            "Dataset Copilot no esta configurado: define GEMINI_API_KEY en el entorno."
        )
    try:
        from google import genai
    except ImportError as error:  # pragma: no cover - depende de extras instalados
        raise CopilotUnavailableError("El SDK de Gemini no esta instalado.") from error
    return genai.Client(api_key=settings.gemini_api_key.get_secret_value())


async def create_interaction(client: Any, **kwargs: Any) -> Any:
    """El SDK de Gemini es sincrono; se ejecuta fuera del event loop de FastAPI."""
    return await asyncio.to_thread(client.interactions.create, **kwargs)


def generation_config(*, require_tool: bool) -> dict[str, Any]:
    """Fuerza evidencia primero; despues deja que Gemini decida si necesita mas."""
    if not require_tool:
        # En Interactions, omitir tool_choice equivale a dejar que el modelo
        # decida. "auto" no es un modo valido para allowed_tools.
        return {}
    # Todas las herramientas de este request ya pertenecen al allowlist local;
    # la forma enum evita diferencias de validacion entre versiones del SDK.
    return {"tool_choice": "any"}


async def _persist(request_id: str, call: CopilotToolCall) -> None:
    try:
        await asyncio.to_thread(record_tool_call, request_id, call)
    except Exception as error:
        raise CopilotUnavailableError("No se pudo registrar la llamada MCP.") from error


async def _verify_tools(client: Any) -> None:
    listed = await client.list_tools()
    tools = _value(listed, "tools", listed)
    names = {str(_value(tool, "name")) for tool in tools}
    if names != set(ALLOWED_TOOL_NAMES):
        raise CopilotUnavailableError(
            "El sidecar MCP no expone el conjunto de herramientas esperado."
        )


async def _execute_call(
    client: Any,
    request_id: str,
    call_id: str,
    name: str,
    arguments: dict[str, Any],
) -> tuple[CopilotToolCall, dict[str, Any]]:
    """Ejecuta, valida y registra exactamente una llamada permitida."""
    started = time.perf_counter()
    citation: SourceCitation | None = None
    try:
        if name not in ALLOWED_TOOL_NAMES:
            raise ValueError("tool_not_allowed")
        result = await client.call_tool(name, arguments)
        payload = _mcp_payload(result)
        validated = ToolResult.model_validate(payload)
        citation = validated.source
        output = validated.model_dump(mode="json")
        status = "success"
        error = None
    except Exception as caught:
        output = {"error": "tool_unavailable"}
        status = "failed"
        error = "tool_unavailable" if str(caught) != "tool_not_allowed" else "tool_not_allowed"

    call = CopilotToolCall(
        id=call_id,
        name=name,
        arguments=arguments,
        status=status,
        duration_ms=round((time.perf_counter() - started) * 1000),
        citation=citation,
        error=error,
    )
    await _persist(request_id, call)
    return call, output


def _no_source_answer(request_id: str, calls: list[CopilotToolCall]) -> CopilotAnswer:
    """Respuesta segura: sin evidencia disponible, no se emite ninguna cifra."""
    return CopilotAnswer(
        request_id=request_id,
        answer="No pude consultar un reporte valido en este momento, asi que no puedo dar cifras.",
        tool_calls=calls,
        citations=[],
    )


def _citations(call_ids: list[str], calls: list[CopilotToolCall]) -> list[SourceCitation]:
    by_id = {call.id: call for call in calls if call.status == "success" and call.citation}
    citations: list[SourceCitation] = []
    seen: set[str] = set()
    for call_id in call_ids:
        call = by_id.get(call_id)
        if call is None or call.citation is None:
            continue
        key = call.citation.artifact_revision
        if key not in seen:
            citations.append(call.citation)
            seen.add(key)
    return citations


async def answer(question: str, settings: Settings) -> CopilotAnswer:
    """Ejecuta un turno sin memoria y devuelve solo evidencia trazable."""
    request_id = str(uuid4())
    provider = gemini_client(settings)
    calls: list[CopilotToolCall] = []
    history: list[Any] = [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": f"{SYSTEM_INSTRUCTIONS}\n\nPregunta: {question}"}],
        }
    ]

    try:
        async with open_mcp_client(settings.mcp_server_url) as mcp_client:
            await _verify_tools(mcp_client)
            for iteration in range(MAX_TOOL_CALLS + 1):
                response = await create_interaction(
                    provider,
                    model=settings.gemini_model,
                    input=history,
                    tools=TOOL_DEFINITIONS,
                    generation_config=generation_config(require_tool=iteration == 0),
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": FINAL_SCHEMA,
                    },
                    store=False,
                )
                steps = list(_value(response, "steps", []))
                requested = [item for item in steps if _value(item, "type") == "function_call"]
                if not requested:
                    if not any(call.status == "success" for call in calls):
                        return _no_source_answer(request_id, calls)
                    try:
                        output_text = str(_value(response, "output_text", ""))
                        final = json.loads(output_text)
                        answer_text = str(final["answer"]).strip()
                        cited_ids = [str(item) for item in final["citation_call_ids"]]
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        logger.warning(
                            "Gemini devolvio salida final no estructurada (chars=%d, steps=%s)",
                            len(str(_value(response, "output_text", ""))),
                            [str(_value(step, "type", "unknown")) for step in steps],
                        )
                        return _no_source_answer(request_id, calls)
                    citations = _citations(cited_ids, calls)
                    if not answer_text or not citations:
                        logger.warning(
                            "Gemini no cito una llamada MCP exitosa (calls=%d, cited_ids=%d)",
                            len([call for call in calls if call.status == "success"]),
                            len(cited_ids),
                        )
                        return _no_source_answer(request_id, calls)
                    return CopilotAnswer(
                        request_id=request_id,
                        answer=answer_text,
                        tool_calls=calls,
                        citations=citations,
                    )

                history.extend(
                    item.model_dump() if hasattr(item, "model_dump") else item for item in steps
                )
                for item in requested:
                    call_id = str(_value(item, "id", uuid4()))
                    name = str(_value(item, "name", ""))
                    try:
                        raw_arguments = _value(item, "arguments", {})
                        arguments = (
                            raw_arguments
                            if isinstance(raw_arguments, dict)
                            else json.loads(str(raw_arguments))
                        )
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments_not_object")
                    except (ValueError, TypeError, json.JSONDecodeError):
                        arguments = {}
                        invalid = CopilotToolCall(
                            id=call_id,
                            name=name,
                            arguments=arguments,
                            status="failed",
                            duration_ms=0,
                            error="invalid_arguments",
                        )
                        await _persist(request_id, invalid)
                        calls.append(invalid)
                        history.append(
                            {
                                "type": "function_result",
                                "name": name,
                                "call_id": call_id,
                                "result": [{"type": "text", "text": "invalid_arguments"}],
                            }
                        )
                        continue

                    if len(calls) >= MAX_TOOL_CALLS:
                        rejected = CopilotToolCall(
                            id=call_id,
                            name=name,
                            arguments=arguments,
                            status="rejected",
                            duration_ms=0,
                            error="tool_limit_reached",
                        )
                        await _persist(request_id, rejected)
                        calls.append(rejected)
                        history.append(
                            {
                                "type": "function_result",
                                "name": name,
                                "call_id": call_id,
                                "result": [{"type": "text", "text": "tool_limit_reached"}],
                            }
                        )
                        continue

                    call, result = await _execute_call(
                        mcp_client, request_id, call_id, name, arguments
                    )
                    calls.append(call)
                    history.append(
                        {
                            "type": "function_result",
                            "name": name,
                            "call_id": call_id,
                            "result": [
                                {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                            ],
                        }
                    )
    except CopilotUnavailableError:
        raise
    except Exception as error:
        # Deja diagnostico tecnico en el servidor sin serializar entradas,
        # salidas de herramientas ni secretos hacia el cliente.
        logger.exception("La orquestacion Gemini/MCP fallo: %s", type(error).__name__)
        raise CopilotProviderError("No se pudo completar la consulta del Copilot.") from error

    return _no_source_answer(request_id, calls)
