"""Sidecar MCP interno: expone solo evidencia de lectura de los reportes."""

from __future__ import annotations

from starlette.responses import JSONResponse

from dataset_quality.copilot import tools


def create_server():
    """Declara el conjunto cerrado de herramientas que ve cualquier cliente MCP."""
    from mcp.server import MCPServer

    server = MCPServer(
        "Dataset Quality Copilot", instructions="Solo lectura de reportes validados."
    )

    @server.tool()
    def get_quality_report() -> dict:
        """Devuelve el veredicto y checks de ``quality.json`` sin recalcularlos."""
        return tools.get_quality_report().model_dump(mode="json")

    @server.tool()
    def get_failed_checks(severity: str = "all") -> dict:
        """Devuelve solo reglas fallidas, opcionalmente filtradas por severidad."""
        return tools.get_failed_checks(severity=severity).model_dump(mode="json")

    @server.tool()
    def get_class_distribution() -> dict:
        """Devuelve imagenes y cajas por clase desde ``stats.json`` validado."""
        return tools.get_class_distribution().model_dump(mode="json")

    @server.tool()
    def get_split_report() -> dict:
        """Devuelve el resumen reproducible de splits, no todas las asignaciones."""
        return tools.get_split_report().model_dump(mode="json")

    @server.tool()
    def list_versions(limit: int = 10) -> dict:
        """Lista las versiones mas recientes del manifiesto inmutable."""
        return tools.list_versions(limit=limit).model_dump(mode="json")

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return server


def create_app():
    """Crea la app ASGI raiz del SDK MCP con healthcheck propio."""
    # Se importa al crear el proceso, no al importar la API principal: asi una
    # instalacion sin extras de Copilot conserva las pantallas existentes.
    server = create_server()
    # El SDK crea el task group de sesiones en el lifespan de esta aplicacion.
    # Montarla bajo FastAPI evita ejecutar ese lifespan y rompe cada llamada.
    return server.streamable_http_app(streamable_http_path="/mcp")


app = create_app()


def run() -> None:
    """Arranca el transporte HTTP con el ciclo de vida oficial del SDK MCP."""
    # El ejecutor del SDK crea y mantiene el task group de sesiones. Uvicorn
    # sobre un app importado no lo conservaba de forma fiable con MCP 2.x.
    create_server().run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8001,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":  # pragma: no cover - se prueba mediante Compose
    run()
