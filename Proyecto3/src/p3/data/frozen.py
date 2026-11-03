"""Manifiestos congelados: los unicos con los que se entrena (F4 T12, criterios 3.1 y M3).

Las >=10 corridas del barrido tienen que usar el MISMO manifiesto. La lista vive
en el codigo, asi que agregar o cambiar un manifiesto solo entra por PR. Antes de
entrenar se comprueba que el `manifest.jsonl` en disco tenga exactamente el
SHA-256 congelado y que su `manifest.meta.json` diga lo mismo.

Solo usa la libreria estandar: la API de P2 lo importa para rechazar con 409 un
trabajo sobre un manifiesto no congelado.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# manifest_id -> SHA-256 de `manifest.jsonl` (tag `p3-manifiesto-congelado`, F3).
FROZEN_MANIFESTS: Mapping[str, str] = {
    "m-0.1.3-s42-1": "45600f297d13f51685e051e0cbc4962beb1f7c6a4e03247cbf61a345e6fa4305",
    # F12 (1.1): mismo release con otra semilla, para mostrar que cambiar de
    # manifiesto cambia el split. Se entrena solo en `p3-pruebas`.
    "m-0.1.3-s7-1": "c7319207ae60b636e8ef45cd0a6f904e3c2b07755e9536fd2eded140a5089f01",
}


# `m-<release_id>-s<seed>-<n>` (docs/manifiesto.md).
MANIFEST_ID = r"^m-(?P<release>\d+\.\d+\.\d+)-s(?P<seed>\d+)-(?P<n>\d+)$"
# El manifiesto del barrido: las 12 corridas de `p3-clasificador` y la seleccion
# salen de el. Los demas congelados solo se entrenan en `p3-pruebas`.
SWEEP_MANIFEST = "m-0.1.3-s42-1"


def frozen_for(
    release_id: str, seed: int, frozen: Mapping[str, str] = FROZEN_MANIFESTS
) -> str | None:
    """El congelado de ese release y esa semilla (el de mayor `n` si hubiera varios)."""
    found = []
    for manifest_id in frozen:
        match = re.match(MANIFEST_ID, manifest_id)
        if match and match["release"] == release_id and int(match["seed"]) == seed:
            found.append((int(match["n"]), manifest_id))
    return max(found)[1] if found else None


def manifests_for(
    release_id: str, frozen: Mapping[str, str] = FROZEN_MANIFESTS
) -> list[tuple[str, int]]:
    """Los congelados de un release como `(manifest_id, seed)`, el del barrido primero."""
    found = []
    for manifest_id in frozen:
        match = re.match(MANIFEST_ID, manifest_id)
        if match and match["release"] == release_id:
            found.append((manifest_id, int(match["seed"]), int(match["n"])))
    found.sort(key=lambda m: (m[0] != SWEEP_MANIFEST, m[1], m[2]))
    return [(manifest_id, seed) for manifest_id, seed, _ in found]


class ManifestNotFrozenError(ValueError):
    """El manifiesto no esta en la lista o no es el que se congelo."""


def verify_frozen(
    manifest_dir: Path, frozen: Mapping[str, str] = FROZEN_MANIFESTS
) -> dict[str, Any]:
    """Devuelve el `manifest.meta.json` si el manifiesto es exactamente el congelado."""
    manifest_id = manifest_dir.name
    expected = frozen.get(manifest_id)
    if expected is None:
        raise ManifestNotFrozenError(
            f"El manifiesto {manifest_id} no esta congelado; solo se entrena con {sorted(frozen)}."
        )
    actual = hashlib.sha256((manifest_dir / "manifest.jsonl").read_bytes()).hexdigest()
    if actual != expected:
        raise ManifestNotFrozenError(
            f"SHA-256 de {manifest_id}/manifest.jsonl = {actual}; el congelado es {expected}. "
            "Corre `dvc pull` del puntero congelado."
        )
    meta = json.loads((manifest_dir / "manifest.meta.json").read_text(encoding="utf-8"))
    if meta.get("manifest_hash") != expected:
        raise ManifestNotFrozenError(
            f"El meta de {manifest_id} dice manifest_hash={meta.get('manifest_hash')}; "
            f"el congelado es {expected}."
        )
    return meta
