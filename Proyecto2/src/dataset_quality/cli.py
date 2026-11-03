"""Interfaz de linea de comandos del pipeline.

Cada tier es un subcomando. Se usa `argparse` de la libreria estandar en vez de
una libreria de CLI para no anadir una dependencia por un punado de comandos;
si el arbol crece, cambiar a Typer es mecanico.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from dataset_quality import __version__
from dataset_quality.models.errors import DatasetValidationError

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[0m"
MAGENTA = "\033[35m"

STATUS_COLOR = {"pass": GREEN, "fail": RED, "skipped": DIM}


def heading(text: str) -> None:
    print(f"\n{MAGENTA}==>{RESET} {text}")


def _progress(done: int, total: int) -> None:
    """Avance de la subida, en la misma linea."""
    if done % 25 and done != total:
        return
    width = 28
    filled = int(width * done / total)
    bar = "#" * filled + "." * (width - filled)
    end = "\n" if done == total else ""
    print(f"\r  [{bar}] {done}/{total}", end=end, flush=True)


def cmd_ingest(args: argparse.Namespace) -> int:
    """Tier 1 — valida el COCO, sube las imagenes a MinIO y puebla MariaDB."""
    from dataset_quality.tiers import ingest

    heading("Tier 1 — ingesta")
    try:
        summary = ingest.run(on_progress=None if args.quiet else _progress)
    except DatasetValidationError as error:
        print(f"\n{RED}El dataset no paso la validacion:{RESET}\n{error}", file=sys.stderr)
        return 1

    print(f"\n{GREEN}Ingesta completa.{RESET}")
    print(
        f"  MariaDB   {summary.images} imagenes, {summary.annotations} cajas, "
        f"{summary.categories} clases"
    )
    print(
        f"  MinIO     bucket `{summary.bucket}` — {summary.uploaded} subidas, "
        f"{summary.already_stored} ya estaban"
    )
    print(
        f"\n{DIM}Los binarios viven en MinIO; en MariaDB queda su llave "
        f"(`images.storage_key`).{RESET}"
    )
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Tier 2 — corre los cinco analizadores y la descriptiva.

    Solo MIDE: aunque un check salga en `fail`, este comando termina en 0. La
    decision de bloquear un release es del Frente 4.
    """
    from dataset_quality.analyzers import describe, run_all
    from dataset_quality.models.coco import load_coco
    from dataset_quality.models.quality import QualityConfig
    from dataset_quality.tiers.ingest import RAW_ANNOTATIONS, RAW_IMAGES

    try:
        dataset = load_coco(RAW_ANNOTATIONS)
        config = QualityConfig.from_yaml(Path(args.config))
    except DatasetValidationError as error:
        print(f"\n{RED}{error}{RESET}", file=sys.stderr)
        return 1

    stats = describe(dataset)
    heading("Descriptiva")
    print(
        f"  {stats.totals.images} imagenes, {stats.totals.annotations} cajas, "
        f"{stats.totals.categories} clases"
    )
    print(
        f"  {stats.annotations_per_image:.2f} cajas por imagen, "
        f"{stats.images_without_annotations} imagenes sin anotar"
    )
    # Las tres juntas: la distribucion esta sesgada y una sola cifra enganaria.
    print(
        f"  area de caja sobre su imagen: media {stats.mean_box_area_ratio:.1%}, "
        f"mediana {stats.median_box_area_ratio:.1%}, p90 {stats.p90_box_area_ratio:.1%}"
    )
    for name, count in sorted(stats.images_per_class.items(), key=lambda item: -item[1]):
        print(f"    {name:<14}{count:>6} imagenes  ({stats.boxes_per_class[name]} cajas)")

    heading("Analizadores")
    results = run_all(dataset, config, RAW_IMAGES)
    for result in results:
        color = STATUS_COLOR[result.status]
        print(
            f"\n  {color}{result.status.upper():<7}{RESET} {result.name}  "
            f"{DIM}[{result.severity}]{RESET}"
        )
        print(f"          {result.message}")
        if result.offenders:
            muestra = ", ".join(str(item) for item in result.offenders[:5])
            print(f"          {DIM}infractores: {len(result.offenders)} (ej. {muestra}){RESET}")

    fallos = [result for result in results if result.status == "fail"]
    print(f"\n{len(fallos)} check(s) en fail. {DIM}El Tier 2 mide; bloquear es del Tier 3.{RESET}")

    if args.json:
        import json

        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(
                {
                    "stats": stats.model_dump(),
                    "checks": [result.model_dump() for result in results],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
            newline="\n",
        )
        print(f"Escrito {destino}")

    if not args.sin_exploracion:
        from dataset_quality.analyzers import exploration as exploration_module

        heading("Exploracion 2D")
        manifiesto = exploration_module.build(dataset, RAW_IMAGES)
        destino = Path(args.exploration)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(manifiesto.model_dump_json(indent=2), encoding="utf-8", newline="\n")
        print(
            f"  {len(manifiesto.points)} puntos por {manifiesto.method.upper()}, "
            f"{manifiesto.variance_explained:.1%} de varianza explicada"
        )
        print(f"Escrito {destino}")

    return 0


def _run_gate(args: argparse.Namespace):
    """Carga, analiza y evalua. Aislado para poder probar el CLI sin datos."""
    from dataset_quality.models.coco import load_coco
    from dataset_quality.models.quality import QualityConfig
    from dataset_quality.tiers import gate
    from dataset_quality.tiers.ingest import RAW_ANNOTATIONS, RAW_IMAGES

    dataset = load_coco(RAW_ANNOTATIONS)
    config = QualityConfig.from_yaml(Path(args.config))
    return gate.run(dataset, config, RAW_IMAGES, out=Path(args.out))


def cmd_gate(args: argparse.Namespace) -> int:
    """Tier 3 — evalua la politica y DEVUELVE el codigo de salida.

    Este `return report.exit_code` es la linea que hace que la compuerta sirva:
    sin ella el reporte diria `fail`, el terminal lo pintaria en rojo, y la
    etapa siguiente del pipeline se ejecutaria igual.
    """
    try:
        report = _run_gate(args)
    except DatasetValidationError as error:
        print(f"\n{RED}{error}{RESET}", file=sys.stderr)
        return 1

    heading("Compuerta de calidad")
    for check in report.checks:
        color = STATUS_COLOR[check.status]
        print(
            f"  {color}{check.status.upper():<7}{RESET} {check.name:<22} "
            f"{check.observed:>10.4g} contra {check.threshold:<10.4g} "
            f"{DIM}[{check.severity}]{RESET}"
        )
        print(f"          {DIM}{check.message}{RESET}")

    from dataset_quality.tiers import gate as gate_module

    bloquean = gate_module.blocking(report.checks)
    avisos = gate_module.warnings(report.checks)

    print(f"\nreporte: {args.out}")
    print(f"  huella:  {report.dataset_fingerprint[:16]}...")

    if report.exit_code == 0:
        print(f"\n{GREEN}La compuerta pasa.{RESET} {len(avisos)} aviso(s) que no bloquean.")
    else:
        nombres = ", ".join(check.name for check in bloquean)
        print(f"\n{RED}RELEASE BLOQUEADO{RESET} por {len(bloquean)} check(s): {nombres}")
        print(f"{DIM}La etapa siguiente del pipeline no se ejecuta.{RESET}")

    return report.exit_code


def _load_quality_report(path: Path) -> object | None:
    """Lee `quality.json` si existe; `None` si nunca se corrio la compuerta."""
    from dataset_quality.models.quality import QualityReport

    if not path.is_file():
        return None
    return QualityReport.model_validate_json(path.read_text(encoding="utf-8"))


class _CompuertaBloqueadaError(Exception):
    """La etapa debe abortar: `quality.json` falta o esta en `fail` sin --force."""


def _exigir_compuerta_en_pass(path: Path, *, force: bool, accion: str) -> object | None:
    """Bloquea una etapa si `quality.json` falta o esta en `fail`.

    Devuelve el reporte cargado (o `None` si nunca se corrio la compuerta y se
    sigue por `--force`) cuando la etapa puede continuar. Lanza
    `_CompuertaBloqueadaError` — ya con el mensaje impreso — cuando debe abortar.
    Compartida por `dq split` y `dq release`: las dos etapas posteriores a la
    compuerta necesitan la misma comprobacion, y duplicarla es como se termina
    teniendo dos politicas que divergen.
    """
    quality_report = _load_quality_report(path)

    if quality_report is None and not force:
        print(
            f"\n{RED}No existe {path}.{RESET} Corre `dq gate` antes de {accion}, o pasa --force.",
            file=sys.stderr,
        )
        raise _CompuertaBloqueadaError

    if quality_report is not None and quality_report.status == "fail" and not force:
        nombres = ", ".join(
            check.name
            for check in quality_report.checks
            if check.status == "fail" and check.severity == "error"
        )
        print(
            f"\n{RED}La compuerta de calidad esta en fail{RESET} "
            f"({nombres}). No se puede {accion} sobre un dataset bloqueado. "
            f"Usa --force para saltar esta comprobacion.",
            file=sys.stderr,
        )
        raise _CompuertaBloqueadaError

    if force and (quality_report is None or quality_report.status == "fail"):
        print(f"{YELLOW}--force: se ignora el estado de la compuerta de calidad.{RESET}")

    return quality_report


def cmd_split(args: argparse.Namespace) -> int:
    """Tier 4 — reparte train/val/test: estratificado, con semilla, sin fuga.

    Antes de repartir, exige que la compuerta de calidad (Tier 3) haya
    pasado: `reports/quality.json` debe existir y no estar en `fail`. Es lo
    que hace real la promesa de F4 de que "la etapa siguiente no se ejecuta"
    — sin este chequeo, F5 seria esa etapa que se ejecuta igual. `--force`
    lo salta a proposito, dejando constancia en la terminal.
    """
    from dataset_quality.models.coco import load_coco
    from dataset_quality.models.quality import QualityConfig
    from dataset_quality.tiers import splits as splits_module
    from dataset_quality.tiers.ingest import RAW_ANNOTATIONS, RAW_IMAGES

    try:
        _exigir_compuerta_en_pass(
            Path(args.quality_report), force=args.force, accion="repartir splits"
        )
    except _CompuertaBloqueadaError:
        return 1

    try:
        dataset = load_coco(RAW_ANNOTATIONS)
        config = QualityConfig.from_yaml(Path(args.config))
    except DatasetValidationError as error:
        print(f"\n{RED}{error}{RESET}", file=sys.stderr)
        return 1

    if args.seed is not None:
        splits_config = config.splits.model_copy(update={"seed": args.seed})
        config = config.model_copy(update={"splits": splits_config})

    heading("Splits estratificados")
    result = splits_module.run(dataset, config, RAW_IMAGES, out=Path(args.out))

    for split_name in ("train", "val", "test"):
        print(f"  {split_name:<6}{result.manifest.counts[split_name]:>6} imagenes")

    tolerancia = config.splits.tolerance
    print(f"\n  {DIM}desviacion maxima por clase (tolerancia {tolerancia:.1%}):{RESET}")
    peor = max(result.deviations.values(), default=0.0)
    for name, value in sorted(result.deviations.items(), key=lambda item: -item[1]):
        color = RED if value > config.splits.tolerance else GREEN
        print(f"    {color}{value:>6.1%}{RESET}  {name}")

    print(
        f"\n  {result.duplicate_group_count} grupo(s) de casi-duplicados "
        f"mantenidos juntos en un solo split."
    )
    print(f"\n  seed={config.splits.seed}")
    print(f"reporte: {args.out}")

    if peor > config.splits.tolerance:
        print(
            f"\n{YELLOW}Aviso:{RESET} la desviacion maxima ({peor:.1%}) supera la "
            f"tolerancia configurada ({config.splits.tolerance:.1%})."
        )
    else:
        print(f"\n{GREEN}Reparto dentro de tolerancia.{RESET}")

    return 0


def cmd_release(args: argparse.Namespace) -> int:
    """Tier 5 — empaqueta, sube y registra una version del dataset.

    Misma compuerta que `dq split`: sin `reports/quality.json` en `pass` no
    hay release, salvo `--force`. `--dry-run` arma la entrada completa
    (incluye armar el `.tar.zst` para calcular su huella) pero no sube nada
    ni toca `versions.json` — util para ver que version y que huellas saldrian
    antes de publicar de verdad.
    """
    from dataset_quality.models.coco import load_coco
    from dataset_quality.settings import get_settings
    from dataset_quality.tiers import release as release_module
    from dataset_quality.tiers.gate import dataset_fingerprint
    from dataset_quality.tiers.ingest import RAW_ANNOTATIONS

    try:
        _exigir_compuerta_en_pass(
            Path(args.quality_report), force=args.force, accion="publicar un release"
        )
    except _CompuertaBloqueadaError:
        return 1

    if not Path(args.splits).is_file():
        print(
            f"\n{RED}No existe {args.splits}.{RESET} Corre `dq split` antes de publicar.",
            file=sys.stderr,
        )
        return 1

    try:
        dataset = load_coco(RAW_ANNOTATIONS)
    except DatasetValidationError as error:
        print(f"\n{RED}{error}{RESET}", file=sys.stderr)
        return 1

    heading("Release")
    remote = args.remote or release_module.DEFAULT_REMOTE
    settings = get_settings()
    bucket = settings.prod_bucket_releases if remote == "prod" else settings.minio_bucket_releases
    try:
        result = release_module.run(
            coco_path=RAW_ANNOTATIONS,
            quality_report_path=Path(args.quality_report),
            splits_path=Path(args.splits),
            dataset_fingerprint=dataset_fingerprint(dataset),
            bucket=bucket,
            bump=args.bump,
            version=args.version,
            notes=args.notes,
            remote=remote,
            profile=args.profile,
            out=Path(args.out),
            upload=not args.dry_run,
        )
    except (ValueError, OSError, BotoCoreError, ClientError) as error:
        print(f"{RED}{error}{RESET}", file=sys.stderr)
        return 1

    entry = result.entry
    print(f"  version         {entry.version}")
    print(f"  storage_uri     {entry.storage_uri}")
    print(f"  quality_status  {entry.quality_status}")
    print(f"  dataset         {entry.dataset_fingerprint[:16]}...")
    print(f"  quality.json    {entry.quality_report_fingerprint[:16]}...")
    print(f"  splits.json     {entry.splits_fingerprint[:16]}...")
    print(f"  archivo         {result.archive_path}")
    publicado = ", ".join(p.remote for p in entry.published_in) or f"{DIM}ninguno{RESET}"
    print(f"  remotes         {publicado}")

    if args.dry_run:
        print(f"\n{YELLOW}--dry-run:{RESET} no se subio nada ni se escribio {args.out}.")
    else:
        print(f"\n{GREEN}Release publicado.{RESET} reporte: {args.out}")

    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Copia un release existente a PROD y registra el resultado verificado."""
    from dataset_quality.tiers import promote

    try:
        entry = promote.run(
            args.version,
            out=Path(args.out),
            profile=args.profile,
            archive_path=Path(args.archive) if args.archive else None,
            dry_run=args.dry_run,
        )
    except (ValueError, OSError, BotoCoreError, ClientError) as error:
        print(f"{RED}{error}{RESET}", file=sys.stderr)
        return 1
    heading("Promocion a PROD")
    print(f"  version {entry.version}")
    if args.dry_run:
        print("  Archivo validado; no se subio nada ni se modifico el registro.")
    else:
        print(next(p.storage_uri for p in entry.published_in if p.remote == "prod"))
    return 0


def cmd_dedupe(args: argparse.Namespace) -> int:
    """Mueve a cuarentena las copias que marco el analizador de duplicados.

    Es la unica operacion que modifica el dataset crudo, asi que por defecto
    solo ENSENA el plan: hace falta `--yes` para ejecutarlo.
    """
    from dataset_quality.models.coco import load_coco
    from dataset_quality.models.quality import QualityReport
    from dataset_quality.tiers import dedupe
    from dataset_quality.tiers.ingest import RAW_ANNOTATIONS, RAW_IMAGES

    reporte_path = Path("reports/quality.json")
    if not reporte_path.is_file():
        print(f"{RED}No hay `reports/quality.json`. Corre `dq gate` antes.{RESET}", file=sys.stderr)
        return 1

    try:
        dataset = load_coco(RAW_ANNOTATIONS)
        reporte = QualityReport.model_validate_json(reporte_path.read_text(encoding="utf-8"))
        plan = dedupe.build_plan(dataset, reporte)
    except DatasetValidationError as error:
        print(f"{RED}{error}{RESET}", file=sys.stderr)
        return 1
    except dedupe.DedupeError as error:
        print(f"{RED}{error}{RESET}", file=sys.stderr)
        return 1

    heading("Duplicados")
    if plan.is_empty:
        print(f"  {GREEN}No hay duplicados que eliminar.{RESET}")
        return 0

    print(f"  se eliminarian {plan.remove_ids.__len__()} imagenes de {plan.total_images}")
    print(f"  y {plan.annotations_removed} cajas asociadas")
    print(f"  quedarian {plan.kept}")
    print(f"\n{DIM}muestra:{RESET}")
    for nombre in plan.remove_files[:8]:
        print(f"    {DIM}{nombre[:72]}{RESET}")
    if len(plan.remove_files) > 8:
        print(f"    {DIM}... y {len(plan.remove_files) - 8} mas{RESET}")

    if not args.yes:
        print(f"\n{YELLOW}Esto es solo el plan.{RESET} Anade --yes para ejecutarlo.")
        return 0

    resultado = dedupe.apply(plan, dataset, RAW_ANNOTATIONS, RAW_IMAGES)
    print(f"\n{GREEN}Hecho.{RESET}")
    print(f"  {resultado.removed_images} imagenes movidas a {resultado.quarantine_dir}/")
    print(f"  {resultado.removed_annotations} cajas eliminadas del COCO")
    print(f"  quedan {resultado.remaining_images} imagenes")
    if resultado.missing_on_disk:
        print(f"  {YELLOW}{len(resultado.missing_on_disk)} no estaban en disco{RESET}")

    print(f"\n{DIM}El dataset cambio: los reportes anteriores ya no lo describen.{RESET}")
    print("  dq analyze --json reports/stats.json")
    print("  dq gate")
    print("  dvc add data/raw && dvc push")
    print(f"\n{DIM}Para revertir: mueve los archivos de vuelta a data/raw/images/.{RESET}")
    return 0


def cmd_init_db(args: argparse.Namespace) -> int:
    """Crea las tablas que falten. Idempotente."""
    del args
    from dataset_quality.db import create_schema

    create_schema()
    print("Esquema creado.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dq", description="Calidad y versionado de datasets COCO."
    )
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser(
        "ingest", help="Tier 1 — valida el COCO, sube imagenes a MinIO y puebla MariaDB."
    )
    ingest.add_argument("--quiet", action="store_true", help="Sin barra de progreso.")
    ingest.set_defaults(handler=cmd_ingest)

    analyze = subcommands.add_parser(
        "analyze", help="Tier 2 — corre los cinco analizadores y la descriptiva."
    )
    analyze.add_argument("--config", default="quality.yaml", help="Ruta de quality.yaml.")
    analyze.add_argument("--json", default=None, help="Escribe el resultado en este JSON.")
    analyze.add_argument(
        "--exploration",
        default="reports/exploration.json",
        help="Donde escribir la proyeccion 2D que consume la pantalla de exploracion.",
    )
    analyze.add_argument(
        "--sin-exploracion",
        action="store_true",
        help="Salta la proyeccion 2D, que vuelve a abrir todas las imagenes.",
    )
    analyze.set_defaults(handler=cmd_analyze)

    gate = subcommands.add_parser(
        "gate", help="Tier 3 — evalua la politica; sale con codigo != 0 si bloquea."
    )
    gate.add_argument("--config", default="quality.yaml", help="Ruta de quality.yaml.")
    gate.add_argument("--out", default="reports/quality.json", help="Donde escribir el reporte.")
    gate.set_defaults(handler=cmd_gate)

    split = subcommands.add_parser(
        "split",
        help="Tier 4 — reparte train/val/test estratificado, con semilla y sin fuga.",
    )
    split.add_argument("--config", default="quality.yaml", help="Ruta de quality.yaml.")
    split.add_argument("--out", default="reports/splits.json", help="Donde escribir el reparto.")
    split.add_argument(
        "--quality-report",
        default="reports/quality.json",
        help="Reporte de la compuerta (Tier 3) que debe estar en pass.",
    )
    split.add_argument(
        "--seed", type=int, default=None, help="Sobreescribe la semilla de quality.yaml."
    )
    split.add_argument(
        "--force",
        action="store_true",
        help="Reparte aunque la compuerta de calidad este en fail o no exista.",
    )
    split.set_defaults(handler=cmd_split)

    release = subcommands.add_parser(
        "release",
        help="Tier 5 — empaqueta, sube y registra una version publicada del dataset.",
    )
    release.add_argument(
        "--quality-report",
        default="reports/quality.json",
        help="Reporte de la compuerta (Tier 3) que debe estar en pass.",
    )
    release.add_argument(
        "--splits", default="reports/splits.json", help="Manifiesto de splits (Tier 4)."
    )
    release.add_argument("--out", default="reports/versions.json", help="Registro de versiones.")
    release.add_argument(
        "--version", default=None, help="Fuerza el semver en vez de auto-incrementar."
    )
    release.add_argument(
        "--bump",
        choices=("patch", "minor", "major"),
        default="patch",
        help="Que parte del semver subir si no se pasa --version (default: patch).",
    )
    release.add_argument("--notes", default=None, help="Nota libre para esta version.")
    release.add_argument(
        "--remote",
        choices=("dev", "prod"),
        default=None,
        help="Destino real de publicacion: MinIO dev o AWS prod (default: dev).",
    )
    release.add_argument("--profile", default=None, help="Perfil AWS para PROD; en CI se usa OIDC.")
    release.add_argument(
        "--dry-run",
        action="store_true",
        help="Arma la entrada y el archivo, pero no sube nada ni escribe versions.json.",
    )
    release.add_argument(
        "--force",
        action="store_true",
        help="Publica aunque la compuerta de calidad este en fail o no exista.",
    )
    release.set_defaults(handler=cmd_release)

    promote = subcommands.add_parser(
        "promote", help="Promueve una version existente de DEV a PROD."
    )
    promote.add_argument("version", help="Semver del release existente.")
    promote.add_argument("--remote", choices=("prod",), default="prod", help="Destino: AWS PROD.")
    promote.add_argument("--profile", default=None, help="Perfil AWS; omitir para OIDC en CI.")
    promote.add_argument("--out", default="reports/versions.json", help="Registro de versiones.")
    promote.add_argument(
        "--archive", default=None, help="Copia local del archivo publicado en DEV."
    )
    promote.add_argument(
        "--dry-run", action="store_true", help="Valida sin subir ni registrar PROD."
    )
    promote.set_defaults(handler=cmd_promote)

    dedupe = subcommands.add_parser(
        "dedupe", help="Mueve a cuarentena las copias que marco el analizador."
    )
    dedupe.add_argument(
        "--yes", action="store_true", help="Ejecuta; sin esto solo muestra el plan."
    )
    dedupe.set_defaults(handler=cmd_dedupe)

    init_db = subcommands.add_parser("init-db", help="Crea las tablas que falten.")
    init_db.set_defaults(handler=cmd_init_db)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


def run() -> None:
    """Punto de entrada declarado en `pyproject.toml`."""
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrumpido.")
        raise SystemExit(130) from None


if __name__ == "__main__":
    run()
