"""Frente 3 — los cinco analizadores, cada uno contra un caso conocido.

Escritas ANTES de la implementacion: este archivo define la interfaz y el
comportamiento esperado, y la implementacion se escribe hasta que pasen.

Ninguna prueba toca MariaDB, MinIO ni la red. Los analizadores son funciones
puras sobre un `CocoDataset`; el unico que necesita disco es el de duplicados,
y usa imagenes que se generan en un `tmp_path`.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from dataset_quality.analyzers import (
    analyze_class_imbalance,
    analyze_degenerate_boxes,
    analyze_duplicates,
    analyze_small_objects,
    analyze_spatial_bias,
    describe,
    percentile,
    run_all,
)
from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import (
    ClassImbalanceCheck,
    DegenerateBoxesCheck,
    DuplicatesCheck,
    MinImagesPerClassCheck,
    QualityConfig,
    SmallObjectsCheck,
    SpatialBiasCheck,
    SplitsConfig,
)
from dataset_quality.models.splits import SplitRatios


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def coco(
    images: list[tuple[int, str, int, int]],
    boxes: list[tuple[int, int, int, float, float, float, float]],
    categories: list[tuple[int, str]],
) -> CocoDataset:
    """Construye un COCO valido desde tuplas. El area se deriva de la bbox.

    images: (id, file_name, width, height)
    boxes:  (id, image_id, category_id, x, y, w, h)
    """
    return CocoDataset.model_validate(
        {
            "images": [{"id": i, "file_name": n, "width": w, "height": h} for i, n, w, h in images],
            "annotations": [
                {
                    "id": bid,
                    "image_id": img,
                    "category_id": cat,
                    "bbox": [x, y, w, h],
                    "area": w * h,
                    "iscrowd": 0,
                }
                for bid, img, cat, x, y, w, h in boxes
            ],
            "categories": [{"id": i, "name": n} for i, n in categories],
        }
    )


def draw(path, seed: int, size: tuple[int, int] = (256, 192)) -> None:
    """Imagen con estructura reconocible: el pHash necesita algo que mirar.

    Una imagen de color plano tiene pHash identico a cualquier otra plana,
    porque no hay frecuencias que comparar.
    """
    canvas = Image.new("RGB", size, (240, 240, 245))
    painter = ImageDraw.Draw(canvas)
    for index in range(7):
        offset = (index * 31 + seed * 47) % (size[0] - 60)
        painter.rectangle(
            [offset, 15 + index * 22, offset + 52, 58 + index * 22],
            fill=(30 + index * 28, (90 + seed * 40) % 256, 210 - index * 24),
        )
    canvas.save(path, "JPEG", quality=93)


@pytest.fixture
def photos(tmp_path):
    """Genera imagenes en disco y devuelve el directorio."""

    def build(**named_seeds: int):
        for name, seed in named_seeds.items():
            draw(tmp_path / f"{name}.jpg", seed)
        return tmp_path

    return build


# --------------------------------------------------------------------------
# Objetos pequenos — dos criterios: area RELATIVA a la imagen y 32x32 absolutos
# --------------------------------------------------------------------------
# `min_area_px=0` apaga el criterio absoluto: este bloque prueba el relativo
# aislado, y sin apagarlo las cajas de los ejemplos (100 px2, 400 px2) caerian
# marcadas por el absoluto y las pruebas dejarian de medir lo que dicen medir.
SMALL = SmallObjectsCheck(area_ratio_threshold=0.01, max_ratio=0.30, min_area_px=0)

# El mismo check con el criterio absoluto en su valor por defecto (32x32).
SMALL_ABS = SmallObjectsCheck(area_ratio_threshold=0.01, max_ratio=0.30)


def test_objeto_bajo_el_umbral_relativo_se_marca() -> None:
    # Imagen 100x100 = 10.000 px2. Caja 5x10 = 50 px2 -> 0.005 < 0.01
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 5, 10)],
        categories=[(1, "car")],
    )
    result = analyze_small_objects(dataset, SMALL)

    assert result.offenders == [1]
    assert result.observed == pytest.approx(1.0)


def test_objeto_grande_no_se_marca() -> None:
    # Caja 40x40 = 1.600 px2 sobre 10.000 -> 0.16, muy por encima de 0.01
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 40, 40)],
        categories=[(1, "car")],
    )
    result = analyze_small_objects(dataset, SMALL)

    assert result.offenders == []
    assert result.observed == pytest.approx(0.0)


def test_objeto_justo_en_el_umbral_no_se_marca() -> None:
    """El umbral es inclusivo: exactamente 0.01 esta permitido."""
    # 10x10 = 100 px2 sobre 10.000 -> exactamente 0.01
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    assert analyze_small_objects(dataset, SMALL).offenders == []


def test_objetos_pequenos_falla_al_pasar_el_maximo() -> None:
    # 3 de 4 cajas son diminutas -> 0.75 > max_ratio 0.30
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[
            (1, 1, 1, 0, 0, 5, 5),
            (2, 1, 1, 10, 10, 5, 5),
            (3, 1, 1, 20, 20, 5, 5),
            (4, 1, 1, 30, 30, 40, 40),
        ],
        categories=[(1, "car")],
    )
    result = analyze_small_objects(dataset, SMALL)

    assert result.observed == pytest.approx(0.75)
    assert result.status == "fail"
    assert result.severity == "warning"


def test_el_umbral_es_relativo_al_tamano_de_cada_imagen() -> None:
    """La misma caja es pequena en una foto grande y normal en una chica."""
    dataset = coco(
        images=[(1, "grande.jpg", 1000, 1000), (2, "chica.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 20, 20), (2, 2, 1, 0, 0, 20, 20)],
        categories=[(1, "car")],
    )
    # 400/1.000.000 = 0.0004 (pequena) vs 400/10.000 = 0.04 (normal)
    assert analyze_small_objects(dataset, SMALL).offenders == [1]


def test_una_caja_diminuta_en_px_se_marca_aunque_la_proporcion_sea_buena() -> None:
    """El punto ciego del criterio relativo: imagen chica, objeto minusculo.

    20x20 = 400 px2 sobre una foto de 200x200 es el 1% del area — por encima
    del umbral relativo de 0.01 — pero son 400 pixeles de objeto, por debajo
    de los 1024 (32x32) de COCO.
    """
    dataset = coco(
        images=[(1, "chica.jpg", 200, 200)],
        boxes=[(1, 1, 1, 0, 0, 20, 20)],
        categories=[(1, "car")],
    )
    result = analyze_small_objects(dataset, SMALL_ABS)

    assert result.offenders == [1]
    assert result.small_objects is not None
    assert result.small_objects.below_min_area == 1
    # El relativo no la habria marcado: 400/40.000 = 0.01, justo en el limite.
    assert result.small_objects.below_ratio == 0


def test_una_caja_grande_en_px_pero_diminuta_en_proporcion_se_marca() -> None:
    """El caso simetrico: 2.500 px2 pasa el absoluto y el relativo la marca."""
    dataset = coco(
        images=[(1, "enorme.jpg", 4000, 4000)],
        boxes=[(1, 1, 1, 0, 0, 50, 50)],
        categories=[(1, "car")],
    )
    result = analyze_small_objects(dataset, SMALL_ABS)

    assert result.offenders == [1]
    assert result.small_objects is not None
    assert result.small_objects.below_ratio == 1
    assert result.small_objects.below_min_area == 0


def test_los_dos_criterios_se_solapan_sin_contar_la_caja_dos_veces() -> None:
    """Una caja que incumple ambos es UNA infractora, pero suma en los dos."""
    dataset = coco(
        images=[(1, "a.jpg", 1000, 1000)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    result = analyze_small_objects(dataset, SMALL_ABS)

    assert result.offenders == [1]
    assert result.small_objects is not None
    assert result.small_objects.below_ratio == 1
    assert result.small_objects.below_min_area == 1


def test_el_desglose_ordena_por_clase_mas_afectada() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100), (2, "b.jpg", 100, 100)],
        boxes=[
            (1, 1, 1, 0, 0, 2, 2),
            (2, 1, 1, 10, 10, 2, 2),
            (3, 2, 1, 20, 20, 2, 2),
            (4, 1, 2, 30, 30, 2, 2),
            (5, 1, 3, 40, 40, 90, 90),
        ],
        categories=[(1, "car"), (2, "dog"), (3, "person")],
    )
    result = analyze_small_objects(dataset, SMALL)
    detalle = result.small_objects

    assert detalle is not None
    # `car` primero por tener mas cajas marcadas; `person` no aparece.
    assert list(detalle.boxes_by_class) == ["car", "dog"]
    assert detalle.boxes_by_class == {"car": 3, "dog": 1}
    # Tres cajas de `car` pero repartidas en dos imagenes distintas.
    assert detalle.images_by_class == {"car": 2, "dog": 1}
    assert "la clase mas afectada es car" in result.message


def test_el_desglose_desempata_por_nombre_para_ser_reproducible() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 2, 0, 0, 2, 2), (2, 1, 1, 10, 10, 2, 2)],
        categories=[(1, "car"), (2, "dog")],
    )
    detalle = analyze_small_objects(dataset, SMALL).small_objects

    assert detalle is not None
    assert list(detalle.boxes_by_class) == ["car", "dog"]


def test_min_area_px_en_cero_deja_el_criterio_relativo_puro() -> None:
    """Apagar el absoluto devuelve exactamente el comportamiento anterior."""
    dataset = coco(
        images=[(1, "chica.jpg", 200, 200)],
        boxes=[(1, 1, 1, 0, 0, 20, 20)],
        categories=[(1, "car")],
    )
    assert analyze_small_objects(dataset, SMALL).offenders == []


def test_el_detalle_repite_los_umbrales_que_se_aplicaron() -> None:
    """La pantalla dibuja el corte sin tener que releer quality.yaml."""
    dataset = coco([(1, "a.jpg", 100, 100)], [(1, 1, 1, 0, 0, 5, 5)], [(1, "car")])
    detalle = analyze_small_objects(dataset, SMALL_ABS).small_objects

    assert detalle is not None
    assert detalle.area_ratio_threshold == pytest.approx(0.01)
    assert detalle.min_area_px == 1024


def test_analizador_desactivado_se_salta() -> None:
    dataset = coco([(1, "a.jpg", 100, 100)], [(1, 1, 1, 0, 0, 5, 5)], [(1, "car")])
    disabled = SmallObjectsCheck(enabled=False, area_ratio_threshold=0.01, max_ratio=0.30)

    assert analyze_small_objects(dataset, disabled).status == "skipped"


def test_dataset_sin_cajas_no_divide_entre_cero() -> None:
    dataset = coco([(1, "a.jpg", 100, 100)], [], [(1, "car")])
    result = analyze_small_objects(dataset, SMALL)

    assert result.observed == 0.0
    assert result.status == "pass"


# --------------------------------------------------------------------------
# Desbalance de clases — se cuentan IMAGENES, no cajas
# --------------------------------------------------------------------------
BALANCE = ClassImbalanceCheck(max_ratio_max_min=2.0)


def test_desbalance_es_la_razon_entre_la_clase_mayor_y_la_menor() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100), (2, "b.jpg", 100, 100), (3, "c.jpg", 100, 100)],
        boxes=[
            (1, 1, 1, 0, 0, 10, 10),
            (2, 2, 1, 0, 0, 10, 10),
            (3, 3, 1, 0, 0, 10, 10),
            (4, 1, 2, 20, 20, 10, 10),
        ],
        categories=[(1, "car"), (2, "cat")],
    )
    result = analyze_class_imbalance(dataset, BALANCE)

    assert result.observed == pytest.approx(3.0)  # car 3 imagenes / cat 1
    assert result.status == "fail"


def test_desbalance_cuenta_imagenes_distintas_no_cajas() -> None:
    """Una foto con siete coches aporta UNA imagen a `car`, no siete."""
    dataset = coco(
        images=[(1, "a.jpg", 100, 100), (2, "b.jpg", 100, 100)],
        boxes=[
            (1, 1, 1, 0, 0, 10, 10),
            (2, 1, 1, 20, 0, 10, 10),
            (3, 1, 1, 40, 0, 10, 10),
            (4, 2, 2, 0, 0, 10, 10),
        ],
        categories=[(1, "car"), (2, "cat")],
    )
    # Si contara cajas seria 3.0; contando imagenes es 1.0.
    assert analyze_class_imbalance(dataset, BALANCE).observed == pytest.approx(1.0)


def test_dataset_balanceado_pasa() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100), (2, "b.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 10, 10), (2, 2, 2, 0, 0, 10, 10)],
        categories=[(1, "car"), (2, "cat")],
    )
    result = analyze_class_imbalance(dataset, BALANCE)

    assert result.observed == pytest.approx(1.0)
    assert result.status == "pass"


def test_desbalance_senala_las_clases_infrarrepresentadas() -> None:
    dataset = coco(
        images=[(i, f"{i}.jpg", 100, 100) for i in range(1, 6)],
        boxes=[(i, i, 1, 0, 0, 10, 10) for i in range(1, 5)] + [(5, 5, 2, 0, 0, 10, 10)],
        categories=[(1, "car"), (2, "cat")],
    )
    # car 4 / cat 1 = 4.0 > 2.0
    assert analyze_class_imbalance(dataset, BALANCE).offenders == [2]


def test_una_sola_clase_no_esta_desbalanceada() -> None:
    dataset = coco([(1, "a.jpg", 100, 100)], [(1, 1, 1, 0, 0, 10, 10)], [(1, "car")])
    result = analyze_class_imbalance(dataset, BALANCE)

    assert result.observed == pytest.approx(1.0)
    assert result.status == "pass"


def test_una_clase_sin_ninguna_imagen_no_hace_infinito_el_ratio() -> None:
    """Una categoria declarada pero nunca usada es un caso aparte, no un 1/0."""
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car"), (2, "jamas_usada")],
    )
    result = analyze_class_imbalance(dataset, BALANCE)

    assert result.observed != float("inf")
    assert 2 in result.offenders


# --------------------------------------------------------------------------
# Cajas degeneradas — las que se salen de la imagen
# --------------------------------------------------------------------------
DEGENERATE = DegenerateBoxesCheck(max_ratio=0.0)


def test_caja_que_se_sale_de_la_imagen_se_marca() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 1, 90, 90, 40, 40)],  # llega a 130 > 100
        categories=[(1, "car")],
    )
    result = analyze_degenerate_boxes(dataset, DEGENERATE)

    assert result.offenders == [1]
    assert result.status == "fail"
    assert result.severity == "error"


def test_caja_pegada_al_borde_es_valida() -> None:
    """Tocar el borde exacto no es salirse."""
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 1, 60, 60, 40, 40)],  # llega justo a 100
        categories=[(1, "car")],
    )
    result = analyze_degenerate_boxes(dataset, DEGENERATE)

    assert result.offenders == []
    assert result.status == "pass"


def test_cajas_degeneradas_reporta_la_proporcion() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[(1, 1, 1, 90, 90, 40, 40), (2, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    assert analyze_degenerate_boxes(dataset, DEGENERATE).observed == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Sesgo espacial
# --------------------------------------------------------------------------
SPATIAL = SpatialBiasCheck(grid_size=4, max_cell_share=0.25)


def test_todos_los_objetos_en_una_celda_es_sesgo_total() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 400, 400)],
        boxes=[(i, 1, 1, 10, 10, 20, 20) for i in range(1, 6)],
        categories=[(1, "car")],
    )
    result = analyze_spatial_bias(dataset, SPATIAL)

    assert result.observed == pytest.approx(1.0)
    assert result.status == "fail"


def test_objetos_repartidos_dan_el_reparto_uniforme() -> None:
    """Un objeto en cada celda de la rejilla 4x4 -> 1/16 por celda."""
    boxes = []
    box_id = 1
    for row in range(4):
        for col in range(4):
            cx, cy = col * 100 + 50, row * 100 + 50
            boxes.append((box_id, 1, 1, cx - 5, cy - 5, 10, 10))
            box_id += 1
    dataset = coco([(1, "a.jpg", 400, 400)], boxes, [(1, "car")])
    result = analyze_spatial_bias(dataset, SPATIAL)

    assert result.observed == pytest.approx(1 / 16)
    assert result.status == "pass"


def test_sesgo_espacial_usa_el_centro_de_la_caja() -> None:
    """Una caja grande pertenece a la celda donde cae su centro."""
    dataset = coco(
        images=[(1, "a.jpg", 400, 400)],
        boxes=[(1, 1, 1, 0, 0, 390, 390)],  # centro en (195, 195) -> celda (1,1)
        categories=[(1, "car")],
    )
    assert analyze_spatial_bias(dataset, SPATIAL).observed == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Duplicados por pHash
# --------------------------------------------------------------------------
DUPLICATES = DuplicatesCheck(phash_hamming_distance=6, max_ratio=0.0)


def test_copia_recomprimida_y_reescalada_se_detecta(tmp_path) -> None:
    """El caso que un md5 NO detecta y que infla el conteo por clase."""
    draw(tmp_path / "original.jpg", seed=3)
    with Image.open(tmp_path / "original.jpg") as handle:
        copia = handle.resize((180, 135), Image.Resampling.LANCZOS)
        copia = copia.resize(handle.size, Image.Resampling.LANCZOS)
    copia.save(tmp_path / "copia.jpg", "JPEG", quality=40)

    dataset = coco(
        images=[(1, "original.jpg", 256, 192), (2, "copia.jpg", 256, 192)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    result = analyze_duplicates(dataset, DUPLICATES, tmp_path)

    assert result.offenders == [2]
    assert result.status == "fail"


def test_imagenes_distintas_no_son_duplicados(photos) -> None:
    images_dir = photos(a=1, b=9)
    dataset = coco(
        images=[(1, "a.jpg", 256, 192), (2, "b.jpg", 256, 192)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    result = analyze_duplicates(dataset, DUPLICATES, images_dir)

    assert result.offenders == []
    assert result.status == "pass"


def test_la_proporcion_de_duplicados_es_sobre_el_total_de_imagenes(photos) -> None:
    images_dir = photos(a=1, b=9, c=17)
    # `d` es copia byte a byte de `a`
    (images_dir / "d.jpg").write_bytes((images_dir / "a.jpg").read_bytes())

    dataset = coco(
        images=[
            (1, "a.jpg", 256, 192),
            (2, "b.jpg", 256, 192),
            (3, "c.jpg", 256, 192),
            (4, "d.jpg", 256, 192),
        ],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    result = analyze_duplicates(dataset, DUPLICATES, images_dir)

    assert result.offenders == [4]
    assert result.observed == pytest.approx(0.25)  # 1 de 4


def test_el_detalle_dice_a_que_clase_afectan_los_duplicados(photos) -> None:
    """La pregunta del Copilot: cuantos duplicados hay y a que clase afectan.

    Sin esto el check solo deja los ids sobrantes, y responderla obligaria a
    volver a abrir todas las imagenes para recalcular los pares.
    """
    images_dir = photos(a=1, b=9)
    (images_dir / "copia_de_a.jpg").write_bytes((images_dir / "a.jpg").read_bytes())

    dataset = coco(
        images=[
            (1, "a.jpg", 256, 192),
            (2, "b.jpg", 256, 192),
            (3, "copia_de_a.jpg", 256, 192),
        ],
        boxes=[
            (1, 1, 1, 0, 0, 10, 10),  # original: car
            (2, 2, 2, 0, 0, 10, 10),  # distinta: cat
            (3, 3, 1, 0, 0, 10, 10),  # la copia: car
            (4, 3, 1, 20, 0, 10, 10),  # la copia: otra caja de car
            (5, 3, 2, 40, 0, 10, 10),  # la copia: ademas cat
        ],
        categories=[(1, "car"), (2, "cat")],
    )
    result = analyze_duplicates(dataset, DUPLICATES, images_dir)
    detalle = result.duplicates

    assert result.offenders == [3]
    assert detalle is not None
    # La copia tiene cajas de dos clases, asi que afecta a las dos.
    assert detalle.images_by_class == {"car": 1, "cat": 1}
    # Pero se perderian tres cajas, no dos: dos de car y una de cat.
    assert detalle.boxes_by_class == {"car": 2, "cat": 1}
    assert detalle.images_without_class == 0
    assert detalle.groups == 1
    assert detalle.max_distance == DUPLICATES.phash_hamming_distance


def test_el_detalle_conserva_los_pares_con_su_similitud(photos) -> None:
    """La rubrica pide los pares con su similitud, no solo el conteo."""
    images_dir = photos(a=1)
    (images_dir / "copia.jpg").write_bytes((images_dir / "a.jpg").read_bytes())

    dataset = coco(
        images=[(1, "a.jpg", 256, 192), (2, "copia.jpg", 256, 192)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    detalle = analyze_duplicates(dataset, DUPLICATES, images_dir).duplicates

    assert detalle is not None
    assert len(detalle.pairs) == 1
    par = detalle.pairs[0]
    # Se conserva el id menor y sobra el mayor.
    assert (par.kept, par.duplicate) == (1, 2)
    # Copia byte a byte: mismo pHash, distancia cero, similitud total.
    assert par.distance == 0
    assert par.similarity == pytest.approx(1.0)


def test_la_clase_mas_afectada_encabeza_el_detalle(photos) -> None:
    """Ordenado por impacto: la primera clave responde la pregunta de un vistazo."""
    images_dir = photos(a=1, b=9)
    (images_dir / "copia_a.jpg").write_bytes((images_dir / "a.jpg").read_bytes())
    (images_dir / "copia_b.jpg").write_bytes((images_dir / "b.jpg").read_bytes())

    dataset = coco(
        images=[
            (1, "a.jpg", 256, 192),
            (2, "b.jpg", 256, 192),
            (3, "copia_a.jpg", 256, 192),
            (4, "copia_b.jpg", 256, 192),
        ],
        boxes=[
            (1, 3, 2, 0, 0, 10, 10),  # copia de a -> cat
            (2, 4, 2, 0, 0, 10, 10),  # copia de b -> cat
            (3, 4, 1, 20, 0, 10, 10),  # copia de b -> tambien car
        ],
        categories=[(1, "car"), (2, "cat")],
    )
    detalle = analyze_duplicates(dataset, DUPLICATES, images_dir).duplicates

    assert detalle is not None
    assert next(iter(detalle.images_by_class)) == "cat"
    assert detalle.images_by_class == {"cat": 2, "car": 1}
    assert detalle.groups == 2
    assert "cat" in analyze_duplicates(dataset, DUPLICATES, images_dir).message


def test_una_copia_sin_ninguna_caja_se_cuenta_aparte(photos) -> None:
    """Una copia sin anotar no afecta a ninguna clase, pero sigue sobrando."""
    images_dir = photos(a=1)
    (images_dir / "copia.jpg").write_bytes((images_dir / "a.jpg").read_bytes())

    dataset = coco(
        images=[(1, "a.jpg", 256, 192), (2, "copia.jpg", 256, 192)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    detalle = analyze_duplicates(dataset, DUPLICATES, images_dir).duplicates

    assert detalle is not None
    assert detalle.images_by_class == {}
    assert detalle.images_without_class == 1


def test_el_detalle_solo_lo_lleva_el_check_de_duplicados(photos) -> None:
    images_dir = photos(a=1)
    dataset = coco([(1, "a.jpg", 256, 192)], [(1, 1, 1, 0, 0, 30, 30)], [(1, "car")])

    results = {r.name: r for r in run_all(dataset, full_config(), images_dir)}

    assert results["duplicates"].duplicates is not None
    assert all(
        result.duplicates is None for name, result in results.items() if name != "duplicates"
    )


def test_un_check_de_duplicados_desactivado_no_inventa_detalle(photos) -> None:
    images_dir = photos(a=1)
    dataset = coco([(1, "a.jpg", 256, 192)], [(1, 1, 1, 0, 0, 30, 30)], [(1, "car")])
    config = DuplicatesCheck(enabled=False, phash_hamming_distance=6, max_ratio=0.1)

    result = analyze_duplicates(dataset, config, images_dir)

    assert result.status == "skipped"
    assert result.duplicates is None


def test_una_imagen_que_falta_en_disco_no_rompe_el_analisis(photos) -> None:
    images_dir = photos(a=1)
    dataset = coco(
        images=[(1, "a.jpg", 256, 192), (2, "no_descargada.jpg", 256, 192)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    result = analyze_duplicates(dataset, DUPLICATES, images_dir)

    assert result.status == "pass"


# --------------------------------------------------------------------------
# Descriptiva
# --------------------------------------------------------------------------
def test_la_descriptiva_resume_el_dataset() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100), (2, "b.jpg", 200, 200)],
        boxes=[
            (1, 1, 1, 0, 0, 10, 10),
            (2, 1, 1, 20, 20, 10, 10),
            (3, 2, 2, 0, 0, 50, 50),
        ],
        categories=[(1, "car"), (2, "cat")],
    )
    stats = describe(dataset)

    assert stats.totals.images == 2
    assert stats.totals.annotations == 3
    assert stats.totals.categories == 2
    assert stats.images_per_class == {"car": 1, "cat": 1}
    assert stats.boxes_per_class == {"car": 2, "cat": 1}
    assert stats.annotations_per_image == pytest.approx(1.5)


def test_la_descriptiva_da_media_mediana_y_p90_del_area_relativa() -> None:
    """Tres cifras y no una: la distribucion del area de caja esta sesgada.

    Cuatro cajas en una imagen de 100x100 ocupando 1%, 1%, 4% y 64%. La mediana
    (2.5%) dice que la caja tipica es diminuta; la media (17.5%) se va detras de
    la grande, y el p90 muestra cuanto se estira la cola. Reportar solo una de
    las tres describe mal el dataset.
    """
    dataset = coco(
        images=[(1, "a.jpg", 100, 100)],
        boxes=[
            (1, 1, 1, 0, 0, 10, 10),  # 100 px  -> 1%
            (2, 1, 1, 10, 0, 10, 10),  # 100 px  -> 1%
            (3, 1, 1, 20, 0, 20, 20),  # 400 px  -> 4%
            (4, 1, 1, 0, 20, 80, 80),  # 6400 px -> 64%
        ],
        categories=[(1, "car")],
    )
    stats = describe(dataset)

    assert stats.median_box_area_ratio == pytest.approx(0.025)
    assert stats.mean_box_area_ratio == pytest.approx(0.175)
    # Con cuatro valores el p90 cae entre 4% y 64%: 0.9*(4-1) = 2.7.
    assert stats.p90_box_area_ratio == pytest.approx(0.04 + 0.7 * (0.64 - 0.04))
    # La senal de la cola larga: la media por encima de la mediana.
    assert stats.mean_box_area_ratio > stats.median_box_area_ratio


def test_un_dataset_sin_cajas_no_rompe_la_descriptiva() -> None:
    dataset = coco(images=[(1, "a.jpg", 100, 100)], boxes=[], categories=[(1, "car")])
    stats = describe(dataset)

    assert stats.mean_box_area_ratio == 0.0
    assert stats.median_box_area_ratio == 0.0
    assert stats.p90_box_area_ratio == 0.0


def test_el_percentil_interpola_entre_los_dos_vecinos() -> None:
    valores = [0.0, 1.0, 2.0, 3.0, 4.0]

    assert percentile(valores, 0.0) == pytest.approx(0.0)
    assert percentile(valores, 0.5) == pytest.approx(2.0)
    assert percentile(valores, 1.0) == pytest.approx(4.0)
    # 0.9 * (5 - 1) = 3.6 -> entre el tercero y el cuarto.
    assert percentile(valores, 0.9) == pytest.approx(3.6)
    # Un solo valor es su propio percentil; sin valores, cero.
    assert percentile([7.0], 0.9) == pytest.approx(7.0)
    assert percentile([], 0.9) == 0.0


def test_la_descriptiva_incluye_imagenes_sin_anotar() -> None:
    dataset = coco(
        images=[(1, "a.jpg", 100, 100), (2, "vacia.jpg", 100, 100)],
        boxes=[(1, 1, 1, 0, 0, 10, 10)],
        categories=[(1, "car")],
    )
    assert describe(dataset).images_without_annotations == 1


# --------------------------------------------------------------------------
# Orquestacion
# --------------------------------------------------------------------------
def full_config(**overrides) -> QualityConfig:
    base = {
        # El minimo real del curso; las pruebas de este frente usan datasets
        # diminutos, asi que se relaja aqui para no tapar lo que se esta midiendo.
        "min_images_per_class": MinImagesPerClassCheck(min_images=1, min_classes=1),
        "small_objects": SmallObjectsCheck(area_ratio_threshold=0.01, max_ratio=0.5),
        "class_imbalance": ClassImbalanceCheck(max_ratio_max_min=10.0),
        "duplicates": DuplicatesCheck(phash_hamming_distance=6, max_ratio=0.1),
        "degenerate_boxes": DegenerateBoxesCheck(max_ratio=0.0),
        "spatial_bias": SpatialBiasCheck(grid_size=4, max_cell_share=0.9),
        "splits": SplitsConfig(ratios=SplitRatios(train=0.7, val=0.15, test=0.15)),
    }
    return QualityConfig(**{**base, **overrides})


def test_run_all_devuelve_un_resultado_por_analizador(photos) -> None:
    images_dir = photos(a=1)
    dataset = coco([(1, "a.jpg", 256, 192)], [(1, 1, 1, 0, 0, 30, 30)], [(1, "car")])

    results = run_all(dataset, full_config(), images_dir)

    assert [r.name for r in results] == [
        "min_images_per_class",
        "small_objects",
        "class_imbalance",
        "duplicates",
        "degenerate_boxes",
        "spatial_bias",
    ]


def test_run_all_marca_como_skipped_los_desactivados(photos) -> None:
    images_dir = photos(a=1)
    dataset = coco([(1, "a.jpg", 256, 192)], [(1, 1, 1, 0, 0, 30, 30)], [(1, "car")])
    config = full_config(
        duplicates=DuplicatesCheck(enabled=False, phash_hamming_distance=6, max_ratio=0.1)
    )

    results = {r.name: r for r in run_all(dataset, config, images_dir)}

    assert results["duplicates"].status == "skipped"
    assert results["small_objects"].status != "skipped"


def test_cada_resultado_cumple_el_contrato_congelado(photos) -> None:
    """`CheckResult` es lo que consumen los Frentes 4, 7 y 8."""
    images_dir = photos(a=1)
    dataset = coco([(1, "a.jpg", 256, 192)], [(1, 1, 1, 0, 0, 30, 30)], [(1, "car")])

    for result in run_all(dataset, full_config(), images_dir):
        assert result.status in {"pass", "fail", "skipped"}
        assert result.severity in {"error", "warning"}
        assert isinstance(result.observed, float)
        assert isinstance(result.threshold, float)
        assert result.message, "cada check debe explicarse en una linea"
        assert all(isinstance(offender, int) for offender in result.offenders)


# --------------------------------------------------------------------------
# Proyeccion 2D — cada punto sabe de que archivo salio
# --------------------------------------------------------------------------
def test_cada_punto_lleva_el_nombre_de_su_archivo(photos) -> None:
    """Sin `file_name`, servir la miniatura obligaba a cargar el COCO entero
    solo para traducir `image_id` a ruta."""
    from dataset_quality.analyzers import exploration

    images_dir = photos(uno=1, dos=2, tres=3)
    dataset = coco(
        images=[(1, "uno.jpg", 256, 192), (2, "dos.jpg", 256, 192), (3, "tres.jpg", 256, 192)],
        boxes=[(1, 1, 1, 0, 0, 60, 60)],
        categories=[(1, "car")],
    )

    manifiesto = exploration.build(dataset, images_dir)
    por_id = {punto.image_id: punto.file_name for punto in manifiesto.points}

    assert por_id == {1: "uno.jpg", 2: "dos.jpg", 3: "tres.jpg"}


def test_una_imagen_que_no_esta_en_disco_no_produce_punto(photos) -> None:
    """El `file_name` de cada punto corresponde a un archivo que existe.

    Si la lista de nombres y la de ids se desalinearan, un punto acabaria
    apuntando a la foto de otro.
    """
    from dataset_quality.analyzers import exploration

    images_dir = photos(existe=1, tambien=2)
    dataset = coco(
        images=[
            (1, "existe.jpg", 256, 192),
            (2, "fantasma.jpg", 256, 192),
            (3, "tambien.jpg", 256, 192),
        ],
        boxes=[(1, 1, 1, 0, 0, 60, 60)],
        categories=[(1, "car")],
    )

    manifiesto = exploration.build(dataset, images_dir)

    assert [(p.image_id, p.file_name) for p in manifiesto.points] == [
        (1, "existe.jpg"),
        (3, "tambien.jpg"),
    ]
