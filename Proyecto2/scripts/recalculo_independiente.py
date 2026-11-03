#!/usr/bin/env python3
"""Recalcula las metricas del dataset SIN usar una sola linea de `dataset_quality`.

Por que existe este archivo
---------------------------
`reports/quality.json` y `reports/stats.json` los escribe el mismo codigo que
dice si el dataset esta bien. Eso los vuelve inutiles como evidencia por si
solos: si un analizador tiene un error, el reporte lo hereda y nada lo delata.
La unica forma de que esos numeros signifiquen algo es que un segundo programa,
escrito aparte, llegue a los mismos valores partiendo del dato crudo.

Eso hace este script. Lee `data/raw/annotations.coco.json`, abre las imagenes
de `data/raw/images/` y relee los umbrales de `quality.yaml`. No importa
`dataset_quality`; ni siquiera lo tiene en el path. Tampoco usa `imagehash`:
el pHash esta reimplementado abajo sobre numpy porque el analizador del
proyecto se apoya en esa libreria, y usarla aqui reproduciria cualquier error
de uso en vez de detectarlo.

Que compara
-----------
Cajas por clase, imagenes por clase, objetos pequenos, duplicados, sesgo
espacial, cajas degeneradas y desbalance. Imprime una tabla "reportado contra
recalculado" y sale con codigo != 0 si algo no coincide.

    python scripts/recalculo_independiente.py
    python scripts/recalculo_independiente.py --sin-imagenes   # salta el pHash
    python scripts/recalculo_independiente.py --md reports/evaluation/recalculo.md

Si `data/raw/` no esta, el script no falla con un rastro de Python: dice el
comando exacto que lo trae del remote de DVC.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image
from scipy.fftpack import dct

PROYECTO2_DIR = Path(__file__).resolve().parent.parent

COCO = PROYECTO2_DIR / "data" / "raw" / "annotations.coco.json"
IMAGENES = PROYECTO2_DIR / "data" / "raw" / "images"
POLITICA = PROYECTO2_DIR / "quality.yaml"
QUALITY_JSON = PROYECTO2_DIR / "reports" / "quality.json"
STATS_JSON = PROYECTO2_DIR / "reports" / "stats.json"

COMO_TRAER_EL_DATASET = """
No encuentro el dataset crudo en data/raw/.

No esta en Git a proposito: son 634 MB de imagenes, y lo que Git versiona es
el PUNTERO (`data/raw.dvc`, 112 bytes) con el hash del directorio. Para
traerlo, desde Proyecto2/:

    # Contra el remote DEV (MinIO local; levanta el entorno primero)
    python scripts/up.py
    python scripts/dvc_remote.py       # escribe .dvc/config.local desde .env
    dvc pull -r dev data/raw.dvc

    # O contra el remote PROD (S3 real; necesita un perfil AWS autorizado)
    dvc remote modify --local prod profile <perfil>
    dvc pull -r prod data/raw.dvc

En ambos casos DVC verifica el hash de lo que baja contra `data/raw.dvc`, asi
que si el contenido no es exactamente el evaluado, falla en vez de continuar.
"""


# ---------------------------------------------------------------------------
# pHash, reimplementado
# ---------------------------------------------------------------------------
# El analizador del proyecto delega en `imagehash.phash`. Aqui se reescribe el
# algoritmo entero (gris -> 32x32 -> DCT 2D -> 8x8 de baja frecuencia ->
# umbral en la mediana) para que el recalculo no comparta ni la libreria ni la
# forma de invocarla. Si el proyecto estuviera, por ejemplo, pasando la imagen
# sin convertir a escala de grises, esta implementacion daria otros hashes y la
# discrepancia saltaria en la tabla.
LADO_HASH = 8
FACTOR_ALTA_FRECUENCIA = 4


def phash_propio(ruta: Path) -> int:
    """pHash de 64 bits, calculado aqui y no por `imagehash`."""
    lado = LADO_HASH * FACTOR_ALTA_FRECUENCIA
    with Image.open(ruta) as handle:
        gris = handle.convert("L").resize((lado, lado), Image.Resampling.LANCZOS)

    pixeles = np.asarray(gris, dtype=np.float64)
    # DCT-II en las dos dimensiones: primero por columnas, luego por filas.
    transformada = dct(dct(pixeles, axis=0), axis=1)
    baja_frecuencia = transformada[:LADO_HASH, :LADO_HASH]
    bits = baja_frecuencia > np.median(baja_frecuencia)

    valor = 0
    for bit in bits.flatten():
        valor = (valor << 1) | int(bit)
    return valor


def distancia_hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


# ---------------------------------------------------------------------------
# Metricas, recalculadas desde el COCO crudo
# ---------------------------------------------------------------------------
def cargar_coco() -> dict[str, Any]:
    if not COCO.is_file():
        sys.exit(COMO_TRAER_EL_DATASET)
    return json.loads(COCO.read_text(encoding="utf-8"))


def recalcular_sin_imagenes(coco: dict[str, Any], politica: dict[str, Any]) -> dict[str, Any]:
    """Todo lo que se deduce del JSON, sin abrir una sola foto."""
    nombres = {categoria["id"]: categoria["name"] for categoria in coco["categories"]}
    tamanos = {imagen["id"]: (imagen["width"], imagen["height"]) for imagen in coco["images"]}

    cajas_por_clase: dict[str, int] = defaultdict(int)
    imagenes_por_clase: dict[str, set[int]] = {nombre: set() for nombre in nombres.values()}

    pequenas = politica["small_objects"]
    umbral_relativo = pequenas["area_ratio_threshold"]
    umbral_absoluto = pequenas["min_area_px"]
    pequenas_ids: list[int] = []
    pequenas_por_clase: dict[str, int] = defaultdict(int)

    rejilla = politica["spatial_bias"]["grid_size"]
    celdas: dict[tuple[int, int], int] = defaultdict(int)

    fuera_de_borde: list[int] = []
    area_declarada_incoherente: list[int] = []

    for anotacion in coco["annotations"]:
        clase = nombres[anotacion["category_id"]]
        cajas_por_clase[clase] += 1
        imagenes_por_clase[clase].add(anotacion["image_id"])

        ancho_imagen, alto_imagen = tamanos[anotacion["image_id"]]
        x, y, ancho, alto = anotacion["bbox"]

        # El area se deriva de la caja en vez de creerle al campo `area` del
        # COCO. Son dos cosas distintas y es justo el tipo de detalle donde un
        # recalculo independiente aporta: si el exportador escribio un `area`
        # que no corresponde a su bbox, aqui se ve.
        area = ancho * alto
        if abs(area - anotacion["area"]) > 1e-6:
            area_declarada_incoherente.append(anotacion["id"])

        proporcion = area / (ancho_imagen * alto_imagen)
        if proporcion < umbral_relativo or area < umbral_absoluto:
            pequenas_ids.append(anotacion["id"])
            pequenas_por_clase[clase] += 1

        # La caja cuenta en la celda donde cae su CENTRO.
        columna = min(rejilla - 1, int((x + ancho / 2) / ancho_imagen * rejilla))
        fila = min(rejilla - 1, int((y + alto / 2) / alto_imagen * rejilla))
        celdas[(fila, columna)] += 1

        if x < 0 or y < 0 or x + ancho > ancho_imagen or y + alto > alto_imagen:
            fuera_de_borde.append(anotacion["id"])

    total_cajas = len(coco["annotations"])
    conteo_por_clase = {nombre: len(ids) for nombre, ids in imagenes_por_clase.items()}
    usadas = [conteo for conteo in conteo_por_clase.values() if conteo > 0]

    return {
        "totales": {
            "images": len(coco["images"]),
            "annotations": total_cajas,
            "categories": len(coco["categories"]),
        },
        "boxes_per_class": dict(sorted(cajas_por_clase.items())),
        "images_per_class": conteo_por_clase,
        "small_objects": {
            "cajas": len(pequenas_ids),
            "ratio": len(pequenas_ids) / total_cajas if total_cajas else 0.0,
            "por_clase": dict(sorted(pequenas_por_clase.items(), key=lambda par: -par[1])),
            "ids": sorted(pequenas_ids),
        },
        "spatial_bias": {
            "celda_mas_poblada": max(celdas.values()) / total_cajas if total_cajas else 0.0,
            "rejilla": rejilla,
        },
        "degenerate_boxes": {
            "cajas": len(fuera_de_borde),
            "ratio": len(fuera_de_borde) / total_cajas if total_cajas else 0.0,
            "ids": sorted(fuera_de_borde),
        },
        "class_imbalance": {
            "ratio": (max(usadas) / min(usadas)) if usadas else 0.0,
            "mayor": max(usadas) if usadas else 0,
            "menor": min(usadas) if usadas else 0,
        },
        "min_images_per_class": {
            "clases_que_cumplen": sorted(
                nombre
                for nombre, conteo in conteo_por_clase.items()
                if conteo >= politica["min_images_per_class"]["min_images"]
            )
        },
        "area_declarada_incoherente": sorted(area_declarada_incoherente),
    }


def recalcular_duplicados(coco: dict[str, Any], politica: dict[str, Any]) -> dict[str, Any]:
    """Abre cada imagen y busca casi-duplicados con el pHash de arriba."""
    if not IMAGENES.is_dir():
        sys.exit(COMO_TRAER_EL_DATASET)

    umbral = politica["duplicates"]["phash_hamming_distance"]
    hashes: dict[int, int] = {}
    ausentes: list[str] = []

    total = len(coco["images"])
    for indice, imagen in enumerate(coco["images"], start=1):
        ruta = IMAGENES / imagen["file_name"]
        if not ruta.is_file():
            ausentes.append(imagen["file_name"])
            continue
        try:
            hashes[imagen["id"]] = phash_propio(ruta)
        except OSError:
            ausentes.append(imagen["file_name"])
        if indice % 200 == 0 or indice == total:
            print(f"  pHash {indice}/{total}", file=sys.stderr)

    ids = sorted(hashes)
    pares: list[tuple[int, int, int]] = []
    for posicion, a in enumerate(ids):
        for b in ids[posicion + 1 :]:
            distancia = distancia_hamming(hashes[a], hashes[b])
            if distancia <= umbral:
                pares.append((a, b, distancia))

    # La copia es el id mayor del par: el primero en aparecer es el original.
    sobrantes = sorted({mayor for _, mayor, _ in pares})

    return {
        "umbral": umbral,
        "hasheadas": len(hashes),
        "ausentes": ausentes,
        "pares": len(pares),
        "sobrantes": len(sobrantes),
        "ratio": len(sobrantes) / total if total else 0.0,
        "ids_sobrantes": sobrantes,
    }


# ---------------------------------------------------------------------------
# Comparacion contra lo que reporto el pipeline
# ---------------------------------------------------------------------------
def leer_reportes() -> tuple[dict[str, Any], dict[str, Any]]:
    faltan = [ruta.name for ruta in (QUALITY_JSON, STATS_JSON) if not ruta.is_file()]
    if faltan:
        sys.exit(
            f"Faltan {', '.join(faltan)} en reports/. Generalos con `dq analyze` y `dq gate` "
            "antes de recalcular: este script compara contra ellos, no los sustituye."
        )
    return (
        json.loads(QUALITY_JSON.read_text(encoding="utf-8")),
        json.loads(STATS_JSON.read_text(encoding="utf-8")),
    )


def check(reporte: dict[str, Any], nombre: str) -> dict[str, Any] | None:
    for item in reporte["checks"]:
        if item["name"] == nombre:
            return item
    return None


class Fila:
    """Una metrica: lo que dijo el pipeline, lo que sale al recalcularla."""

    def __init__(self, metrica: str, reportado: Any, recalculado: Any, tolerancia: float = 0.0):
        self.metrica = metrica
        self.reportado = reportado
        self.recalculado = recalculado
        self.tolerancia = tolerancia

    @property
    def coincide(self) -> bool:
        if isinstance(self.reportado, float) and isinstance(self.recalculado, float):
            return abs(self.reportado - self.recalculado) <= self.tolerancia
        return self.reportado == self.recalculado

    def formato(self, valor: Any, *, maximo: int | None = None) -> str:
        """`maximo` acota las listas largas SOLO al imprimirlas.

        La comparacion de `coincide` usa siempre la lista entera: los 231 ids de
        objetos pequenos se contrastan uno a uno. Lo que se acota es la celda de
        la tabla, porque una fila de 231 numeros no la lee nadie y el archivo
        deja de servir como evidencia.
        """
        if isinstance(valor, float):
            return f"{valor:.6f}"
        if isinstance(valor, dict):
            return ", ".join(f"{clave}={numero}" for clave, numero in valor.items())
        if isinstance(valor, list):
            if not valor:
                return "(vacio)"
            if maximo is not None and len(valor) > maximo:
                cabeza = ", ".join(str(item) for item in valor[:maximo])
                return f"{len(valor)} ids: {cabeza}, ... (+{len(valor) - maximo})"
            return ", ".join(str(item) for item in valor)
        return str(valor)

    def como_dict(self) -> dict[str, Any]:
        return {
            "metrica": self.metrica,
            "reportado": self.reportado,
            "recalculado": self.recalculado,
            "coincide": self.coincide,
        }

    def como_markdown(self) -> str:
        marca = "si" if self.coincide else "**NO**"
        return (
            f"| {self.metrica} | `{self.formato(self.reportado, maximo=8)}` "
            f"| `{self.formato(self.recalculado, maximo=8)}` | {marca} |"
        )


def comparar(
    recalculado: dict[str, Any],
    duplicados: dict[str, Any] | None,
    quality: dict[str, Any],
    stats: dict[str, Any],
) -> list[Fila]:
    resumen = stats["stats"]
    filas: list[Fila] = [
        Fila("totales.images", resumen["totals"]["images"], recalculado["totales"]["images"]),
        Fila(
            "totales.annotations",
            resumen["totals"]["annotations"],
            recalculado["totales"]["annotations"],
        ),
        Fila(
            "totales.categories",
            resumen["totals"]["categories"],
            recalculado["totales"]["categories"],
        ),
        Fila(
            "cajas por clase",
            dict(sorted(resumen["boxes_per_class"].items())),
            recalculado["boxes_per_class"],
        ),
        Fila(
            "imagenes por clase",
            dict(sorted(resumen["images_per_class"].items())),
            dict(sorted(recalculado["images_per_class"].items())),
        ),
    ]

    pequenos = check(quality, "small_objects")
    if pequenos:
        filas += [
            Fila(
                "objetos pequenos (ratio)",
                float(pequenos["observed"]),
                recalculado["small_objects"]["ratio"],
                tolerancia=1e-9,
            ),
            Fila(
                "objetos pequenos (cajas)",
                len(pequenos["offenders"]),
                recalculado["small_objects"]["cajas"],
            ),
            Fila(
                "objetos pequenos (ids)",
                pequenos["offenders"],
                recalculado["small_objects"]["ids"],
            ),
            Fila(
                "objetos pequenos por clase",
                pequenos["small_objects"]["boxes_by_class"],
                recalculado["small_objects"]["por_clase"],
            ),
        ]

    sesgo = check(quality, "spatial_bias")
    if sesgo:
        filas.append(
            Fila(
                "sesgo espacial (celda mas poblada)",
                float(sesgo["observed"]),
                recalculado["spatial_bias"]["celda_mas_poblada"],
                tolerancia=1e-9,
            )
        )

    degeneradas = check(quality, "degenerate_boxes")
    if degeneradas:
        filas += [
            Fila(
                "cajas degeneradas (ratio)",
                float(degeneradas["observed"]),
                recalculado["degenerate_boxes"]["ratio"],
                tolerancia=1e-9,
            ),
            Fila(
                "cajas degeneradas (ids)",
                degeneradas["offenders"],
                recalculado["degenerate_boxes"]["ids"],
            ),
        ]

    desbalance = check(quality, "class_imbalance")
    if desbalance:
        filas.append(
            Fila(
                "desbalance (max/min)",
                float(desbalance["observed"]),
                recalculado["class_imbalance"]["ratio"],
                tolerancia=1e-9,
            )
        )

    if duplicados is not None:
        copias = check(quality, "duplicates")
        if copias:
            filas += [
                Fila(
                    "duplicados (ratio)",
                    float(copias["observed"]),
                    duplicados["ratio"],
                    tolerancia=1e-9,
                ),
                Fila(
                    "duplicados (pares)",
                    len(copias["duplicates"]["pairs"]),
                    duplicados["pares"],
                ),
                Fila(
                    "duplicados (copias sobrantes)",
                    len(copias["offenders"]),
                    duplicados["sobrantes"],
                ),
                Fila(
                    "duplicados (ids sobrantes)",
                    copias["offenders"],
                    duplicados["ids_sobrantes"],
                ),
            ]

    return filas


def markdown(filas: list[Fila], recalculado: dict[str, Any], duplicados: dict[str, Any] | None):
    lineas = [
        "# Recalculo independiente del dataset",
        "",
        "Generado por `python scripts/recalculo_independiente.py`. La columna",
        "**Reportado** sale de `reports/quality.json` y `reports/stats.json`, que escribe",
        "`dataset_quality`. La columna **Recalculado** sale de leer",
        "`data/raw/annotations.coco.json` y las imagenes desde cero, con un pHash",
        "reimplementado sobre numpy: este script no importa `dataset_quality` ni",
        "`imagehash`, asi que un error del analizador no puede propagarse a los dos lados.",
        "",
        "| Metrica | Reportado | Recalculado | Coincide |",
        "| --- | --- | --- | --- |",
    ]
    lineas += [fila.como_markdown() for fila in filas]

    incoherentes = recalculado["area_declarada_incoherente"]
    lineas += [
        "",
        "> Sobre duplicados: en este dataset el valor correcto es cero, asi que la fila",
        "> de arriba confirma que ambos lados coinciden en un negativo. Que el detector",
        "> encuentre una copia CUANDO la hay se prueba aparte, inyectandola:",
        "> `tests/test_mutaciones.py::test_mutacion_copia_recomprimida`.",
        "",
        "## Comprobaciones extra que el pipeline no hace",
        "",
        f"- Anotaciones cuyo campo `area` del COCO no coincide con `ancho*alto` de su "
        f"`bbox`: **{len(incoherentes)}**.",
    ]
    if duplicados is not None:
        lineas.append(
            f"- Imagenes del COCO sin archivo legible en `data/raw/images/`: "
            f"**{len(duplicados['ausentes'])}** (se hashearon {duplicados['hasheadas']})."
        )
    else:
        lineas.append("- pHash omitido en esta corrida (`--sin-imagenes`).")

    fallan = [fila for fila in filas if not fila.coincide]
    lineas += [
        "",
        "## Veredicto",
        "",
        (
            f"**{len(fallan)} de {len(filas)} metricas no coinciden.**"
            if fallan
            else f"**Las {len(filas)} metricas coinciden.** El recalculo independiente reproduce "
            "exactamente lo que reporta el pipeline."
        ),
        "",
    ]
    return "\n".join(lineas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sin-imagenes",
        action="store_true",
        help="Salta el pHash de las 2045 imagenes (tarda minutos); el resto se recalcula igual.",
    )
    parser.add_argument(
        "--md",
        type=Path,
        default=PROYECTO2_DIR / "reports" / "evaluation" / "recalculo.md",
        help="Donde escribir la tabla en markdown.",
    )
    parser.add_argument(
        "--json",
        dest="json_destino",
        type=Path,
        default=PROYECTO2_DIR / "reports" / "evaluation" / "recalculo.json",
        help="Donde escribir el resultado crudo.",
    )
    args = parser.parse_args()

    politica = yaml.safe_load(POLITICA.read_text(encoding="utf-8"))
    coco = cargar_coco()
    quality, stats = leer_reportes()

    print("Recalculando desde data/raw/ sin importar dataset_quality...", file=sys.stderr)
    recalculado = recalcular_sin_imagenes(coco, politica)
    duplicados = None if args.sin_imagenes else recalcular_duplicados(coco, politica)

    filas = comparar(recalculado, duplicados, quality, stats)

    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(markdown(filas, recalculado, duplicados), encoding="utf-8", newline="\n")
    args.json_destino.write_text(
        json.dumps(
            {
                "dataset_fingerprint_reportado": quality["dataset_fingerprint"],
                "comparacion": [fila.como_dict() for fila in filas],
                "recalculado": {
                    clave: valor
                    for clave, valor in recalculado.items()
                    # Las listas de ids completas ya viajan en la comparacion.
                    if clave != "area_declarada_incoherente"
                },
                "duplicados": duplicados,
                "area_declarada_incoherente": recalculado["area_declarada_incoherente"],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    ancho = max(len(fila.metrica) for fila in filas)
    for fila in filas:
        marca = "OK  " if fila.coincide else "NO  "
        print(f"{marca}{fila.metrica.ljust(ancho)}  {fila.formato(fila.recalculado)[:60]}")

    fallan = [fila for fila in filas if not fila.coincide]
    print(f"\n{args.md} y {args.json_destino} escritos.")
    if fallan:
        print(f"\n{len(fallan)} de {len(filas)} metricas NO coinciden:", file=sys.stderr)
        for fila in fallan:
            print(
                f"  - {fila.metrica}: reportado {fila.formato(fila.reportado)[:80]} "
                f"!= recalculado {fila.formato(fila.recalculado)[:80]}",
                file=sys.stderr,
            )
        return 1

    print(f"Las {len(filas)} metricas coinciden con lo que reporta el pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
