"""`up.py` avisa como levantar P1 si no responde (F13, criterio 6.5 de Proyecto 3).

"Enviar a la cola de anotacion" sube la imagen a P1; sin P1 arriba responde 502.
Al terminar, `up.py` revisa P1 y, si no responde, imprime los comandos del README.
"""

from __future__ import annotations

import http.server
import importlib.util
import socket
import threading
from pathlib import Path

UP = Path(__file__).resolve().parents[1] / "scripts" / "up.py"


def _up():
    spec = importlib.util.spec_from_file_location("up_script", UP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_sin_p1_da_los_comandos_para_levantarlo() -> None:
    url = f"http://127.0.0.1:{_free_port()}"
    hint = _up().p1_hint(url)
    assert hint is not None
    assert url in hint
    assert "cd ../Proyecto1" in hint and "npm run db:migrate" in hint and "npm run dev:api" in hint


class _P1(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"[]")

    def log_message(self, *args: object) -> None:
        del args


def test_con_p1_arriba_no_hay_aviso() -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _P1)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert _up().p1_hint(f"http://127.0.0.1:{server.server_port}") is None
    finally:
        server.shutdown()
