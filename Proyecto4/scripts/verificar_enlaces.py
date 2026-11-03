"""Comprueba que abren todos los enlaces relativos del paquete de entrega (INT-08).

    python Proyecto4/scripts/verificar_enlaces.py

Revisa los Markdown que lee el evaluador: la ficha (`README.md`), `docs/` y los README
de `evidencias/`. Cada enlace relativo `[texto](ruta)` debe apuntar a un archivo o
carpeta que exista en el repositorio. No sigue enlaces externos (`http`, `https`,
`mailto`) ni valida anclas (`#seccion`): solo el archivo al que llevan.
Termina con codigo 1 y la lista de enlaces rotos si falta alguno.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

RAIZ = Path(__file__).resolve().parents[1]  # Proyecto4/
# `[texto](destino)` o `[texto](destino "titulo")`; tambien las imagenes `![...](...)`.
ENLACE = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
BLOQUE_CODIGO = re.compile(r"```.*?```", re.DOTALL)
CODIGO_EN_LINEA = re.compile(r"`[^`\n]*`")


def documentos(raiz: Path = RAIZ) -> list[Path]:
    return sorted(
        [raiz / "README.md", *raiz.glob("docs/*.md"), *raiz.glob("evidencias/**/README.md")]
    )


def enlaces_rotos(documento: Path) -> list[str]:
    texto = BLOQUE_CODIGO.sub("", documento.read_text(encoding="utf-8"))
    # Sin el codigo en linea, `[`archivo`](ruta)` queda como `[](ruta)` y sigue contando,
    # mientras que un `[x](y)` escrito como ejemplo dentro de codigo desaparece.
    texto = CODIGO_EN_LINEA.sub("", texto)
    rotos = []
    for destino in ENLACE.findall(texto):
        if re.match(r"^[a-z][a-z0-9+.-]*:", destino) or destino.startswith("#"):
            continue
        ruta = unquote(destino.split("#", 1)[0])
        if not (documento.parent / ruta).exists():
            rotos.append(destino)
    return rotos


def main() -> int:
    total = 0
    for documento in documentos():
        for destino in enlaces_rotos(documento):
            print(f"ROTO  {documento.relative_to(RAIZ)} -> {destino}")
            total += 1
    revisados = len(documentos())
    print(f"{revisados} documentos revisados; {total} enlace(s) roto(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
