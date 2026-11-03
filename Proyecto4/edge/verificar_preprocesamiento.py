"""VAL-07 (#19): preprocesamiento y entradas conocidas en el runtime del edge (rubrica 2.2, 6.2).

El **mismo** script corre en la Raspberry y en la laptop de VAL ("offline"), con las mismas
entradas y los mismos modelos, para contrastar despues los dos resultados:

1. **Comprobaciones sinteticas** del preprocesamiento (`modelo/preprocesar.py`), contra
   valores calculados a mano en float32, sin depender de ninguna otra maquina:
   RGB y orden de canales, tamano 224x224 estirando sin recortar, escala [0, 1], media y
   desviacion de ImageNet, conversion de grises y RGBA, forma `[1, 3, 224, 224]` float32.
2. **Entradas conocidas** (`entradas.jsonl` del paquete de `validacion/preparar_entradas_edge.py`:
   los 292 recortes `val` y las fotos de la camara de EDGE-03), verificadas por SHA-256.
   Para cada una registra el SHA-256 del tensor preprocesado y los logits y la clase de:
   - `int8`: model_int8.onnx con onnxruntime por defecto (como `edge/inferencia.py`);
   - `int8_referencia`: el mismo archivo con `ORT_DISABLE_ALL` (QDQ paso a paso);
   - `fp32`: model_fp32.onnx (el original sin cuantizar) con onnxruntime por defecto.

No hace llamadas de red. En la Raspberry (ver docs/preprocesamiento-edge.md):

    cd "$HOME/edge01" && source .venv/bin/activate
    python app/verificar_preprocesamiento.py

Escribe `<salida>/resultados.csv` (una fila por entrada) y `<salida>/resultados.json`
(dispositivo, runtime, modelos, comprobaciones sinteticas y conteos).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

AQUI = Path(__file__).resolve().parent
BASE = AQUI.parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(BASE / "modelo"))

import benchmark as bench  # noqa: E402
from preprocesar import DESVIACION, MEDIA, TAMANO, preprocesar  # noqa: E402

CLASES = bench.CLASES
EJECUCIONES = ("int8", "int8_referencia", "fp32")


# ---------------------------------------------------------------------------
# Comprobaciones sinteticas: valores esperados calculados a mano
# ---------------------------------------------------------------------------


def esperado(rgb: tuple[int, int, int]) -> np.ndarray:
    """Valor normalizado de un pixel, con las mismas operaciones float32 de preprocesar."""
    x = np.asarray([[list(rgb)]], dtype=np.float32) / 255.0
    return ((x - MEDIA) / DESVIACION)[0, 0]


def sha_tensor(tensor: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(tensor, dtype="<f4").tobytes()).hexdigest()


def comprobaciones_sinteticas() -> list[dict[str, Any]]:
    resultado = []

    def anotar(id_: str, ok: bool, detalle: str, tensor: np.ndarray | None = None) -> None:
        fila = {"id": id_, "ok": bool(ok), "detalle": detalle}
        if tensor is not None:
            fila["tensor_sha256"] = sha_tensor(tensor)
        resultado.append(fila)

    # 1. Forma, tipo y contigüidad.
    t = preprocesar(Image.new("RGB", (64, 48), (255, 128, 0)))
    anotar(
        "tensor.forma_tipo",
        t.shape == (1, 3, TAMANO, TAMANO) and t.dtype == np.float32 and t.flags["C_CONTIGUOUS"],
        f"forma {list(t.shape)}, tipo {t.dtype}, NCHW contiguo; TAMANO={TAMANO}",
        t,
    )
    # 2. Escala [0, 1], media y desviacion de ImageNet, canal 0 = R: color solido exacto.
    valor = esperado((255, 128, 0))
    anotar(
        "normalizacion.exacta",
        all(np.array_equal(t[0, c], np.full((TAMANO, TAMANO), valor[c])) for c in range(3)),
        f"(255,128,0) -> {[float(v) for v in valor]} en los 224x224 pixeles, igual bit a bit a "
        f"(x/255 - media {MEDIA.tolist()}) / desviacion {DESVIACION.tolist()}",
        t,
    )
    # 3. Orden de canales y orientacion: mitad izquierda roja, derecha azul.
    mitades = Image.new("RGB", (448, 224), (0, 0, 255))
    mitades.paste((255, 0, 0), (0, 0, 224, 224))
    t = preprocesar(mitades)
    rojo, azul = esperado((255, 0, 0)), esperado((0, 0, 255))
    anotar(
        "rgb.orden_y_orientacion",
        np.array_equal(t[0, :, :, :100], np.broadcast_to(rojo[:, None, None], (3, 224, 100)))
        and np.array_equal(t[0, :, :, -100:], np.broadcast_to(azul[:, None, None], (3, 224, 100))),
        "izquierda roja y derecha azul se conservan: RGB (no BGR), sin espejo ni transposicion",
        t,
    )
    # 4. Estirar a 224x224 sin recortar: una franja en el borde izquierdo sobrevive.
    ancho = Image.new("RGB", (400, 100), (255, 255, 255))
    ancho.paste((0, 0, 0), (0, 0, 8, 100))
    t = preprocesar(ancho)
    negro, blanco = esperado((0, 0, 0)), esperado((255, 255, 255))
    anotar(
        "resize.sin_recorte",
        np.array_equal(t[0, :, :, 0], np.broadcast_to(negro[:, None], (3, 224)))
        and np.array_equal(t[0, :, :, -1], np.broadcast_to(blanco[:, None], (3, 224))),
        "400x100 con franja negra en x<8 -> la franja queda en la columna 0: se estira la "
        "imagen completa (resize_to_square), no hay recorte central",
        t,
    )
    # 5. Escala [0, 1]: un degradado 0..255 vuelve a [0, 1] al deshacer la normalizacion.
    degradado = Image.fromarray(np.tile(np.arange(256, dtype=np.uint8), (16, 1)), "L")
    t = preprocesar(degradado)
    crudo = t[0] * DESVIACION[:, None, None] + MEDIA[:, None, None]
    anotar(
        "escala.cero_uno",
        abs(float(crudo.min())) < 1e-6 and abs(float(crudo.max()) - 1) < 1e-6,
        f"degradado 0..255 -> [{float(crudo.min()):.7f}, {float(crudo.max()):.7f}] tras deshacer "
        "media y desviacion",
        t,
    )
    # 6. Grises y RGBA se convierten a RGB.
    t_gris = preprocesar(Image.new("L", (30, 30), 77))
    t_rgba = preprocesar(Image.new("RGBA", (30, 30), (10, 20, 30, 0)))
    anotar(
        "rgb.conversion",
        np.array_equal(t_gris[0, :, 0, 0], esperado((77, 77, 77)))
        and np.array_equal(t_rgba[0, :, 0, 0], esperado((10, 20, 30))),
        "gris 77 -> (77,77,77); RGBA (10,20,30,0) -> (10,20,30): alfa descartado",
    )
    return resultado


# ---------------------------------------------------------------------------
# Entradas conocidas y modelos
# ---------------------------------------------------------------------------


def sesiones(modelos: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Las tres ejecuciones, cada una con el SHA-256 del archivo verificado."""
    import onnxruntime as ort

    ejecutores, identidad = {}, {}
    for nombre, clave, optimizado in (
        ("int8", "int8", True),
        ("int8_referencia", "int8", False),
        ("fp32", "fp32", True),
    ):
        especificacion = bench.MODELOS[clave]
        datos = (modelos / especificacion["archivo"]).read_bytes()
        digest = hashlib.sha256(datos).hexdigest()
        if digest != especificacion["sha256"]:
            raise ValueError(f"{especificacion['archivo']}: SHA-256 {digest} incorrecto")
        opciones = ort.SessionOptions()
        if not optimizado:
            opciones.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        sesion = ort.InferenceSession(datos, opciones, providers=["CPUExecutionProvider"])
        entrada, salida = sesion.get_inputs()[0], sesion.get_outputs()[0]
        if entrada.shape != [1, 3, TAMANO, TAMANO] or salida.shape != [1, len(CLASES)]:
            raise ValueError(f"{nombre}: forma inesperada {entrada.shape} -> {salida.shape}")
        ejecutores[nombre] = (sesion, entrada.name, salida.name)
        identidad[nombre] = {
            "archivo": especificacion["archivo"],
            "version": especificacion["version"],
            "sha256": digest,
            "optimizaciones": "por defecto" if optimizado else "ORT_DISABLE_ALL",
            "entrada": {"nombre": entrada.name, "forma": entrada.shape, "tipo": entrada.type},
            "salida": {"nombre": salida.name, "forma": salida.shape},
        }
    return ejecutores, identidad


def evaluar(entrada: dict[str, Any], datos: bytes, ejecutores: dict[str, Any]) -> dict[str, Any]:
    with Image.open(io.BytesIO(datos)) as imagen:
        modo, tamano = imagen.mode, list(imagen.size)
        tensor = preprocesar(imagen)
    fila = {
        "id": entrada["id"],
        "tipo": entrada["tipo"],
        "clase": entrada["clase"],
        "archivo_sha256": entrada["sha256"],
        "imagen_modo": modo,
        "imagen_tamano": f"{tamano[0]}x{tamano[1]}",
        "tensor_forma": "x".join(str(d) for d in tensor.shape),
        "tensor_tipo": str(tensor.dtype),
        "tensor_sha256": sha_tensor(tensor),
    }
    for nombre in EJECUCIONES:
        sesion, nombre_entrada, nombre_salida = ejecutores[nombre]
        logits = np.asarray(sesion.run([nombre_salida], {nombre_entrada: tensor})[0])[0]
        fila[f"{nombre}_prediction"] = CLASES[int(logits.argmax())]
        for clase, valor in zip(CLASES, logits, strict=True):
            fila[f"{nombre}_logit_{clase}"] = repr(float(valor))
    return fila


def columnas() -> list[str]:
    base = [
        "id",
        "tipo",
        "clase",
        "archivo_sha256",
        "imagen_modo",
        "imagen_tamano",
        "tensor_forma",
        "tensor_tipo",
        "tensor_sha256",
    ]
    for nombre in EJECUCIONES:
        base.append(f"{nombre}_prediction")
        base += [f"{nombre}_logit_{c}" for c in CLASES]
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--entradas", type=Path, default=BASE / "entradas_edge")
    parser.add_argument("--modelos", type=Path, default=BASE / "modelo")
    parser.add_argument("--salida", type=Path, default=BASE / "evidencias" / "VAL-07")
    parser.add_argument("--maquina", default="raspberry", help="nombre de la corrida")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    sinteticas = comprobaciones_sinteticas()
    for c in sinteticas:
        print(f"[{'ok' if c['ok'] else 'FALLA':5}] {c['id']}")

    indice = (args.entradas / "entradas.jsonl").read_bytes()
    entradas = [json.loads(x) for x in indice.decode("utf-8").splitlines() if x.strip()]
    ejecutores, identidad = sesiones(args.modelos)
    filas = []
    for numero, entrada in enumerate(entradas, 1):
        datos = (args.entradas / entrada["archivo"]).read_bytes()
        if hashlib.sha256(datos).hexdigest() != entrada["sha256"]:
            raise SystemExit(f"FALLA: {entrada['archivo']} no tiene el SHA-256 del indice")
        filas.append(evaluar(entrada, datos, ejecutores))
        if numero % 50 == 0:
            print(f"  {numero}/{len(entradas)} entradas")

    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=columnas(), lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(filas)
    datos_csv = salida.getvalue().encode("utf-8")
    destino = args.salida / args.maquina
    destino.mkdir(parents=True, exist_ok=True)
    evidencia = {
        "schema_version": 1,
        "tarea": "VAL-07 (#19)",
        "maquina": args.maquina,
        "fecha": datetime.now().astimezone().isoformat(),
        "hardware": bench.hardware(),
        "runtime": bench.runtime(),
        "codigo": {
            "verificar_preprocesamiento.py": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "preprocesar.py": hashlib.sha256(
                Path(preprocesar.__code__.co_filename).read_bytes()
            ).hexdigest(),
        },
        "preprocesamiento": {
            "entrada_esperada": {
                "forma": [1, 3, TAMANO, TAMANO],
                "tipo": "float32",
                "orden": "NCHW, RGB",
            },
            "media": MEDIA.tolist(),
            "desviacion": DESVIACION.tolist(),
            "clases": list(CLASES),
            "comprobaciones_sinteticas": sinteticas,
        },
        "modelos": identidad,
        "entradas": {
            "indice_sha256": hashlib.sha256(indice).hexdigest(),
            "total": len(entradas),
            "por_tipo": {t: sum(e["tipo"] == t for e in entradas) for t in ("val", "camara")},
        },
        "resultados": {
            "archivo": "resultados.csv",
            "sha256": hashlib.sha256(datos_csv).hexdigest(),
            "filas": len(filas),
        },
    }
    (destino / "resultados.csv").write_bytes(datos_csv)
    (destino / "resultados.json").write_bytes(
        (json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    for nombre in EJECUCIONES:
        aciertos = sum(f[f"{nombre}_prediction"] == f["clase"] for f in filas if f["tipo"] == "val")
        print(f"{nombre}: {aciertos}/{evidencia['entradas']['por_tipo']['val']} aciertos en val")
    print(f"Escrito {destino / 'resultados.csv'} y resultados.json")
    return 0 if all(c["ok"] for c in sinteticas) else 1


if __name__ == "__main__":
    sys.exit(main())
