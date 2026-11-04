import argparse
import json
import logging
from pathlib import Path

import yaml
from p3.policy.config import cargar_config

from p5.policy.replay import run_cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay determinista de politica C1-C7 (sin pesos)."
    )
    parser.add_argument("--cases", type=Path, default=Path("casos/politica_c1_c7.yaml"))
    parser.add_argument("--config", type=Path, default=Path("config/politica.yaml"))
    parser.add_argument("--output", type=Path, required=True, help="Carpeta nueva de evidencia.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        if args.output.exists():
            raise ValueError(f"la salida ya existe: {args.output}")
        config, sha256 = cargar_config(args.config)
        data = yaml.safe_load(args.cases.read_text(encoding="utf-8"))
        report = run_cases(data, config, sha256)
        # mkdir sin exist_ok: una segunda ejecucion nunca reemplaza evidencia.
        args.output.mkdir(parents=True)
        (args.output / "resultados.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        for name in ("decisiones", "transiciones"):
            with (args.output / f"{name}.jsonl").open(
                "x", encoding="utf-8", newline="\n"
            ) as output:
                for case in report["casos"]:
                    for record in case[name]:
                        output.write(
                            json.dumps(
                                {"caso": case["id"], **record},
                                ensure_ascii=False,
                                allow_nan=False,
                            )
                            + "\n"
                        )
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as failure:
        logging.error("policy_replay_error: %s", failure)
        return 1
    print(f"{report['pasan']}/{report['total']} casos pasan -> {args.output}")
    return 0 if report["pasan"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
