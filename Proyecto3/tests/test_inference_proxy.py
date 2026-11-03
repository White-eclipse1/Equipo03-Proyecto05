"""La app de P2 reenvia `/api/p3/inference` al servicio con PyTorch (F4 T24).

El proxy solo usa la libreria estandar: la app de P2 no tiene PyTorch.
"""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.inference import proxy


class Upstream(http.server.BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[str, str, bytes]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        Upstream.received.append((self.path, self.headers.get("Content-Type", ""), body))
        status = 415 if b"text/plain" in body else 200
        payload = json.dumps({"eco": self.path, "bytes": len(body)}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        del args


@pytest.fixture
def client() -> Iterator[TestClient]:
    Upstream.received = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    app = FastAPI()
    app.include_router(proxy.router)
    app.dependency_overrides[proxy.get_upstream] = lambda: f"http://127.0.0.1:{server.server_port}"
    yield TestClient(app)
    server.shutdown()


def test_reenvia_el_multipart_tal_cual(client: TestClient) -> None:
    response = client.post(
        "/api/p3/inference", files={"file": ("a.png", b"\x89PNG datos", "image/png")}
    )
    assert response.status_code == 200
    path, content_type, body = Upstream.received[0]
    assert path == "/api/p3/inference"
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b"\x89PNG datos" in body


def test_conserva_el_codigo_de_error_del_servicio(client: TestClient) -> None:
    response = client.post("/api/p3/inference", files={"file": ("a.txt", b"hola", "text/plain")})
    assert response.status_code == 415


def test_reenvia_send_to_annotation(client: TestClient) -> None:
    response = client.post("/api/p3/inference/abc123/send-to-annotation")
    assert response.status_code == 200
    assert Upstream.received[0][0] == "/api/p3/inference/abc123/send-to-annotation"


def test_servicio_caido_da_503(client: TestClient) -> None:
    app = FastAPI()
    app.include_router(proxy.router)
    app.dependency_overrides[proxy.get_upstream] = lambda: "http://127.0.0.1:9"
    assert TestClient(app).post("/api/p3/inference", content=b"x").status_code == 503


def test_no_importa_torch() -> None:
    texto = Path(proxy.__file__).read_text(encoding="utf-8")
    assert "import torch" not in texto


class P1(http.server.BaseHTTPRequestHandler):
    body = b""
    content_type = ""

    def do_POST(self) -> None:
        P1.content_type = self.headers.get("Content-Type", "")
        P1.body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        payload = json.dumps({"data": {"id": 91, "status": "pending"}}).encode()
        self.send_response(201 if self.path == "/api/images/upload" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        del args


def test_el_cliente_de_p1_sube_al_endpoint_de_carga_con_el_campo_file() -> None:
    from p3.inference.annotation import P1Annotation

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), P1)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        item = P1Annotation(f"http://127.0.0.1:{server.server_port}").upload(
            "foto.png", "image/png", b"\x89PNG bytes"
        )
    finally:
        server.shutdown()
    assert item == {"id": 91, "status": "pending"}
    assert P1.content_type.startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="foto.png"' in P1.body
    assert b"\x89PNG bytes" in P1.body


# --- Cola de P1 caida o con error: 502 en espanol con que hacer (F13, 6.5) ---------------


def _puerto_libre() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_si_p1_no_responde_el_error_dice_como_levantarlo() -> None:
    from p3.inference.annotation import AnnotationUnavailableError, P1Annotation

    url = f"http://127.0.0.1:{_puerto_libre()}"
    with pytest.raises(AnnotationUnavailableError) as raised:
        P1Annotation(url, timeout=2).upload("foto.png", "image/png", b"x")
    message = str(raised.value)
    assert "no responde" in message
    assert url in message
    assert "P3_ANNOTATION_URL" in message
    assert "cd Proyecto1" in message and "npm run dev:api" in message


class P1ConError(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        payload = b'{"error": "boom"}'
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        del args


def test_si_p1_rechaza_la_imagen_el_error_trae_su_codigo() -> None:
    from p3.inference.annotation import AnnotationUnavailableError, P1Annotation

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), P1ConError)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(AnnotationUnavailableError) as raised:
            P1Annotation(f"http://127.0.0.1:{server.server_port}").upload(
                "foto.png", "image/png", b"x"
            )
    finally:
        server.shutdown()
    message = str(raised.value)
    assert "respondio 500" in message
    assert "npm run dev:api" not in message  # P1 si esta arriba: no hay que levantarlo
