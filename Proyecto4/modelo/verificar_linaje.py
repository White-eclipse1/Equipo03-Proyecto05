"""Verificacion del linaje del modelo optimizado (VAL-01, issue #1; requisito M1, criterio 1.1).

Reconstruye la cadena

    model.pt 1.0.0 del P3  ->  registro de conversion  ->  variante 1.0.0-int8-e05.1

y contrasta version, run_id, checkpoint, SHA-256, orden de clases y preprocesamiento
entre fuentes independientes:

- lo que el P3 dejo en su repositorio: `docs/selection.json`, `docs/corridas.md`,
  `docs/publicacion_s3.md`, `config/classes.yaml`, `src/p3/data/transforms.py`,
  `src/p3/model/build.py` y el reporte de evaluacion en test del run;
- la conversion del P4: `modelo/conversion.yaml`, `modelo/convertir.py`,
  `modelo/preprocesar.py`, `modelo/registros/registro_conversion.json` y
  `modelo/registros/calibracion_ids.jsonl`;
- lo publicado en `s3://<bucket>/modelos/` (con `--profile`).

Niveles:

- Sin argumentos ("registros"): solo archivos versionados; sin red, sin pesos y sin
  dependencias pesadas (stdlib + PyYAML). Reconstruye byte a byte `model_package.json`
  con las clases y el preprocesamiento del P3 y compara su SHA-256 con el del registro.
- `--profile <perfil>` ("s3"): descarga de S3 el `model.pt` del P3 y los objetos de la
  variante, recalcula sus SHA-256, los compara con el registro y con el metadato
  `sha256` de cada objeto, y anota su `VersionId` en la evidencia. Necesita boto3.
- `--local`: recalcula los SHA-256 de las copias locales que existan (checkpoint de
  `dvc pull` en el P3 y `modelo/artefactos/<version>/`).

Lo que el nivel elegido no puede comprobar queda "pendiente", nunca "ok". Sale con
codigo 1 si alguna comprobacion falla.

Uso (desde Proyecto4/):
    python modelo/verificar_linaje.py
    python modelo/verificar_linaje.py --profile <perfil-de-la-cuenta-del-p4>
    python modelo/verificar_linaje.py --local
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent  # Proyecto4/
P3 = RAIZ.parent / "Proyecto3"
REGISTROS = AQUI / "registros"

# Lo que VAL-01 exige encontrar en los extremos de la cadena.
VERSION_P3 = "1.0.0"
VARIANTE = "1.0.0-int8-e05.1"
CLASES = ["cat", "dog", "person"]

BUCKET = "p4-capturas-474665692638"
PREFIJO_P3 = "modelos/clasificador-p3"
PREFIJO_EDGE = "modelos/clasificador-edge"

OK, FALLA, PENDIENTE = "ok", "falla", "pendiente"


@dataclass
class Comprobacion:
    id: str
    criterio: str
    estado: str
    detalle: str


class Comprobaciones(list):
    def agregar(self, id_: str, criterio: str, cumple: bool, detalle: str) -> None:
        self.append(Comprobacion(id_, criterio, OK if cumple else FALLA, detalle))

    def pendiente(self, id_: str, criterio: str, detalle: str) -> None:
        self.append(Comprobacion(id_, criterio, PENDIENTE, detalle))


def sha256_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def leer_json(ruta: Path) -> Any:
    return json.loads(ruta.read_text(encoding="utf-8"))


def leer_yaml(ruta: Path) -> Any:
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


def leer_texto(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


def constantes(ruta: Path) -> dict[str, Any]:
    """Constantes literales de un modulo sin importarlo (evita torch y numpy).

    `X = (0.1, 0.2)` da la tupla; `X = np.array([...], ...)` da su primer argumento.
    """
    valores: dict[str, Any] = {}
    for nodo in ast.parse(leer_texto(ruta)).body:
        if not (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1):
            continue
        destino, valor = nodo.targets[0], nodo.value
        if not isinstance(destino, ast.Name):
            continue
        if isinstance(valor, ast.Call) and valor.args:
            valor = valor.args[0]
        try:
            valores[destino.id] = ast.literal_eval(valor)
        except ValueError:
            continue
    return valores


def fila_tabla(ruta: Path, inicio: str, columna: str) -> str | None:
    """Celda `columna` de la fila de una tabla Markdown que empieza con `inicio`."""
    encabezado: list[str] | None = None
    for linea in leer_texto(ruta).splitlines():
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if columna in celdas:
            encabezado = celdas
        elif encabezado and linea.startswith(inicio):
            return celdas[encabezado.index(columna)].strip("`")
    return None


def fila_publicacion_p3(version: str) -> str:
    """Fila de `version` en la tabla de versiones de `Proyecto3/docs/publicacion_s3.md`."""
    for linea in leer_texto(P3 / "docs" / "publicacion_s3.md").splitlines():
        if linea.startswith((f"| **{version}** |", f"| {version} |")):
            return linea
    return ""


def preprocesamiento_p3(run_id: str) -> dict[str, Any]:
    """Preprocesamiento del run segun el P3, en el orden de claves de su checkpoint."""
    transforms = constantes(P3 / "src" / "p3" / "data" / "transforms.py")
    tamano = fila_tabla(P3 / "docs" / "corridas.md", f"| r10 | `{run_id}`", "image")
    return {
        "image_size": int(tamano) if tamano else None,
        "resize": transforms["EVAL_RESIZE"],
        "mean": list(transforms["IMAGENET_MEAN"]),
        "std": list(transforms["IMAGENET_STD"]),
    }


def reconstruir_paquete(cfg: dict, registro: dict, clases: list[str], pre: dict) -> bytes:
    """Mismos bytes que escribe `convertir.py` en `model_package.json` (UTF-8, LF)."""
    origen, variante = cfg["origen"], cfg["variante"]
    tamano = pre["image_size"]
    paquete = {
        "version": variante["version"],
        "origen": {
            "proyecto": "Proyecto 3",
            "version": origen["version_p3"],
            "run_id": origen["run_id"],
            "sha256": registro["entrada"]["sha256"],
        },
        "archivo": registro["salidas"]["int8"]["archivo"],
        "sha256": registro["salidas"]["int8"]["sha256"],
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
    return (json.dumps(paquete, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Nivel "registros": solo archivos versionados
# ---------------------------------------------------------------------------


def comprobar_registros(c: Comprobaciones) -> dict[str, Any]:
    cfg = leer_yaml(AQUI / "conversion.yaml")
    registro = leer_json(REGISTROS / "registro_conversion.json")
    seleccion = leer_json(P3 / "docs" / "selection.json")
    clases_yaml = leer_yaml(P3 / "config" / "classes.yaml")
    build_p3 = constantes(P3 / "src" / "p3" / "model" / "build.py")
    edge = constantes(AQUI / "preprocesar.py")
    convertir = leer_texto(AQUI / "convertir.py")
    ficha_doc = leer_texto(RAIZ / "docs" / "modelo-optimizado.md")
    origen, entrada = cfg["origen"], registro["entrada"]
    int8, fp32 = registro["salidas"]["int8"], registro["salidas"]["fp32"]
    run_id = origen["run_id"]
    fila_p3 = fila_publicacion_p3(VERSION_P3)

    # 1. Version original 1.0.0
    c.agregar(
        "origen.version",
        "Se identifica la version original 1.0.0 del P3",
        origen["version_p3"] == entrada["version_p3"] == VERSION_P3 and bool(fila_p3),
        f"conversion.yaml={origen['version_p3']}, registro={entrada['version_p3']}; "
        "publicada por el P3 en docs/publicacion_s3.md"
        + ("" if fila_p3 else " (FILA NO ENCONTRADA)"),
    )

    # 2. run_id de MLflow
    reporte = P3 / "reports" / "evaluation" / run_id / "metrics.json"
    run_reporte = leer_json(reporte).get("run_id") if reporte.is_file() else None
    c.agregar(
        "origen.run_id",
        "Se identifica el run_id de MLflow de origen",
        run_id == entrada["run_id"] == seleccion["run_id"] == run_reporte and run_id in fila_p3,
        f"{run_id}: igual en conversion.yaml, registro, Proyecto3/docs/selection.json (regla "
        f"'{seleccion['rule']}', {seleccion['candidates']} candidatas), publicacion_s3.md y el "
        "reporte de evaluacion en test del P3",
    )

    # 3. Checkpoint original
    sufijo = f"{run_id}/artifacts/checkpoint/model.pt"
    c.agregar(
        "origen.checkpoint",
        "Se identifica el checkpoint original",
        seleccion["checkpoint_uri"].endswith(sufijo)
        and origen["checkpoint"].endswith(sufijo)
        and entrada["archivo"] == origen["checkpoint"],
        f"MLflow {seleccion['checkpoint_uri']}; copia DVC {origen['checkpoint']}",
    )

    # 4. SHA-256 del original contra lo que el P3 registro por su cuenta
    c.agregar(
        "origen.sha256_registros",
        "El SHA-256 del original coincide en todas las fuentes",
        origen["sha256"] == entrada["sha256"] == seleccion["checkpoint_sha256"]
        and origen["sha256"] in fila_p3
        and str(entrada["bytes"]) in ficha_doc.replace(" ", ""),
        f"{origen['sha256']} ({entrada['bytes']} bytes) en conversion.yaml, registro, "
        "selection.json y publicacion_s3.md del P3, y docs/modelo-optimizado.md",
    )

    # 5. Variante
    c.agregar(
        "variante.version",
        f"Se identifica la variante {VARIANTE}",
        cfg["variante"]["version"] == registro["configuracion"]["variante"]["version"] == VARIANTE
        and f"`{VARIANTE}`" in ficha_doc,
        f"{VARIANTE} en conversion.yaml, registro y docs/modelo-optimizado.md",
    )

    # 6. SHA-256 de la variante
    aceptado = f"P4_MODELOS_ACEPTADOS={VARIANTE}={int8['sha256']}"
    c.agregar(
        "variante.sha256_registros",
        "El SHA-256 de la variante coincide en todas las fuentes",
        len(int8["sha256"]) == 64 and int8["sha256"] in ficha_doc and aceptado in ficha_doc,
        f"{int8['archivo']} {int8['sha256']} ({int8['bytes']} bytes) en el registro, la ficha "
        "y la linea P4_MODELOS_ACEPTADOS del receptor",
    )

    # 7. Orden de clases: P3 (classes.yaml) -> receptor del P4
    orden_p3 = [
        x["category_name"] for x in sorted(clases_yaml["classes"], key=lambda x: x["class_index"])
    ]
    receptor = constantes(RAIZ / "src" / "p4" / "capturas" / "config.py").get("CLASES_P3", "")
    c.agregar(
        "clases.orden",
        "Se conserva el orden de clases cat, dog, person",
        orden_p3 == CLASES
        and receptor.split(",") == CLASES
        and set(registro["calibracion"]["por_clase"]) == set(CLASES),
        f"Proyecto3/config/classes.yaml={orden_p3}; receptor CLASES_P3={receptor!r}; "
        "el paquete reconstruido (paquete.reconstruido) declara el mismo orden",
    )

    # 8. Preprocesamiento: P3 -> preprocesar.py del edge
    pre = preprocesamiento_p3(run_id)
    c.agregar(
        "preprocesamiento",
        "Se conserva el preprocesamiento requerido",
        pre["image_size"] == edge["TAMANO"]
        and pre["mean"] == list(edge["MEDIA"])
        and pre["std"] == list(edge["DESVIACION"])
        and pre["resize"] == "resize_to_square"
        and 'convert("RGB")' in leer_texto(AQUI / "preprocesar.py")
        and "Image.Resampling.BILINEAR" in leer_texto(AQUI / "preprocesar.py"),
        f"P3: {pre['image_size']}x{pre['image_size']} (docs/corridas.md) {pre['resize']}, "
        f"mean {pre['mean']}, std {pre['std']} (src/p3/data/transforms.py); igual a "
        "TAMANO/MEDIA/DESVIACION de modelo/preprocesar.py (RGB, bilineal)",
    )

    # 9. Referencia al script y la configuracion de conversion
    cuant = cfg["cuantizacion"]
    c.agregar(
        "conversion.referencia",
        "Se conserva la referencia al script y la configuracion de conversion",
        (AQUI / "requirements-conversion.lock.txt").is_file()
        and 'AQUI / "conversion.yaml"' in convertir
        and registro["configuracion"] == cfg
        and registro["comando"].endswith("modelo/convertir.py"),
        "modelo/convertir.py (lee modelo/conversion.yaml) + requirements-conversion.lock.txt; "
        f"el registro guarda la configuracion completa ({cuant['tecnica']}, {cuant['formato']}, "
        f"pesos {cuant['pesos']}, activaciones {cuant['activaciones']}) y es igual a la versionada",
    )

    # 10. El registro identifica entrada y salida
    con_hash = all(
        len(x.get("sha256", "")) == 64 and x.get("bytes") and x.get("archivo")
        for x in (entrada, fp32, int8)
    )
    c.agregar(
        "conversion.entrada_salida",
        "El registro de conversion identifica entrada y salida",
        con_hash and len(registro["salidas"]["model_package.json"]["sha256"]) == 64,
        f"entrada {entrada['archivo']} {entrada['sha256'][:12]}...; salidas {fp32['archivo']} "
        f"{fp32['sha256'][:12]}..., {int8['archivo']} {int8['sha256'][:12]}..., "
        f"model_package.json {registro['salidas']['model_package.json']['sha256'][:12]}...",
    )

    # 11. El paquete que lee el dispositivo sale de las clases y el preprocesamiento del P3
    paquete = reconstruir_paquete(cfg, registro, orden_p3, pre)
    sha_paquete = registro["salidas"]["model_package.json"]["sha256"]
    c.agregar(
        "paquete.reconstruido",
        "model_package.json se reconstruye con las clases y el preprocesamiento del P3",
        sha256_bytes(paquete) == sha_paquete,
        f"SHA-256 reconstruido {sha256_bytes(paquete)} = registro {sha_paquete}: el paquete "
        "del dispositivo declara exactamente esas clases, ese preprocesamiento, ese origen y ese "
        "SHA-256 de la variante",
    )

    # 12. Calibracion solo con train y nunca con el test del P3
    filas = [json.loads(x) for x in leer_texto(REGISTROS / "calibracion_ids.jsonl").splitlines()]
    por_clase: dict[str, int] = {}
    for fila in filas:
        por_clase[fila["clase"]] = por_clase.get(fila["clase"], 0) + 1
    test_csv = P3 / "reports" / "evaluation" / run_id / "predictions_test.csv"
    ids_test = {x.split(",", 1)[0] for x in leer_texto(test_csv).splitlines()[1:] if x}
    ids_cal = [f["crop_id"] for f in filas]
    cal = registro["calibracion"]
    c.agregar(
        "calibracion.train",
        "La calibracion uso solo train y ninguna muestra del test del P3",
        {f["split"] for f in filas} == {"train"}
        and len(ids_cal) == len(set(ids_cal)) == cfg["calibracion"]["muestras"] == cal["muestras"]
        and dict(sorted(por_clase.items())) == cal["por_clase"]
        and sha256(REGISTROS / "calibracion_ids.jsonl") == cal["ids_sha256"]
        and cfg["calibracion"]["manifiesto_sha256"] == seleccion["manifest_hash"]
        and not set(ids_cal) & ids_test,
        f"{len(ids_cal)} recortes unicos, todos de train ({dict(sorted(por_clase.items()))}); "
        f"0 de los {len(ids_test)} IDs del test del P3; manifiesto "
        f"{seleccion['manifest_id']}, el mismo con que se entreno el modelo seleccionado",
    )

    # 13. No se sustituye el modelo del equipo por uno externo
    c.agregar(
        "origen.no_externo",
        "No se sustituye el modelo del equipo por un modelo externo",
        "from p3.model.build import load_checkpoint" in convertir
        and 'if sha_original != origen["sha256"]' in convertir
        and build_p3["ARCHITECTURE"] == "resnet18"
        and registro["verificacion_rapida"]["max_dif_logits_fp32_vs_torch"] <= 1e-3,
        "convertir.py carga el checkpoint con load_checkpoint del P3 y se detiene si su "
        "SHA-256 no es el de conversion.yaml; ONNX FP32 igual a PyTorch (max |dlogit| "
        f"{registro['verificacion_rapida']['max_dif_logits_fp32_vs_torch']:.1e})",
    )

    return {
        "cfg": cfg,
        "registro": registro,
        "paquete": paquete,
        "ficha": {
            "original": {
                "version": origen["version_p3"],
                "run_id": run_id,
                "mlflow": seleccion["checkpoint_uri"],
                "publicado_por_p3": "s3://dataset-quality-releases-750702272375/"
                f"models/clasificador/{VERSION_P3}/model.pt",
                "sha256": origen["sha256"],
                "bytes": entrada["bytes"],
            },
            "variante": {
                "version": VARIANTE,
                "archivo": int8["archivo"],
                "sha256": int8["sha256"],
                "bytes": int8["bytes"],
            },
            "class_map": {str(i): nombre for i, nombre in enumerate(orden_p3)},
            "preprocesamiento": pre,
            "conversion": {
                "script": "modelo/convertir.py",
                "configuracion": "modelo/conversion.yaml",
                "registro": "modelo/registros/registro_conversion.json",
                "registro_sha256": sha256(REGISTROS / "registro_conversion.json"),
            },
        },
    }


# ---------------------------------------------------------------------------
# Nivel "local": copias locales de los binarios
# ---------------------------------------------------------------------------


def comprobar_local(c: Comprobaciones, ctx: dict) -> None:
    registro = ctx["registro"]
    artefactos = AQUI / "artefactos" / VARIANTE
    objetivos = [
        ("local.original", RAIZ / registro["entrada"]["archivo"], registro["entrada"]["sha256"]),
        *(
            (
                f"local.{n}",
                artefactos / registro["salidas"][n]["archivo"],
                registro["salidas"][n]["sha256"],
            )
            for n in ("fp32", "int8")
        ),
        ("local.paquete", artefactos / "model_package.json", sha256_bytes(ctx["paquete"])),
    ]
    for id_, ruta, esperado in objetivos:
        criterio = f"SHA-256 recalculado de {ruta.name} local"
        if not ruta.is_file():
            c.pendiente(id_, criterio, f"no existe {ruta}")
            continue
        obtenido = sha256(ruta)
        c.agregar(id_, criterio, obtenido == esperado, f"{ruta.name} {obtenido}")


# ---------------------------------------------------------------------------
# Nivel "s3": objetos publicados
# ---------------------------------------------------------------------------


def descargar(s3: Any, bucket: str, llave: str) -> dict[str, Any]:
    """SHA-256, bytes, VersionId y metadato `sha256` de un objeto, sin guardarlo."""
    respuesta = s3.get_object(Bucket=bucket, Key=llave)
    h, tamano, datos = hashlib.sha256(), 0, bytearray()
    for bloque in respuesta["Body"].iter_chunks(1 << 20):
        h.update(bloque)
        tamano += len(bloque)
        if tamano <= 1 << 20:  # los JSON se guardan para leerlos
            datos.extend(bloque)
    return {
        "sha256": h.hexdigest(),
        "bytes": tamano,
        "version_id": respuesta.get("VersionId"),
        "metadato_sha256": (respuesta.get("Metadata") or {}).get("sha256"),
        "datos": bytes(datos),
    }


def comprobar_s3(c: Comprobaciones, ctx: dict, s3: Any, bucket: str) -> None:
    registro = ctx["registro"]
    salidas = registro["salidas"]
    prefijo = f"{PREFIJO_EDGE}/{VARIANTE}"
    esperados = {
        f"{PREFIJO_P3}/{VERSION_P3}/model.pt": registro["entrada"]["sha256"],
        f"{prefijo}/{salidas['int8']['archivo']}": salidas["int8"]["sha256"],
        f"{prefijo}/{salidas['fp32']['archivo']}": salidas["fp32"]["sha256"],
        f"{prefijo}/model_package.json": salidas["model_package.json"]["sha256"],
        f"{prefijo}/registro_conversion.json": sha256(REGISTROS / "registro_conversion.json"),
        f"{prefijo}/calibracion_ids.jsonl": sha256(REGISTROS / "calibracion_ids.jsonl"),
    }
    publicados: dict[str, dict[str, Any]] = {}
    for llave, esperado in esperados.items():
        obj = descargar(s3, bucket, llave)
        publicados[llave] = {k: v for k, v in obj.items() if k != "datos"}
        metadato = obj["metadato_sha256"]
        c.agregar(
            f"s3.{llave.rsplit('/', 1)[-1]}",
            f"SHA-256 recalculado de {llave.rsplit('/', 1)[-1]} publicado",
            obj["sha256"] == esperado and metadato in (None, esperado),
            f"s3://{bucket}/{llave} VersionId {obj['version_id']}, {obj['bytes']} bytes, sha256 "
            f"{obj['sha256']}" + (f", metadato sha256 {metadato}" if metadato else ""),
        )
        if llave.endswith("model_package.json"):
            paquete = json.loads(obj["datos"])

    c.agregar(
        "s3.paquete_contenido",
        "model_package.json publicado declara el origen, las clases y el SHA-256 de la variante",
        paquete["clases"] == CLASES
        and paquete["origen"]["run_id"] == registro["entrada"]["run_id"]
        and paquete["origen"]["sha256"] == registro["entrada"]["sha256"]
        and paquete["sha256"] == salidas["int8"]["sha256"],
        f"clases {paquete['clases']}; origen {paquete['origen']['version']} run "
        f"{paquete['origen']['run_id'][:12]}...; variante {paquete['sha256'][:12]}...",
    )
    ctx["ficha"]["publicacion"] = {"bucket": bucket, "objetos": publicados}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--profile", help="perfil de AWS con lectura sobre el bucket del P4")
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument("--local", action="store_true", help="recalcular SHA-256 de copias locales")
    parser.add_argument("--salida", default="modelo/registros/linaje_verificacion.json")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    c = Comprobaciones()
    ctx = comprobar_registros(c)
    niveles = ["registros"]
    if args.local:
        comprobar_local(c, ctx)
        niveles.append("local")
    if args.profile:
        import boto3

        sesion = boto3.Session(profile_name=args.profile)
        identidad = sesion.client("sts").get_caller_identity()["Arn"]
        comprobar_s3(c, ctx, sesion.client("s3"), args.bucket)
        niveles.append(f"s3 ({identidad})")
    else:
        c.pendiente(
            "s3.binarios",
            "SHA-256 recalculado sobre los objetos publicados en S3",
            "este nivel no consulta S3; correr con --profile <perfil de la cuenta del P4>",
        )

    resumen = {estado: sum(x.estado == estado for x in c) for estado in (OK, FALLA, PENDIENTE)}
    evidencia = {
        "schema_version": 2,
        "tarea": "VAL-01 (#1)",
        "verificado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "niveles": niveles,
        "resumen": resumen,
        "linaje_verificado": resumen[FALLA] == 0 and resumen[PENDIENTE] == 0,
        "ficha": ctx["ficha"],
        "comprobaciones": [asdict(x) for x in c],
        "entorno": {"python": platform.python_version(), "sistema": platform.system()},
    }
    destino = (RAIZ / args.salida).resolve()
    destino.write_bytes(
        (json.dumps(evidencia, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )

    for x in c:
        print(f"[{x.estado:9}] {x.id}: {x.criterio}")
        if x.estado != OK:
            print(f"            {x.detalle}")
    print(f"\n{resumen} -> {destino.as_posix()}")
    if resumen[FALLA]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
