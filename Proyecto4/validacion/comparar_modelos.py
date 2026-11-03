"""Comparacion por muestra: modelo original del P3 contra la variante INT8 (VAL-02, #2).

Corre el `model.pt` 1.0.0 del P3 y la variante `1.0.0-int8-e05.1` (y, como referencia,
su exportacion ONNX FP32) sobre exactamente las muestras `val` del manifiesto del P3,
y deja una fila por muestra con la clase real, la prediccion de cada modelo y sus
probabilidades sin redondear (rubrica 1.3 y 6.2; regla: numeros recalculables).

    cd Proyecto4
    modelo/.venv/Scripts/python validacion/comparar_modelos.py
    modelo/.venv/Scripts/python validacion/comparar_modelos.py --profile <perfil> --descargar

Cada modelo usa el preprocesamiento con el que se usa en produccion:

- original: PyTorch con `build_eval_transform` del P3 (como se evaluo en el P3);
- fp32 e int8: onnxruntime con `modelo/preprocesar.py` (como corre en el dispositivo).

Asi la diferencia original -> int8 es la que vera el usuario; la columna fp32 separa lo
que aporta la cuantizacion (fp32 -> int8) de lo que aporta el cambio de runtime y de
preprocesamiento (original -> fp32).

El mismo `model_int8.onnx` se corre dos veces:

- `int8`: con las optimizaciones por defecto de onnxruntime, que funden los pares QDQ en
  kernels enteros. Es lo que ejecuta el runtime en esta maquina. Su resultado puede
  cambiar de CPU a CPU (por eso se registra su nombre); la causa no esta confirmada
  (hipotesis: saturacion U8S8 en x86 sin VNNI, ver docs/comparacion-modelos.md).
- `int8_referencia`: con las optimizaciones apagadas, cada QuantizeLinear/DequantizeLinear
  se ejecuta tal cual y la convolucion en float. Es la aritmetica que define el grafo,
  sin kernels enteros fusionados, y sirve para contrastar la medicion del dispositivo.

Antes de correr, exige el SHA-256 del manifiesto, de `crops.jsonl` y de los tres
modelos (los de `modelo/conversion.yaml` y `modelo/registros/registro_conversion.json`),
el de cada recorte de `val` (inventario congelado por `validacion/inventario_recortes.py`)
y comprueba contra el manifiesto que la calibracion del INT8 uso solo train. Despues,
vuelve a leer el CSV escrito y comprueba que sus IDs son exactamente los de `val`, sin
duplicados ni faltantes, y que el original reproduce el accuracy y el val_loss que el
P3 registro en `selection.json` (huella de que son las mismas imagenes). Sale con
codigo 1 si algo no se cumple.

Salidas en `validacion/resultados/`: `comparacion_val.csv` (por muestra) y
`comparacion_val.json` (procedencia, comprobaciones y resumen).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import platform
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent  # Proyecto4/
MODELO = RAIZ / "modelo"
P3 = RAIZ.parent / "Proyecto3"
RESULTADOS = AQUI / "resultados"
REGISTROS_VAL = AQUI / "registros"
ARCHIVO_CSV = "comparacion_val.csv"
ARCHIVO_JSON = "comparacion_val.json"

SPLIT = "val"
MODELOS = ("original", "fp32", "int8", "int8_referencia")
BUCKET = "p4-capturas-474665692638"

# Una prediccion: probabilidades (softmax) en el orden de clases del modelo.
Predictor = Callable[[Path], list[float]]


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_jsonl(ruta: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]


def configuracion() -> dict[str, Any]:
    """Rutas y SHA-256 esperados, tomados de la conversion (una sola fuente de verdad)."""
    conversion = yaml.safe_load((MODELO / "conversion.yaml").read_text(encoding="utf-8"))
    registro = json.loads((MODELO / "registros" / "registro_conversion.json").read_text("utf-8"))
    seleccion = json.loads((P3 / "docs" / "selection.json").read_text(encoding="utf-8"))
    cal = conversion["calibracion"]
    version = conversion["variante"]["version"]
    artefactos = MODELO / "artefactos" / version
    salidas = registro["salidas"]
    return {
        "variante": version,
        "entrada_onnx": conversion["variante"]["entrada"],
        "manifiesto": {"ruta": RAIZ / cal["manifiesto"], "sha256": cal["manifiesto_sha256"]},
        "recortes": RAIZ / cal["recortes"],
        "crops_jsonl_sha256": seleccion["crops_jsonl_sha256"],
        "modelos": {
            "original": {
                "ruta": RAIZ / conversion["origen"]["checkpoint"],
                "sha256": conversion["origen"]["sha256"],
                "s3": f"modelos/clasificador-p3/{conversion['origen']['version_p3']}/model.pt",
            },
            **{
                nombre: {
                    "ruta": artefactos / salidas[nombre]["archivo"],
                    "sha256": salidas[nombre]["sha256"],
                    "s3": f"modelos/clasificador-edge/{version}/{salidas[nombre]['archivo']}",
                }
                for nombre in ("fp32", "int8")
            },
        },
        "calibracion_ids": MODELO / "registros" / "calibracion_ids.jsonl",
        # Inventario congelado con el SHA-256 de cada recorte (validacion/inventario_recortes.py).
        "inventario": REGISTROS_VAL / f"recortes_{Path(cal['recortes']).name}.jsonl",
        # Huella de validacion del modelo seleccionado, registrada por el P3.
        "seleccion_p3": {k: seleccion[k] for k in ("run_id", "val_accuracy", "val_loss")},
    }


# ---------------------------------------------------------------------------
# Muestras y comprobaciones previas (sin modelos)
# ---------------------------------------------------------------------------


class ComparacionError(Exception):
    """Una condicion de VAL-02 no se cumple: no se escribe una comparacion invalida."""


def exigir_sha(ruta: Path, esperado: str, que: str) -> None:
    if not ruta.is_file():
        raise ComparacionError(f"No existe {que}: {ruta}")
    obtenido = sha256(ruta)
    if obtenido != esperado:
        raise ComparacionError(f"{que} {ruta} tiene SHA-256 {obtenido}; se esperaba {esperado}")


def muestras_val(
    manifiesto: list[dict[str, Any]], recortes: Path, clases: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Filas `val` del manifiesto con su imagen, y las que faltan con su motivo."""
    recortes_meta = {r["crop_id"]: r for r in leer_jsonl(recortes / "crops.jsonl")}
    rutas = {cid: r["crop_path"] for cid, r in recortes_meta.items()}
    muestras, faltantes = [], []
    for fila in manifiesto:
        if fila["split"] != SPLIT:
            continue
        cid = fila["crop_id"]
        if clases[fila["class_index"]] != fila["category_name"]:
            raise ComparacionError(
                f"{cid}: class_index {fila['class_index']} no es {fila['category_name']}"
            )
        if cid not in rutas:
            faltantes.append({"sample_id": cid, "motivo": "no esta en crops.jsonl"})
        elif not (recortes / rutas[cid]).is_file():
            faltantes.append({"sample_id": cid, "motivo": f"no existe {rutas[cid]}"})
        else:
            muestras.append(
                {
                    "sample_id": cid,
                    "true_class": fila["category_name"],
                    "ruta": recortes / rutas[cid],
                    "tamano": (recortes_meta[cid].get("width"), recortes_meta[cid].get("height")),
                }
            )
    return muestras, faltantes


def dimensiones_distintas(muestras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recortes cuyo PNG no mide lo que dice `crops.jsonl` (archivo equivocado o corrupto)."""
    from PIL import Image

    distintas = []
    for m in muestras:
        with Image.open(m["ruta"]) as imagen:
            if imagen.size != tuple(m["tamano"]):
                distintas.append(
                    {"sample_id": m["sample_id"], "esperado": m["tamano"], "png": imagen.size}
                )
    return distintas


def cargar_inventario(ruta: Path) -> dict[str, str]:
    """`crop_id -> sha256` del inventario, tras comprobar el SHA-256 que registra su resumen."""
    resumen = ruta.with_suffix(".json")
    if not ruta.is_file() or not resumen.is_file():
        raise ComparacionError(f"No existe el inventario de recortes {ruta} (y su .json)")
    esperado = json.loads(resumen.read_text(encoding="utf-8"))["inventario"]["sha256"]
    exigir_sha(ruta, esperado, "inventario de recortes")
    return {f["crop_id"]: f["sha256"] for f in leer_jsonl(ruta)}


def hashes_distintos(
    muestras: list[dict[str, Any]], inventario: dict[str, str]
) -> list[dict[str, str]]:
    """Recortes cuyo PNG no tiene el SHA-256 del inventario congelado."""
    distintos = []
    for m in muestras:
        esperado = inventario.get(m["sample_id"])
        obtenido = sha256(m["ruta"])
        if obtenido != esperado:
            distintos.append({"sample_id": m["sample_id"], "esperado": esperado, "png": obtenido})
    return distintos


def huella_p3(
    filas: list[dict[str, Any]], seleccion: dict[str, Any], tolerancia: float = 1e-5
) -> dict[str, Any]:
    """Accuracy y val_loss del original sobre estas imagenes contra los registrados por el P3.

    El P3 guardo en `selection.json` el accuracy y la perdida de validacion del modelo
    seleccionado. Recalcularlos con las probabilidades del original sobre estas imagenes
    comprueba, por otro camino que el hash, que son las mismas que evaluo el P3: la
    perdida es continua y se moveria con cualquier imagen distinta. La tolerancia cubre
    float32 por muestra contra por lotes.
    """
    n = len(filas)
    accuracy = sum(f["original_prediction"] == f["true_class"] for f in filas) / n
    perdida = sum(-math.log(float(f[f"prob_original_{f['true_class']}"])) for f in filas) / n
    return {
        "run_id": seleccion["run_id"],
        "val_accuracy": {"recalculada": accuracy, "p3": seleccion["val_accuracy"]},
        "val_loss": {
            "recalculada": perdida,
            "p3": seleccion["val_loss"],
            "diferencia": abs(perdida - seleccion["val_loss"]),
            "tolerancia": tolerancia,
        },
        "ok": accuracy == seleccion["val_accuracy"]
        and abs(perdida - seleccion["val_loss"]) <= tolerancia,
    }


def comprobar_calibracion(
    manifiesto: list[dict[str, Any]], calibracion: list[dict[str, Any]]
) -> dict[str, Any]:
    """Cada ID de calibracion del INT8 debe ser `train` segun el manifiesto del P3."""
    split_de = {f["crop_id"]: f["split"] for f in manifiesto}
    por_split = Counter(split_de.get(c["crop_id"], "ausente") for c in calibracion)
    fuera = sorted(c["crop_id"] for c in calibracion if split_de.get(c["crop_id"]) != "train")
    return {
        "muestras": len(calibracion),
        "por_split_segun_manifiesto": dict(sorted(por_split.items())),
        "fuera_de_train": fuera,
        "solo_train": not fuera,
    }


# ---------------------------------------------------------------------------
# Comparacion y evidencia
# ---------------------------------------------------------------------------


def comparar(
    muestras: Iterable[dict[str, Any]], predictores: dict[str, Predictor], clases: list[str]
) -> list[dict[str, Any]]:
    filas = []
    for m in muestras:
        fila: dict[str, Any] = {"sample_id": m["sample_id"], "true_class": m["true_class"]}
        probs = {nombre: predictores[nombre](m["ruta"]) for nombre in MODELOS}
        for nombre in MODELOS:
            fila[f"{nombre}_prediction"] = clases[
                max(range(len(clases)), key=probs[nombre].__getitem__)
            ]
        fila["optimized_prediction"] = fila["int8_prediction"]
        for nombre in MODELOS:
            for clase, p in zip(clases, probs[nombre], strict=True):
                fila[f"prob_{nombre}_{clase}"] = repr(float(p))
        filas.append(fila)
    return filas


def columnas(clases: list[str]) -> list[str]:
    return [
        "sample_id",
        "true_class",
        "original_prediction",
        "optimized_prediction",
        "fp32_prediction",
        "int8_prediction",
        "int8_referencia_prediction",
        *(f"prob_{n}_{c}" for n in MODELOS for c in clases),
    ]


def csv_bytes(filas: list[dict[str, Any]], clases: list[str]) -> bytes:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=columnas(clases), lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return salida.getvalue().encode("utf-8")


def verificar_csv(
    datos: bytes, esperadas: list[dict[str, Any]], faltantes: list[dict[str, str]]
) -> dict[str, Any]:
    """Relee el CSV escrito: mismos IDs y etiquetas que `val`, sin duplicados ni faltantes."""
    filas = list(csv.DictReader(io.StringIO(datos.decode("utf-8"))))
    ids = [f["sample_id"] for f in filas]
    etiqueta = {m["sample_id"]: m["true_class"] for m in esperadas}
    duplicados = sorted(k for k, n in Counter(ids).items() if n > 1)
    resultado = {
        "filas": len(filas),
        "ids_unicos": len(set(ids)),
        "duplicados": duplicados,
        "mismos_ids_que_val": set(ids) == set(etiqueta) and len(ids) == len(etiqueta),
        "mismo_orden_que_manifiesto": ids == [m["sample_id"] for m in esperadas],
        "etiquetas_iguales_al_manifiesto": all(
            etiqueta.get(f["sample_id"]) == f["true_class"] for f in filas
        ),
        # Cada faltante lleva su motivo, pero la comparacion exige el val completo.
        "faltantes": faltantes,
    }
    resultado["ok"] = (
        not duplicados
        and resultado["mismos_ids_que_val"]
        and resultado["etiquetas_iguales_al_manifiesto"]
        and not faltantes
    )
    return resultado


def resumen(filas: list[dict[str, Any]], clases: list[str]) -> dict[str, Any]:
    n = len(filas)
    aciertos = {m: sum(f[f"{m}_prediction"] == f["true_class"] for f in filas) for m in MODELOS}
    return {
        "muestras": n,
        "por_clase": dict(sorted(Counter(f["true_class"] for f in filas).items())),
        "aciertos": aciertos,
        "accuracy": {m: aciertos[m] / n for m in MODELOS} if n else {},
        "acuerdo_int8_vs_original": sum(
            f["int8_prediction"] == f["original_prediction"] for f in filas
        ),
        "acuerdo_int8_vs_fp32": sum(f["int8_prediction"] == f["fp32_prediction"] for f in filas),
        "acuerdo_int8_vs_int8_referencia": sum(
            f["int8_prediction"] == f["int8_referencia_prediction"] for f in filas
        ),
        "nota": "Metricas formales por clase y analisis de errores: VAL-04 (#14).",
        "clases_presentes": sorted({f["true_class"] for f in filas}) == sorted(clases),
    }


# ---------------------------------------------------------------------------
# Modelos reales (torch y onnxruntime se importan solo aqui)
# ---------------------------------------------------------------------------


def crear_predictores(cfg: dict[str, Any]) -> tuple[dict[str, Predictor], list[str], dict]:
    import numpy as np
    import onnxruntime as ort
    import torch
    from PIL import Image

    sys.path.insert(0, str(MODELO))
    sys.path.insert(0, str(P3 / "src"))
    from p3.data.transforms import build_eval_transform
    from p3.model.build import load_checkpoint
    from preprocesar import preprocesar, softmax

    modelo, meta = load_checkpoint(cfg["modelos"]["original"]["ruta"])
    tamano = meta["preprocessing"]["image_size"]
    transformar = build_eval_transform(tamano)

    def original(ruta: Path) -> list[float]:
        with Image.open(ruta) as imagen, torch.no_grad():
            x = transformar(imagen.convert("RGB")).unsqueeze(0)
            return torch.softmax(modelo(x), dim=1)[0].tolist()

    def onnx(nombre: str, optimizado: bool = True) -> Predictor:
        opciones = ort.SessionOptions()
        opciones.log_severity_level = 3
        if not optimizado:
            opciones.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        sesion = ort.InferenceSession(
            str(cfg["modelos"][nombre]["ruta"]), opciones, providers=["CPUExecutionProvider"]
        )

        def predecir(ruta: Path) -> list[float]:
            with Image.open(ruta) as imagen:
                x = preprocesar(imagen, tamano)
            logits = sesion.run(None, {cfg["entrada_onnx"]: x})[0]
            return [float(p) for p in softmax(np.asarray(logits))[0]]

        return predecir

    entorno = {
        "torch": torch.__version__,
        "onnxruntime": ort.__version__,
        "numpy": np.__version__,
        "proveedor_onnx": "CPUExecutionProvider",
    }
    return (
        {
            "original": original,
            "fp32": onnx("fp32"),
            "int8": onnx("int8"),
            "int8_referencia": onnx("int8", optimizado=False),
        },
        list(meta["class_names"]),
        entorno,
    )


def procesador() -> str:
    """Nombre del CPU: el resultado de los kernels enteros del INT8 puede cambiar con el CPU."""
    try:
        if platform.system() == "Windows":
            import winreg

            clave = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, clave) as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        for linea in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if linea.split(":")[0].strip() in ("model name", "Model", "Hardware"):
                return linea.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "desconocido"


def descargar(cfg: dict[str, Any], perfil: str, bucket: str) -> None:
    """Baja de S3 los modelos y los datos del P3 que falten en local.

    Los datos viven en `datos/p3/` con las mismas rutas que bajo `Proyecto3/data/`. Lo
    descargado no se da por bueno: despues se exige el SHA-256 de cada insumo.
    """
    import boto3

    s3 = boto3.Session(profile_name=perfil).client("s3")
    for nombre, modelo in cfg["modelos"].items():
        if modelo["ruta"].is_file():
            continue
        modelo["ruta"].parent.mkdir(parents=True, exist_ok=True)
        print(f"Descargando {nombre}: s3://{bucket}/{modelo['s3']}")
        s3.download_file(bucket, modelo["s3"], str(modelo["ruta"]))

    datos_p3 = (P3 / "data").resolve()
    for carpeta in (cfg["manifiesto"]["ruta"].parent, cfg["recortes"]):
        local = carpeta.resolve()
        prefijo = "datos/p3/" + local.relative_to(datos_p3).as_posix() + "/"
        print(f"Datos: s3://{bucket}/{prefijo} -> {local}")
        for pagina in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefijo):
            for objeto in pagina.get("Contents", []):
                destino = local / objeto["Key"][len(prefijo) :]
                if not destino.is_file():
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    s3.download_file(bucket, objeto["Key"], str(destino))


def fallas(evidencia: dict[str, Any]) -> list[str]:
    """Validaciones de VAL-02 que la corrida no cumple (vacia si la evidencia es valida)."""
    problemas = []
    if not evidencia["verificacion"]["ok"]:
        problemas.append("el CSV no tiene exactamente los IDs y etiquetas de val")
    if not evidencia["calibracion"]["solo_train"]:
        fuera = evidencia["calibracion"]["fuera_de_train"]
        problemas.append(f"la calibracion usa IDs fuera de train: {fuera}")
    if not evidencia["resumen"]["clases_presentes"]:
        problemas.append("no estan todas las clases en val")
    if not evidencia["huella_p3"]["ok"]:
        problemas.append("el original no reproduce el val_accuracy/val_loss del P3")
    return problemas


def guardar(destino: Path, datos: bytes, evidencia: dict[str, Any]) -> None:
    """Escribe CSV y JSON solo si la corrida es valida, sin dejar evidencia a medias.

    Si alguna validacion falla no toca los archivos existentes. Si pasa, escribe cada
    archivo en un temporal del mismo directorio y despues lo renombra (`os.replace` es
    atomico por archivo): una corrida interrumpida no deja un CSV o un JSON a medias. El
    CSV se reemplaza antes que el JSON y el JSON guarda el SHA-256 del CSV, asi que si
    algo cortara la ejecucion entre los dos renombres, el par desparejo se detecta.
    """
    problemas = fallas(evidencia)
    if problemas:
        raise ComparacionError(
            "no se escribio evidencia; la anterior queda intacta: " + "; ".join(problemas)
        )
    destino.mkdir(parents=True, exist_ok=True)
    salidas = {
        ARCHIVO_CSV: datos,
        ARCHIVO_JSON: (json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n").encode(),
    }
    temporales = {}
    try:
        for nombre, contenido in salidas.items():
            temporales[nombre] = destino / f".{nombre}.tmp"
            temporales[nombre].write_bytes(contenido)
        for nombre, temporal in temporales.items():
            os.replace(temporal, destino / nombre)
    finally:
        for temporal in temporales.values():
            temporal.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--descargar",
        action="store_true",
        help="bajar de S3 los modelos y los datos del P3 que falten",
    )
    parser.add_argument("--profile", help="perfil de AWS para --descargar")
    parser.add_argument("--bucket", default=BUCKET)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cfg = configuracion()
    if args.descargar:
        descargar(cfg, args.profile, args.bucket)
    try:
        exigir_sha(cfg["manifiesto"]["ruta"], cfg["manifiesto"]["sha256"], "manifiesto")
        exigir_sha(cfg["recortes"] / "crops.jsonl", cfg["crops_jsonl_sha256"], "crops.jsonl")
        for nombre, modelo in cfg["modelos"].items():
            exigir_sha(modelo["ruta"], modelo["sha256"], f"modelo {nombre}")
    except ComparacionError as error:
        raise SystemExit(f"FALLA: {error}") from error

    manifiesto = leer_jsonl(cfg["manifiesto"]["ruta"])
    calibracion = comprobar_calibracion(manifiesto, leer_jsonl(cfg["calibracion_ids"]))
    predictores, clases, entorno = crear_predictores(cfg)
    muestras, faltantes = muestras_val(manifiesto, cfg["recortes"], clases)
    print(f"{len(muestras)} muestras de {SPLIT}; faltantes: {len(faltantes)}")

    distintas = dimensiones_distintas(muestras)
    if distintas:
        raise SystemExit(f"FALLA: recortes con dimensiones distintas a crops.jsonl: {distintas}")
    try:
        inventario = cargar_inventario(cfg["inventario"])
    except ComparacionError as error:
        raise SystemExit(f"FALLA: {error}") from error
    distintos = hashes_distintos(muestras, inventario)
    if distintos:
        raise SystemExit(f"FALLA: recortes con SHA-256 distinto al inventario: {distintos}")

    filas = comparar(muestras, predictores, clases)
    datos = csv_bytes(filas, clases)
    verificacion = verificar_csv(datos, muestras, faltantes)

    # Todo se arma en memoria; solo se escribe si la corrida pasa todas las validaciones.
    evidencia = {
        "schema_version": 1,
        "tarea": "VAL-02 (#2)",
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "comando": "modelo/.venv/Scripts/python validacion/comparar_modelos.py",
        "split": SPLIT,
        "clases": clases,
        "manifiesto": {
            "ruta": str(cfg["manifiesto"]["ruta"].relative_to(RAIZ.parent)).replace("\\", "/"),
            "sha256": cfg["manifiesto"]["sha256"],
            "crops_jsonl_sha256": cfg["crops_jsonl_sha256"],
            "filas_val": len(muestras) + len(faltantes),
            "recortes_con_dimensiones_de_crops_jsonl": len(muestras),
            "recortes_con_sha256_del_inventario": len(muestras),
            "inventario": {
                "archivo": cfg["inventario"].name,
                "sha256": sha256(cfg["inventario"]),
            },
        },
        "modelos": {
            n: {
                "archivo": m["ruta"].name,
                "sha256": m["sha256"],
                "preprocesamiento": "build_eval_transform del P3 (torchvision)"
                if n == "original"
                else "modelo/preprocesar.py (numpy + Pillow)",
            }
            for n, m in cfg["modelos"].items()
        },
        "columnas_int8": {
            "int8": "onnxruntime con optimizaciones por defecto (kernels enteros fusionados); "
            "puede cambiar con el CPU. Hipotesis sin confirmar: saturacion U8S8 en x86 sin VNNI",
            "int8_referencia": "mismo model_int8.onnx con ORT_DISABLE_ALL: QDQ ejecutado tal "
            "cual, sin kernels enteros fusionados",
            "optimized_prediction": "igual a int8_prediction",
        },
        "calibracion": calibracion,
        "verificacion": verificacion,
        "resumen": resumen(filas, clases),
        "huella_p3": huella_p3(filas, cfg["seleccion_p3"]),
        "csv": {"archivo": ARCHIVO_CSV, "sha256": hashlib.sha256(datos).hexdigest()},
        "entorno": {
            "python": platform.python_version(),
            "sistema": platform.system(),
            "maquina": platform.machine(),
            "procesador": procesador(),
            **entorno,
        },
    }
    r = evidencia["resumen"]
    print(f"accuracy: {r['accuracy']}")
    print(f"acuerdo int8/original: {r['acuerdo_int8_vs_original']}/{r['muestras']}")
    print(f"acuerdo int8/int8_referencia: {r['acuerdo_int8_vs_int8_referencia']}/{r['muestras']}")
    print(f"calibracion solo train: {calibracion['solo_train']}; CSV ok: {verificacion['ok']}")
    huella = evidencia["huella_p3"]
    print(
        f"huella P3: val_acc {huella['val_accuracy']['recalculada']:.6f}, val_loss "
        f"{huella['val_loss']['recalculada']:.7f} (P3 {huella['val_loss']['p3']:.7f}); "
        f"ok: {huella['ok']}"
    )
    try:
        guardar(RESULTADOS, datos, evidencia)
    except ComparacionError as error:
        raise SystemExit(f"FALLA: {error}") from error
    print(f"Evidencia escrita en {RESULTADOS.relative_to(RAIZ).as_posix()}/")


if __name__ == "__main__":
    main()
