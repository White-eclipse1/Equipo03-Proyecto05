"""API de versiones de modelo para la pagina Models (F7, contratos §4; criterios 5.3 y 6.4).

Vive en el servicio `p3-inference` (el que tiene acceso a S3) y el portal de P2
la reenvia. Contra el almacen falso de `test_publish`: nada toca S3 real.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from p3.registry import api
from p3.registry.publish import read_registry
from test_publish import BUCKET, PREFIX, FakeStore, checkpoint_bytes, publish


@pytest.fixture(scope="module")
def checkpoints() -> tuple[bytes, bytes]:
    return checkpoint_bytes(0), checkpoint_bytes(1)


@pytest.fixture
def store(checkpoints) -> FakeStore:
    fake = FakeStore()
    publish(fake, "0.9.0", checkpoints[1])
    publish(fake, "1.0.0", checkpoints[0], activate=True)
    return fake


def client_with(store: Any) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_models_store] = lambda: api.ModelsStore(
        store=store, bucket=BUCKET, prefix=PREFIX
    )
    return TestClient(app)


def test_lista_versiones_con_la_forma_del_contrato(store) -> None:
    body = client_with(store).get("/api/p3/models").json()
    assert body["active_version"] == "1.0.0"
    assert [m["version"] for m in body["models"]] == ["0.9.0", "1.0.0"]
    first = body["models"][0]
    assert set(first) >= {"version", "run_id", "manifest_id", "release_id", "s3", "card_uri"}
    assert set(first["s3"]) == {"uri", "version_id", "sha256", "exists"}
    assert first["s3"]["exists"] is True


def test_version_de_modelo_distinta_de_la_del_dataset(store) -> None:
    model = client_with(store).get("/api/p3/models").json()["models"][1]
    assert model["version"] == "1.0.0"
    assert model["release_id"] == "0.1.3"


def test_tarjeta_de_una_version(store) -> None:
    response = client_with(store).get("/api/p3/models/1.0.0/card")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == "# Tarjeta 1.0.0\n"


def test_tarjeta_de_version_desconocida_404(store) -> None:
    assert client_with(store).get("/api/p3/models/7.7.7/card").status_code == 404


def test_activar_cambia_la_version_activa(store) -> None:
    response = client_with(store).post("/api/p3/models/0.9.0/activate")
    assert response.status_code == 200
    assert response.json()["active_version"] == "0.9.0"
    assert read_registry(store, bucket=BUCKET, prefix=PREFIX).active_version == "0.9.0"


def test_activar_version_desconocida_404(store) -> None:
    response = client_with(store).post("/api/p3/models/7.7.7/activate")
    assert response.status_code == 404
    assert read_registry(store, bucket=BUCKET, prefix=PREFIX).active_version == "1.0.0"


def test_no_se_activa_un_objeto_inexistente_409(store) -> None:
    store.delete(BUCKET, f"{PREFIX}/0.9.0/model.pt")
    response = client_with(store).post("/api/p3/models/0.9.0/activate")
    assert response.status_code == 409
    assert "no existe" in response.json()["detail"]
    assert read_registry(store, bucket=BUCKET, prefix=PREFIX).active_version == "1.0.0"


# --- Descarga de pesos (contrato C2, F13; criterio 6.4) ----------------------------------


def test_descarga_sirve_el_model_pt_publicado_con_su_sha256(store, checkpoints) -> None:
    response = client_with(store).get("/api/p3/models/1.0.0/download")
    assert response.status_code == 200
    assert response.content == checkpoints[0]
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == (
        'attachment; filename="clasificador-1.0.0-model.pt"'
    )
    registered = next(
        e
        for e in read_registry(store, bucket=BUCKET, prefix=PREFIX).versions
        if e.version == "1.0.0"
    ).sha256
    assert response.headers["x-model-sha256"] == registered
    assert hashlib.sha256(response.content).hexdigest() == registered


def test_descarga_de_una_version_anterior(store, checkpoints) -> None:
    response = client_with(store).get("/api/p3/models/0.9.0/download")
    assert response.status_code == 200
    assert response.content == checkpoints[1]


def test_descarga_de_version_no_publicada_404(store) -> None:
    assert client_with(store).get("/api/p3/models/7.7.7/download").status_code == 404


def test_descarga_de_objeto_inexistente_409(store) -> None:
    store.delete(BUCKET, f"{PREFIX}/0.9.0/model.pt")
    response = client_with(store).get("/api/p3/models/0.9.0/download")
    assert response.status_code == 409
    assert "no existe" in response.json()["detail"]


def test_descarga_con_sha256_distinto_409_y_no_sirve_bytes(store) -> None:
    store.corrupt_on_get.add(f"{PREFIX}/1.0.0/model.pt")
    response = client_with(store).get("/api/p3/models/1.0.0/download")
    assert response.status_code == 409
    assert "SHA-256" in response.json()["detail"]
    assert "content-disposition" not in response.headers


def test_descarga_si_la_version_actual_no_es_la_registrada_409(store) -> None:
    from p3.registry.s3 import VersionMismatchError

    class Sobrescrito:
        def head(self, bucket: str, key: str) -> dict[str, Any] | None:
            return store.head(bucket, key)

        def get_bytes(self, bucket: str, key: str, version_id: str | None = None) -> bytes:
            if key.endswith("model.pt"):
                raise VersionMismatchError(f"s3://{bucket}/{key} no es la version registrada")
            return store.get_bytes(bucket, key, version_id)

    response = client_with(Sobrescrito()).get("/api/p3/models/1.0.0/download")
    assert response.status_code == 409


@pytest.mark.parametrize("version", ["1.0", "../1.0.0", "1.0.0;rm"])
def test_descarga_con_version_invalida_no_llega_a_s3(store, version: str) -> None:
    assert client_with(store).get(f"/api/p3/models/{version}/download").status_code in (404, 422)


@pytest.mark.parametrize("version", ["1.0", "../1.0.0", "1.0.0;rm"])
def test_version_con_formato_invalido_422(store, version: str) -> None:
    response = client_with(store).post(f"/api/p3/models/{version}/activate")
    assert response.status_code in (404, 422)
    assert read_registry(store, bucket=BUCKET, prefix=PREFIX).active_version == "1.0.0"


# --- S3 no disponible: 503 con motivo, nunca 500 (hallazgo 3 del ensayo de F10) -----------


class BrokenStore:
    """Almacen cuyo S3 falla como falla boto3 sin credenciales o sin red."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def head(self, bucket: str, key: str) -> dict[str, Any] | None:
        raise self.error

    def get_bytes(self, bucket: str, key: str, version_id: str | None = None) -> bytes:
        raise self.error

    def put_bytes(self, bucket: str, key: str, data: bytes) -> str | None:  # pragma: no cover
        raise AssertionError("no debe escribir")


def s3_errors() -> list[Exception]:
    from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

    return [
        NoCredentialsError(),
        EndpointConnectionError(endpoint_url="https://s3.amazonaws.com"),
        ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "HeadObject"),
    ]


@pytest.mark.parametrize("error", s3_errors(), ids=["sin-credenciales", "sin-red", "denegado"])
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/p3/models"),
        ("GET", "/api/p3/models/1.0.0/card"),
        ("POST", "/api/p3/models/1.0.0/activate"),
        ("GET", "/api/p3/models/1.0.0/download"),
    ],
)
def test_s3_no_disponible_responde_503_con_motivo(error, method: str, path: str) -> None:
    client = TestClient(client_with(BrokenStore(error)).app, raise_server_exceptions=False)
    response = client.request(method, path)
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "S3" in detail and "P3_AWS_PROFILE" in detail


def test_sin_credenciales_el_detalle_lo_dice() -> None:
    from botocore.exceptions import NoCredentialsError

    client = TestClient(client_with(BrokenStore(NoCredentialsError())).app)
    assert "credenciales" in client.get("/api/p3/models").json()["detail"]


def test_perfil_de_aws_inexistente_responde_503(monkeypatch, tmp_path) -> None:
    from p3.inference import settings

    empty = tmp_path / "vacio"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(empty))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(empty))
    monkeypatch.setenv("P3_AWS_PROFILE", "perfil-que-no-existe")
    monkeypatch.delenv("P3_S3_ENDPOINT", raising=False)
    settings.get_settings.cache_clear()
    try:
        app = FastAPI()
        app.include_router(api.router)
        response = TestClient(app, raise_server_exceptions=False).get("/api/p3/models")
    finally:
        settings.get_settings.cache_clear()
    assert response.status_code == 503
    assert "perfil-que-no-existe" in response.json()["detail"]
