"""Analizadores que solo necesitan el COCO, sin abrir una sola imagen.

Cuatro de los cinco: objetos pequenos, desbalance de clases, cajas degeneradas
y sesgo espacial. Son funciones puras sobre un `CocoDataset`, asi que se prueban
sin base de datos, sin disco y sin Docker.

Cada uno devuelve un `CheckResult` — el contrato congelado que consumen la
compuerta (Frente 4), la app web (7) y el Copilot (8).
"""

from __future__ import annotations

from collections import defaultdict

from dataset_quality.models.coco import CocoDataset
from dataset_quality.models.quality import CheckResult as Result
from dataset_quality.models.quality import (
    ClassImbalanceCheck,
    DegenerateBoxesCheck,
    MinImagesPerClassCheck,
    SmallObjectsCheck,
    SmallObjectsDetail,
    SpatialBiasCheck,
)


def _skipped(name: str, severity: str, threshold: float) -> Result:
    return Result(
        name=name,
        status="skipped",
        severity=severity,  # type: ignore[arg-type]
        observed=0.0,
        threshold=threshold,
        message="desactivado en quality.yaml",
    )


def _verdict(observed: float, max_allowed: float) -> str:
    """La regla se cumple mientras lo observado no supere el maximo."""
    return "fail" if observed > max_allowed else "pass"


def por_impacto(conteos: dict[str, int]) -> dict[str, int]:
    """De mayor a menor. La primera clave es la clase mas afectada, que es lo
    primero que se pregunta; los empates se desempatan por nombre para que el
    reporte sea reproducible."""
    return dict(sorted(conteos.items(), key=lambda item: (-item[1], item[0])))


def images_per_class(dataset: CocoDataset) -> dict[str, int]:
    """Imagenes DISTINTAS que contienen al menos una caja de cada clase.

    Se cuentan imagenes y no cajas porque es la metrica que exige el curso y la
    que refleja cuanta variedad ve el modelo: una foto con siete coches aporta
    UNA imagen a `car`, no siete. Incluye las clases declaradas y nunca usadas,
    con cero.
    """
    names = {category.id: category.name for category in dataset.categories}
    buckets: dict[int, set[int]] = {category.id: set() for category in dataset.categories}
    for annotation in dataset.annotations:
        buckets[annotation.category_id].add(annotation.image_id)
    return {names[category_id]: len(ids) for category_id, ids in buckets.items()}


def analyze_small_objects(dataset: CocoDataset, config: SmallObjectsCheck) -> Result:
    """Proporcion de cajas demasiado pequenas, por area relativa o absoluta.

    El criterio principal es relativo: una caja de 20x20 es diminuta en una
    foto de 4000 px y normal en una de 200, y lo que decide si el objeto
    sobrevive es cuantos pixeles le quedan despues de que el detector reescale
    la imagen. Pero el relativo solo tiene un punto ciego — en imagenes ya
    pequenas, un objeto absolutamente minusculo pasa como una fraccion
    razonable — y ahi entra `min_area_px`, los 32x32 de COCO. Una caja
    infractora incumple cualquiera de los dos.

    El desglose por clase viaja en el resultado: saber que las cajas diminutas
    se concentran en una clase es lo que distingue "asi se anoto esa clase" de
    "asi es la resolucion del dataset".
    """
    if not config.enabled:
        return _skipped("small_objects", config.severity, config.max_ratio)

    sizes = {image.id: image.width * image.height for image in dataset.images}
    names = {category.id: category.name for category in dataset.categories}

    offenders: list[int] = []
    below_ratio = below_min_area = 0
    cajas_por_clase: dict[str, int] = defaultdict(int)
    imagenes_por_clase: dict[str, set[int]] = defaultdict(set)

    for annotation in dataset.annotations:
        # Ambos umbrales son inclusivos: exactamente en el limite esta permitido.
        chica_relativa = annotation.area / sizes[annotation.image_id] < config.area_ratio_threshold
        chica_absoluta = annotation.area < config.min_area_px
        if not (chica_relativa or chica_absoluta):
            continue

        offenders.append(annotation.id)
        below_ratio += chica_relativa
        below_min_area += chica_absoluta

        clase = names[annotation.category_id]
        cajas_por_clase[clase] += 1
        imagenes_por_clase[clase].add(annotation.image_id)

    total = len(dataset.annotations)
    observed = len(offenders) / total if total else 0.0
    por_clase = por_impacto(dict(cajas_por_clase))

    return Result(
        name="small_objects",
        status=_verdict(observed, config.max_ratio),
        severity=config.severity,
        observed=observed,
        threshold=config.max_ratio,
        message=(
            f"{len(offenders)} de {total} cajas son diminutas "
            f"(menos del {config.area_ratio_threshold:.2%} de su imagen "
            f"o menos de {config.min_area_px} px de area) "
            f"({observed:.1%}; maximo permitido {config.max_ratio:.1%})"
            + (f"; la clase mas afectada es {next(iter(por_clase))}" if por_clase else "")
        ),
        offenders=sorted(offenders),
        small_objects=SmallObjectsDetail(
            area_ratio_threshold=config.area_ratio_threshold,
            min_area_px=config.min_area_px,
            boxes_by_class=por_clase,
            images_by_class=por_impacto(
                {clase: len(ids) for clase, ids in imagenes_por_clase.items()}
            ),
            below_ratio=below_ratio,
            below_min_area=below_min_area,
        ),
    )


def analyze_class_imbalance(dataset: CocoDataset, config: ClassImbalanceCheck) -> Result:
    """Razon entre la clase mas y la menos representada, contando imagenes.

    Con un desbalance grande al modelo le sale mas rentable ignorar la clase
    rara y aun asi acertar casi siempre: aprende a no detectarla nunca.
    """
    if not config.enabled:
        return _skipped("class_imbalance", config.severity, config.max_ratio_max_min)

    per_class = images_per_class(dataset)
    ids = {category.name: category.id for category in dataset.categories}

    usadas = {name: count for name, count in per_class.items() if count > 0}
    # Una clase declarada y nunca usada haria el ratio infinito; se trata como
    # un caso aparte, se reporta como infractora y se excluye de la division.
    sin_usar = sorted(ids[name] for name, count in per_class.items() if count == 0)

    if not usadas:
        return Result(
            name="class_imbalance",
            status="fail" if sin_usar else "pass",
            severity=config.severity,
            observed=0.0,
            threshold=config.max_ratio_max_min,
            message="ninguna clase tiene imagenes anotadas",
            offenders=sin_usar,
        )

    mayor = max(usadas.values())
    menor = min(usadas.values())
    observed = mayor / menor

    # Infractoras: las que quedan por debajo de lo que el ratio maximo permite.
    escasas = sorted(
        ids[name] for name, count in usadas.items() if count * config.max_ratio_max_min < mayor
    )

    return Result(
        name="class_imbalance",
        status=_verdict(observed, config.max_ratio_max_min),
        severity=config.severity,
        observed=observed,
        threshold=config.max_ratio_max_min,
        message=(
            f"la clase mas representada tiene {mayor} imagenes y la menos "
            f"{menor} ({observed:.1f}x; maximo permitido {config.max_ratio_max_min:.1f}x)"
            + (f"; {len(sin_usar)} clase(s) sin ninguna imagen" if sin_usar else "")
        ),
        offenders=sorted(set(escasas) | set(sin_usar)),
    )


def analyze_degenerate_boxes(dataset: CocoDataset, config: DegenerateBoxesCheck) -> Result:
    """Cajas que se salen del borde de su imagen.

    Las cajas con ancho o alto <= 0, origen negativo o area incoherente ya no
    llegan hasta aqui: los modelos Pydantic las rechazan en la ingesta. Lo que
    si puede atravesar la validacion — porque no se puede saber mirando la
    anotacion sola — es una caja cuyas coordenadas exceden el tamano de la
    imagen a la que pertenece. Eso es lo que este analizador encuentra.
    """
    if not config.enabled:
        return _skipped("degenerate_boxes", config.severity, config.max_ratio)

    offenders = dataset.bbox_out_of_bounds()
    total = len(dataset.annotations)
    observed = len(offenders) / total if total else 0.0

    return Result(
        name="degenerate_boxes",
        status=_verdict(observed, config.max_ratio),
        severity=config.severity,
        observed=observed,
        threshold=config.max_ratio,
        message=(
            f"{len(offenders)} de {total} cajas se salen del borde de su imagen "
            f"({observed:.1%}; maximo permitido {config.max_ratio:.1%})"
        ),
        offenders=sorted(offenders),
    )


def analyze_spatial_bias(dataset: CocoDataset, config: SpatialBiasCheck) -> Result:
    """Concentracion de los objetos en una zona de la imagen.

    Si todos los coches aparecen siempre en el centro, el modelo aprende
    "coche = centro" y falla cuando uno entra por la orilla. Se mide con una
    rejilla sobre el centro de cada caja: en un dataset sano ninguna celda
    deberia acaparar mucho mas que su parte proporcional.
    """
    if not config.enabled:
        return _skipped("spatial_bias", config.severity, config.max_cell_share)

    grid = config.grid_size
    sizes = {image.id: (image.width, image.height) for image in dataset.images}
    cells: dict[tuple[int, int], int] = defaultdict(int)

    for annotation in dataset.annotations:
        width, height = sizes[annotation.image_id]
        x, y, box_w, box_h = annotation.bbox
        # La caja pertenece a la celda donde cae su CENTRO, no su esquina.
        column = min(grid - 1, int((x + box_w / 2) / width * grid))
        row = min(grid - 1, int((y + box_h / 2) / height * grid))
        cells[(row, column)] += 1

    total = len(dataset.annotations)
    observed = max(cells.values()) / total if total else 0.0
    uniforme = 1 / (grid * grid)

    return Result(
        name="spatial_bias",
        status=_verdict(observed, config.max_cell_share),
        severity=config.severity,
        observed=observed,
        threshold=config.max_cell_share,
        message=(
            f"la celda mas poblada de la rejilla {grid}x{grid} concentra el "
            f"{observed:.1%} de los objetos (reparto uniforme: {uniforme:.1%}; "
            f"maximo permitido {config.max_cell_share:.1%})"
        ),
    )


def analyze_min_images_per_class(dataset: CocoDataset, config: MinImagesPerClassCheck) -> Result:
    """Exige `min_images` imagenes distintas en al menos `min_classes` clases.

    El valor observado es el conteo de la clase que ocupa la posicion
    `min_classes` al ordenar de mayor a menor. Con min_classes=2 eso es la
    SEGUNDA clase mas poblada: si esa llega al minimo, por definicion la
    primera tambien, y el requisito se cumple. Si hay menos clases con
    imagenes que las exigidas, el observado es 0.
    """
    if not config.enabled:
        return _skipped("min_images_per_class", config.severity, float(config.min_images))

    per_class = images_per_class(dataset)
    ids = {category.name: category.id for category in dataset.categories}
    ranked = sorted(per_class.values(), reverse=True)

    observed = float(ranked[config.min_classes - 1]) if len(ranked) >= config.min_classes else 0.0
    cumplen = [name for name, count in per_class.items() if count >= config.min_images]
    faltan = sorted(ids[name] for name, count in per_class.items() if count < config.min_images)

    ok = len(cumplen) >= config.min_classes
    detalle = (
        f"{len(cumplen)} clase(s) llegan a {config.min_images} imagenes "
        f"(se exigen {config.min_classes})"
    )
    if not ok and ranked:
        mejores = sorted(per_class.items(), key=lambda item: -item[1])[: config.min_classes]
        cerca = ", ".join(
            f"{name} {count} (+{config.min_images - count})" for name, count in mejores
        )
        detalle += f"; las mas cercanas: {cerca}"

    return Result(
        name="min_images_per_class",
        status="pass" if ok else "fail",
        severity=config.severity,
        observed=observed,
        threshold=float(config.min_images),
        message=detalle,
        offenders=faltan,
    )
