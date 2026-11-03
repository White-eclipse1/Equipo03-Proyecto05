"""EDGE-04: cargar una sesión CPU y conservarla antes, durante y después del corte."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from camara import capturar
from inferencia import Modelo, procesar, registrar


def ejecutar(ruta_modelo, url, salida):
    salida.mkdir(parents=True, exist_ok=True)
    log = salida / "offline.jsonl"
    sesion_id = uuid4().hex

    def anotar(datos):
        registrar(log, {"session_id": sesion_id, "pid": os.getpid(),
                        "timestamp": datetime.now().astimezone().isoformat(), **datos})

    # Debe ocurrir antes de pedir al operador que desconecte Internet.
    modelo = Modelo(ruta_modelo)
    anotar(modelo.metadatos)
    print("MODELO CARGADO. No cierres este programa ni esta Terminal.", flush=True)
    input("Desconecta Internet conservando USB/IP Webcam. Guarda evidencia de red. "
          "Cuando esté listo pulsa Enter: ")
    anotar({"estado": "fase_declarada_por_operador", "fase": "sin_internet"})
    for fase, numero in [("sin_internet", 1), ("sin_internet", 2), ("reconectado", 3)]:
        if fase == "reconectado":
            input("Reconecta Internet, guarda evidencia de red y pulsa Enter para continuar "
                  "con el MISMO modelo: ")
            anotar({"estado": "fase_declarada_por_operador", "fase": fase})
        esperada = input(f"Captura {numero}, fase {fase}. Clase que presentarás "
                         "(cat/dog/person): ").strip()
        if esperada not in ("cat", "dog", "person"):
            raise ValueError("Clase esperada inválida; no se tomó la foto")
        input("Presenta una escena nueva y pulsa Enter para capturar y clasificar: ")
        carpeta = salida / fase
        carpeta.mkdir(parents=True, exist_ok=True)
        captura = capturar(url, carpeta, "edge01")
        resultado = procesar(modelo, Path(captura["image_ref"]), esperada)
        anotar({**resultado, "fase": fase})
    anotar({"estado": "demostracion_finalizada"})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", type=Path, required=True)
    parser.add_argument("--url", required=True, help="HTTP local /shot.jpg de IP Webcam")
    parser.add_argument("--salida", type=Path, required=True)
    args = parser.parse_args()
    try:
        return ejecutar(args.modelo, args.url, args.salida)
    except (KeyboardInterrupt, EOFError):
        print("Demostración interrumpida; evidencias anteriores conservadas.", file=sys.stderr)
        return 130
    except Exception as error:
        # No registrar URLs que puedan incluir credenciales.
        args.salida.mkdir(parents=True, exist_ok=True)
        registrar(args.salida / "offline.jsonl", {
            "estado": "error_demostracion", "tipo": type(error).__name__,
            "timestamp": datetime.now().astimezone().isoformat(),
            "mensaje": "Revisar modelo, cámara y enlace USB local; evidencias conservadas.",
        })
        return 1


if __name__ == "__main__":
    sys.exit(main())
