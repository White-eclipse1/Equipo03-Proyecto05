"""Imagenes de relleno para que el hover de Exploracion tenga algo que servir.

`GET /api/exploration/thumbnail/{id}` traduce el id a un nombre de archivo
mirando `reports/exploration.json` y abre ese archivo en `data/raw/images/`. El
manifiesto SI esta versionado en Git; las imagenes NO: el dataset real pesa
cientos de megas y vive en el remote de DVC. En un clon recien hecho — y en el
job `smoke` de CI, que no tiene credenciales para `dvc pull` — el endpoint
responde 404 con toda la razon, y la prueba del hover falla por falta de
dataset, no por un defecto de la aplicacion.

Este script escribe un JPEG diminuto por cada `file_name` del manifiesto. No
sustituye al endpoint ni lo simula: lo obliga a hacer su trabajo entero
—resolver el id contra el manifiesto, abrir el archivo, redimensionar y
codificar el JPEG— contra archivos que existen de verdad. Lo unico que no
prueba es como se ve la foto, que es justo lo que ninguna prueba automatica
comprueba de todos modos.

    python scripts/imagenes_de_prueba.py

Nunca sobrescribe. Si `dvc pull` ya trajo el dataset real, cada archivo que ya
esta se deja intacto: correr esto sobre un dataset de verdad no puede estropear
ninguna imagen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFIESTO = REPO_ROOT / "reports" / "exploration.json"
IMAGENES = REPO_ROOT / "data" / "raw" / "images"

# El endpoint reduce a 160 px de lado. Generarlas ya a ese tamano evita que la
# miniatura servida sea el escalado de algo mas chico.
LADO = 160


def color(punto: dict[str, Any]) -> tuple[int, int, int]:
    """Un color estable por punto: las capturas del reporte no salen todas grises."""
    semilla = (punto.get("category_id") or 0) * 47 + (punto.get("image_id") or 0)
    return (60 + (semilla * 7) % 180, 60 + (semilla * 13) % 180, 60 + (semilla * 29) % 180)


def main() -> int:
    if not MANIFIESTO.is_file():
        print(f"No existe {MANIFIESTO}; sin manifiesto no se sabe que archivos hacen falta.")
        return 1

    puntos = json.loads(MANIFIESTO.read_text(encoding="utf-8")).get("points") or []
    if not puntos:
        print(f"{MANIFIESTO.name} no tiene puntos: no hay miniaturas que sembrar.")
        return 1

    IMAGENES.mkdir(parents=True, exist_ok=True)

    escritas = 0
    existentes = 0
    for punto in puntos:
        nombre = punto.get("file_name")
        if not nombre:
            continue
        # `.name` por lo mismo que el endpoint: lo que venga del manifiesto no
        # puede sacar la escritura de `data/raw/images/`.
        destino = IMAGENES / Path(nombre).name
        if destino.exists():
            existentes += 1
            continue
        Image.new("RGB", (LADO, LADO), color(punto)).save(destino, "JPEG", quality=70)
        escritas += 1

    print(f"{escritas} imagenes de relleno en {IMAGENES} ({existentes} ya estaban).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
