#!/usr/bin/env python3
"""Sube en lote las imagenes de una carpeta a la API del proyecto.

Usa `POST /api/images/upload` (multipart, campo `file`), el mismo endpoint que
la pantalla de carga del frontend. Solo stdlib: no hace falta instalar nada.

Uso:
    python scripts/upload_images.py ./mis_imagenes
    python scripts/upload_images.py ./mis_imagenes --recursive
    python scripts/upload_images.py ./mis_imagenes --url http://localhost:3000
"""

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Mismas reglas que `src/schemas/image.ts` (RN-08).
ACCEPTED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def guess_mime_type(path: Path) -> str:
    """Tipo MIME a partir de la extension, con JPEG/WebP asegurados."""
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if path.suffix.lower() == ".webp":
        return "image/webp"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def build_multipart(path: Path, mime_type: str) -> tuple[bytes, str]:
    """Codifica el archivo como multipart/form-data en el campo `file`."""
    boundary = f"----pyupload{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + path.read_bytes() + tail, f"multipart/form-data; boundary={boundary}"


def upload(path: Path, base_url: str, timeout: float) -> dict:
    """Sube un archivo y devuelve el objeto `data` creado por la API."""
    body, content_type = build_multipart(path, guess_mime_type(path))
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/images/upload",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())["data"]


def describe_http_error(error: urllib.error.HTTPError) -> str:
    """Extrae el mensaje del sobre `{"error": {...}}` que devuelve la API."""
    raw = error.read().decode("utf-8", "replace")
    try:
        payload = json.loads(raw)["error"]
        return f"HTTP {error.code} {payload.get('code', '')}: {payload.get('message', '')}".strip()
    except (ValueError, KeyError, TypeError):
        return f"HTTP {error.code}: {raw[:200]}"


def collect(folder: Path, recursive: bool) -> list[Path]:
    """Imagenes candidatas de la carpeta, ordenadas por nombre."""
    files = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in files if p.is_file() and p.suffix.lower() in EXTENSIONS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sube las imagenes de una carpeta a la API.")
    parser.add_argument("folder", type=Path, help="Carpeta con las imagenes")
    parser.add_argument("--url", default="http://localhost:3000", help="Base de la API")
    parser.add_argument("--recursive", action="store_true", help="Incluir subcarpetas")
    parser.add_argument("--timeout", type=float, default=60.0, help="Timeout por archivo (s)")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"No es una carpeta: {args.folder}", file=sys.stderr)
        return 1

    candidates = collect(args.folder, args.recursive)
    if not candidates:
        print(f"No se encontraron imagenes ({', '.join(sorted(EXTENSIONS))}) en {args.folder}")
        return 0

    print(f"{len(candidates)} imagen(es) encontradas. Subiendo a {args.url} ...\n")
    uploaded = 0
    failed = 0

    for index, path in enumerate(candidates, start=1):
        prefix = f"[{index}/{len(candidates)}] {path.name}"
        size = path.stat().st_size

        # Se descartan aqui los casos que la API rechazaria igualmente (RN-08).
        if size == 0:
            print(f"{prefix}: OMITIDA (archivo vacio)")
            failed += 1
            continue
        if size > MAX_IMAGE_BYTES:
            print(f"{prefix}: OMITIDA ({size / 1024 / 1024:.1f} MB supera el maximo de 10 MB)")
            failed += 1
            continue
        if guess_mime_type(path) not in ACCEPTED_MIME_TYPES:
            print(f"{prefix}: OMITIDA (formato no soportado)")
            failed += 1
            continue

        try:
            created = upload(path, args.url, args.timeout)
        except urllib.error.HTTPError as error:
            print(f"{prefix}: ERROR {describe_http_error(error)}")
            failed += 1
        except urllib.error.URLError as error:
            print(f"{prefix}: ERROR de conexion: {error.reason}")
            print("\nLa API no responde. Levantala con `npm run up` y reintenta.")
            return 1
        except OSError as error:
            print(f"{prefix}: ERROR leyendo el archivo: {error}")
            failed += 1
        else:
            print(f"{prefix}: OK -> id={created['id']} {created['width']}x{created['height']}")
            uploaded += 1

    print(f"\nListo: {uploaded} subida(s), {failed} fallida(s)/omitida(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
