"""`scripts/consultar_captura.py` con una CLI de AWS falsa (sin red ni credenciales)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "consultar_captura.py"
_spec = importlib.util.spec_from_file_location("consultar_captura", SCRIPT)
consultar_captura = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = consultar_captura
_spec.loader.exec_module(consultar_captura)

CID = "edge01-20261016T103000-0001"
FOTO = b"\xff\xd8 bytes de la foto \xff\xd9"
SHA_FOTO = hashlib.sha256(FOTO).hexdigest()
EVENTO = {
    "schema_version": 1,
    "capture_id": CID,
    "captured_at": "2026-10-16T10:30:00-06:00",
    "predicted_class": "dog",
    "confidence": 0.9312,
    "device_id": "edge01",
    "model_version": "1.0.0-int8-e05.1",
    "model_sha256": "ab" * 32,
    "image_sha256": SHA_FOTO,
    "image_ref": f"capturas/{CID}.jpg",
    "region": None,
}
REGISTRO = EVENTO | {
    "received_at": "2026-10-16T16:30:04.512+00:00",
    "image_key": f"edge-capturas/fotos/{CID}.jpg",
    "image_bytes": len(FOTO),
}


@pytest.fixture(autouse=True)
def aws_falso(monkeypatch):
    """Responde como la CLI: `get-object` escribe el objeto en el archivo de destino."""

    def aws(*argumentos: str, perfil, region) -> dict:
        if argumentos[0] == "sts":
            return {"Arn": "arn:aws:iam::000000000000:user/p4-lectura"}
        llave = argumentos[argumentos.index("--key" if "--key" in argumentos else "--prefix") + 1]
        if argumentos[1] == "list-object-versions":
            return {"Versions": [{"Key": llave}]}
        destino = Path(argumentos[-1])
        if llave.endswith(".json"):
            destino.write_text(json.dumps(REGISTRO), encoding="utf-8")
            return {"VersionId": "v-registro", "LastModified": "2026-10-16T16:30:05+00:00"}
        destino.write_bytes(FOTO)
        return {"VersionId": "v-foto", "ContentLength": len(FOTO), "Metadata": {"sha256": SHA_FOTO}}

    monkeypatch.setattr(consultar_captura, "aws", aws)


def correr(monkeypatch, *extra: str) -> int:
    monkeypatch.setattr(sys, "argv", ["consultar_captura.py", CID, *extra])
    return consultar_captura.main()


def registro_local(tmp_path: Path, evento: dict, foto: bytes = FOTO) -> tuple[str, str]:
    ruta_evento, ruta_foto = tmp_path / f"{CID}.json", tmp_path / f"{CID}.jpg"
    ruta_evento.write_text(json.dumps(evento), encoding="utf-8")
    ruta_foto.write_bytes(foto)
    return str(ruta_evento), str(ruta_foto)


def test_sin_registro_local_solo_consulta_s3(monkeypatch, capsys):
    assert correr(monkeypatch) == 0
    salida = capsys.readouterr().out
    assert "Resultado: OK" in salida
    assert "6. Contra el registro local" not in salida


def test_registro_local_igual_aunque_traiga_campos_propios(monkeypatch, capsys, tmp_path):
    # El dispositivo guarda campos que no manda (estado, width...): no se comparan.
    local = EVENTO | {"estado": "enviada", "width": 1920, "height": 1080}
    evento, foto = registro_local(tmp_path, local)
    assert correr(monkeypatch, "--evento-local", evento, "--foto-local", foto) == 0
    salida = capsys.readouterr().out
    assert "evento (11 campos del contrato) igual: True" in salida
    assert "igual a la de S3: True" in salida
    assert "Resultado: OK" in salida


def test_campo_distinto_se_muestra_y_falla(monkeypatch, capsys, tmp_path):
    evento, _ = registro_local(tmp_path, EVENTO | {"predicted_class": "cat"})
    assert correr(monkeypatch, "--evento-local", evento) == 1
    salida = capsys.readouterr().out
    assert "DISTINTO predicted_class" in salida
    assert "S3='dog'  local='cat'" in salida
    assert "Resultado: REVISAR" in salida


def test_foto_local_distinta_falla(monkeypatch, capsys, tmp_path):
    _, foto = registro_local(tmp_path, EVENTO, foto=b"otra foto")
    assert correr(monkeypatch, "--foto-local", foto) == 1
    assert "igual a la de S3: False" in capsys.readouterr().out


def test_region_omitida_en_local_equivale_a_null():
    local = {k: v for k, v in EVENTO.items() if k != "region"}
    assert consultar_captura.diferencias_con_local(REGISTRO, local) == []
