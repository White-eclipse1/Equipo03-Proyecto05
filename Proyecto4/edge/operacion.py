"""EDGE-07: captura e inferencia continuas, export local y reinicio auditable."""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

from camara import capturar
from eventos import construir_evento, guardar_evento
from inferencia import CLASES, VERSION, Modelo, registrar


def ejecutar(modelo_path, url, salida, cantidad=21, intervalo=16, fase="continua", device_id="edge01"):
    salida.mkdir(parents=True, exist_ok=True)
    session_id = uuid4().hex
    carpeta = salida / "sesiones" / session_id
    carpeta.mkdir(parents=True)
    fotos = carpeta / "capturas"
    fotos.mkdir()
    log = salida / "operacion.jsonl"
    inicio = time.monotonic()
    modelo = Modelo(modelo_path)
    configuracion = {
        "camera_url": url, "model_path": str(modelo_path.resolve()),
        "model_version": VERSION, "model_sha256": modelo.hash, "device_id": device_id,
        "intervalo_s": intervalo, "region": None,
    }
    config_hash = hashlib.sha256(json.dumps(configuracion, sort_keys=True).encode()).hexdigest()
    (carpeta / "configuracion.json").write_text(
        json.dumps(configuracion, indent=2), encoding="utf-8")

    def anotar(datos):
        registrar(log, {"session_id": session_id, "pid": os.getpid(), "fase": fase,
                        "config_sha256": config_hash,
                        "timestamp": datetime.now().astimezone().isoformat(), **datos})

    anotar({**modelo.metadatos, "cantidad_solicitada": cantidad})
    print("Preparar CAT. La clase solicitada no fuerza la predicción. "
          "No cerrar el programa durante la serie.", flush=True)
    input("Pulsa Enter para comenzar las fotografías nuevas: ")
    comienzo_serie = time.monotonic()
    clases = Counter()
    errores = 0
    momentos = []
    for indice in range(cantidad):
        objetivo = CLASES[min(2, indice * 3 // cantidad)]
        print(f"Captura {indice + 1}/{cantidad}: presenta {objetivo}. "
              f"{'Ahora' if indice == 0 else f'Esperando {intervalo} s'}.", flush=True)
        if indice:
            time.sleep(intervalo)
        try:
            captura = capturar(url, fotos, device_id)
            prediccion = modelo.predecir(Path(captura["image_ref"]).read_bytes())
            evento = construir_evento(captura, prediccion, modelo)
            ruta = guardar_evento(carpeta / "eventos", evento)
            # Export de eventos del contrato, independiente de los logs operativos.
            registrar(salida / "historial.jsonl", evento)
            anotar({"estado": "captura_completa", "indice": indice + 1,
                    "clase_a_presentar": objetivo, "evento_local": str(ruta.resolve()),
                    "evento": evento, "inferencia_local": prediccion})
            clases[evento["predicted_class"]] += 1
            momentos.append(time.monotonic())
        except Exception as error:
            errores += 1
            anotar({"estado": "fallo_captura", "indice": indice + 1,
                    "tipo": type(error).__name__, "clase_a_presentar": objetivo,
                    "mensaje": "Fallo visible; revisar cámara, modelo y almacenamiento. "
                               "Las evidencias anteriores se conservan."})
    duracion = time.monotonic() - comienzo_serie
    resumen = {
        "estado": "sesion_finalizada", "capturas_completas": sum(clases.values()),
        "fallos": errores, "predicciones_por_clase": dict(clases),
        "serie_s": duracion, "proceso_desde_carga_s": time.monotonic() - inicio,
        "entre_primera_ultima_captura_s": momentos[-1] - momentos[0] if len(momentos) > 1 else 0,
        "cumple_20_y_5min_y_3clases": sum(clases.values()) >= 20 and duracion >= 300
        and all(clases[c] > 0 for c in CLASES),
    }
    anotar(resumen)
    return 0 if sum(clases.values()) == cantidad else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--salida", type=Path, required=True)
    parser.add_argument("--cantidad", type=int, default=21)
    parser.add_argument("--intervalo", type=float, default=16)
    parser.add_argument("--fase", choices=["continua", "reinicio"], default="continua")
    parser.add_argument("--device-id", default="edge01")
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query:
        parser.error("URL local de cámara inválida o con secretos; usar /shot.jpg sin credenciales")
    if args.cantidad < 1 or not math.isfinite(args.intervalo) or args.intervalo <= 0:
        parser.error("cantidad e intervalo deben ser positivos")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.device_id):
        parser.error("device_id inválido")
    try:
        return ejecutar(args.modelo, args.url, args.salida, args.cantidad,
                        args.intervalo, args.fase, args.device_id)
    except (KeyboardInterrupt, EOFError):
        print("Interrumpido; historial y archivos previos conservados.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"ERROR de operación ({type(error).__name__}); revisar configuración y archivos.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
