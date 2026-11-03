"""API de inferencia y envio a la cola de anotacion (F4 T24, criterio 6.5; contratos §4)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import test_inference as ti
from p3.inference import api, records, service


class FakeAnnotation:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes]] = []

    def upload(self, filename: str, content_type: str, data: bytes) -> dict[str, object]:
        self.uploads.append((filename, content_type, data))
        return {"id": 77, "status": "pending", "originalName": filename}


@pytest.fixture
def entorno(tmp_path: Path):
    store = ti.FakeStore()
    ti._publicar(store, tmp_path, {"1.0.0": 1}, activa="1.0.0")
    inference = service.InferenceService(store, bucket=ti.BUCKET, prefix=ti.PREFIX)
    engine = create_engine(f"sqlite:///{tmp_path / 'inf.db'}")
    records.create_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    annotation = FakeAnnotation()

    def session() -> Iterator[Session]:
        with factory.begin() as s:
            yield s

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_service] = lambda: inference
    app.dependency_overrides[api.get_session] = session
    app.dependency_overrides[api.get_annotation] = lambda: annotation
    return TestClient(app), factory, annotation, store, tmp_path


def _post(client: TestClient, data: bytes, tipo: str = "image/png", **form: str):
    return client.post("/api/p3/inference", files={"file": ("foto.png", data, tipo)}, data=form)


def test_predice_y_guarda_la_inferencia(entorno) -> None:
    client, factory, *_ = entorno
    response = _post(client, ti._png())
    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "1.0.0"
    assert abs(sum(body["probabilities"].values()) - 1) < 1e-4
    assert body["predicted_class"] in ti.CLASES
    with factory() as session:
        stored = session.get(records.Inference, body["inference_id"])
        assert stored is not None
        assert stored.predicted_class == body["predicted_class"]
        assert stored.model_sha256 == body["model_sha256"]
        assert stored.image == ti._png()


def test_el_recorte_opcional_llega_como_json(entorno) -> None:
    client, *_ = entorno
    ok = _post(client, ti._png((60, 40)), bbox_xywh=json.dumps([10, 5, 20, 20]))
    assert ok.status_code == 200
    fuera = _post(client, ti._png((60, 40)), bbox_xywh=json.dumps([50, 0, 20, 10]))
    assert fuera.status_code == 422
    malo = _post(client, ti._png(), bbox_xywh="no es json")
    assert malo.status_code == 422


def test_tipo_invalido_415_y_archivo_grande_413(entorno) -> None:
    client, *_ = entorno
    assert _post(client, b"hola", "text/plain").status_code == 415
    grande = b"x" * (service.MAX_BYTES + 1)
    assert _post(client, grande, "image/jpeg").status_code == 413


def test_sin_version_activa_409(entorno) -> None:
    client, _, _, store, tmp_path = entorno
    ti._publicar(store, tmp_path, {"1.0.0": 1}, activa="1.0.0")
    body = json.loads(store.objects[(ti.BUCKET, f"{ti.PREFIX}/registry.json")])
    body["active_version"] = None
    store.put(f"{ti.PREFIX}/registry.json", json.dumps(body).encode())
    response = _post(client, ti._png())
    assert response.status_code == 409


def test_enviar_a_anotacion_sube_la_misma_imagen_a_p1(entorno) -> None:
    client, factory, annotation, *_ = entorno
    inference_id = _post(client, ti._png()).json()["inference_id"]

    response = client.post(f"/api/p3/inference/{inference_id}/send-to-annotation")

    assert response.status_code == 201
    assert response.json() == {"annotation_queue_item": {"image_id": 77, "status": "pending"}}
    assert annotation.uploads == [("foto.png", "image/png", ti._png())]
    with factory() as session:
        assert session.get(records.Inference, inference_id).annotation_image_id == 77


def test_enviar_dos_veces_no_duplica(entorno) -> None:
    client, _, annotation, *_ = entorno
    inference_id = _post(client, ti._png()).json()["inference_id"]
    client.post(f"/api/p3/inference/{inference_id}/send-to-annotation")
    otra = client.post(f"/api/p3/inference/{inference_id}/send-to-annotation")
    assert otra.status_code == 200
    assert otra.json()["annotation_queue_item"]["image_id"] == 77
    assert len(annotation.uploads) == 1


def test_enviar_una_inferencia_inexistente_404(entorno) -> None:
    client, *_ = entorno
    assert client.post("/api/p3/inference/no-existe/send-to-annotation").status_code == 404


# --- S3 no disponible: 503 con que configurar, nunca 500 ------------------------------------


def test_perfil_de_aws_inexistente_responde_503(entorno, monkeypatch: pytest.MonkeyPatch) -> None:
    from p3.inference import settings

    client, *_ = entorno
    del client.app.dependency_overrides[api.get_service]
    monkeypatch.setenv("P3_AWS_PROFILE", "perfil-que-no-existe")
    monkeypatch.delenv("P3_S3_ENDPOINT", raising=False)
    settings.get_settings.cache_clear()
    settings.get_inference_service.cache_clear()
    try:
        response = _post(client, ti._png())
    finally:
        settings.get_settings.cache_clear()
        settings.get_inference_service.cache_clear()
    assert response.status_code == 503
    assert "P3_AWS_PROFILE" in response.json()["detail"]


def test_s3_sin_credenciales_al_predecir_responde_503(entorno) -> None:
    client, _, _, store, _ = entorno

    def sin_credenciales(*_args, **_kw) -> bytes:
        raise service.StorageUnavailableError(
            "S3 sin credenciales de AWS. Configura P3_AWS_PROFILE"
        )

    store.get_bytes = sin_credenciales  # type: ignore[method-assign]
    response = _post(client, ti._png())
    assert response.status_code == 503
    assert "P3_AWS_PROFILE" in response.json()["detail"]
