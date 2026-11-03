"""VAL-05 (#17): benchmark de latencia en el dispositivo edge (rubrica 3.1 y 3.2).

Mide, en la Raspberry de la demostracion, el tiempo de **preprocesamiento + inferencia
local** de la variante INT8 y, bajo condiciones equivalentes, del original exportado a
ONNX FP32: mismo runtime (onnxruntime, CPUExecutionProvider, opciones por defecto como
`edge/inferencia.py`), mismo `modelo/preprocesar.py`, mismas imagenes JPEG de la camara
y el mismo orden.

Cada repeticion mide desde los bytes JPEG ya leidos hasta la clase predicha:
decodificar el JPEG, preprocesar (RGB, 224x224, normalizacion), ejecutar el modelo y
softmax. No incluye la lectura del archivo ni la captura HTTP (son de la camara) y no
hace ninguna llamada de red: el envio a AWS se mide aparte (EDGE-06).

Protocolo por modelo, cada uno en su propio proceso (memoria pico por modelo; si un
modelo no carga, su error queda registrado como evidencia):

1. verificar el SHA-256 del archivo y cargar la sesion (tiempo de carga aparte);
2. `--calentamientos` repeticiones marcadas `calentamiento` (minimo 10), excluidas;
3. `--repeticiones` mediciones marcadas `medicion` (minimo 100).

Se registra la temperatura del CPU en cada repeticion y se hace una pausa entre
modelos. Uso en la Raspberry (ver docs/benchmark-edge.md):

    cd "$HOME/edge01" && source .venv/bin/activate
    python app/benchmark.py

Escribe `evidencias/VAL-05/tiempos.csv` (una fila por repeticion, en milisegundos) y
`evidencias/VAL-05/benchmark.json` (hardware, runtime, modelos, imagenes, condiciones
y conteos). p50/p95 y la comparacion se calculan en VAL-06.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# En el repositorio: ../modelo/preprocesar.py. En la Raspberry: app/ y modelo/.
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "modelo"))
from preprocesar import preprocesar, softmax  # noqa: E402

CLASES = ("cat", "dog", "person")
# Identidad de los artefactos: modelo/registros/registro_conversion.json (VAL-01).
MODELOS = {
    "int8": {
        "archivo": "model_int8.onnx",
        "version": "1.0.0-int8-e05.1",
        "sha256": "ba89ee435ce33e0f0cdd4e8ed84dfb50d74e5a3bc23c32af975085306ca02a12",
        "precision": "INT8: cuantizacion estatica QDQ, pesos INT8 por canal, activaciones UINT8",
    },
    "fp32": {
        "archivo": "model_fp32.onnx",
        "version": "1.0.0 (original del P3 exportado a ONNX FP32, sin cuantizar)",
        "sha256": "6b640343a5862ad546d074e0b2a7701d5da61d65552f18555d1b4dccf30506c1",
        "precision": "FP32",
    },
}
ENTRADA = [1, 3, 224, 224]
MINIMO_CALENTAMIENTOS = 10
MINIMO_REPETICIONES = 100
COLUMNAS = (
    "modelo",
    "fase",
    "indice",
    "repeticion",
    "imagen",
    "ms_total",
    "ms_preprocesamiento",
    "ms_inferencia",
    "valido",
    "clase_predicha",
    "confianza",
    "temperatura_c",
    "error",
)


# ---------------------------------------------------------------------------
# Condiciones del dispositivo (todo opcional: lo que no exista queda en None)
# ---------------------------------------------------------------------------


def leer(ruta: str) -> str | None:
    try:
        return Path(ruta).read_text(encoding="utf-8", errors="replace").replace("\x00", "").strip()
    except OSError:
        return None


def temperatura() -> float | None:
    """Temperatura del SoC en grados C (sysfs de Linux); None si no existe."""
    valor = leer("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(valor) / 1000 if valor else None
    except ValueError:
        return None


def comando(*args: str) -> str | None:
    try:
        salida = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
        return (salida.stdout or salida.stderr).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def cpufreq() -> dict[str, Any]:
    cpus = {}
    for cpu in sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*")):
        base = cpu / "cpufreq"
        if base.is_dir():
            cpus[cpu.name] = {
                k: leer(str(base / k))
                for k in (
                    "scaling_governor",
                    "scaling_cur_freq",
                    "scaling_min_freq",
                    "scaling_max_freq",
                    "cpuinfo_max_freq",
                )
            }
    return cpus


def condiciones() -> dict[str, Any]:
    """Estado del dispositivo en un instante: temperatura, frecuencias, carga, throttling."""
    return {
        "instante": datetime.now().astimezone().isoformat(),
        "temperatura_c": temperatura(),
        "cpufreq": cpufreq(),
        "loadavg": leer("/proc/loadavg"),
        "vcgencmd_temp": comando("vcgencmd", "measure_temp"),
        "vcgencmd_clock_arm": comando("vcgencmd", "measure_clock", "arm"),
        "vcgencmd_throttled": comando("vcgencmd", "get_throttled"),
    }


def hardware() -> dict[str, Any]:
    cpuinfo = leer("/proc/cpuinfo") or ""
    campos = {}
    for linea in cpuinfo.splitlines():
        clave, _, valor = linea.partition(":")
        if clave.strip() in ("Model", "Hardware", "Revision", "CPU part", "model name"):
            campos.setdefault(clave.strip(), valor.strip())
    memoria = next(
        (
            x.split(":", 1)[1].strip()
            for x in (leer("/proc/meminfo") or "").splitlines()
            if x.startswith("MemTotal")
        ),
        None,
    )
    os_release = dict(
        linea.split("=", 1)
        for linea in (leer("/etc/os-release") or "").splitlines()
        if "=" in linea
    )
    return {
        "modelo_dispositivo": leer("/proc/device-tree/model"),
        "cpuinfo": campos,
        "nucleos": os.cpu_count(),
        "memoria_total": memoria,
        "sistema_operativo": os_release.get("PRETTY_NAME", "").strip('"') or platform.platform(),
        "kernel": platform.release(),
        "arquitectura": platform.machine(),
    }


def runtime() -> dict[str, Any]:
    import onnxruntime as ort
    import PIL

    return {
        "python": platform.python_version(),
        "onnxruntime": ort.__version__,
        "providers_disponibles": ort.get_available_providers(),
        "numpy": np.__version__,
        "pillow": PIL.__version__,
    }


# ---------------------------------------------------------------------------
# Medicion (un modelo por proceso)
# ---------------------------------------------------------------------------


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def leer_imagenes(carpeta: Path) -> list[dict[str, Any]]:
    """JPEG de la camara (bytes en memoria; leerlos no forma parte de la medicion)."""
    imagenes = []
    for ruta in sorted(carpeta.rglob("*.jpg")):
        datos = ruta.read_bytes()
        with Image.open(io.BytesIO(datos)) as imagen:
            tamano = list(imagen.size)
        imagenes.append(
            {
                "nombre": ruta.relative_to(carpeta).as_posix(),
                "sha256": sha256(datos),
                "bytes": len(datos),
                "tamano": tamano,
                "datos": datos,
            }
        )
    if not imagenes:
        raise ValueError(f"No hay JPEG en {carpeta}")
    return imagenes


def repeticion(ejecutar: Callable[[np.ndarray], np.ndarray], datos: bytes) -> dict[str, Any]:
    """Una repeticion: bytes JPEG -> clase. Mismo camino que edge/inferencia.py."""
    inicio = time.perf_counter_ns()
    with Image.open(io.BytesIO(datos)) as imagen:
        if imagen.format != "JPEG":
            raise ValueError("Se requiere JPEG")
        tensor = preprocesar(imagen)
    preprocesado = time.perf_counter_ns()
    logits = np.asarray(ejecutar(tensor))
    inferido = time.perf_counter_ns()
    if logits.shape != (1, len(CLASES)) or not np.isfinite(logits).all():
        raise ValueError("El modelo debe producir tres logits finitos")
    probabilidades = softmax(logits)[0]
    indice = int(probabilidades.argmax())
    fin = time.perf_counter_ns()
    return {
        "ms_total": (fin - inicio) / 1e6,
        "ms_preprocesamiento": (preprocesado - inicio) / 1e6,
        "ms_inferencia": (inferido - preprocesado) / 1e6,
        "clase_predicha": CLASES[indice],
        "confianza": float(probabilidades[indice]),
    }


def medir(
    modelo: str,
    ejecutar: Callable[[np.ndarray], np.ndarray],
    imagenes: list[dict[str, Any]],
    calentamientos: int,
    repeticiones: int,
    leer_temperatura: Callable[[], float | None] = temperatura,
) -> list[dict[str, Any]]:
    """Calentamientos marcados y mediciones, recorriendo las imagenes en orden fijo."""
    filas = []
    fases = [("calentamiento", r) for r in range(calentamientos)]
    fases += [("medicion", r) for r in range(repeticiones)]
    for indice, (fase, numero) in enumerate(fases):
        imagen = imagenes[indice % len(imagenes)]
        fila = {
            "modelo": modelo,
            "fase": fase,
            "indice": indice,
            "repeticion": numero,
            "imagen": imagen["nombre"],
            "temperatura_c": leer_temperatura(),
        }
        try:
            fila |= repeticion(ejecutar, imagen["datos"]) | {"valido": True, "error": ""}
        except Exception as error:  # se registra y la corrida sigue
            fila |= {"valido": False, "error": f"{type(error).__name__}: {error}"}
        filas.append(fila)
    return filas


def pico_memoria_mb() -> float | None:
    """Memoria residente maxima del proceso (Linux: ru_maxrss en KiB)."""
    try:
        import resource
    except ImportError:
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def proceso_modelo(args: argparse.Namespace) -> int:
    """Hijo: mide un solo modelo y escribe su resultado parcial en JSON."""
    especificacion = MODELOS[args.solo]
    ruta = args.modelos / especificacion["archivo"]
    resultado: dict[str, Any] = {"modelo": args.solo, "archivo": str(ruta), "filas": []}
    try:
        datos = ruta.read_bytes()
        resultado |= {"sha256": sha256(datos), "bytes": len(datos)}
        if resultado["sha256"] != especificacion["sha256"]:
            raise ValueError(f"SHA-256 {resultado['sha256']} != {especificacion['sha256']}")
        import onnxruntime as ort

        inicio = time.perf_counter_ns()
        sesion = ort.InferenceSession(datos, providers=["CPUExecutionProvider"])
        resultado["ms_carga"] = (time.perf_counter_ns() - inicio) / 1e6
        entrada, salida = sesion.get_inputs()[0], sesion.get_outputs()[0]
        if entrada.shape != ENTRADA or entrada.type != "tensor(float)":
            raise ValueError(f"Entrada incompatible: {entrada.shape} {entrada.type}")
        opciones = sesion.get_session_options()
        resultado["sesion"] = {
            "providers": sesion.get_providers(),
            "entrada": {"nombre": entrada.name, "forma": entrada.shape, "tipo": entrada.type},
            "salida": {"nombre": salida.name, "forma": salida.shape},
            "intra_op_num_threads": opciones.intra_op_num_threads,
            "inter_op_num_threads": opciones.inter_op_num_threads,
            "graph_optimization_level": str(opciones.graph_optimization_level),
            "nota": "opciones por defecto, como edge/inferencia.py (0 hilos = automatico)",
        }
        imagenes = leer_imagenes(args.imagenes)
        resultado["condiciones_inicio"] = condiciones()

        def ejecutar(tensor: np.ndarray) -> np.ndarray:
            return sesion.run([salida.name], {entrada.name: tensor})[0]

        resultado["filas"] = medir(
            args.solo, ejecutar, imagenes, args.calentamientos, args.repeticiones
        )
        resultado["condiciones_fin"] = condiciones()
        resultado["pico_memoria_mb"] = pico_memoria_mb()
        resultado["estado"] = "ok"
    except Exception as error:
        resultado |= {"estado": "error", "error": f"{type(error).__name__}: {error}"}
    args.parcial.write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")
    return 0 if resultado["estado"] == "ok" else 1


# ---------------------------------------------------------------------------
# Orquestacion (padre)
# ---------------------------------------------------------------------------


def correr_hijo(args: argparse.Namespace, modelo: str) -> dict[str, Any]:
    parcial = args.salida / f".parcial-{modelo}.json"
    parcial.unlink(missing_ok=True)
    orden = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--solo",
        modelo,
        "--parcial",
        str(parcial),
        "--modelos",
        str(args.modelos),
        "--imagenes",
        str(args.imagenes),
        "--calentamientos",
        str(args.calentamientos),
        "--repeticiones",
        str(args.repeticiones),
    ]
    proceso = subprocess.run(orden, capture_output=True, text=True, check=False)
    if parcial.is_file():
        resultado = json.loads(parcial.read_text(encoding="utf-8"))
        parcial.unlink()
    else:  # el proceso murio sin escribir (p. ej. sin memoria): esa es la evidencia
        resultado = {"modelo": modelo, "estado": "error", "filas": []}
    resultado["codigo_salida"] = proceso.returncode
    if proceso.returncode != 0:
        resultado["stderr_final"] = proceso.stderr[-4000:]
    return resultado


def resumen_modelo(resultado: dict[str, Any]) -> dict[str, Any]:
    filas = resultado.get("filas", [])
    medidas = [f for f in filas if f["fase"] == "medicion"]
    return {
        "estado": resultado.get("estado"),
        "calentamientos": sum(f["fase"] == "calentamiento" for f in filas),
        "mediciones": len(medidas),
        "mediciones_validas": sum(f["valido"] for f in medidas),
        "cumple_minimos": sum(f["fase"] == "calentamiento" for f in filas) >= MINIMO_CALENTAMIENTOS
        and sum(f["valido"] for f in medidas) >= MINIMO_REPETICIONES,
        "clases_predichas_por_imagen": sorted(
            {f"{f['imagen']} -> {f['clase_predicha']}" for f in medidas if f["valido"]}
        ),
    }


def tiempos_csv(resultados: list[dict[str, Any]]) -> bytes:
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=COLUMNAS, lineterminator="\n")
    escritor.writeheader()
    for resultado in resultados:
        for fila in resultado.get("filas", []):
            escritor.writerow(
                {
                    k: (repr(fila[k]) if isinstance(fila.get(k), float) else fila.get(k, ""))
                    for k in COLUMNAS
                }
            )
    return salida.getvalue().encode("utf-8")


def orquestar(args: argparse.Namespace) -> int:
    if args.calentamientos < MINIMO_CALENTAMIENTOS or args.repeticiones < MINIMO_REPETICIONES:
        raise SystemExit(
            f"Minimo {MINIMO_CALENTAMIENTOS} calentamientos y {MINIMO_REPETICIONES} repeticiones"
        )
    args.salida.mkdir(parents=True, exist_ok=True)
    imagenes = leer_imagenes(args.imagenes)
    print(
        f"{len(imagenes)} imagenes; orden {args.orden}; "
        f"{args.calentamientos} calentamientos + {args.repeticiones} mediciones por modelo"
    )
    inicio = condiciones()
    resultados = []
    for numero, modelo in enumerate(args.orden):
        if numero:
            print(f"Pausa de {args.pausa} s entre modelos...")
            time.sleep(args.pausa)
        print(f"Midiendo {modelo}...")
        resultados.append(correr_hijo(args, modelo))
        r = resumen_modelo(resultados[-1])
        print(
            f"  {modelo}: {r['estado']}, {r['calentamientos']} calentamientos, "
            f"{r['mediciones_validas']}/{r['mediciones']} mediciones validas"
        )

    datos = tiempos_csv(resultados)
    evidencia = {
        "schema_version": 1,
        "tarea": "VAL-05 (#17)",
        "fecha": datetime.now().astimezone().isoformat(),
        "comando": " ".join([Path(sys.executable).name, *sys.argv]),
        "hardware": hardware(),
        "runtime": runtime(),
        "entrada": {"forma": ENTRADA, "tipo": "float32", "orden": "NCHW, RGB"},
        "medicion": {
            "incluye": "decodificar JPEG + modelo/preprocesar.py + sesion.run + softmax",
            "excluye": "lectura del archivo, captura HTTP de la camara, carga del modelo "
            "(ms_carga aparte) y envio a AWS: el benchmark no hace llamadas de red",
            "reloj": "time.perf_counter_ns, en milisegundos",
            "calentamientos": args.calentamientos,
            "repeticiones": args.repeticiones,
            "orden_modelos": args.orden,
            "pausa_entre_modelos_s": args.pausa,
            "proceso_por_modelo": True,
        },
        "codigo": {
            "benchmark.py": sha256(Path(__file__).read_bytes()),
            "preprocesar.py": sha256(Path(preprocesar.__code__.co_filename).read_bytes()),
            "preprocesar_ruta": preprocesar.__code__.co_filename,
        },
        "imagenes": [{k: v for k, v in i.items() if k != "datos"} for i in imagenes],
        "condiciones_inicio": inicio,
        "condiciones_fin": condiciones(),
        "modelos": {
            r["modelo"]: {
                **MODELOS[r["modelo"]],
                **{k: v for k, v in r.items() if k not in ("filas", "modelo")},
                "resumen": resumen_modelo(r),
            }
            for r in resultados
        },
        "tiempos": {
            "archivo": "tiempos.csv",
            "sha256": sha256(datos),
            "filas": datos.count(b"\n") - 1,
        },
        "nota": "p50/p95 y comparacion entre modelos: VAL-06 (#18)",
    }
    (args.salida / "tiempos.csv").write_bytes(datos)
    (args.salida / "benchmark.json").write_text(
        json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Escrito {args.salida / 'tiempos.csv'} y benchmark.json")
    return 0 if all(resumen_modelo(r)["cumple_minimos"] for r in resultados) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--modelos", type=Path, default=BASE / "modelo")
    parser.add_argument("--imagenes", type=Path, default=BASE / "evidencias" / "EDGE-03")
    parser.add_argument("--salida", type=Path, default=BASE / "evidencias" / "VAL-05")
    parser.add_argument("--calentamientos", type=int, default=10)
    parser.add_argument("--repeticiones", type=int, default=200)
    parser.add_argument("--pausa", type=int, default=60, help="segundos entre modelos")
    parser.add_argument(
        "--orden", type=lambda s: s.split(","), default=["int8", "fp32"], help="p. ej. int8,fp32"
    )
    parser.add_argument("--solo", choices=sorted(MODELOS), help=argparse.SUPPRESS)
    parser.add_argument("--parcial", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    return proceso_modelo(args) if args.solo else orquestar(args)


if __name__ == "__main__":
    sys.exit(main())
