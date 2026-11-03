"""El paquete de entrega no tiene enlaces rotos (`scripts/verificar_enlaces.py`, INT-08)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verificar_enlaces.py"
_spec = importlib.util.spec_from_file_location("verificar_enlaces", SCRIPT)
verificar_enlaces = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = verificar_enlaces
_spec.loader.exec_module(verificar_enlaces)


def test_todos_los_enlaces_del_paquete_abren():
    rotos = {
        str(doc.relative_to(verificar_enlaces.RAIZ)): verificar_enlaces.enlaces_rotos(doc)
        for doc in verificar_enlaces.documentos()
    }
    assert {doc: lista for doc, lista in rotos.items() if lista} == {}


def test_detecta_rotos_e_ignora_externos_anclas_y_codigo(tmp_path):
    (tmp_path / "existe.md").write_text("ok", encoding="utf-8")
    (tmp_path / "con espacio.png").write_bytes(b"")
    doc = tmp_path / "README.md"
    doc.write_text(
        "[bien](existe.md) [ancla](existe.md#seccion) [`codigo`](existe.md)\n"
        "[espacio](con%20espacio.png) [web](https://example.com) [aqui](#arriba)\n"
        "[roto](falta.md) [`otro`](carpeta/falta/)\n"
        "`[ejemplo](no-cuenta.md)`\n"
        "```\n[en bloque](tampoco-cuenta.md)\n```\n",
        encoding="utf-8",
    )
    assert verificar_enlaces.enlaces_rotos(doc) == ["falta.md", "carpeta/falta/"]
