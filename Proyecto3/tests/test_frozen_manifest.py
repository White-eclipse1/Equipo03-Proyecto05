"""Solo se entrena con un manifiesto congelado y con el hash esperado (F4 T12, 3.1 y M3)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from p3.data import frozen


def _manifest(tmp_path: Path, contenido: str, meta_hash: str | None = None) -> tuple[Path, str]:
    folder = tmp_path / "m-9.9.9-s1-1"
    folder.mkdir()
    (folder / "manifest.jsonl").write_text(contenido, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(contenido.encode("utf-8")).hexdigest()
    meta = {"manifest_id": "m-9.9.9-s1-1", "manifest_hash": meta_hash or digest}
    (folder / "manifest.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return folder, digest


def test_el_manifiesto_real_esta_en_la_lista_de_congelados() -> None:
    assert frozen.FROZEN_MANIFESTS["m-0.1.3-s42-1"] == (
        "45600f297d13f51685e051e0cbc4962beb1f7c6a4e03247cbf61a345e6fa4305"
    )


def test_un_manifiesto_congelado_e_intacto_pasa(tmp_path: Path) -> None:
    folder, digest = _manifest(tmp_path, '{"crop_id":"x"}\n')
    meta = frozen.verify_frozen(folder, {"m-9.9.9-s1-1": digest})
    assert meta["manifest_hash"] == digest


def test_un_manifiesto_no_congelado_se_rechaza(tmp_path: Path) -> None:
    folder, _ = _manifest(tmp_path, '{"crop_id":"x"}\n')
    with pytest.raises(frozen.ManifestNotFrozenError, match="no esta congelado"):
        frozen.verify_frozen(folder, {})


def test_un_manifiesto_editado_se_rechaza(tmp_path: Path) -> None:
    folder, digest = _manifest(tmp_path, '{"crop_id":"x"}\n')
    (folder / "manifest.jsonl").write_text('{"crop_id":"y"}\n', encoding="utf-8")
    with pytest.raises(frozen.ManifestNotFrozenError, match="SHA-256"):
        frozen.verify_frozen(folder, {"m-9.9.9-s1-1": digest})


def test_un_meta_que_no_coincide_se_rechaza(tmp_path: Path) -> None:
    folder, digest = _manifest(tmp_path, '{"crop_id":"x"}\n', meta_hash="0" * 64)
    with pytest.raises(frozen.ManifestNotFrozenError, match="meta"):
        frozen.verify_frozen(folder, {"m-9.9.9-s1-1": digest})


def test_no_importa_torch() -> None:
    assert "import torch" not in Path(frozen.__file__).read_text(encoding="utf-8")
