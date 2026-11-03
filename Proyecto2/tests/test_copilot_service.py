"""La orquestacion exige evidencia, conserva auditoria y no usa la red en CI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dataset_quality.api import copilot
from dataset_quality.copilot import service
from dataset_quality.copilot.tools import ALLOWED_TOOL_NAMES, SourceCitation, ToolResult
from dataset_quality.main import create_app
from dataset_quality.settings import Settings
from dataset_quality.tables import CopilotToolCall


def settings(env, *, key: str | None = "test-key") -> Settings:
    del env
    return Settings(_env_file=None, gemini_api_key=SecretStr(key) if key else None)


class FakeMcp:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(tools=[SimpleNamespace(name=name) for name in ALLOWED_TOOL_NAMES])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> SimpleNamespace:
        del name, arguments
        if self.fail:
            raise RuntimeError("sidecar down")
        result = ToolResult(
            source=SourceCitation(
                artifact="quality.json",
                artifact_revision="a" * 64,
                generated_at="2026-09-16T00:00:00+00:00",
                dataset_fingerprint="b" * 64,
                dataset_version="0.1.1",
            ),
            data={"status": "fail"},
        )
        return SimpleNamespace(structured_content=result.model_dump(mode="json"))


class FakeInteractions:
    def __init__(self, final: str) -> None:
        self.final = final
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        id="call_quality",
                        name="get_quality_report",
                        model_dump=lambda: {"type": "function_call", "id": "call_quality"},
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(steps=[], output_text=self.final)


def test_consulta_exige_herramienta_y_devuelve_cita(env, monkeypatch: pytest.MonkeyPatch) -> None:
    mcp = FakeMcp()
    interactions = FakeInteractions(
        '{"answer":"La compuerta esta en fail.", "citation_call_ids":["call_quality"]}'
    )
    audits: list[Any] = []

    @asynccontextmanager
    async def fake_session(_: str):
        yield mcp

    monkeypatch.setattr(service, "open_mcp_client", fake_session)
    monkeypatch.setattr(
        service, "gemini_client", lambda _: SimpleNamespace(interactions=interactions)
    )
    monkeypatch.setattr(
        service, "record_tool_call", lambda request_id, call: audits.append((request_id, call))
    )

    result = asyncio.run(service.answer("Cual es el estado?", settings(env)))

    assert result.answer == "La compuerta esta en fail."
    assert result.tool_calls[0].status == "success"
    assert result.citations[0].artifact_revision == "a" * 64
    assert result.tool_calls[0].citation is not None
    assert result.tool_calls[0].citation.dataset_version == "0.1.1"
    assert result.citations[0].dataset_version == "0.1.1"
    assert len(audits) == 1
    config = interactions.calls[0]["generation_config"]
    assert config["tool_choice"] == "any"
    assert interactions.calls[0]["response_format"]["mime_type"] == "application/json"
    assert interactions.calls[0]["store"] is False
    assert "source.dataset_version" in service.SYSTEM_INSTRUCTIONS
    tool_result = interactions.calls[1]["input"][-1]["result"][0]["text"]
    assert '"dataset_version": "0.1.1"' in tool_result


def test_sin_evidencia_no_devuelve_cifras(env, monkeypatch: pytest.MonkeyPatch) -> None:
    mcp = FakeMcp(fail=True)
    interactions = FakeInteractions('{"answer":"Hay 838 imagenes.", "citation_call_ids":[]}')

    @asynccontextmanager
    async def fake_session(_: str):
        yield mcp

    monkeypatch.setattr(service, "open_mcp_client", fake_session)
    monkeypatch.setattr(
        service, "gemini_client", lambda _: SimpleNamespace(interactions=interactions)
    )
    monkeypatch.setattr(service, "record_tool_call", lambda request_id, call: None)

    result = asyncio.run(service.answer("Cuantas imagenes hay?", settings(env)))

    assert result.citations == []
    assert result.tool_calls[0].status == "failed"
    assert not any(character.isdigit() for character in result.answer)


def test_sin_clave_no_intenta_abrir_el_sidecar(env) -> None:
    with pytest.raises(service.CopilotUnavailableError, match="GEMINI_API_KEY"):
        asyncio.run(service.answer("hola", settings(env, key=None)))


def test_endpoint_explica_cuando_falta_la_clave(env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(copilot, "get_settings", lambda: settings(env, key=None))

    response = TestClient(create_app()).post("/api/copilot/chat", json={"question": "hola"})

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_auditoria_no_declara_campos_de_conversacion_ni_payload() -> None:
    columns = set(CopilotToolCall.__table__.columns.keys())

    assert {"request_id", "call_id", "tool_name", "arguments", "source_revision"} <= columns
    assert {"question", "answer", "payload", "api_key"}.isdisjoint(columns)
