"""Modelo publicado del Proyecto 3 -> variante ONNX INT8 para el dispositivo edge.

    cd Proyecto4
    modelo/.venv/Scripts/python modelo/convertir.py          # Linux: modelo/.venv/bin/python

Pasos (configuracion en `modelo/conversion.yaml`, entorno en
`modelo/requirements-conversion.lock.txt`):

1. Exige el SHA-256 del `model.pt` del P3 y lo carga con `load_checkpoint` del
   propio P3: arquitectura, clases y preprocesamiento salen del checkpoint.
2. Exporta a ONNX FP32 y compara sus logits contra PyTorch.
3. Cuantiza estaticamente a INT8 (QDQ, pesos por canal) calibrando SOLO con
   recortes de train del manifiesto del P3; los IDs quedan en un registro.
4. Verificacion rapida en la validacion del P3: clase del original, FP32 e INT8.
5. Escribe `artefactos/<version>/` (pesos + `model_package.json`) y el registro
   `registros/registro_conversion.json` con entrada, salidas y SHA-256 de cada una.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import onnx
import onnxruntime as ort
import torch
import torchvision
import yaml
from onnxruntime.quantization import (
    CalibrationDataReader,
    CalibrationMethod,
    QuantFormat,
    QuantType,
    quantize_static,
)
from onnxruntime.quantization.shape_inference import quant_pre_process
from PIL import Image

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent  # Proyecto4/
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(RAIZ.parent / "Proyecto3" / "src"))

from p3.data.transforms import build_eval_transform  # noqa: E402
from p3.model.build import load_checkpoint  # noqa: E402
from preprocesar import preprocesar  # noqa: E402


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def escribir_json(ruta: Path, datos: Any) -> None:
    # Bytes fijos en cualquier sistema operativo: LF y UTF-8 (el SHA-256 no cambia).
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(datos, ensure_ascii=False, indent=2) + "\n"
    ruta.write_bytes(texto.encode("utf-8"))


def leer_muestras(cfg: dict[str, Any], split: str) -> list[dict[str, Any]]:
    """Recortes de un split del manifiesto del P3, con su ruta y clase."""
    manifiesto = RAIZ / cfg["calibracion"]["manifiesto"]
    if sha256(manifiesto) != cfg["calibracion"]["manifiesto_sha256"]:
        raise SystemExit(f"El manifiesto {manifiesto} no tiene el SHA-256 de conversion.yaml")
    recortes = RAIZ / cfg["calibracion"]["recortes"]
    rutas = {
        r["crop_id"]: recortes / r["crop_path"]
        for r in map(json.loads, (recortes / "crops.jsonl").read_text("utf-8").splitlines())
    }
    filas = [json.loads(linea) for linea in manifiesto.read_text("utf-8").splitlines()]
    return [
        {"crop_id": f["crop_id"], "clase": f["category_name"], "ruta": rutas[f["crop_id"]]}
        for f in filas
        if f["split"] == split
    ]


class LectorCalibracion(CalibrationDataReader):
    def __init__(self, muestras: list[dict[str, Any]], entrada: str) -> None:
        self._datos = iter([{entrada: preprocesar(Image.open(m["ruta"]))} for m in muestras])

    def get_next(self) -> dict[str, np.ndarray] | None:
        return next(self._datos, None)


def operadores(ruta: Path) -> dict[str, int]:
    return dict(sorted(Counter(n.op_type for n in onnx.load(str(ruta)).graph.node).items()))


def main() -> None:
    cfg = yaml.safe_load((AQUI / "conversion.yaml").read_text("utf-8"))
    origen, variante, cuant = cfg["origen"], cfg["variante"], cfg["cuantizacion"]
    version = variante["version"]
    salida = AQUI / "artefactos" / version
    salida.mkdir(parents=True, exist_ok=True)

    # 1. Original del P3, con su hash exigido.
    checkpoint = RAIZ / origen["checkpoint"]
    sha_original = sha256(checkpoint)
    if sha_original != origen["sha256"]:
        raise SystemExit(
            f"SHA-256 de {checkpoint} = {sha_original}; se esperaba {origen['sha256']}"
        )
    modelo, meta = load_checkpoint(checkpoint)
    clases, pre = meta["class_names"], meta["preprocessing"]
    tamano = pre["image_size"]
    print(f"Original: {checkpoint.name} {sha_original[:12]}… clases={clases} tamano={tamano}")

    # 2. Exportacion FP32.
    fp32 = salida / "model_fp32.onnx"
    ejemplo = torch.zeros(1, 3, tamano, tamano)
    torch.onnx.export(
        modelo,
        (ejemplo,),
        str(fp32),
        input_names=[variante["entrada"]],
        output_names=[variante["salida"]],
        opset_version=variante["opset"],
        dynamo=False,
    )
    onnx.checker.check_model(str(fp32))

    # 3. Cuantizacion INT8 calibrada solo con train.
    cal = cfg["calibracion"]
    entrenamiento = leer_muestras(cfg, cal["split"])
    assert cal["split"] == "train", "la calibracion solo puede usar train"
    calibracion = sorted(
        random.Random(cal["semilla"]).sample(entrenamiento, cal["muestras"]),
        key=lambda m: m["crop_id"],
    )
    ids_calibracion = AQUI / "registros" / "calibracion_ids.jsonl"
    ids_calibracion.parent.mkdir(parents=True, exist_ok=True)
    ids_calibracion.write_bytes(
        "".join(
            json.dumps({"crop_id": m["crop_id"], "clase": m["clase"], "split": "train"}) + "\n"
            for m in calibracion
        ).encode("utf-8")
    )
    preparado = salida / "model_fp32_preparado.onnx"
    quant_pre_process(str(fp32), str(preparado), skip_symbolic_shape=True)
    int8 = salida / "model_int8.onnx"
    quantize_static(
        model_input=str(preparado),
        model_output=str(int8),
        calibration_data_reader=LectorCalibracion(calibracion, variante["entrada"]),
        quant_format=QuantFormat.QDQ,
        per_channel=cuant["por_canal"],
        weight_type=getattr(QuantType, cuant["pesos"]),
        activation_type=getattr(QuantType, cuant["activaciones"]),
        calibrate_method=getattr(CalibrationMethod, cuant["metodo_calibracion"]),
    )
    preparado.unlink()

    # 4. Verificacion rapida en validacion: original (torchvision) contra FP32 e INT8 (edge).
    validacion = leer_muestras(cfg, cfg["verificacion"]["split"])
    transformar = build_eval_transform(tamano)
    opciones = ort.SessionOptions()
    opciones.log_severity_level = 3
    s_fp32 = ort.InferenceSession(str(fp32), opciones, providers=["CPUExecutionProvider"])
    s_int8 = ort.InferenceSession(str(int8), opciones, providers=["CPUExecutionProvider"])
    aciertos = Counter()
    acuerdo_int8 = 0
    max_dif_fp32 = 0.0
    for m in validacion:
        imagen = Image.open(m["ruta"])
        with torch.no_grad():
            x_torch = transformar(imagen.convert("RGB")).unsqueeze(0)
            l_torch = modelo(x_torch).numpy()
        l_fp32_mismo = s_fp32.run(None, {variante["entrada"]: x_torch.numpy()})[0]
        max_dif_fp32 = max(max_dif_fp32, float(np.abs(l_fp32_mismo - l_torch).max()))
        x_edge = preprocesar(imagen, tamano)
        l_fp32 = s_fp32.run(None, {variante["entrada"]: x_edge})[0]
        l_int8 = s_int8.run(None, {variante["entrada"]: x_edge})[0]
        clase = {
            k: clases[int(v.argmax())]
            for k, v in {"original": l_torch, "fp32": l_fp32, "int8": l_int8}.items()
        }
        for nombre, predicha in clase.items():
            aciertos[nombre] += predicha == m["clase"]
        acuerdo_int8 += clase["int8"] == clase["original"]
    n = len(validacion)

    # 5. Paquete y registro.
    sha_fp32, sha_int8 = sha256(fp32), sha256(int8)
    paquete = {
        "version": version,
        "origen": {
            "proyecto": "Proyecto 3",
            "version": origen["version_p3"],
            "run_id": origen["run_id"],
            "sha256": sha_original,
        },
        "archivo": int8.name,
        "sha256": sha_int8,
        "entrada": {
            "nombre": variante["entrada"],
            "forma": [1, 3, tamano, tamano],
            "tipo": "float32",
            "orden": "NCHW, RGB",
        },
        "salida": {"nombre": variante["salida"], "forma": [1, len(clases)], "confianza": "softmax"},
        "clases": clases,
        "preprocesamiento": {
            **pre,
            "implementacion_edge": "modelo/preprocesar.py (numpy + Pillow, bilineal)",
        },
    }
    escribir_json(salida / "model_package.json", paquete)
    registro = {
        "fecha": datetime.now(UTC).isoformat(timespec="seconds"),
        "comando": "modelo/.venv/Scripts/python modelo/convertir.py",
        "configuracion": cfg,
        "entorno": {
            "python": platform.python_version(),
            "maquina": platform.machine(),
            "sistema": platform.system(),
            "torch": torch.__version__,
            "torchvision": torchvision.__version__,
            "onnx": onnx.__version__,
            "onnxruntime": ort.__version__,
            "numpy": np.__version__,
        },
        "entrada": {
            "archivo": origen["checkpoint"],
            "sha256": sha_original,
            "bytes": checkpoint.stat().st_size,
            "version_p3": origen["version_p3"],
            "run_id": origen["run_id"],
        },
        "salidas": {
            "fp32": {
                "archivo": fp32.name,
                "sha256": sha_fp32,
                "bytes": fp32.stat().st_size,
                "operadores": operadores(fp32),
            },
            "int8": {
                "archivo": int8.name,
                "sha256": sha_int8,
                "bytes": int8.stat().st_size,
                "operadores": operadores(int8),
            },
            "model_package.json": {"sha256": sha256(salida / "model_package.json")},
        },
        "reduccion_tamano_pct": round(
            100 * (1 - int8.stat().st_size / checkpoint.stat().st_size), 2
        ),
        "calibracion": {
            "split": cal["split"],
            "muestras": len(calibracion),
            "por_clase": dict(sorted(Counter(m["clase"] for m in calibracion).items())),
            "ids": "registros/calibracion_ids.jsonl",
            "ids_sha256": sha256(ids_calibracion),
        },
        "verificacion_rapida": {
            "split": cfg["verificacion"]["split"],
            "muestras": n,
            "max_dif_logits_fp32_vs_torch": max_dif_fp32,
            "accuracy": {k: round(v / n, 4) for k, v in sorted(aciertos.items())},
            "acuerdo_int8_vs_original": round(acuerdo_int8 / n, 4),
            "nota": "Comprobacion de la conversion; la comparacion formal por muestra es de VAL.",
        },
    }
    escribir_json(AQUI / "registros" / "registro_conversion.json", registro)

    print(f"FP32: {fp32.stat().st_size:>11,} B  {sha_fp32}")
    print(f"INT8: {int8.stat().st_size:>11,} B  {sha_int8}")
    print(f"Reduccion contra model.pt: {registro['reduccion_tamano_pct']} %")
    print(f"Max |logits FP32 - torch|: {max_dif_fp32:.2e}")
    print(f"Accuracy val ({n}): {registro['verificacion_rapida']['accuracy']}")
    rapida = registro["verificacion_rapida"]
    print(f"Acuerdo INT8 vs original: {rapida['acuerdo_int8_vs_original']}")


if __name__ == "__main__":
    main()
