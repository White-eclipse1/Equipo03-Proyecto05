"""La guarda anti-AWS de `scripts/e2e_portal.py` (F14 / 7.2, regla 14 AGENTS.md).

El recorrido E2E solo puede correr contra un MinIO de prueba: nunca contra AWS
ni contra el bucket de produccion. Se prueba la guarda sin levantar el stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROYECTO3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROYECTO3 / "scripts"))

import e2e_portal  # noqa: E402


@pytest.mark.parametrize(
    ("endpoint", "bucket"),
    [
        ("", "p3-e2e"),  # sin endpoint => se resolveria a AWS
        ("https://s3.amazonaws.com", "p3-e2e"),  # AWS explicito
        ("https://s3.us-east-1.amazonaws.com", "p3-e2e"),
        ("http://localhost:9100", e2e_portal.PROD_BUCKET),  # bucket de produccion
    ],
)
def test_se_niega_contra_aws_o_produccion(endpoint: str, bucket: str) -> None:
    with pytest.raises(e2e_portal.E2ERefusedError):
        e2e_portal.check_not_aws(endpoint, bucket)


@pytest.mark.parametrize(
    "endpoint", ["http://localhost:9100", "http://127.0.0.1:9000", "http://minio:9000"]
)
def test_acepta_minio_local_con_bucket_de_prueba(endpoint: str) -> None:
    e2e_portal.check_not_aws(endpoint, "p3-e2e")  # no debe lanzar
