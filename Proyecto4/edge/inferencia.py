"""EDGE-03: inferencia local CPU sobre capturas JPEG reales de EDGE-02."""

import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

# En el repositorio: ../modelo/preprocesar.py. En Raspberry: app/ y modelo/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modelo"))
from preprocesar import DESVIACION, MEDIA, preprocesar, softmax

VERSION = "1.0.0-int8-e05.1"
SHA256 = "ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12"
CLASES = ("cat", "dog", "person")


def registrar(ruta, registro):
    texto = json.dumps(registro, ensure_ascii=False, allow_nan=False)
    with ruta.open("a", encoding="utf-8") as archivo:
        archivo.write(texto + "\n")
        archivo.flush()
        os.fsync(archivo.fileno())
    print(texto, flush=True)


class Modelo:
    def __init__(self, ruta):
        datos = ruta.read_bytes()
        self.hash = hashlib.sha256(datos).hexdigest()
        if self.hash != SHA256:
            raise ValueError(f"Hash incorrecto: esperado {SHA256}; obtenido {self.hash}")
        import onnxruntime as ort

        # El runtime recibe exactamente los bytes cuyo hash se verificó.
        self.sesion = ort.InferenceSession(datos, providers=["CPUExecutionProvider"])
        entradas = self.sesion.get_inputs()
        salidas = self.sesion.get_outputs()
        if len(entradas) != 1 or entradas[0].type != "tensor(float)":
            raise ValueError("Se requiere una entrada float32")
        if entradas[0].shape != [1, 3, 224, 224]:
            raise ValueError(f"Input incompatible: {entradas[0].shape}")
        if len(salidas) != 1 or salidas[0].shape != [1, 3]:
            raise ValueError("Se requiere salida logits [1, 3]")
        self.entrada = entradas[0].name
        self.salida = salidas[0].name
        self.metadatos = {
            "estado": "modelo_cargado", "model_version": VERSION,
            "model_sha256": self.hash, "runtime": ort.__version__,
            "providers": self.sesion.get_providers(),
            "input_name": self.entrada, "input_shape": entradas[0].shape,
            "input_dtype": "float32", "output_name": self.salida,
            "class_order": list(CLASES), "rgb": True,
            "resize": "224x224 bilinear, imagen completa", "scale": "0..1",
            "mean": MEDIA.tolist(), "std": DESVIACION.tolist(),
        }

    def predecir(self, datos):
        inicio = time.perf_counter()
        with Image.open(io.BytesIO(datos)) as imagen:
            if imagen.format != "JPEG":
                raise ValueError("Se requiere JPEG")
            tensor = preprocesar(imagen)
        logits = np.asarray(self.sesion.run([self.salida], {self.entrada: tensor})[0])
        if logits.shape != (1, 3) or not np.isfinite(logits).all():
            raise ValueError("El modelo debe producir tres logits finitos")
        probabilidades = softmax(logits)[0]
        indice = int(probabilidades.argmax())
        return {
            "predicted_class": CLASES[indice], "confidence": float(probabilidades[indice]),
            "logits": logits[0].tolist(), "probabilities": probabilidades.tolist(),
            "input_shape": list(tensor.shape), "input_dtype": str(tensor.dtype),
            "preprocessing_inferencia_ms": (time.perf_counter() - inicio) * 1000,
        }


def procesar(modelo, foto, esperada):
    captura = json.loads(foto.with_suffix(".json").read_text(encoding="utf-8"))
    datos = foto.read_bytes()
    digest = hashlib.sha256(datos).hexdigest()
    if captura["capture_id"] != foto.stem or captura["image_sha256"] != digest:
        raise ValueError("El JPEG no corresponde al registro de captura EDGE-02")
    if datetime.fromisoformat(captura["captured_at"]).utcoffset() is None:
        raise ValueError("captured_at debe tener zona horaria")
    resultado = modelo.predecir(datos)
    return {
        "estado": "inferencia_local", "capture_id": captura["capture_id"],
        "captured_at": captura["captured_at"],
        "inferred_at": datetime.now().astimezone().isoformat(),
        "device_id": captura["device_id"], "image_ref": str(foto.resolve()),
        "image_sha256": digest, "model_version": VERSION, "model_sha256": modelo.hash,
        "expected_class": esperada, **resultado,
        "matches_expected": resultado["predicted_class"] == esperada,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", type=Path, required=True)
    parser.add_argument("--carpeta", type=Path, required=True, help="JPEG y JSON de EDGE-02")
    parser.add_argument("--esperada", choices=CLASES, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    try:
        modelo = Modelo(args.modelo)
        registrar(args.log, modelo.metadatos)
        fotos = sorted(args.carpeta.glob("*.jpg"))
        if not fotos:
            raise ValueError("No hay capturas JPEG en la carpeta indicada")
        for foto in fotos:
            registrar(args.log, procesar(modelo, foto, args.esperada))
    except Exception as error:
        registrar(args.log, {"estado": "error_inferencia", "tipo": type(error).__name__,
                             "mensaje": str(error)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
