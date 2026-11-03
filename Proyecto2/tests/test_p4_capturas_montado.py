"""El portal monta el receptor de Capturas Edge (Proyecto 4) bajo `/api/p4/capturas`."""

from __future__ import annotations

from fastapi.testclient import TestClient
from p4.capturas import api as p4_api
from p4.capturas.config import ConfigCapturas

from dataset_quality import main


def test_capturas_edge_responde_desde_el_portal() -> None:
    app = main.create_app()
    app.dependency_overrides[p4_api.obtener_config] = lambda: ConfigCapturas(P4_ALMACEN="memoria")
    client = TestClient(app)

    assert client.get("/api/p4/capturas").json() == {"items": [], "total": 0, "errores": []}
    # Sin token configurado el receptor no acepta envios: nunca queda abierto por olvido.
    respuesta = client.post("/api/p4/capturas")
    assert respuesta.status_code == 503
    assert respuesta.json()["error"] == "receptor_no_configurado"
