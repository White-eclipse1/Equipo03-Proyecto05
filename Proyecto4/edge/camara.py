"""EDGE-02: fotografías físicas por HTTP local, sin modelo ni portal."""

import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 5_000_000


def registrar(carpeta, datos):
    linea = json.dumps(datos, ensure_ascii=False, allow_nan=False)
    with (carpeta / "capturas.jsonl").open("a", encoding="utf-8") as archivo:
        archivo.write(linea + "\n")
        archivo.flush()
        os.fsync(archivo.fileno())
    print(linea, flush=True)


def capturar(url, carpeta, device_id):
    solicitud = Request(url, headers={"Cache-Control": "no-cache"})
    with urlopen(solicitud, timeout=15) as respuesta:
        datos = respuesta.read(MAX_BYTES + 1)
    if len(datos) > MAX_BYTES:
        raise ValueError("La foto supera 5 MB")
    with Image.open(io.BytesIO(datos)) as imagen:
        if imagen.format != "JPEG":
            raise ValueError("La cámara no entregó un JPEG")
        ancho, alto = imagen.size
        imagen.verify()
    capture_id = f"{device_id}-{uuid4().hex}"
    ruta = carpeta / f"{capture_id}.jpg"
    fecha = datetime.now().astimezone().isoformat(timespec="microseconds")
    with ruta.open("xb") as archivo:
        archivo.write(datos)
        archivo.flush()
        os.fsync(archivo.fileno())
    registro = {
        "estado": "capturada", "capture_id": capture_id, "captured_at": fecha,
        "device_id": device_id, "image_ref": str(ruta.resolve()),
        "image_sha256": hashlib.sha256(datos).hexdigest(),
        "width": ancho, "height": alto, "image_bytes": len(datos),
    }
    # Registro de captura EDGE-02; no es el evento de inferencia del backend.
    temporal = ruta.with_suffix(".json.tmp")
    with temporal.open("w", encoding="utf-8") as archivo:
        json.dump(registro, archivo, ensure_ascii=False, indent=2)
        archivo.flush()
        os.fsync(archivo.fileno())
    temporal.replace(ruta.with_suffix(".json"))
    registrar(carpeta, registro)
    return registro


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="URL local de IP Webcam /shot.jpg")
    parser.add_argument("--device-id", default="edge01")
    parser.add_argument("--salida", type=Path, default=Path("capturas-edge02"))
    parser.add_argument("--cantidad", type=int, default=1)
    parser.add_argument("--intervalo", type=float, help="Segundos de espera entre capturas")
    args = parser.parse_args()
    partes = urlsplit(args.url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        parser.error("URL HTTP/HTTPS local inválida")
    if args.cantidad < 1 or (args.intervalo is not None and
                             (not 0 < args.intervalo < float("inf"))):
        parser.error("cantidad e intervalo deben ser positivos y finitos")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.device_id):
        parser.error("device_id inválido")
    args.salida.mkdir(parents=True, exist_ok=True)
    print("Cámara física HTTP local; sin modelo ni envío al portal.", flush=True)
    for numero in range(args.cantidad):
        if args.intervalo is None:
            input("Presenta un objeto nuevo y pulsa Enter para capturar: ")
        try:
            capturar(args.url, args.salida, args.device_id)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError,
                UnidentifiedImageError, Image.DecompressionBombError) as error:
            # No imprimir la URL: podría contener credenciales de la cámara.
            registrar(args.salida, {
                "estado": "error_camara", "tipo": type(error).__name__,
                "timestamp": datetime.now().astimezone().isoformat(),
                "mensaje": "No se pudo capturar un JPEG válido. Revisar cámara y enlace local.",
            })
            return 1
        if args.intervalo is not None and numero + 1 < args.cantidad:
            time.sleep(args.intervalo)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("Captura interrumpida.", file=sys.stderr)
        sys.exit(130)
