"""EDGE-06: enviar el evento persistido y su JPEG, sin regenerar la captura."""

import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from PIL import Image

from eventos import validar_evento
from inferencia import registrar

RECEPTOR = "https://54-80-197-58.sslip.io/api/p4/capturas"


class SinRedireccion(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def preparar(ruta):
    texto = ruta.read_bytes()
    if len(texto) > 16384:
        raise ValueError("Evento supera 16 KiB")
    evento = json.loads(texto)
    validar_evento(evento)
    foto = Path(evento["image_ref"]).read_bytes()
    if len(foto) > 5_000_000:
        raise ValueError("JPEG supera 5 MB")
    if hashlib.sha256(foto).hexdigest() != evento["image_sha256"]:
        raise ValueError("El hash del JPEG no coincide con el evento")
    with Image.open(io.BytesIO(foto)) as imagen:
        if imagen.format != "JPEG" or imagen.width * imagen.height > 40_000_000:
            raise ValueError("JPEG incompatible con el receptor")
        imagen.verify()
    limite = "edge06-" + uuid4().hex
    cuerpo = (
        f'--{limite}\r\nContent-Disposition: form-data; name="evento"\r\n\r\n'.encode()
        + texto + f'\r\n--{limite}\r\nContent-Disposition: form-data; name="foto"; '
        f'filename="{evento["capture_id"]}.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        + foto + f"\r\n--{limite}--\r\n".encode()
    )
    return evento, cuerpo, limite, hashlib.sha256(texto).hexdigest()


def enviar(ruta, url, token, log, reintentos=2):
    partes = urlsplit(url)
    if partes.scheme != "https" or not partes.hostname or partes.username or partes.password:
        raise ValueError("Receptor debe usar HTTPS sin credenciales en la URL")
    if not token or "\n" in token or "\r" in token:
        raise ValueError("Falta un token válido en P4_TOKEN_DISPOSITIVO")
    evento, cuerpo, limite, evento_hash = preparar(ruta)
    log.parent.mkdir(parents=True, exist_ok=True)
    abrir = build_opener(SinRedireccion()).open
    for numero in range(reintentos + 1):
        solicitud = Request(url, data=cuerpo, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={limite}",
        }, method="POST")
        inicio = time.perf_counter()
        try:
            with abrir(solicitud, timeout=30) as respuesta:
                estado = respuesta.status
                datos = respuesta.read(32768)
        except HTTPError as error:
            estado = error.code
            try:
                datos = error.read(32768)
            finally:
                error.close()
        except (URLError, TimeoutError, socket.timeout, ConnectionError):
            estado, datos = None, b"Error de red o timeout; evento local conservado"
        # No registrar Authorization ni detalles de excepciones que contengan URLs.
        detalle = datos.decode("utf-8", errors="replace").replace(token, "[REDACTADO]")[:16384]
        try:
            contenido = json.loads(detalle)
        except ValueError:
            contenido = {}
        exito = (
            estado in (200, 201) and isinstance(contenido, dict)
            and contenido.get("estado") == ("creado" if estado == 201 else "duplicado")
            and contenido.get("capture_id") == evento["capture_id"]
        )
        repetir = estado is None or estado == 503
        registrar(log, {
            "capture_id": evento["capture_id"], "captured_at": evento["captured_at"],
            "timestamp": datetime.now().astimezone().isoformat(),
            "http_status": estado, "respuesta": detalle, "confirmado": exito,
            "intento": numero + 1, "reintentable": repetir,
            "evento_sha256": evento_hash, "image_sha256": evento["image_sha256"],
            "envio_ms": (time.perf_counter() - inicio) * 1000,
        })
        if exito:
            return True
        if not repetir or numero == reintentos:
            return False
        time.sleep(2 ** numero)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evento", type=Path, required=True, help="JSON de eventos/, no de capturas/")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--url", default=os.environ.get("P4_RECEPTOR_URL", RECEPTOR))
    args = parser.parse_args()
    try:
        return 0 if enviar(args.evento, args.url, os.environ.get("P4_TOKEN_DISPOSITIVO", ""), args.log) else 1
    except KeyboardInterrupt:
        print("Envío interrumpido; evento y foto se conservan.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"ERROR local ({type(error).__name__}): revisar token externo, evento, JPEG y URL. "
              "No se borraron archivos.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
