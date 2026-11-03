"""Los montajes de la app existen en un clon limpio (revision de Edith en el #29).

Si la app monta una carpeta del host que Git no trae (por ejemplo
`Proyecto3/data/crops`), Docker la crea al arrancar. En Linux nativo la crea
como root, y despues `generate_crops.py` no puede escribir ahi
(PermissionError). Por eso cada carpeta de `Proyecto3/` que monta la app debe
tener al menos un archivo versionado.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
COMPOSE = ROOT / "Proyecto2" / "docker-compose.yml"


def _app_mounts_from_proyecto3() -> list[str]:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    sources = [v.split(":")[0] for v in services["app"]["volumes"] if isinstance(v, str)]
    return [s.removeprefix("../") for s in sources if s.startswith("../Proyecto3/")]


def _tracked(folder: str) -> bool:
    listed = subprocess.run(
        ["git", "ls-files", "--", folder], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return bool(listed.stdout.strip())


def test_la_app_solo_monta_carpetas_de_proyecto3_que_existen_en_git() -> None:
    mounts = _app_mounts_from_proyecto3()
    assert mounts, "la app deberia montar codigo y datos de Proyecto3"
    missing = [m for m in mounts if not _tracked(m)]
    assert missing == [], f"Docker crearia estas carpetas como root en Linux: {missing}"


def test_la_app_ve_los_recortes_dentro_del_montaje_de_data() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    env = services["app"]["environment"]
    assert "../Proyecto3/data:/opt/p3/data:ro" in services["app"]["volumes"]
    assert env["P3_CROPS_DIR"] == "/opt/p3/data/crops"
    assert env["P3_MANIFESTS_DIR"] == "/opt/p3/data/manifests"
