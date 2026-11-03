"""Prueba del contrato contra el receptor desplegado (INT-02; evidencia previa de INT-03/04/05).

    python Proyecto4/scripts/enviar_prueba.py --profile p4-equipo

Hace lo mismo que hara el dispositivo y comprueba cada respuesta del contrato
(`docs/contrato-capturas.md`):

1. evento valido (foto JPEG + metadatos)          -> 201 creado
2. el MISMO evento otra vez (reintento)          -> 200 duplicado, no escribe
3. mismo capture_id con otra clase                -> 409 conflicto_capture_id
4. evento sin zona horaria en captured_at         -> 422 evento_invalido
5. evento valido sin token                        -> 401 no_autorizado
6. el reintento devuelve el received_at del primer envio

El token se lee de Parameter Store (`/p4/token-dispositivo`) con la CLI de AWS, nunca se
imprime ni se guarda y SOLO se envia al receptor desplegado (`URL`): con otra `--url` el
script se detiene, salvo con `--token-de-entorno` y un token de prueba.

La captura del paso 1 queda guardada en S3 y aparece
en Capturas Edge con `device_id=prueba-int`, para distinguirla de las del dispositivo.

Deja en `Proyecto4/capturas/pruebas/<capture_id>/` (ignorado por Git) la foto, el
evento y un `resultado.json` con cada respuesta: el registro local del "dispositivo".
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

URL = "https://54-80-197-58.sslip.io/api/p4/capturas"
MODELO = "1.0.0-int8-e05.1"
MODELO_SHA256 = "ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12"
DISPOSITIVO = "prueba-int"
REGISTRO_LOCAL = Path(__file__).resolve().parents[1] / "capturas" / "pruebas"


def leer_token(perfil: str | None, region: str) -> str:
    comando = [
        "aws",
        "ssm",
        "get-parameter",
        "--name",
        "/p4/token-dispositivo",
        "--with-decryption",
        "--query",
        "Parameter.Value",
        "--output",
        "text",
        "--region",
        region,
    ]
    if perfil:
        comando += ["--profile", perfil]
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        sys.exit(f"No se pudo leer el token de Parameter Store: {resultado.stderr.strip()}")
    return resultado.stdout.strip()


def foto_de_prueba(capture_id: str) -> bytes:
    """JPEG 640x480 que dice claramente que es una prueba (no es una captura de camara)."""
    imagen = Image.new("RGB", (640, 480), (232, 236, 244))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle((40, 40, 600, 440), outline=(79, 70, 200), width=6)
    for i, linea in enumerate(
        ["PRUEBA DEL CONTRATO (INT-02)", "no es una captura de camara", capture_id]
    ):
        dibujo.text((70, 180 + 30 * i), linea, fill=(27, 31, 46))
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=90)
    return salida.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=URL)
    parser.add_argument("--profile", help="perfil de ~/.aws con acceso a Parameter Store")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--token-de-entorno",
        action="store_true",
        help="leer el token de P4_TOKEN_DISPOSITIVO (pruebas locales) en vez de Parameter Store",
    )
    args = parser.parse_args(argv)
    # El token REAL (Parameter Store) solo viaja al receptor desplegado: otra URL podria
    # entregarlo a un servidor ajeno. Para otro receptor (local, CI), un token de prueba
    # en P4_TOKEN_DISPOSITIVO con --token-de-entorno.
    if not args.token_de_entorno and args.url != URL:
        sys.exit(
            f"El token real solo se envia a {URL}. Para probar contra {args.url} usa "
            "--token-de-entorno con un token de prueba en P4_TOKEN_DISPOSITIVO."
        )

    ahora = datetime.now().astimezone()
    capture_id = f"{DISPOSITIVO}-{ahora:%Y%m%dT%H%M%S}-0001"
    carpeta = REGISTRO_LOCAL / capture_id
    carpeta.mkdir(parents=True, exist_ok=True)

    foto = foto_de_prueba(capture_id)
    (carpeta / "foto.jpg").write_bytes(foto)
    evento = {
        "schema_version": 1,
        "capture_id": capture_id,
        "captured_at": ahora.isoformat(timespec="seconds"),
        "predicted_class": "dog",
        "confidence": 0.5,
        "device_id": DISPOSITIVO,
        "model_version": MODELO,
        "model_sha256": MODELO_SHA256,
        "image_sha256": hashlib.sha256(foto).hexdigest(),
        "image_ref": f"capturas/pruebas/{capture_id}/foto.jpg",
        "region": None,
    }
    # Registro local ANTES de enviar, como exige el contrato.
    (carpeta / "evento.json").write_text(json.dumps(evento, indent=2), encoding="utf-8")

    token = (
        os.environ.get("P4_TOKEN_DISPOSITIVO", "")
        if args.token_de_entorno
        else leer_token(args.profile, args.region)
    )
    if not token:
        sys.exit("Falta el token del dispositivo.")
    casos = [
        ("1. evento valido", evento, token, 201, "creado"),
        ("2. mismo evento (reintento)", evento, token, 200, "duplicado"),
        (
            "3. mismo ID, otra clase",
            {**evento, "predicted_class": "cat"},
            token,
            409,
            "conflicto_capture_id",
        ),
        (
            "4. captured_at sin zona",
            {
                **evento,
                "capture_id": capture_id + "-x",
                "captured_at": ahora.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            token,
            422,
            "evento_invalido",
        ),
        ("5. sin token", {**evento, "capture_id": capture_id + "-y"}, None, 401, "no_autorizado"),
    ]
    resultados = []
    for nombre, ev, tok, status_esperado, codigo_esperado in casos:
        cabeceras = {"Authorization": f"Bearer {tok}"} if tok else {}
        try:
            r = httpx.post(
                args.url,
                headers=cabeceras,
                data={"evento": json.dumps(ev)},
                files={"foto": ("foto.jpg", foto, "image/jpeg")},
                timeout=30,
            )
            cuerpo = r.json()
            status = r.status_code
        except (httpx.HTTPError, ValueError) as error:
            cuerpo, status = {"error": type(error).__name__, "detail": str(error)}, None
        codigo = cuerpo.get("estado") or cuerpo.get("error")
        ok = status == status_esperado and codigo == codigo_esperado
        resultados.append(
            {
                "caso": nombre,
                "esperado": [status_esperado, codigo_esperado],
                "obtenido": [status, codigo],
                "ok": ok,
                "respuesta": cuerpo,
            }
        )
        print(
            f"[{'OK' if ok else 'FALLA':5}] {nombre:30} -> {status} {codigo}"
            + ("" if ok else f"  (esperado {status_esperado} {codigo_esperado})")
        )
    del token

    # El reintento no escribe: debe devolver el received_at del primer envio.
    primero = resultados[0]["respuesta"].get("received_at")
    reintento = resultados[1]["respuesta"].get("received_at")
    conserva = primero is not None and primero == reintento
    resultados.append(
        {
            "caso": "6. el reintento conserva received_at",
            "esperado": ["received_at del caso 1", primero],
            "obtenido": ["received_at del caso 2", reintento],
            "ok": conserva,
        }
    )
    print(f"[{'OK' if conserva else 'FALLA':5}] {'6. reintento, received_at':30} -> {reintento}")

    todo_ok = all(r["ok"] for r in resultados)
    (carpeta / "resultado.json").write_text(
        json.dumps(
            {
                "url": args.url,
                "capture_id": capture_id,
                "enviado_en": ahora.isoformat(),
                "todo_ok": todo_ok,
                "casos": resultados,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\ncapture_id: {capture_id}")
    print(f"Registro local: {carpeta}")
    print(
        "Siguiente: abre Capturas Edge en el portal y corre "
        f"`python Proyecto4/scripts/consultar_captura.py {capture_id} --profile p4-lectura`"
    )
    return 0 if todo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
