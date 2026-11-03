"""Manifiesto 70/20/10 agrupado, estratificado y reproducible (F3 T08, criterios 1.3 y M3).

Invariantes de `docs/contratos.md` §2 que protege esta suite:

1. Ningun `crop_id`, `source_image_id` ni `dup_group_id` aparece en dos particiones.
2. La proporcion de recortes por particion queda a +-5 puntos de 70/20/10.
3. Cada clase tiene al menos un recorte en `val` y en `test`.
4. Misma semilla y mismo release -> mismos `crop_id` por particion y mismo hash.

Los datos sinteticos imitan el release: varias cajas por original, originales con
dos clases y grupos de casi duplicados.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import pytest

from p3.data.crops import CropSource, read_image_sizes, validate_annotations
from p3.data.split import (
    ManifestRelease,
    SplitError,
    build_manifest,
    check_manifest,
    dup_group_ids,
    manifest_counts,
    manifest_hash,
    manifest_jsonl,
)

FIXTURE = Path(__file__).parent / "fixtures" / "p3"
NAMES = {2: "person", 3: "dog", 4: "cat"}
CLASS_INDEX = {4: 0, 3: 1, 2: 2}  # contratos §1: orden alfabetico
RELEASE = ManifestRelease(release_id="9.9.9", dataset_fingerprint="f" * 64)
PARTICIONES = ("train", "val", "test")


def source(annotation_id: int, image_id: int, category_id: int) -> CropSource:
    return CropSource(
        annotation_id=annotation_id,
        source_image_id=image_id,
        source_file_name=f"img_{image_id}.jpg",
        category_id=category_id,
        category_name=NAMES[category_id],
        bbox_xywh=(1.0, 2.0, 30.0, 40.0),
    )


def sintetico(seed: int = 0) -> tuple[list[CropSource], list[set[int]]]:
    """~600 recortes de 450 originales: desbalance de clases, varias cajas por foto,
    fotos con dos clases y grupos de casi duplicados de 2 y 3 imagenes."""
    rng = random.Random(seed)
    sources: list[CropSource] = []
    annotation_id = 0
    for image_id in range(1, 451):
        category = 2 if image_id <= 200 else (3 if image_id <= 330 else 4)
        for _ in range(rng.choice((1, 1, 1, 2, 3))):
            annotation_id += 1
            sources.append(source(annotation_id, image_id, category))
        if image_id % 25 == 0:  # algunas fotos tambien tienen una persona
            annotation_id += 1
            sources.append(source(annotation_id, image_id, 2))
    groups = [{10, 11}, {205, 206, 207}, {340, 341}, {400, 401}, {3, 150}]
    return sources, groups


def rows_of(sources, groups, seed: int = 42):
    return build_manifest(
        sources,
        release=RELEASE,
        class_index=CLASS_INDEX,
        dup_groups=dup_group_ids({s.source_image_id for s in sources}, groups),
        seed=seed,
    )


# --- Grupos de casi duplicados ------------------------------------------------------------


def test_dup_group_id_es_g_mas_el_menor_image_id() -> None:
    assert dup_group_ids({1, 2, 3, 7, 9}, [{7, 3}, {9}]) == {
        1: "g1",
        2: "g2",
        3: "g3",
        7: "g3",
        9: "g9",
    }


def test_una_imagen_en_dos_grupos_es_un_error() -> None:
    with pytest.raises(SplitError, match="5"):
        dup_group_ids({4, 5, 6}, [{4, 5}, {5, 6}])


# --- Aislamiento entre particiones (M3) ------------------------------------------------------


def _particiones_por(rows, campo: str) -> dict[object, set[str]]:
    visto: dict[object, set[str]] = {}
    for row in rows:
        visto.setdefault(row[campo], set()).add(row["split"])
    return visto


@pytest.mark.parametrize("campo", ["crop_id", "source_image_id", "dup_group_id"])
def test_ningun_identificador_aparece_en_dos_particiones(campo: str) -> None:
    rows = rows_of(*sintetico())
    assert all(len(splits) == 1 for splits in _particiones_por(rows, campo).values())


def test_los_casi_duplicados_viajan_juntos() -> None:
    rows = rows_of(*sintetico())
    split_de = {row["source_image_id"]: row["split"] for row in rows}
    for grupo in ({10, 11}, {205, 206, 207}, {3, 150}):
        assert len({split_de[i] for i in grupo}) == 1, grupo


def test_muchos_pares_de_casi_duplicados_nunca_se_separan() -> None:
    # 60 pares: si el reparto ignorara los grupos, alguno quedaria partido.
    sources, _ = sintetico()
    pares = [{i, i + 1} for i in range(1, 121, 2)]
    rows = rows_of(sources, pares)
    split_de = {row["source_image_id"]: row["split"] for row in rows}
    assert all(split_de[a] == split_de[b] for a, b in map(sorted, pares))


def test_una_foto_con_dos_clases_no_se_parte() -> None:
    rows = rows_of(*sintetico())
    de_la_225 = {row["split"] for row in rows if row["source_image_id"] == 225}
    assert {row["category_name"] for row in rows if row["source_image_id"] == 225} == {
        "dog",
        "person",
    }
    assert len(de_la_225) == 1


# --- Proporciones y presencia de clases -----------------------------------------------------


def test_proporciones_globales_a_menos_de_5_puntos_de_70_20_10() -> None:
    rows = rows_of(*sintetico())
    conteo = Counter(row["split"] for row in rows)
    for particion, objetivo in zip(PARTICIONES, (0.7, 0.2, 0.1), strict=True):
        assert abs(conteo[particion] / len(rows) - objetivo) <= 0.05, conteo


def test_proporciones_por_clase_cerca_de_70_20_10() -> None:
    rows = rows_of(*sintetico())
    for clase in NAMES.values():
        conteo = Counter(row["split"] for row in rows if row["category_name"] == clase)
        total = sum(conteo.values())
        for particion, objetivo in zip(PARTICIONES, (0.7, 0.2, 0.1), strict=True):
            assert abs(conteo[particion] / total - objetivo) <= 0.05, (clase, conteo)


def test_cada_clase_aparece_en_val_y_en_test() -> None:
    rows = rows_of(*sintetico())
    for particion in ("val", "test"):
        assert {row["category_name"] for row in rows if row["split"] == particion} == set(
            NAMES.values()
        )


def test_falla_si_una_clase_no_alcanza_para_val_y_test() -> None:
    sources = [source(i, i, 2) for i in range(1, 40)] + [source(99, 99, 4)]
    with pytest.raises(SplitError, match="cat"):
        rows_of(sources, [])


def test_falla_si_una_clase_queda_en_val_pero_no_en_test() -> None:
    # 3 originales de cat: 2 van a train y 1 a val; test se queda sin cat.
    sources = [source(i, i, 2) for i in range(1, 40)]
    sources += [source(97, 97, 4), source(98, 98, 4), source(99, 99, 4)]
    with pytest.raises(SplitError, match=r"cat.*test"):
        rows_of(sources, [])


# --- Reproducibilidad ------------------------------------------------------------------------


def test_misma_semilla_mismo_manifiesto_y_mismo_hash() -> None:
    uno, dos = rows_of(*sintetico()), rows_of(*sintetico())
    assert uno == dos
    assert manifest_hash(uno) == manifest_hash(dos)


def test_el_orden_de_entrada_no_cambia_el_resultado() -> None:
    sources, groups = sintetico()
    barajados = list(sources)
    random.Random(1).shuffle(barajados)
    assert manifest_hash(rows_of(sources, groups)) == manifest_hash(rows_of(barajados, groups))


def test_otra_semilla_da_otro_reparto() -> None:
    assert manifest_hash(rows_of(*sintetico(), seed=42)) != manifest_hash(
        rows_of(*sintetico(), seed=7)
    )


# --- Forma de las filas y del archivo (contratos §2) -----------------------------------------


def test_filas_con_los_campos_del_contrato() -> None:
    rows = rows_of(*sintetico())
    first = rows[0]
    assert set(first) == {
        "crop_id",
        "source_image_id",
        "source_file_name",
        "annotation_id",
        "category_id",
        "category_name",
        "class_index",
        "bbox_xywh",
        "dup_group_id",
        "split",
        "release_id",
        "release_hash",
    }
    assert [row["crop_id"] for row in rows] == sorted(row["crop_id"] for row in rows)
    for row in rows:
        assert row["crop_id"] == f"9.9.9:a{row['annotation_id']}"
        assert row["class_index"] == CLASS_INDEX[row["category_id"]]
        assert row["release_id"] == "9.9.9" and row["release_hash"] == "f" * 64
        assert row["split"] in PARTICIONES


def test_jsonl_canonico_y_hash_del_archivo() -> None:
    rows = rows_of(*sintetico())
    texto = manifest_jsonl(rows)
    lineas = texto.splitlines()
    assert texto.endswith("\n") and len(lineas) == len(rows)
    assert json.loads(lineas[0]) == rows[0]
    assert lineas[0] == json.dumps(rows[0], sort_keys=True, separators=(",", ":"))
    assert manifest_hash(rows) == hashlib.sha256(texto.encode("utf-8")).hexdigest()


def test_conteos_de_recortes_y_originales_por_clase_y_particion() -> None:
    rows = rows_of(*sintetico())
    counts = manifest_counts(rows)
    assert set(counts) == {"crops", "originals"}
    assert sum(sum(c.values()) for c in counts["crops"].values()) == len(rows)
    originales_test_cat = {
        row["source_image_id"]
        for row in rows
        if row["split"] == "test" and row["category_name"] == "cat"
    }
    assert counts["originals"]["test"]["cat"] == len(originales_test_cat)


# --- check_manifest: lo que revisara el evaluador ---------------------------------------------


def test_check_manifest_limpio() -> None:
    assert check_manifest(rows_of(*sintetico())) == []


def test_check_manifest_detecta_un_original_en_dos_particiones() -> None:
    rows = rows_of(*sintetico())
    victima = next(r for r in rows if r["split"] == "train")
    rows.append(victima | {"crop_id": "9.9.9:a999999", "split": "test"})
    problemas = check_manifest(rows)
    assert any("source_image_id" in p for p in problemas)
    assert any("dup_group_id" in p for p in problemas)


def test_check_manifest_detecta_una_clase_ausente_de_test() -> None:
    rows = [
        r for r in rows_of(*sintetico()) if not (r["split"] == "test" and r["category_id"] == 4)
    ]
    assert any("cat" in p and "test" in p for p in check_manifest(rows))


def test_check_manifest_detecta_proporciones_fuera_de_tolerancia() -> None:
    # Pasa a train la mitad de val: val queda en ~10 % y ninguna clase desaparece.
    rows = [
        r | {"split": "train"} if r["split"] == "val" and r["source_image_id"] % 2 else r
        for r in rows_of(*sintetico())
    ]
    problemas = check_manifest(rows)
    assert any(p.startswith("val:") and "objetivo 20%" in p for p in problemas), problemas
    assert not any("no tiene recortes" in p for p in problemas)


# --- Fixture: la caja degenerada no llega al manifiesto -------------------------------------


def test_fixture_la_caja_degenerada_y_la_fuera_de_imagen_no_estan_en_el_manifiesto() -> None:
    coco = json.loads((FIXTURE / "annotations.coco.json").read_text(encoding="utf-8"))
    sizes = read_image_sizes(coco["images"], FIXTURE / "images")
    valid = validate_annotations(coco, set(NAMES), sizes).valid
    rows = build_manifest(
        valid,
        release=RELEASE,
        class_index=CLASS_INDEX,
        dup_groups=dup_group_ids({i["id"] for i in coco["images"]}, [{25, 26}]),
        seed=42,
    )
    ids = {row["annotation_id"] for row in rows}
    assert len(rows) == 28
    assert {27, 30, 31}.isdisjoint(ids)  # faltante, degenerada, fuera de la imagen
    split_de = {row["source_image_id"]: row["split"] for row in rows}
    assert split_de[25] == split_de[26]
