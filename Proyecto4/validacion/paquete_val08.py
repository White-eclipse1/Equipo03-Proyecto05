# ruff: noqa: E501, RUF001  (plantilla del README en Markdown: lineas largas y signos tipograficos)
"""Construye el paquete de evidencia de calidad y recursos para el evaluador (VAL-08, #24).

Copia en `evidencias/VAL-08/` los datos primarios y los resultados de VAL-01 a VAL-07, para
que el evaluador recalcule todo **solo con el paquete** (`python recalcular.py`):

    modelo/       ficha_modelos.json (identidad, hashes, tamanos, S3), registro de
                  conversion, verificacion de linaje (VAL-01), IDs de calibracion
    validacion/   extracto val del manifiesto y su meta, predicciones por muestra (VAL-03),
                  metricas (VAL-04), contraste del preprocesamiento en el edge (VAL-07) y
                  primarios/: probabilidades del original (VAL-02) y logits del INT8 en la
                  Raspberry (VAL-07)
    benchmark/    tiempos crudos y condiciones de la Raspberry (VAL-05), recursos (VAL-06)
    recalcular.py README.md SHA256SUMS.txt

Arma el paquete en una carpeta temporal, corre `recalcular.py` sobre ella y solo si da
VERIFICADO reemplaza `evidencias/VAL-08/`.

    cd Proyecto4
    python validacion/paquete_val08.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent  # Proyecto4/
RES = AQUI / "resultados"
DESTINO = RAIZ / "evidencias" / "VAL-08"

COPIAS = {
    "modelo/registro_conversion.json": RAIZ / "modelo/registros/registro_conversion.json",
    "modelo/linaje_verificacion.json": RAIZ / "modelo/registros/linaje_verificacion.json",
    "modelo/calibracion_ids.jsonl": RAIZ / "modelo/registros/calibracion_ids.jsonl",
    "validacion/manifest_val.jsonl": RES / "manifiesto/manifest_val.jsonl",
    "validacion/manifest.meta.json": RES / "manifiesto/manifest.meta.json",
    "validacion/predicciones_val.csv": RES / "predicciones_val.csv",
    "validacion/predicciones_val.json": RES / "predicciones_val.json",
    "validacion/metricas_val.json": RES / "metricas_val.json",
    "validacion/metricas_val.csv": RES / "metricas_val.csv",
    "validacion/contraste_edge.json": RES / "contraste_edge.json",
    "validacion/entradas_conocidas.csv": RES / "entradas_conocidas.csv",
    "validacion/primarios/comparacion_val_val02.csv": RES / "comparacion_val.csv",
    "validacion/primarios/comparacion_val_val02.json": RES / "comparacion_val.json",
    "validacion/primarios/resultados_raspberry_val07.csv": (
        RAIZ / "evidencias/VAL-07/raspberry/resultados.csv"
    ),
    "validacion/primarios/resultados_raspberry_val07.json": (
        RAIZ / "evidencias/VAL-07/raspberry/resultados.json"
    ),
    "benchmark/tiempos.csv": RAIZ / "evidencias/VAL-05/tiempos.csv",
    "benchmark/benchmark.json": RAIZ / "evidencias/VAL-05/benchmark.json",
    "benchmark/recursos_edge.json": RES / "recursos_edge.json",
    "benchmark/recursos_edge.csv": RES / "recursos_edge.csv",
    "recalcular.py": AQUI / "recalcular_paquete.py",
}


def leer_json(ruta: Path) -> Any:
    return json.loads(ruta.read_text(encoding="utf-8"))


def ficha_modelos() -> dict[str, Any]:
    """Identidad de los modelos desde el registro de conversion y el linaje (VAL-01)."""
    registro = leer_json(RAIZ / "modelo/registros/registro_conversion.json")
    linaje = leer_json(RAIZ / "modelo/registros/linaje_verificacion.json")
    objetos = linaje["ficha"]["publicacion"]["objetos"]
    s3 = {k.rsplit("/", 1)[-1]: (k, v) for k, v in objetos.items()}
    bucket = linaje["ficha"]["publicacion"]["bucket"]

    def ubicacion(archivo: str) -> dict[str, Any]:
        llave, objeto = s3[archivo]
        return {"s3": f"s3://{bucket}/{llave}", "version_id": objeto["version_id"]}

    entrada, salidas = registro["entrada"], registro["salidas"]
    original = linaje["ficha"]["original"]
    reduccion = Fraction(entrada["bytes"] - salidas["int8"]["bytes"], entrada["bytes"]) * 100
    return {
        "schema_version": 1,
        "tarea": "VAL-08 (#24)",
        "original": {
            "descripcion": "modelo publicado 1.0.0 del Proyecto 3 (PyTorch)",
            "version": entrada["version_p3"],
            "run_id": entrada["run_id"],
            "mlflow": original["mlflow"],
            "archivo": "model.pt",
            "sha256": entrada["sha256"],
            "bytes": entrada["bytes"],
            "publicado_por_p3": original["publicado_por_p3"],
            **ubicacion("model.pt"),
        },
        "optimizado": {
            "descripcion": "variante INT8 del edge",
            "version": linaje["ficha"]["variante"]["version"],
            "archivo": salidas["int8"]["archivo"],
            "sha256": salidas["int8"]["sha256"],
            "bytes": salidas["int8"]["bytes"],
            "tecnica": registro["configuracion"]["cuantizacion"],
            **ubicacion(salidas["int8"]["archivo"]),
        },
        "fp32_onnx": {
            "descripcion": "el original exportado a ONNX FP32: el 'original' medido en el edge",
            "archivo": salidas["fp32"]["archivo"],
            "sha256": salidas["fp32"]["sha256"],
            "bytes": salidas["fp32"]["bytes"],
            **ubicacion(salidas["fp32"]["archivo"]),
        },
        "clases": linaje["ficha"]["class_map"],
        "preprocesamiento": linaje["ficha"]["preprocesamiento"],
        "reduccion_tamano_pct": float(reduccion),
        "reduccion_tamano_pct_fraccion": f"{reduccion.numerator}/{reduccion.denominator}",
        "conversion": linaje["ficha"]["conversion"],
    }


def readme(ficha: dict, metricas: dict, recursos: dict, bench: dict, contraste: dict) -> str:
    orig, opt = metricas["modelos"]["original"], metricas["modelos"]["optimized"]
    lat, comp = recursos["latencia_edge"], recursos["comparacion"]
    hw, rt = bench["hardware"], bench["runtime"]
    ini, fin = bench["condiciones_inicio"], bench["condiciones_fin"]
    pct = 100

    def clase(m: dict, c: str) -> str:
        x = m["por_clase"][c]
        return f"{x['f1'] * pct:.2f} % (support {x['support']})"

    filas_clase = "\n".join(
        f"| `{c}` | {clase(orig, c)} | {clase(opt, c)} |" for c in ("cat", "dog", "person")
    )
    return f"""# Paquete de evidencia: calidad y recursos — VAL-08 (#24)

Archivos para que el evaluador **recalcule** calidad y recursos sin depender de capturas de pantalla (criterios 1.1–1.3, 3.1–3.3 y 6.2). Todo se recalcula **solo con esta carpeta** y Python 3.11 o superior, sin instalar nada:

```bash
python recalcular.py
```

[`recalcular.py`](recalcular.py) verifica cada archivo contra [`SHA256SUMS.txt`](SHA256SUMS.txt). Reconstruye las predicciones por muestra desde los datos primarios, las une con el manifiesto y recalcula accuracy, F1, la caída en pp, la reducción de tamaño y p50/p95 desde los tiempos crudos. Termina en `VERIFICADO` si todo coincide con lo declarado.

## Resumen

| | Original | Optimizado | Cambio |
|---|---:|---:|---:|
| Modelo | `{ficha["original"]["archivo"]}` {ficha["original"]["version"]} (P3) | `{ficha["optimizado"]["archivo"]}` `{ficha["optimizado"]["version"]}` | |
| Tamaño | {ficha["original"]["bytes"]:,} B | {ficha["optimizado"]["bytes"]:,} B | **−{ficha["reduccion_tamano_pct"]:.2f} %** |
| Accuracy en `val` (292) | {orig["accuracy"] * pct:.3f} % | {opt["accuracy"] * pct:.3f} % | **−{metricas["caida_accuracy"]["pp"]:.4f} pp** ({metricas["caida_accuracy"]["pp_fraccion"]}; cumple ≤ 2 pp) |
| F1 macro en `val` | {orig["f1_macro"] * pct:.3f} % | {opt["f1_macro"] * pct:.3f} % | |
| Latencia p50 en la Raspberry | {lat["fp32"]["ms_total"]["p50"]:.2f} ms | {lat["int8"]["ms_total"]["p50"]:.2f} ms | **−{comp["latencia_edge"]["p50_reduccion_pct"]:.2f} %** |
| Latencia p95 en la Raspberry | {lat["fp32"]["ms_total"]["p95"]:.2f} ms | {lat["int8"]["ms_total"]["p95"]:.2f} ms | **−{comp["latencia_edge"]["p95_reduccion_pct"]:.2f} %** |

F1 por clase en `val`:

| Clase | Original | Optimizado |
|---|---:|---:|
{filas_clase}

El optimizado es el INT8 **ejecutado en la Raspberry Pi 4 de la demostración** (VAL-07), con el mismo preprocesamiento bit a bit que offline. Las latencias comparan el INT8 con el original exportado a ONNX FP32 **en el mismo dispositivo**, el mismo runtime y las mismas imágenes; no se usan tiempos de laptop.

## Dónde está cada cosa

| Criterio de VAL-08 | Archivo (campo) |
|---|---|
| Identificación del modelo original y del optimizado; hashes SHA-256 | [`modelo/ficha_modelos.json`](modelo/ficha_modelos.json) (`original`, `optimizado`, `fp32_onnx`); [`modelo/registro_conversion.json`](modelo/registro_conversion.json) (`entrada`, `salidas`); [`modelo/linaje_verificacion.json`](modelo/linaje_verificacion.json) (VAL-01: 20 comprobaciones, incluidos los binarios en S3) |
| Referencia al manifiesto de validación | [`validacion/manifest_val.jsonl`](validacion/manifest_val.jsonl) (las 292 líneas `val`, byte a byte) y [`validacion/manifest.meta.json`](validacion/manifest.meta.json): `m-0.1.3-s42-1`, SHA-256 del manifiesto completo `45600f29…` |
| Predicciones por muestra | [`validacion/predicciones_val.csv`](validacion/predicciones_val.csv) (`sample_id`, `true_class`, `original_prediction`, `optimized_prediction`, probabilidades). Datos primarios en [`validacion/primarios/`](validacion/primarios/): probabilidades del original (VAL-02) y logits del INT8 en la Raspberry (VAL-07) |
| Accuracy y F1 macro de los dos; F1 y support por clase; caída en pp | [`validacion/metricas_val.json`](validacion/metricas_val.json) (`modelos`, `caida_accuracy`) y [`validacion/metricas_val.csv`](validacion/metricas_val.csv) |
| Tamaño original, tamaño optimizado y reducción | [`modelo/ficha_modelos.json`](modelo/ficha_modelos.json) (`bytes`, `reduccion_tamano_pct`); [`benchmark/recursos_edge.json`](benchmark/recursos_edge.json) (`tamanos`, contrastados en tres fuentes) |
| Archivo crudo con más de 100 tiempos y calentamientos identificados | [`benchmark/tiempos.csv`](benchmark/tiempos.csv): una fila por repetición, `fase` = `calentamiento` o `medicion`; 10 + 200 por modelo |
| p50 y p95 | [`benchmark/recursos_edge.json`](benchmark/recursos_edge.json) (`latencia_edge`, `metodo_percentil`: interpolación lineal, tipo 7) |
| Hardware, runtime y condiciones | [`benchmark/benchmark.json`](benchmark/benchmark.json) (`hardware`, `runtime`, `condiciones_inicio`/`fin`, `modelos.*.sesion`); preprocesamiento verificado en el edge: [`validacion/contraste_edge.json`](validacion/contraste_edge.json) |
| Interpretación del intercambio | [abajo](#intercambio-entre-recursos-y-calidad) |

## Condiciones de medición

- **Dispositivo:** {hw["modelo_dispositivo"]}, {hw["nucleos"]} núcleos, {hw["memoria_total"]} de RAM, {hw["sistema_operativo"]}, kernel `{hw["kernel"]}`, {hw["arquitectura"]}.
- **Runtime:** Python {rt["python"]}, onnxruntime {rt["onnxruntime"]} (`CPUExecutionProvider`, opciones por defecto), numpy {rt["numpy"]}, Pillow {rt["pillow"]}.
- **Entrada:** float32 `[1, 3, 224, 224]`, RGB normalizado con la media y la desviación de ImageNet; precisión INT8 (QDQ estático, pesos INT8 por canal, activaciones UINT8) contra FP32.
- **Qué mide cada repetición:** decodificar el JPEG, preprocesar, inferir y aplicar softmax. Queda fuera la captura, la carga del modelo y el envío a AWS, porque el benchmark no hace llamadas de red.
- **Estado del dispositivo:** temperatura de {ini["temperatura_c"]:.1f} °C al inicio y {fin["temperatura_c"]:.1f} °C al final, y `vcgencmd get_throttled` = `{fin["vcgencmd_throttled"]}`, sin limitación.
- **Preprocesamiento en el edge:** {next(c["detalle"] for c in contraste["comprobaciones"] if c["id"] == "tensor.bit_a_bit")}.

## Intercambio entre recursos y calidad

La cuantización a INT8 reduce el modelo **{ficha["reduccion_tamano_pct"]:.1f} %** (3.96 veces menor) y su latencia en la Raspberry **{comp["latencia_edge"]["p50_reduccion_pct"]:.1f} %** en p50 y p95. La medición INT8 más lenta es más rápida que la FP32 más rápida, así que la diferencia no está dentro de la variabilidad. La memoria pico baja {comp["memoria_pico"]["reduccion_pct"]:.1f} %.

A cambio, la accuracy en `val` baja **{metricas["caida_accuracy"]["pp"]:.2f} pp**: una sola muestra de 292 (`a559`). Es una muestra frontera en la que el original ya dudaba, y el INT8 empata exactamente `cat` y `dog`. `person` conserva precisión y recall de 100 %. La caída cumple el límite de 2 pp con un margen de {2 - metricas["caida_accuracy"]["pp"]:.2f} pp.

En una Raspberry Pi 4 de 1 GB, el INT8 deja más memoria libre para la captura y el envío y clasifica unas {1000 / lat["int8"]["ms_total"]["p50"]:.1f} fotos por segundo, contra {1000 / lat["fp32"]["ms_total"]["p50"]:.1f} del original. El costo en calidad es de una muestra.

## Procedencia

El paquete lo genera [`validacion/paquete_val08.py`](../../validacion/paquete_val08.py) a partir de la evidencia de VAL-01 a VAL-07, y solo lo escribe si `recalcular.py` da VERIFICADO. El análisis completo está en `docs/`: [`linaje-modelo.md`](../../docs/linaje-modelo.md), [`predicciones-val.md`](../../docs/predicciones-val.md), [`metricas-val.md`](../../docs/metricas-val.md), [`benchmark-edge.md`](../../docs/benchmark-edge.md), [`recursos-edge.md`](../../docs/recursos-edge.md) y [`preprocesamiento-edge.md`](../../docs/preprocesamiento-edge.md).
"""


def construir(destino: Path) -> None:
    for nombre, origen in COPIAS.items():
        (destino / nombre).parent.mkdir(parents=True, exist_ok=True)
        (destino / nombre).write_bytes(origen.read_bytes())
    ficha = ficha_modelos()
    (destino / "modelo/ficha_modelos.json").write_bytes(
        (json.dumps(ficha, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    texto = readme(
        ficha,
        leer_json(RES / "metricas_val.json"),
        leer_json(RES / "recursos_edge.json"),
        leer_json(RAIZ / "evidencias/VAL-05/benchmark.json"),
        leer_json(RES / "contraste_edge.json"),
    )
    (destino / "README.md").write_bytes(texto.encode("utf-8"))
    archivos = sorted(
        p.relative_to(destino).as_posix()
        for p in destino.rglob("*")
        if p.is_file() and p.name != "SHA256SUMS.txt"
    )
    sumas = "".join(
        f"{hashlib.sha256((destino / a).read_bytes()).hexdigest()}  {a}\n" for a in archivos
    )
    (destino / "SHA256SUMS.txt").write_bytes(sumas.encode("utf-8"))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    temporal = DESTINO.with_name(".VAL-08.tmp")
    if temporal.exists():
        shutil.rmtree(temporal)
    construir(temporal)
    proceso = subprocess.run(
        [sys.executable, "-I", str(temporal / "recalcular.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    print(proceso.stdout)
    if proceso.returncode != 0:
        shutil.rmtree(temporal)
        raise SystemExit(f"FALLA: recalcular.py no verifica el paquete\n{proceso.stderr}")
    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    temporal.rename(DESTINO)
    total = len(list(DESTINO.rglob("*.*")))
    print(f"Paquete escrito en {DESTINO.relative_to(RAIZ).as_posix()}/ ({total} archivos)")


if __name__ == "__main__":
    main()
