"""Consulta de SOLO LECTURA de una captura en S3, para la demostracion (INT-03 a INT-07).

    python Proyecto4/scripts/consultar_captura.py <capture_id> --profile p4-lectura

y, para compararla con el registro local del dispositivo, ademas:
`--evento-local <capture_id>.json --foto-local <capture_id>.jpg`.

Muestra, con las mismas llamadas que podria hacer el evaluador:
1. quien consulta (`sts get-caller-identity`);
2. el registro `edge-capturas/eventos/{id}.json`: VersionId, fecha de S3 y campos;
3. la foto `edge-capturas/fotos/{id}.jpg`: VersionId y el SHA-256 de sus metadatos;
4. el SHA-256 recalculado de la foto descargada, contra el del registro y el de S3;
5. cuantas versiones tiene cada objeto (1 = nunca se sobrescribio: sin duplicados);
6. con `--evento-local` / `--foto-local` (copias del registro local del dispositivo):
   que S3 guardo exactamente ese evento y esa foto. Asi se sigue un mismo `capture_id`
   del dispositivo a AWS (INT-04: reintento tras una falla; INT-06: traza completa).

Solo usa `sts get-caller-identity`, `s3api get-object` y `s3api list-object-versions`
por la CLI de AWS (asi funciona con `aws login`). No escribe ni borra nada; la foto se
descarga a una carpeta temporal que se borra al terminar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BUCKET = "p4-capturas-474665692638"
PREFIJO = "edge-capturas/"
CAMPOS = [
    "capture_id",
    "captured_at",
    "received_at",
    "device_id",
    "predicted_class",
    "confidence",
    "model_version",
    "model_sha256",
    "image_sha256",
    "image_ref",
    "region",
]
# Los campos del contrato (docs/contrato-capturas.md) que el dispositivo manda y S3 debe
# guardar tal cual. El registro local puede traer mas campos propios: no se comparan.
CONTRATO = [
    "schema_version",
    "capture_id",
    "captured_at",
    "predicted_class",
    "confidence",
    "device_id",
    "model_version",
    "model_sha256",
    "image_sha256",
    "image_ref",
    "region",
]


def aws(*argumentos: str, perfil: str | None, region: str) -> dict:
    comando = ["aws", *argumentos, "--region", region, "--output", "json"]
    if perfil:
        comando += ["--profile", perfil]
    resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8")
    if resultado.returncode != 0:
        sys.exit(f"Fallo `aws {' '.join(argumentos[:2])}`: {resultado.stderr.strip()}")
    return json.loads(resultado.stdout or "{}")


def diferencias_con_local(registro: dict, local: dict) -> list[tuple[str, object, object]]:
    """(campo, en S3, en local) de cada campo del contrato que no coincide."""
    return [
        (campo, registro.get(campo), local.get(campo))
        for campo in CONTRATO
        if registro.get(campo) != local.get(campo)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture_id")
    parser.add_argument("--profile", help="perfil de ~/.aws (por defecto, la cadena estandar)")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--prefijo", default=PREFIJO, help="solo para pruebas")
    parser.add_argument("--evento-local", type=Path, help="JSON del registro local del dispositivo")
    parser.add_argument("--foto-local", type=Path, help="JPEG del registro local del dispositivo")
    args = parser.parse_args()
    perfil, region, b, cid = args.profile, args.region, args.bucket, args.capture_id
    llave_reg = f"{args.prefijo}eventos/{cid}.json"
    llave_foto = f"{args.prefijo}fotos/{cid}.jpg"

    identidad = aws("sts", "get-caller-identity", perfil=perfil, region=region)
    print(f"1. Consulta como: {identidad['Arn']}")

    with tempfile.TemporaryDirectory() as carpeta:
        destino_reg = Path(carpeta) / "registro.json"
        meta_reg = aws(
            "s3api",
            "get-object",
            "--bucket",
            b,
            "--key",
            llave_reg,
            str(destino_reg),
            perfil=perfil,
            region=region,
        )
        registro = json.loads(destino_reg.read_text(encoding="utf-8"))
        print(f"\n2. Registro s3://{b}/{llave_reg}")
        print(f"   VersionId {meta_reg['VersionId']}  LastModified {meta_reg['LastModified']}")
        for campo in CAMPOS:
            print(f"   {campo:16} {registro.get(campo)}")

        destino_foto = Path(carpeta) / "foto.jpg"
        meta_foto = aws(
            "s3api",
            "get-object",
            "--bucket",
            b,
            "--key",
            llave_foto,
            str(destino_foto),
            perfil=perfil,
            region=region,
        )
        sha_s3 = meta_foto.get("Metadata", {}).get("sha256")
        sha_calc = hashlib.sha256(destino_foto.read_bytes()).hexdigest()
        print(f"\n3. Foto s3://{b}/{llave_foto}")
        print(f"   VersionId {meta_foto['VersionId']}  {meta_foto['ContentLength']} bytes")
        print(f"   SHA-256 en metadatos de S3: {sha_s3}")
        print(f"\n4. SHA-256 recalculado:       {sha_calc}")
        print(f"   igual al de S3:      {sha_calc == sha_s3}")
        print(f"   igual al del evento: {sha_calc == registro.get('image_sha256')}")

    # `--prefix` tambien traeria llaves que EMPIEZAN igual: se cuentan solo las exactas.
    versiones = {
        llave: sum(
            v["Key"] == llave
            for v in aws(
                "s3api",
                "list-object-versions",
                "--bucket",
                b,
                "--prefix",
                llave,
                perfil=perfil,
                region=region,
            ).get("Versions", [])
        )
        for llave in (llave_reg, llave_foto)
    }
    print("\n5. Versiones (1 = sin sobrescrituras ni duplicados):")
    for llave, n in versiones.items():
        print(f"   {n}  {llave}")

    ok = sha_calc == sha_s3 == registro.get("image_sha256") and set(versiones.values()) == {1}

    if args.evento_local or args.foto_local:
        print("\n6. Contra el registro local del dispositivo:")
    if args.evento_local:
        local = json.loads(args.evento_local.read_text(encoding="utf-8"))
        diferencias = diferencias_con_local(registro, local)
        for campo, en_s3, en_local in diferencias:
            print(f"   DISTINTO {campo:16} S3={en_s3!r}  local={en_local!r}")
        print(f"   evento ({len(CONTRATO)} campos del contrato) igual: {not diferencias}")
        ok = ok and not diferencias
    if args.foto_local:
        sha_local = hashlib.sha256(args.foto_local.read_bytes()).hexdigest()
        print(f"   foto local SHA-256 {sha_local}, igual a la de S3: {sha_local == sha_calc}")
        ok = ok and sha_local == sha_calc
    print(f"\nResultado: {'OK' if ok else 'REVISAR'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
