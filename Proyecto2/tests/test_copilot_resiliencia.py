"""El Copilot bajo las tres condiciones en las que un asistente miente.

`test_copilot_service.py` prueba el camino feliz y `test_copilot_tools.py` el
contrato de las herramientas. Aqui se cubre lo otro: que pasa cuando la
evidencia cambia debajo, cuando la pregunta no se puede responder con las
herramientas que hay, y cuando el proveedor se cae.

Las tres tienen el mismo criterio de exito, y no es "que responda bien": es que
NO invente. Un asistente que contesta con una cifra plausible cuando no pudo
leer nada es peor que uno que se calla, porque el usuario no tiene forma de
distinguir esa respuesta de una buena.

Ninguna prueba toca la red: el proveedor y el sidecar MCP son dobles.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dataset_quality.api import artifacts
from dataset_quality.api import copilot as copilot_api
from dataset_quality.copilot import service, tools
from dataset_quality.copilot.tools import ALLOWED_TOOL_NAMES
from dataset_quality.main import create_app
from dataset_quality.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"

# Una clave inventada, con una forma reconocible: si alguna vez se filtrara a
# una respuesta HTTP, la prueba que la busca la encontraria sin ambiguedad.
CLAVE_FALSA = "AIza-CLAVE-QUE-NO-DEBE-SALIR-NUNCA"


def ajustes(clave: str | None = CLAVE_FALSA) -> Settings:
    return Settings(_env_file=None, gemini_api_key=SecretStr(clave) if clave else None)


@pytest.fixture
def reportes(env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Artefactos propios en un directorio temporal.

    No se copian los `reports/` del repositorio a proposito: si lo hicieran,
    regenerar el pipeline cambiaria las cifras y estas pruebas empezarian a
    fallar por algo que no tiene nada que ver con el Copilot.

    Pide `env` (de `conftest.py`) porque construir `Settings` exige el entorno
    completo: sin el, estas pruebas fallarian por una credencial ausente y no
    por lo que vienen a comprobar.
    """
    del env
    for nombre in ("quality.json", "splits.json", "versions.json"):
        shutil.copy(FIXTURES / nombre, tmp_path / nombre)

    # `stats.json` no tiene fixture propia; se construye el minimo que valida
    # contra `AnalysisArtifact` reutilizando los checks de quality.json.
    quality = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    (tmp_path / "stats.json").write_text(
        json.dumps(
            {
                "stats": {
                    "totals": quality["totals"],
                    "images_per_class": {"person": 2, "car": 1},
                    "boxes_per_class": {"person": 3, "car": 1},
                    "annotations_per_image": 1.3333333333333333,
                    "images_without_annotations": 0,
                    "mean_box_area_ratio": 0.2,
                    "median_box_area_ratio": 0.2,
                    "p90_box_area_ratio": 0.3,
                },
                "checks": quality["checks"],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(artifacts, "REPORTS", tmp_path)
    monkeypatch.setattr(
        artifacts,
        "ARTIFACTS",
        {
            nombre: artifacts.Artifact(
                item.name, tmp_path / item.path.name, item.model, item.produced_by
            )
            for nombre, item in artifacts.ARTIFACTS.items()
        },
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Dobles del proveedor y del sidecar
# ---------------------------------------------------------------------------
class McpReal:
    """Sidecar que ejecuta las herramientas DE VERDAD sobre los artefactos.

    Los dobles de `test_copilot_service.py` devuelven una cita fija, que es lo
    correcto para probar la orquestacion. Aqui hace falta lo contrario: que la
    cita salga de leer el archivo, porque lo que se prueba es justamente que
    siga al archivo cuando el archivo cambia.
    """

    def __init__(self) -> None:
        self.llamadas: list[str] = []

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(tools=[SimpleNamespace(name=n) for n in ALLOWED_TOOL_NAMES])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> SimpleNamespace:
        self.llamadas.append(name)
        resultado = tools.execute_tool(name, arguments)
        return SimpleNamespace(structured_content=resultado.model_dump(mode="json"))


class ProveedorGuionizado:
    """Gemini falso: primero pide una herramienta, luego entrega el JSON final."""

    def __init__(self, final: str, *, herramienta: str = "get_quality_report") -> None:
        self.final = final
        self.herramienta = herramienta
        self.llamadas: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.llamadas.append(kwargs)
        if len(self.llamadas) == 1:
            return SimpleNamespace(
                steps=[
                    SimpleNamespace(
                        type="function_call",
                        id="call_1",
                        name=self.herramienta,
                        arguments={},
                        model_dump=lambda: {"type": "function_call", "id": "call_1"},
                    )
                ],
                output_text="",
            )
        return SimpleNamespace(steps=[], output_text=self.final)


class ProveedorCaido:
    """Gemini que no responde. Es el fallo mas probable en produccion."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.llamadas = 0

    def create(self, **kwargs: Any) -> SimpleNamespace:
        del kwargs
        self.llamadas += 1
        raise self.error


def montar(monkeypatch: pytest.MonkeyPatch, mcp: Any, proveedor: Any) -> list[Any]:
    """Enchufa los dobles y devuelve la lista donde cae la auditoria."""
    auditoria: list[Any] = []

    @asynccontextmanager
    async def sesion(_: str):
        yield mcp

    monkeypatch.setattr(service, "open_mcp_client", sesion)
    monkeypatch.setattr(service, "gemini_client", lambda _: SimpleNamespace(interactions=proveedor))
    monkeypatch.setattr(
        service, "record_tool_call", lambda request_id, call: auditoria.append(call)
    )
    return auditoria


# ---------------------------------------------------------------------------
# 1. Fuente modificada
# ---------------------------------------------------------------------------
def test_la_cita_cambia_cuando_cambia_el_archivo(reportes: Path) -> None:
    """`artifact_revision` es el sha256 del archivo servido, no un valor fijo.

    Si esta revision se calculara una vez y se cacheara, el Copilot seguiria
    citando un reporte que ya no existe — y la cita, que es toda la garantia
    que ofrece, dejaria de valer nada.
    """
    antes = tools.get_quality_report().source

    quality = json.loads((reportes / "quality.json").read_text(encoding="utf-8"))
    quality["checks"][0]["observed"] = 0.5
    quality["checks"][0]["status"] = "fail"
    (reportes / "quality.json").write_text(json.dumps(quality), encoding="utf-8")

    despues = tools.get_quality_report().source

    assert antes.artifact_revision != despues.artifact_revision
    assert len(despues.artifact_revision) == 64


def test_la_version_citada_sigue_a_la_huella_del_reporte(reportes: Path) -> None:
    """La version solo se atribuye si la huella coincide con una publicada.

    Un reporte generado sobre un dataset que nunca se publico no puede
    presentarse como `v0.1.0`. Se cambia la huella a una desconocida y la
    version tiene que desaparecer de la cita, no quedarse pegada de la lectura
    anterior.
    """
    con_version = tools.get_quality_report().source
    assert con_version.dataset_version == "0.1.0"

    quality = json.loads((reportes / "quality.json").read_text(encoding="utf-8"))
    quality["dataset_fingerprint"] = "f" * 64
    (reportes / "quality.json").write_text(json.dumps(quality), encoding="utf-8")

    sin_version = tools.get_quality_report().source

    assert sin_version.dataset_fingerprint == "f" * 64
    assert sin_version.dataset_version is None


def test_la_respuesta_cita_la_version_del_reporte_que_leyo(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """De punta a punta: el archivo cambia y la traza lo refleja.

    Es la prueba que pidio la retroalimentacion: una traza con su tool call y
    su cita de version, comprobada contra una fuente que se modifico en medio.
    """
    mcp = McpReal()
    proveedor = ProveedorGuionizado(
        '{"answer":"La compuerta esta en pass.","citation_call_ids":["call_1"]}'
    )
    montar(monkeypatch, mcp, proveedor)

    primera = asyncio.run(service.answer("Como esta la compuerta?", ajustes()))

    assert mcp.llamadas == ["get_quality_report"]
    assert primera.tool_calls[0].status == "success"
    assert primera.citations[0].dataset_version == "0.1.0"
    revision_inicial = primera.citations[0].artifact_revision

    # Ahora el reporte pasa a describir un dataset que no esta publicado.
    quality = json.loads((reportes / "quality.json").read_text(encoding="utf-8"))
    quality["dataset_fingerprint"] = "e" * 64
    (reportes / "quality.json").write_text(json.dumps(quality), encoding="utf-8")

    # Proveedor nuevo para el segundo turno: el guion del doble avanza con cada
    # `create`, y reutilizarlo saltaria directo a la respuesta final sin pedir
    # ninguna herramienta. El Copilot es stateless, asi que dos preguntas son
    # dos conversaciones distintas tambien aqui.
    segundo_proveedor = ProveedorGuionizado(
        '{"answer":"La compuerta esta en pass.","citation_call_ids":["call_1"]}'
    )
    montar(monkeypatch, mcp, segundo_proveedor)

    segunda = asyncio.run(service.answer("Como esta la compuerta?", ajustes()))

    assert segunda.citations[0].artifact_revision != revision_inicial
    assert segunda.citations[0].dataset_version is None


def test_un_reporte_corrupto_no_se_sirve_como_evidencia(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el archivo dejo de cumplir su contrato, la herramienta falla.

    El modo de fallo que se evita: servir el JSON tal cual, que el modelo lea
    un campo que ya no significa lo mismo, y que la respuesta salga con una
    cita que parece impecable.
    """
    (reportes / "quality.json").write_text('{"status": "pass"}', encoding="utf-8")

    mcp = McpReal()
    proveedor = ProveedorGuionizado(
        '{"answer":"Todo en orden, 3 imagenes.","citation_call_ids":["call_1"]}'
    )
    montar(monkeypatch, mcp, proveedor)

    resultado = asyncio.run(service.answer("Como esta la compuerta?", ajustes()))

    assert resultado.tool_calls[0].status == "failed"
    assert resultado.tool_calls[0].error == "tool_unavailable"
    assert resultado.citations == []
    assert not any(caracter.isdigit() for caracter in resultado.answer)


# ---------------------------------------------------------------------------
# 2. Pregunta que las herramientas no pueden responder
# ---------------------------------------------------------------------------
def test_pregunta_no_respondible_no_se_contesta_con_cifras(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ninguna de las cinco herramientas sabe cuantos perros hay en el split 4.

    El modelo, aun asi, devuelve una respuesta con una cifra y sin citar nada.
    Ese es el caso interesante: la orquestacion tiene que descartarla, porque
    una cifra sin cita es exactamente lo que el sistema promete no emitir.
    """
    mcp = McpReal()
    proveedor = ProveedorGuionizado(
        '{"answer":"Hay 412 perros en el cuarto split.","citation_call_ids":[]}'
    )
    montar(monkeypatch, mcp, proveedor)

    resultado = asyncio.run(service.answer("Cuantos perros hay en el cuarto split?", ajustes()))

    # La herramienta SI se ejecuto y quedo auditada: la traza no se pierde.
    assert resultado.tool_calls[0].status == "success"
    # Pero la respuesta inventada no sale.
    assert "412" not in resultado.answer
    assert resultado.citations == []
    assert "no puedo dar cifras" in resultado.answer


def test_citar_una_llamada_inexistente_equivale_a_no_citar(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inventar el ID de la cita no es una forma de colar una cifra."""
    mcp = McpReal()
    proveedor = ProveedorGuionizado(
        '{"answer":"Son 3 imagenes.","citation_call_ids":["call_que_no_existe"]}'
    )
    montar(monkeypatch, mcp, proveedor)

    resultado = asyncio.run(service.answer("Cuantas imagenes hay?", ajustes()))

    assert resultado.citations == []
    assert "3" not in resultado.answer


def test_una_pregunta_fuera_de_alcance_no_dispara_herramientas_no_permitidas(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el modelo pide una herramienta que no existe, se rechaza y se audita.

    `borrar_dataset` no esta en el allowlist. Lo que no puede pasar es que el
    intento se descarte en silencio: queda registrado como llamada fallida.
    """
    mcp = McpReal()
    proveedor = ProveedorGuionizado(
        '{"answer":"Listo.","citation_call_ids":["call_1"]}',
        herramienta="borrar_dataset",
    )
    auditoria = montar(monkeypatch, mcp, proveedor)

    resultado = asyncio.run(service.answer("Borra el dataset", ajustes()))

    assert mcp.llamadas == [], "una herramienta fuera del allowlist no llega al sidecar"
    assert resultado.tool_calls[0].status == "failed"
    assert resultado.tool_calls[0].error == "tool_not_allowed"
    assert [llamada.name for llamada in auditoria] == ["borrar_dataset"]
    assert resultado.citations == []


# ---------------------------------------------------------------------------
# 3. Proveedor caido
# ---------------------------------------------------------------------------
def test_proveedor_caido_da_un_error_controlado(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un 503 de Gemini se traduce a `CopilotProviderError`, no a un rastro."""
    proveedor = ProveedorCaido(RuntimeError("503 Service Unavailable from generativelanguage"))
    montar(monkeypatch, McpReal(), proveedor)

    with pytest.raises(service.CopilotProviderError) as error:
        asyncio.run(service.answer("Como esta la compuerta?", ajustes()))

    assert proveedor.llamadas == 1
    assert "No se pudo completar la consulta" in str(error.value)


def test_el_endpoint_devuelve_502_sin_filtrar_nada(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El mensaje al cliente no lleva la clave, ni la URL interna, ni el rastro.

    Lo que se filtra en un error es lo que nadie revisa. Se comprueba contra la
    respuesta serializada entera, no solo contra `detail`.
    """
    proveedor = ProveedorCaido(
        RuntimeError(f"401 Unauthorized: api_key={CLAVE_FALSA} host=http://mcp:9000")
    )
    montar(monkeypatch, McpReal(), proveedor)
    monkeypatch.setattr(copilot_api, "get_settings", ajustes)

    respuesta = TestClient(create_app(), raise_server_exceptions=False).post(
        "/api/copilot/chat", json={"question": "Como esta la compuerta?"}
    )

    assert respuesta.status_code == 502
    cuerpo = respuesta.text
    assert CLAVE_FALSA not in cuerpo
    assert "api_key" not in cuerpo
    assert "Traceback" not in cuerpo
    assert respuesta.json()["detail"] == "No se pudo completar la consulta del Copilot."


def test_sidecar_mcp_caido_tambien_es_un_error_controlado(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La otra mitad de "proveedor caido": el que no responde es el sidecar."""

    @asynccontextmanager
    async def sesion_rota(_: str):
        raise ConnectionRefusedError("no hay nadie escuchando en mcp:9000")
        yield  # pragma: no cover - inalcanzable, pero exige el contextmanager

    monkeypatch.setattr(service, "open_mcp_client", sesion_rota)
    monkeypatch.setattr(
        service,
        "gemini_client",
        lambda _: SimpleNamespace(interactions=ProveedorGuionizado("{}")),
    )
    monkeypatch.setattr(service, "record_tool_call", lambda request_id, call: None)

    with pytest.raises(service.CopilotProviderError):
        asyncio.run(service.answer("Como esta la compuerta?", ajustes()))


def test_un_sidecar_con_otras_herramientas_se_rechaza_antes_de_preguntar(
    reportes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el sidecar no expone exactamente las cinco, no se usa.

    Un sidecar que expone una herramienta de mas es un sidecar que no es el
    nuestro. Preguntarle igualmente seria confiar en un servidor desconocido.
    """

    class McpImpostor(McpReal):
        async def list_tools(self) -> SimpleNamespace:
            nombres = [*ALLOWED_TOOL_NAMES, "borrar_dataset"]
            return SimpleNamespace(tools=[SimpleNamespace(name=n) for n in nombres])

    proveedor = ProveedorGuionizado("{}")
    montar(monkeypatch, McpImpostor(), proveedor)

    with pytest.raises(service.CopilotUnavailableError, match="herramientas esperado"):
        asyncio.run(service.answer("Como esta la compuerta?", ajustes()))

    assert proveedor.llamadas == [], "no se le pregunta al modelo si el sidecar no es el nuestro"
