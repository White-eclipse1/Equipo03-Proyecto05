"""Duplicados por hash perceptual.

El hash lo calcula `imagehash`, no este modulo. Implementar un pHash a mano
(escala de grises, DCT 2D, mediana de las bajas frecuencias) es media tarde de
trabajo y una fuente de errores sutiles que solo se notan cuando el analizador
deja pasar una copia — justo lo que no se puede permitir. La libreria esta
probada por mucha gente; lo que si es nuestro es la politica: que distancia
cuenta como duplicado y como se reporta.

Por que pHash y no un md5: un md5 cambia por completo si se recomprime el JPEG
o se reescala la foto, asi que no ve la copia. El pHash compara COMO SE VE la
imagen y sobrevive a ambas cosas. Ese es exactamente el duplicado que infla el
conteo de imagenes por clase sin aportar variedad.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from pathlib import Path

import imagehash
from PIL import Image, UnidentifiedImageError

from dataset_quality.analyzers.structural import por_impacto
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import (
    PHASH_BITS,
    DuplicatePair,
    DuplicatesCheck,
    DuplicatesDetail,
)
from dataset_quality.models.quality import CheckResult as Result


def perceptual_hash(path: Path) -> int:
    """pHash de 64 bits como entero, para comparar con operaciones de bits."""
    with Image.open(path) as handle:
        return int(str(imagehash.phash(handle)), 16)


def hamming(a: int, b: int) -> int:
    """Numero de bits en que difieren dos hashes."""
    return (a ^ b).bit_count()


def compute_hashes(dataset: CocoDataset, images_dir: Path) -> dict[int, int]:
    """pHash de cada imagen que este en disco, indexado por id.

    Una imagen ausente o ilegible se omite en lugar de romper el analisis: que
    la descarga este incompleta es problema del Tier 1, no de este analizador.
    """
    hashes: dict[int, int] = {}
    for image in dataset.images:
        path = images_dir / image.file_name
        if not path.is_file():
            continue
        try:
            hashes[image.id] = perceptual_hash(path)
        except (UnidentifiedImageError, OSError):
            continue
    return hashes


def find_pairs(hashes: dict[int, int], max_distance: int) -> list[tuple[int, int, int]]:
    """Pares `(id_menor, id_mayor, distancia)` por debajo del umbral."""
    return [
        (a, b, distance)
        for a, b in combinations(sorted(hashes), 2)
        if (distance := hamming(hashes[a], hashes[b])) <= max_distance
    ]


def duplicate_groups(hashes: dict[int, int], max_distance: int) -> list[set[int]]:
    """Componentes conexas del grafo de casi-duplicados.

    Un par por debajo del umbral no basta para decidir con quien viaja cada
    imagen: si A~B y B~C pero A y C quedan por encima del umbral entre si, los
    tres deben repartirse juntos igual, porque A y C comparten una copia (B) y
    separarlos filtraria esa copia entre splits. Union-find sobre los pares de
    `find_pairs` agrupa por esa relacion transitiva. Las imagenes sin ningun
    par cercano quedan en su propio grupo de tamano 1.
    """
    parent = {image_id: image_id for image_id in hashes}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, _ in find_pairs(hashes, max_distance):
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    groups: dict[int, set[int]] = {}
    for image_id in hashes:
        groups.setdefault(find(image_id), set()).add(image_id)
    return list(groups.values())


def classes_of_image(dataset: CocoDataset) -> dict[int, list[str]]:
    """Clases con al menos una caja en cada imagen, en el orden del COCO."""
    names = {category.id: category.name for category in dataset.categories}
    por_imagen: dict[int, list[str]] = {}
    for annotation in dataset.annotations:
        clases = por_imagen.setdefault(annotation.image_id, [])
        nombre = names[annotation.category_id]
        if nombre not in clases:
            clases.append(nombre)
    return por_imagen


def affected_classes(
    dataset: CocoDataset, offenders: list[int]
) -> tuple[dict[str, int], dict[str, int], int]:
    """A que clases afectan las copias: imagenes, cajas y copias sin clase.

    Una copia con cajas de dos clases suma en las dos — inflo el conteo de las
    dos — asi que la suma de `imagenes` puede superar `len(offenders)`. Ese es
    el numero que hay que restarle a cada clase para saber con cuantas imagenes
    distintas se queda de verdad.
    """
    names = {category.id: category.name for category in dataset.categories}
    sobrantes = set(offenders)

    por_imagen = classes_of_image(dataset)
    imagenes: dict[str, int] = defaultdict(int)
    for image_id in sobrantes:
        for nombre in por_imagen.get(image_id, ()):
            imagenes[nombre] += 1

    cajas: dict[str, int] = defaultdict(int)
    for annotation in dataset.annotations:
        if annotation.image_id in sobrantes:
            cajas[names[annotation.category_id]] += 1

    sin_clase = sum(1 for image_id in sobrantes if not por_imagen.get(image_id))

    return por_impacto(imagenes), por_impacto(cajas), sin_clase


def analyze_duplicates(dataset: CocoDataset, config: DuplicatesCheck, images_dir: Path) -> Result:
    """Marca como infractora la copia, no el original.

    De cada par se reporta el id mayor: el primero en aparecer se considera el
    original y el segundo, la copia. Asi el conteo de infractoras equivale a
    "cuantas imagenes sobran".

    Los pares y su reparto por clase viajan en `duplicates` dentro del propio
    `CheckResult`: son lo unico caro de este analizador — abrir cada imagen y
    calcular su pHash — y tirarlos obligaria a recalcularlos a todo el que
    quiera responder "a que clase afectan estos duplicados".
    """
    if not config.enabled:
        return _skipped(config)

    hashes = compute_hashes(dataset, images_dir)
    pairs = find_pairs(hashes, config.phash_hamming_distance)
    offenders = sorted({mayor for _, mayor, _ in pairs})

    total = len(dataset.images)
    observed = len(offenders) / total if total else 0.0

    imagenes_por_clase, cajas_por_clase, sin_clase = affected_classes(dataset, offenders)
    todos = duplicate_groups(hashes, config.phash_hamming_distance)
    grupos = [grupo for grupo in todos if len(grupo) > 1]

    return Result(
        name="duplicates",
        status="fail" if observed > config.max_ratio else "pass",
        severity=config.severity,
        observed=observed,
        threshold=config.max_ratio,
        message=(
            f"{len(pairs)} par(es) de imagenes casi identicas a distancia "
            f"<= {config.phash_hamming_distance} de {PHASH_BITS} bits; "
            f"{len(offenders)} de {total} imagenes sobran "
            f"({observed:.1%}; maximo permitido {config.max_ratio:.1%})"
            + (
                f"; la clase mas afectada es {next(iter(imagenes_por_clase))}"
                if imagenes_por_clase
                else ""
            )
        ),
        offenders=offenders,
        duplicates=DuplicatesDetail(
            max_distance=config.phash_hamming_distance,
            pairs=[
                DuplicatePair(
                    kept=menor,
                    duplicate=mayor,
                    distance=distancia,
                    similarity=1 - distancia / PHASH_BITS,
                )
                for menor, mayor, distancia in pairs
            ],
            groups=len(grupos),
            images_by_class=imagenes_por_clase,
            boxes_by_class=cajas_por_clase,
            images_without_class=sin_clase,
        ),
    )


def _skipped(config: DuplicatesCheck) -> Result:
    return Result(
        name="duplicates",
        status="skipped",
        severity=config.severity,
        observed=0.0,
        threshold=config.max_ratio,
        message="desactivado en quality.yaml",
    )
