import hashlib
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from p5.detector import weights as weights_module
from p5.detector.weights import (
    WEIGHTS_SHA256,
    WEIGHTS_SIZE,
    WEIGHTS_URL,
    WeightsError,
    download_weights,
    main,
    verify_weights,
)

CONTENT = b"modelo de prueba" * 1000
CONTENT_SHA256 = hashlib.sha256(CONTENT).hexdigest()
ROOT = Path(__file__).resolve().parents[2]
REAL_WEIGHTS = os.environ.get("P5_DETECTOR_WEIGHTS")


@pytest.fixture
def server():
    state = {"body": CONTENT, "status": 200, "requests": 0, "declared_length": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"] += 1
            self.send_response(state["status"])
            length = state["declared_length"] or len(state["body"])
            self.send_header("Content-Length", str(length))
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *_args):
            pass

    http_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{http_server.server_port}/model.onnx"
    yield state
    http_server.shutdown()
    http_server.server_close()
    thread.join()


def download(server, path, **overrides):
    arguments = {
        "url": server["url"],
        "sha256": CONTENT_SHA256,
        "size": len(CONTENT),
        **overrides,
    }
    return download_weights(path, **arguments)


def folder_files(path):
    return sorted(item.name for item in path.parent.iterdir())


def test_download_writes_verified_file_and_creates_the_folder(server, tmp_path):
    path = tmp_path / "models" / "model.onnx"

    assert download(server, path) is True

    assert path.read_bytes() == CONTENT
    assert folder_files(path) == ["model.onnx"]


def test_valid_existing_file_is_not_downloaded_again(server, tmp_path):
    path = tmp_path / "model.onnx"
    path.write_bytes(CONTENT)

    assert download(server, path) is False

    assert server["requests"] == 0


def test_wrong_existing_file_is_replaced_by_a_verified_download(server, tmp_path, caplog):
    path = tmp_path / "model.onnx"
    path.write_bytes(b"archivo equivocado")

    with caplog.at_level(logging.WARNING):
        assert download(server, path) is True

    assert path.read_bytes() == CONTENT
    assert "weights_invalid" in caplog.text


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (CONTENT[:-1] + b"X", "SHA-256"),
        (CONTENT + b"X", "size"),
        (CONTENT[:-1], "size"),
    ],
)
def test_rejected_download_leaves_nothing_behind(server, tmp_path, body, message):
    server["body"] = body
    path = tmp_path / "model.onnx"

    with pytest.raises(WeightsError, match=message):
        download(server, path)

    assert folder_files(path) == []


def test_connection_closed_early_leaves_nothing_behind(server, tmp_path):
    server["body"] = CONTENT[:100]
    server["declared_length"] = len(CONTENT)
    path = tmp_path / "model.onnx"

    with pytest.raises(WeightsError):
        download(server, path)

    assert folder_files(path) == []


def test_failed_download_keeps_the_existing_file(server, tmp_path):
    server["body"] = b"contenido corrupto"
    path = tmp_path / "model.onnx"
    path.write_bytes(b"archivo anterior")

    with pytest.raises(WeightsError):
        download(server, path)

    assert path.read_bytes() == b"archivo anterior"
    assert folder_files(path) == ["model.onnx"]


def test_http_error_raises_and_logs(server, tmp_path, caplog):
    server["status"] = 404
    path = tmp_path / "model.onnx"

    with caplog.at_level(logging.ERROR), pytest.raises(WeightsError, match="404"):
        download(server, path)

    assert "weights_error" in caplog.text
    assert not path.exists()


def test_unreachable_url_raises(tmp_path):
    path = tmp_path / "model.onnx"

    with pytest.raises(WeightsError):
        download_weights(
            path,
            url="http://127.0.0.1:9/model.onnx",
            sha256=CONTENT_SHA256,
            size=len(CONTENT),
            timeout=2,
        )


def test_verify_accepts_the_expected_file(tmp_path):
    path = tmp_path / "model.onnx"
    path.write_bytes(CONTENT)

    verify_weights(path, sha256=CONTENT_SHA256, size=len(CONTENT))


@pytest.mark.parametrize(
    ("content", "sha256", "size", "message"),
    [
        (None, CONTENT_SHA256, len(CONTENT), "not found"),
        (CONTENT, CONTENT_SHA256, len(CONTENT) + 1, "size"),
        (CONTENT, "0" * 64, len(CONTENT), "SHA-256"),
    ],
)
def test_verify_rejects_a_missing_or_wrong_file(tmp_path, content, sha256, size, message):
    path = tmp_path / "model.onnx"
    if content is not None:
        path.write_bytes(content)

    with pytest.raises(WeightsError, match=message):
        verify_weights(path, sha256=sha256, size=size)


def test_published_constants_identify_the_release_artifact():
    assert WEIGHTS_URL == (
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
    )
    assert WEIGHTS_SIZE == 20219662
    assert WEIGHTS_SHA256 == "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7"


def test_provenance_doc_and_ci_use_the_same_artifact():
    provenance = (ROOT / "Proyecto5" / "docs" / "A1-02_PROCEDENCIA.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "p5-ci.yml").read_text(encoding="utf-8")

    assert WEIGHTS_SHA256 in provenance
    assert WEIGHTS_URL in provenance
    assert "python -m p5.detector.weights" in workflow


def test_cli_downloads_to_the_given_path(server, tmp_path, monkeypatch, capsys):
    path = tmp_path / "model.onnx"
    monkeypatch.setattr(weights_module, "WEIGHTS_URL", server["url"])
    monkeypatch.setattr(weights_module, "WEIGHTS_SHA256", CONTENT_SHA256)
    monkeypatch.setattr(weights_module, "WEIGHTS_SIZE", len(CONTENT))

    assert main(["--path", str(path)]) == 0

    assert path.read_bytes() == CONTENT
    assert CONTENT_SHA256 in capsys.readouterr().out


def test_cli_verify_only_never_downloads(server, tmp_path, monkeypatch, capsys):
    path = tmp_path / "model.onnx"
    monkeypatch.setattr(weights_module, "WEIGHTS_URL", server["url"])
    monkeypatch.setattr(weights_module, "WEIGHTS_SHA256", CONTENT_SHA256)
    monkeypatch.setattr(weights_module, "WEIGHTS_SIZE", len(CONTENT))

    assert main(["--path", str(path), "--verify-only"]) == 1
    assert server["requests"] == 0
    assert capsys.readouterr().out == ""

    path.write_bytes(CONTENT)
    assert main(["--path", str(path), "--verify-only"]) == 0
    assert server["requests"] == 0


@pytest.mark.skipif(not REAL_WEIGHTS, reason="P5_DETECTOR_WEIGHTS not set")
def test_real_weights_match_the_published_identity():
    verify_weights(REAL_WEIGHTS)
