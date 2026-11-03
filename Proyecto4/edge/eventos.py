"""EDGE-05: capturar, inferir y guardar eventos del contrato antes de cualquier envío."""

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from camara import capturar
from inferencia import CLASES, VERSION, Modelo, registrar

# La prueba controlada permanece en loopback aun si hay un proxy en el entorno.
urlopen = build_opener(ProxyHandler({})).open

CAMPOS = frozenset({
    "schema_version", "capture_id", "captured_at", "predicted_class", "confidence",
    "device_id", "model_version", "model_sha256", "image_sha256", "image_ref", "region",
})


def validar_evento(evento):
    if set(evento) != CAMPOS:
        raise ValueError("Campos incompatibles con el contrato de capturas")
    if type(evento["schema_version"]) is not int or evento["schema_version"] != 1:
        raise ValueError("schema_version debe ser 1")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", evento["capture_id"]):
        raise ValueError("capture_id inválido")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", evento["device_id"]):
        raise ValueError("device_id inválido")
    if datetime.fromisoformat(evento["captured_at"]).utcoffset() is None:
        raise ValueError("captured_at requiere zona horaria")
    if evento["predicted_class"] not in CLASES:
        raise ValueError("Clase inválida")
    confianza = evento["confidence"]
    if type(confianza) not in (float, int) or not math.isfinite(confianza) or not 0 <= confianza <= 1:
        raise ValueError("confidence debe ser un número finito entre 0 y 1")
    for campo in ("model_sha256", "image_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", evento[campo]):
            raise ValueError(f"{campo} inválido")
    if not evento["model_version"].strip() or not evento["image_ref"].strip():
        raise ValueError("Versión y referencia no pueden estar vacías")
    if evento["region"] is not None:
        raise ValueError("Esta aplicación clasifica imagen completa: region debe ser null")


def construir_evento(captura, prediccion, modelo):
    ruta = Path(captura["image_ref"])
    digest = hashlib.sha256(ruta.read_bytes()).hexdigest()
    if ruta.stem != captura["capture_id"] or digest != captura["image_sha256"]:
        raise ValueError("Foto y captura no corresponden")
    # Lista explícita: no copiar estado, dimensiones, tiempos ni logits al evento.
    evento = {
        "schema_version": 1, "capture_id": captura["capture_id"],
        "captured_at": captura["captured_at"], "predicted_class": prediccion["predicted_class"],
        "confidence": prediccion["confidence"], "device_id": captura["device_id"],
        "model_version": VERSION, "model_sha256": modelo.hash,
        "image_sha256": digest, "image_ref": str(ruta.resolve()), "region": None,
    }
    validar_evento(evento)
    return evento


def guardar_evento(carpeta, evento):
    validar_evento(evento)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{evento['capture_id']}.json"
    contenido = (json.dumps(evento, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(contenido) > 16384:
        raise ValueError("Evento supera 16 KiB")
    if ruta.exists():
        if ruta.read_bytes() != contenido:
            raise ValueError("Conflicto local: capture_id ya existe con otros datos")
        return ruta
    temporal = carpeta / f".{evento['capture_id']}-{uuid4().hex}.tmp"
    try:
        with temporal.open("xb") as archivo:
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())
        # Publicar completo sin sobrescribir otro evento con el mismo ID.
        os.link(temporal, ruta)
    finally:
        temporal.unlink(missing_ok=True)
    return ruta


def probar_fallo_envio(ruta_evento, log):
    """POST controlado solo a loopback: evidencia de persistencia, no integración real."""
    texto = ruta_evento.read_bytes()
    evento = json.loads(texto)
    validar_evento(evento)
    foto = Path(evento["image_ref"])
    datos = foto.read_bytes()
    if hashlib.sha256(datos).hexdigest() != evento["image_sha256"]:
        raise ValueError("JPEG modificado antes de la prueba de envío")
    limite = "edge05-" + uuid4().hex
    cuerpo = (
        f'--{limite}\r\nContent-Disposition: form-data; name="evento"\r\n\r\n'.encode()
        + texto + f'\r\n--{limite}\r\nContent-Disposition: form-data; name="foto"; '
        f'filename="{foto.name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        + datos + f"\r\n--{limite}--\r\n".encode()
    )
    solicitud = Request("http://127.0.0.1:1/api/p4/capturas", data=cuerpo,
                        headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
    try:
        with urlopen(solicitud, timeout=3):
            raise ValueError("El puerto local respondió; no se demostró fallo de red")
    except URLError as error:
        intactos = ruta_evento.read_bytes() == texto and foto.read_bytes() == datos
        registrar(log, {
            "estado": "fallo_envio_controlado", "tipo": type(error).__name__,
            "capture_id": evento["capture_id"], "destino": "loopback:1",
            "timestamp": datetime.now().astimezone().isoformat(),
            "evento_conservado": ruta_evento.exists(), "jpeg_conservado": foto.exists(),
            "bytes_intactos": intactos,
        })
        if not intactos:
            raise ValueError("Los archivos cambiaron durante la prueba")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", required=True, type=Path)
    parser.add_argument("--url", required=True, help="HTTP local de IP Webcam /shot.jpg")
    parser.add_argument("--salida", required=True, type=Path)
    parser.add_argument("--cantidad", type=int, default=3)
    parser.add_argument("--device-id", default="edge01")
    parser.add_argument("--probar-fallo-envio", action="store_true")
    args = parser.parse_args()
    if args.cantidad < 1 or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.device_id):
        parser.error("cantidad o device_id inválido")
    args.salida.mkdir(parents=True, exist_ok=True)
    log = args.salida / "eventos.jsonl"
    try:
        modelo = Modelo(args.modelo)
        registrar(log, modelo.metadatos)
        fotos = args.salida / "capturas"
        fotos.mkdir(parents=True, exist_ok=True)
        for _ in range(args.cantidad):
            input("Presenta una escena nueva y pulsa Enter para capturar, inferir y guardar: ")
            captura = capturar(args.url, fotos, args.device_id)
            prediccion = modelo.predecir(Path(captura["image_ref"]).read_bytes())
            evento = construir_evento(captura, prediccion, modelo)
            ruta = guardar_evento(args.salida / "eventos", evento)
            registrar(log, {"estado": "evento_guardado", "evento_local": str(ruta.resolve()),
                            "evento": evento, "inferencia_local": prediccion})
            if args.probar_fallo_envio:
                probar_fallo_envio(ruta, log)
    except (KeyboardInterrupt, EOFError):
        print("Interrumpido; archivos anteriores conservados.", file=sys.stderr)
        return 130
    except Exception as error:
        registrar(log, {"estado": "error_evento", "tipo": type(error).__name__,
                        "mensaje": "Revisar cámara, modelo y archivos; no se borraron evidencias."})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
