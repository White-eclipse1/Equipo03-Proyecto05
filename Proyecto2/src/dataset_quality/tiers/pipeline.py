"""Un recorrido completo del Tier 2 y el Tier 3 en una sola pasada.

`dq analyze` y `dq gate` seguidos recorren los analizadores DOS veces: el
primero para la descriptiva, el segundo para el veredicto. Sobre 838 imagenes
eso son trece segundos pagados dos veces, y algo peor — entre una pasada y la
otra alguien puede tocar el disco, y entonces `stats.json` describe un dataset
y `quality.json` otro.

Aqui los analizadores corren una vez y los dos artefactos salen de ese mismo
resultado. Por construccion no pueden discrepar.

Esto NO reemplaza al CLI: la terminal sigue siendo donde se corre el pipeline
en CI, y `dq gate` sigue siendo quien devuelve el codigo de salida que detiene
un build. Esto es lo que necesita la app web, que no tiene codigos de salida
sino pantallas.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from dataset_quality.analyzers import describe, run_all
from dataset_quality.models.quality import CheckResult, QualityConfig, QualityTotals
from dataset_quality.tiers import gate


@dataclass(frozen=True)
class RefreshResult:
    """El veredicto y lo suficiente para pintarlo sin releer los archivos."""

    status: str
    exit_code: int
    dataset_fingerprint: str
    totals: QualityTotals
    checks: list[CheckResult]
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    stats_path: str = ""
    quality_path: str = ""


def write_stats(dataset, checks: list[CheckResult], destino: Path) -> Path:
    """Escribe `stats.json` con el mismo formato que produce `dq analyze --json`.

    Vive aqui y no en el CLI para que los dos caminos no se separen: si el
    formato cambia, cambia en un solo sitio.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(
            {
                "stats": describe(dataset).model_dump(),
                "checks": [check.model_dump() for check in checks],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return destino


def refresh(
    *,
    coco_path: Path,
    images_dir: Path,
    config_path: Path,
    stats_out: Path,
    quality_out: Path,
) -> RefreshResult:
    """Recorre los analizadores una vez y reescribe los dos artefactos.

    Un veredicto negativo NO es una excepcion: se devuelve en `exit_code`. Que
    el dataset no pase es informacion, no un fallo de la operacion.
    """
    from dataset_quality.models.coco import load_coco

    inicio = time.monotonic()

    dataset = load_coco(coco_path)
    config = QualityConfig.from_yaml(config_path)

    # La unica pasada cara. Todo lo demas se deriva de `checks`.
    checks = run_all(dataset, config, images_dir)

    totals = QualityTotals(
        images=len(dataset.images),
        annotations=len(dataset.annotations),
        categories=len(dataset.categories),
    )
    fingerprint = gate.dataset_fingerprint(dataset)

    report = gate.evaluate(
        checks,
        fingerprint=fingerprint,
        config_version=config.version,
        totals=totals,
    )
    gate.write_report(report, quality_out)
    write_stats(dataset, checks, stats_out)

    return RefreshResult(
        status=report.status,
        exit_code=report.exit_code,
        dataset_fingerprint=fingerprint,
        totals=totals,
        checks=checks,
        blocking=[check.name for check in gate.blocking(checks)],
        warnings=[check.name for check in gate.warnings(checks)],
        duration_seconds=round(time.monotonic() - inicio, 2),
        stats_path=stats_out.as_posix(),
        quality_path=quality_out.as_posix(),
    )
