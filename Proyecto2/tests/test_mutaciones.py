"""Pruebas de mutacion: se rompe el dataset a proposito y la compuerta tiene que verlo.

La diferencia con el resto de la suite es el sentido de la prueba. Las demas
comprueban que el codigo hace lo que dice sobre datos correctos. Estas parten
de un dataset que la compuerta aprueba (`test_la_base_sin_mutar_pasa`) y le
introducen UN defecto cada vez. Si despues de la mutacion la compuerta sigue
diciendo que todo esta bien, el analizador correspondiente no sirve para nada,
por mucho que sus pruebas unitarias esten en verde.

Las cuatro mutaciones son las que de verdad pueden llegar a un dataset real:

1. una copia recomprimida de una foto — el duplicado que un `md5` no ve;
2. una bbox con coordenada negativa — basura del exportador;
3. una bbox que se sale del borde de su imagen — la que SI atraviesa la
   validacion, porque mirando la anotacion sola no se puede saber;
4. un `min_images_per_class` inalcanzable — la compuerta contra la propia
   politica.

Todas se ejecutan por el CLI (`dq gate`) y no llamando al analizador a mano:
lo que hay que demostrar es el CODIGO DE SALIDA, porque es lo que detiene al
pipeline. Un analizador que calcula bien y un CLI que devuelve 0 igualmente
dejan pasar el release.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from PIL import Image

from dataset_quality import cli
from dataset_quality.tiers import ingest

PROYECTO2_DIR = Path(__file__).resolve().parent.parent
POLITICA_REAL = PROYECTO2_DIR / "quality.yaml"

LADO = 160


def _imagen_distinta(semilla: int) -> Image.Image:
    """Imagen reconocible y distinta de las demas, sin usar numpy aleatorio.

    El pHash mira las bajas frecuencias, asi que ruido puro daria hashes muy
    parecidos entre si y la prueba de duplicados no probaria nada. Un degradado
    con un bloque de color en una posicion distinta por semilla produce
    imagenes que el pHash separa con claridad.

    Se construye con numpy y no con un doble bucle sobre `Image.load()`: son
    160x160 pixeles por imagen y seis imagenes por prueba, y a razon de una
    llamada Python por pixel esta fixture sola costaba varios segundos en cada
    uno de los siete casos.
    """
    filas = np.arange(LADO).reshape(LADO, 1)
    columnas = np.arange(LADO).reshape(1, LADO)

    lienzo = np.empty((LADO, LADO, 3), dtype=np.uint8)
    lienzo[..., 0] = (columnas * 3 + semilla * 37) % 256
    lienzo[..., 1] = (filas * 3 + semilla * 91) % 256
    lienzo[..., 2] = (columnas + filas + semilla * 53) % 256

    # Un bloque opaco que se mueve con la semilla: separa las bajas frecuencias.
    lado_bloque = LADO // 2
    x = (semilla * 17) % lado_bloque
    y = (semilla * 29) % lado_bloque
    lienzo[y : y + lado_bloque, x : x + lado_bloque] = 255

    return Image.fromarray(lienzo, mode="RGB")


@pytest.fixture
def dataset(tmp_path: Path) -> dict[str, Any]:
    """Seis imagenes distintas, dos clases, una caja sana en cada una."""
    directorio = tmp_path / "raw"
    imagenes = directorio / "images"
    imagenes.mkdir(parents=True)

    coco: dict[str, Any] = {
        "images": [],
        "annotations": [],
        "categories": [{"id": 1, "name": "car"}, {"id": 2, "name": "person"}],
    }

    for numero in range(1, 7):
        nombre = f"img_{numero}.jpg"
        _imagen_distinta(numero).save(imagenes / nombre, quality=95)
        coco["images"].append({"id": numero, "file_name": nombre, "width": LADO, "height": LADO})
        # Caja centrada y grande: ni diminuta (no dispara small_objects) ni
        # concentrada siempre en la misma celda de la rejilla 3x3.
        desplazamiento = (numero % 3) * 20
        coco["annotations"].append(
            {
                "id": numero,
                "image_id": numero,
                "category_id": 1 if numero % 2 else 2,
                "bbox": [float(desplazamiento), float(desplazamiento), 60.0, 60.0],
                "area": 3600.0,
                "iscrowd": 0,
            }
        )

    anotaciones = directorio / "annotations.coco.json"
    anotaciones.write_text(json.dumps(coco), encoding="utf-8")

    return {"dir": directorio, "imagenes": imagenes, "coco": anotaciones, "tmp": tmp_path}


@pytest.fixture
def politica(tmp_path: Path):
    """La politica REAL, con el minimo de volumen bajado a lo que cabe aqui.

    Se parte de `quality.yaml` en vez de escribir umbrales inventados para que
    estas pruebas usen los de verdad: si alguien afloja `phash_hamming_distance`
    o sube `max_ratio` de duplicados en el archivo del proyecto, la mutacion 1
    deja de detectarse y esta suite se pone en rojo, que es justo lo que se
    quiere. Lo unico que se cambia es `min_images`, porque exigir 300 imagenes
    haria fallar a las cuatro mutaciones por un motivo que no es el suyo.
    """

    def construir(**cambios: Any) -> Path:
        config = yaml.safe_load(POLITICA_REAL.read_text(encoding="utf-8"))
        config["min_images_per_class"]["min_images"] = 2
        for clave, valor in cambios.items():
            config[clave].update(valor)
        destino = tmp_path / "quality.yaml"
        destino.write_text(yaml.safe_dump(config), encoding="utf-8")
        return destino

    return construir


def correr_compuerta(
    monkeypatch: pytest.MonkeyPatch,
    dataset: dict[str, Any],
    config: Path,
) -> tuple[int, dict[str, Any] | None]:
    """Ejecuta `dq gate` sobre este dataset y devuelve (codigo, reporte)."""
    monkeypatch.setattr(ingest, "RAW_ANNOTATIONS", dataset["coco"])
    monkeypatch.setattr(ingest, "RAW_IMAGES", dataset["imagenes"])

    salida = dataset["tmp"] / "quality.json"
    codigo = cli.main(["gate", "--config", str(config), "--out", str(salida)])
    reporte = json.loads(salida.read_text(encoding="utf-8")) if salida.is_file() else None
    return codigo, reporte


def bloquean(reporte: dict[str, Any]) -> set[str]:
    """Nombres de los checks que fallan CON severidad error."""
    return {
        check["name"]
        for check in reporte["checks"]
        if check["status"] == "fail" and check["severity"] == "error"
    }


# ---------------------------------------------------------------------------
# La base: sin esto, las cuatro mutaciones no demuestran nada
# ---------------------------------------------------------------------------
def test_la_base_sin_mutar_pasa(monkeypatch, dataset, politica) -> None:
    """Si la base ya estuviera en rojo, cualquier mutacion "se detectaria" sola."""
    codigo, reporte = correr_compuerta(monkeypatch, dataset, politica())

    assert reporte is not None
    assert bloquean(reporte) == set()
    assert codigo == 0


# ---------------------------------------------------------------------------
# Mutacion 1 — una copia recomprimida
# ---------------------------------------------------------------------------
def test_mutacion_copia_recomprimida(monkeypatch, dataset, politica) -> None:
    """El duplicado que sobrevive a la recompresion: mismo contenido, otro md5.

    Se vuelve a guardar `img_3.jpg` con calidad JPEG mucho mas baja y como una
    imagen nueva del COCO. Byte a byte no se parece en nada al original — un
    hash criptografico no las relaciona — pero se VE igual, que es lo que
    infla el conteo de imagenes por clase sin aportar variedad.
    """
    coco = json.loads(dataset["coco"].read_text(encoding="utf-8"))

    original = dataset["imagenes"] / "img_3.jpg"
    copia = dataset["imagenes"] / "img_3_recomprimida.jpg"
    with Image.open(original) as abierta:
        abierta.save(copia, quality=30, optimize=True)

    assert original.read_bytes() != copia.read_bytes(), "la copia tiene que diferir en bytes"

    coco["images"].append({"id": 7, "file_name": copia.name, "width": LADO, "height": LADO})
    coco["annotations"].append(
        {
            "id": 7,
            "image_id": 7,
            "category_id": 1,
            "bbox": [40.0, 40.0, 60.0, 60.0],
            "area": 3600.0,
            "iscrowd": 0,
        }
    )
    dataset["coco"].write_text(json.dumps(coco), encoding="utf-8")

    codigo, reporte = correr_compuerta(monkeypatch, dataset, politica())

    assert reporte is not None
    duplicados = next(check for check in reporte["checks"] if check["name"] == "duplicates")

    # El hallazgo: la copia (id mayor del par), no el original.
    assert duplicados["offenders"] == [7]
    assert duplicados["duplicates"]["pairs"][0]["kept"] == 3
    assert duplicados["duplicates"]["pairs"][0]["duplicate"] == 7
    # Y el efecto: el pipeline se detiene.
    assert "duplicates" in bloquean(reporte)
    assert codigo != 0


# ---------------------------------------------------------------------------
# Mutacion 2 — una bbox con coordenada negativa
# ---------------------------------------------------------------------------
def test_mutacion_bbox_negativa(monkeypatch, dataset, politica) -> None:
    """Se rechaza al leer el COCO, antes de que ningun analizador la toque.

    Este es el unico de los cuatro defectos que no llega a producir un
    `quality.json`: el dataset entero se considera invalido. Lo que importa es
    que el CLI lo traduzca a un codigo de salida y a un mensaje que diga que
    anotacion es, no que reviente con un rastro de Pydantic.
    """
    coco = json.loads(dataset["coco"].read_text(encoding="utf-8"))
    coco["annotations"][2]["bbox"] = [-12.0, 20.0, 60.0, 60.0]
    dataset["coco"].write_text(json.dumps(coco), encoding="utf-8")

    monkeypatch.setattr(ingest, "RAW_ANNOTATIONS", dataset["coco"])
    monkeypatch.setattr(ingest, "RAW_IMAGES", dataset["imagenes"])
    salida = dataset["tmp"] / "quality.json"

    codigo = cli.main(["gate", "--config", str(politica()), "--out", str(salida)])

    assert codigo != 0
    # No se escribe un reporte "aprobado" para un dataset que no se pudo leer.
    assert not salida.is_file()


def test_mutacion_bbox_negativa_dice_cual_es(dataset) -> None:
    """El mensaje de error nombra la anotacion y el campo, no solo que fallo."""
    from dataset_quality.models.coco import load_coco
    from dataset_quality.models.errors import DatasetValidationError

    coco = json.loads(dataset["coco"].read_text(encoding="utf-8"))
    coco["annotations"][2]["bbox"] = [-12.0, 20.0, 60.0, 60.0]
    dataset["coco"].write_text(json.dumps(coco), encoding="utf-8")

    with pytest.raises(DatasetValidationError) as error:
        load_coco(dataset["coco"])

    mensaje = str(error.value)
    assert "bbox" in mensaje
    assert "annotations.2" in mensaje


# ---------------------------------------------------------------------------
# Mutacion 3 — una bbox fuera del borde de su imagen
# ---------------------------------------------------------------------------
def test_mutacion_bbox_fuera_de_la_imagen(monkeypatch, dataset, politica) -> None:
    """La que SI atraviesa la validacion, y por eso necesita un analizador.

    `[120, 120, 60, 60]` es una caja perfectamente valida vista sola: origen
    positivo, ancho y alto positivos, area coherente. Solo es imposible cuando
    se sabe que su imagen mide 160x160 y la caja termina en 180. Por eso
    `degenerate_boxes` existe como check y no como validador de modelo.
    """
    coco = json.loads(dataset["coco"].read_text(encoding="utf-8"))
    coco["annotations"][4]["bbox"] = [120.0, 120.0, 60.0, 60.0]
    coco["annotations"][4]["area"] = 3600.0
    dataset["coco"].write_text(json.dumps(coco), encoding="utf-8")

    codigo, reporte = correr_compuerta(monkeypatch, dataset, politica())

    assert reporte is not None
    degeneradas = next(check for check in reporte["checks"] if check["name"] == "degenerate_boxes")

    assert degeneradas["offenders"] == [5]
    assert "degenerate_boxes" in bloquean(reporte)
    assert codigo != 0


# ---------------------------------------------------------------------------
# Mutacion 4 — un minimo de volumen inalcanzable
# ---------------------------------------------------------------------------
def test_mutacion_min_images_imposible(monkeypatch, dataset, politica) -> None:
    """La compuerta aplicada a la propia politica, no al dataset.

    Con seis imagenes y un minimo de diez mil, el unico resultado aceptable es
    que bloquee. Si pasara, significaria que el check se esta evaluando contra
    algo que no es el umbral configurado.
    """
    config = politica(min_images_per_class={"min_images": 10_000})

    codigo, reporte = correr_compuerta(monkeypatch, dataset, config)

    assert reporte is not None
    minimo = next(check for check in reporte["checks"] if check["name"] == "min_images_per_class")

    assert minimo["threshold"] == 10_000
    assert minimo["status"] == "fail"
    assert "min_images_per_class" in bloquean(reporte)
    assert codigo != 0


def test_mutacion_min_images_imposible_no_se_puede_esquivar_bajando_severidad(
    monkeypatch, dataset, politica
) -> None:
    """Degradar el check a `warning` deja pasar el release: por eso hay una prueba.

    No es un fallo del codigo — la politica dice lo que dice — sino la razon de
    que `tests/test_min_images.py` vigile el archivo real. Aqui se documenta el
    agujero de forma ejecutable: bajar la severidad ES la manera de saltarse la
    compuerta, y cualquiera que lo intente en `quality.yaml` pone la otra suite
    en rojo.
    """
    config = politica(
        min_images_per_class={"min_images": 10_000, "severity": "warning"},
    )

    codigo, reporte = correr_compuerta(monkeypatch, dataset, config)

    assert reporte is not None
    assert bloquean(reporte) == set()
    assert codigo == 0
