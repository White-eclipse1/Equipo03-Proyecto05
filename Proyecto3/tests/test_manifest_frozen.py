"""El manifiesto `m-0.1.3-s42-1` esta congelado: sus 10+ corridas dependen de el (F3, 3.1).

En Git va solo el puntero de DVC. Si alguien regenera o edita el manifiesto, el md5
del puntero cambia y esta prueba falla antes de que el cambio llegue a `main`. Si el
manifiesto esta descargado (`dvc pull`), tambien se revisa su `manifest_hash`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

MANIFESTS = Path(__file__).parents[1] / "data" / "manifests"
MANIFEST_ID = "m-0.1.3-s42-1"
POINTER_MD5 = "64eae7e52ddd9c73261680c860805494.dir"
MANIFEST_HASH = "45600f297d13f51685e051e0cbc4962beb1f7c6a4e03247cbf61a345e6fa4305"


def test_el_puntero_dvc_del_manifiesto_congelado_no_cambia() -> None:
    pointer = yaml.safe_load((MANIFESTS / f"{MANIFEST_ID}.dvc").read_text(encoding="utf-8"))
    [out] = pointer["outs"]
    assert out["path"] == MANIFEST_ID
    assert out["md5"] == POINTER_MD5
    assert out["nfiles"] == 2


def test_si_el_manifiesto_esta_descargado_su_hash_es_el_congelado() -> None:
    folder = MANIFESTS / MANIFEST_ID
    if not (folder / "manifest.jsonl").is_file():
        pytest.skip("manifiesto no descargado (dvc pull); el puntero ya se reviso")
    assert hashlib.sha256((folder / "manifest.jsonl").read_bytes()).hexdigest() == MANIFEST_HASH
    meta = json.loads((folder / "manifest.meta.json").read_text(encoding="utf-8"))
    assert meta["manifest_hash"] == MANIFEST_HASH
    assert meta["release"]["release_id"] == "0.1.3"
    # M2: el hash DVC de las imagenes del release viaja con el manifiesto.
    assert meta["release"]["dvc_pointer"]["md5"] == "ca56420c9992f8b75fdb10f2ece81704.dir"
