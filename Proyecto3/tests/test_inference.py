"""Servicio de inferencia con el paquete de la version activa (F4 T24, criterios 6.5 y M4).

El almacen de objetos es un falso en memoria con la misma interfaz que S3: las
pruebas nunca tocan el bucket real.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
import torch
from PIL import Image

from p3.data.transforms import build_eval_transform
from p3.inference import registry, service
from p3.model.build import build_model, save_checkpoint

BUCKET = "bucket-de-prueba"
PREFIX = "models/clasificador"
CLASES = ["cat", "dog", "person"]


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.reads: list[str] = []

    def put(self, key: str, data: bytes) -> None:
        self.objects[(BUCKET, key)] = data

    def get_bytes(self, bucket: str, key: str, version_id: str | None = None) -> bytes:
        self.reads.append(key)
        try:
            return self.objects[(bucket, key)]
        except KeyError as error:
            raise service.ModelUnavailableError(f"no existe s3://{bucket}/{key}") from error


def _checkpoint_bytes(tmp_path: Path, seed: int, image_size: int = 32) -> bytes:
    torch.manual_seed(seed)
    model = build_model(num_classes=3, hidden_layers=[8], dropout=0.0, pretrained=False)
    path = tmp_path / f"m{seed}.pt"
    save_checkpoint(
        path,
        model,
        class_names=CLASES,
        hidden_layers=[8],
        dropout=0.0,
        preprocessing={"image_size": image_size, "resize": "resize_to_square"},
    )
    return path.read_bytes()


def _publicar(store: FakeStore, tmp_path: Path, versiones: dict[str, int], activa: str) -> None:
    entries = []
    for version, seed in versiones.items():
        data = _checkpoint_bytes(tmp_path, seed)
        key = f"{PREFIX}/{version}/model.pt"
        store.put(key, data)
        entries.append(
            {
                "version": version,
                "run_id": f"run-{version}",
                "manifest_id": "m-0.1.3-s42-1",
                "key": key,
                "sha256": hashlib.sha256(data).hexdigest(),
                "s3_version_id": None,
            }
        )
    body = {"schema_version": 1, "active_version": activa, "versions": entries}
    store.put(f"{PREFIX}/registry.json", json.dumps(body).encode())


def _png(size=(60, 40), color=(200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def svc(tmp_path: Path) -> tuple[service.InferenceService, FakeStore]:
    store = FakeStore()
    _publicar(store, tmp_path, {"1.0.0": 1, "1.1.0": 2}, activa="1.0.0")
    return service.InferenceService(store, bucket=BUCKET, prefix=PREFIX), store


def test_el_registro_se_valida() -> None:
    with pytest.raises(ValueError, match="active_version"):
        registry.ModelRegistry.model_validate(
            {"schema_version": 1, "active_version": "9.9.9", "versions": []}
        )


def test_predice_con_la_version_activa_y_las_probabilidades_suman_1(svc) -> None:
    inference, _ = svc
    result = inference.predict(_png(), "image/png")
    assert result.model_version == "1.0.0"
    assert set(result.probabilities) == set(CLASES)
    assert abs(sum(result.probabilities.values()) - 1) < 1e-4
    assert result.predicted_class == max(result.probabilities, key=result.probabilities.get)


def test_usa_los_pesos_descargados_y_no_reglas_fijas(svc, tmp_path: Path) -> None:
    inference, store = svc
    result = inference.predict(_png(), "image/png")
    # Mismo calculo a mano con el checkpoint publicado: mismas probabilidades.
    from p3.model.build import load_checkpoint

    path = tmp_path / "descargado.pt"
    path.write_bytes(store.objects[(BUCKET, f"{PREFIX}/1.0.0/model.pt")])
    model, _ = load_checkpoint(path)
    x = build_eval_transform(32)(Image.open(io.BytesIO(_png())).convert("RGB")).unsqueeze(0)
    with torch.no_grad():
        esperado = torch.softmax(model(x), dim=1)[0].tolist()
    assert [result.probabilities[c] for c in CLASES] == pytest.approx(esperado, abs=1e-6)


def test_cambiar_la_version_activa_cambia_el_modelo_cargado(svc, tmp_path: Path) -> None:
    inference, store = svc
    antes = inference.predict(_png(), "image/png")
    _publicar(store, tmp_path, {"1.0.0": 1, "1.1.0": 2}, activa="1.1.0")
    despues = inference.predict(_png(), "image/png")
    assert (antes.model_version, despues.model_version) == ("1.0.0", "1.1.0")
    assert antes.model_sha256 != despues.model_sha256
    assert antes.probabilities != despues.probabilities


def test_el_paquete_se_cachea_por_version(svc) -> None:
    inference, store = svc
    inference.predict(_png(), "image/png")
    inference.predict(_png(), "image/png")
    assert store.reads.count(f"{PREFIX}/1.0.0/model.pt") == 1


def test_un_sha256_distinto_al_registro_se_rechaza(svc) -> None:
    inference, store = svc
    store.put(f"{PREFIX}/1.0.0/model.pt", b"pesos alterados")
    with pytest.raises(service.ModelIntegrityError, match="SHA-256"):
        inference.predict(_png(), "image/png")


@pytest.mark.parametrize("tipo", ["text/plain", "application/pdf", "image/gif"])
def test_tipos_no_imagen_se_rechazan(svc, tipo) -> None:
    inference, _ = svc
    with pytest.raises(service.UnsupportedMediaError):
        inference.predict(_png(), tipo)


def test_bytes_que_no_son_imagen_se_rechazan(svc) -> None:
    inference, _ = svc
    with pytest.raises(service.UnsupportedMediaError):
        inference.predict(b"no soy una imagen", "image/png")


def test_archivos_mayores_al_limite_se_rechazan(svc) -> None:
    inference, _ = svc
    with pytest.raises(service.PayloadTooLargeError):
        inference.predict(b"x" * (service.MAX_BYTES + 1), "image/jpeg")


def test_el_recorte_opcional_se_aplica_antes_de_predecir(svc) -> None:
    inference, _ = svc
    imagen = Image.new("RGB", (80, 40), (255, 255, 255))
    imagen.paste((0, 0, 255), (40, 0, 80, 40))
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    solo_azul = inference.predict(buffer.getvalue(), "image/png", bbox_xywh=(40, 0, 40, 40))
    azul = inference.predict(_png((40, 40), (0, 0, 255)), "image/png")
    assert solo_azul.probabilities == pytest.approx(azul.probabilities, abs=1e-5)


def test_una_caja_fuera_de_la_imagen_se_rechaza(svc) -> None:
    inference, _ = svc
    with pytest.raises(service.InvalidBoxError):
        inference.predict(_png((60, 40)), "image/png", bbox_xywh=(50, 0, 20, 10))


def test_una_foto_rotada_por_exif_llega_al_modelo_ya_girada(svc, monkeypatch) -> None:
    """Fotos de celular (F2): guardada acostada con orientacion 6, se ve de pie."""
    tamanos: list[tuple[int, int]] = []
    original = service.build_eval_transform

    def espia(image_size: int):
        transform = original(image_size)

        def registrar(image):
            tamanos.append(image.size)
            return transform(image)

        return registrar

    monkeypatch.setattr(service, "build_eval_transform", espia)
    acostada = Image.new("RGB", (60, 40), (10, 200, 10))
    exif = acostada.getexif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    acostada.save(buffer, format="JPEG", exif=exif.tobytes())

    inference, _ = svc
    inference.predict(buffer.getvalue(), "image/jpeg")

    assert tamanos == [(40, 60)]


def test_un_png_declarado_como_jpeg_se_rechaza_con_415(svc) -> None:
    inference, _ = svc
    with pytest.raises(service.UnsupportedMediaError) as error:
        inference.predict(_png(), "image/jpeg")
    assert error.value.status_code == 415


def test_el_cache_es_por_version_y_sha256_no_solo_por_version(svc, tmp_path: Path) -> None:
    inference, store = svc
    antes = inference.predict(_png(), "image/png")

    # Misma version 1.0.0, pero otro objeto y otro sha256 en el registro.
    nuevo = _checkpoint_bytes(tmp_path, seed=99)
    store.put(f"{PREFIX}/1.0.0/model.pt", nuevo)
    body = json.loads(store.objects[(BUCKET, f"{PREFIX}/registry.json")])
    for entry in body["versions"]:
        if entry["version"] == "1.0.0":
            entry["sha256"] = hashlib.sha256(nuevo).hexdigest()
    store.put(f"{PREFIX}/registry.json", json.dumps(body).encode())

    despues = inference.predict(_png(), "image/png")

    assert despues.model_version == antes.model_version == "1.0.0"
    assert despues.model_sha256 == hashlib.sha256(nuevo).hexdigest() != antes.model_sha256
    assert despues.probabilities != antes.probabilities
