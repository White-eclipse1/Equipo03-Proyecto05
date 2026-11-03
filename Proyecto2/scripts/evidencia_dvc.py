#!/usr/bin/env python3
"""Comprueba que el pipeline es reproducible, y deja la prueba por escrito.

`dvc.lock` puede estar versionado y ser mentira: basta con que alguien
regenere un reporte a mano despues de la ultima corrida para que el archivo
describa un estado que ya no existe. La unica forma de saberlo es correr el
pipeline dos veces seguidas y exigir que la SEGUNDA no ejecute ni una etapa.

Eso hace este script:

1. `dvc repro` — primera corrida; puede rehacer etapas si algo cambio.
2. `dvc repro` — segunda; aqui no se permite ni un "Running stage".
3. `dvc status` — el grafo coincide con el disco.
4. `dvc status -r dev` y `-r prod` — el cache local coincide con cada remote.

Ademas compara los hashes de `dvc.lock` antes y despues de la segunda corrida:
si un `dvc repro` a vacio los moviera, el pipeline no seria determinista aunque
DVC dijera que no reejecuto nada.

    python scripts/evidencia_dvc.py
    python scripts/evidencia_dvc.py --sin-remotes   # salta dev/prod

Sale con codigo != 0 si la reproducibilidad no se sostiene, para que pueda ser
un paso de CI y no un comando que alguien corre y mira por encima.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

PROYECTO2_DIR = Path(__file__).resolve().parent.parent
LOCKFILE = PROYECTO2_DIR / "dvc.lock"
DESTINO = PROYECTO2_DIR / "reports" / "evaluation"


def entorno() -> dict[str, str]:
    """PATH con los ejecutables del venv delante.

    No es un detalle: las etapas de `dvc.yaml` invocan `dq`, y si el directorio
    de scripts del interprete no esta en PATH, `dvc repro` falla con
    "'dq' is not recognized" — un error que parece del pipeline y es del
    entorno. Derivarlo de `sys.executable` hace que funcione igual en el venv
    de Windows del autor, en el contenedor y en el runner de CI.
    """
    entorno = dict(os.environ)
    scripts = Path(sys.executable).parent
    entorno["PATH"] = f"{scripts}{os.pathsep}{entorno.get('PATH', '')}"
    return entorno


def correr(titulo: str, comando: list[str]) -> dict[str, Any]:
    print(f"==> {titulo}: {' '.join(comando)}", flush=True)
    resultado = subprocess.run(
        comando,
        cwd=PROYECTO2_DIR,
        capture_output=True,
        text=True,
        env=entorno(),
    )
    salida = (resultado.stdout + resultado.stderr).strip()
    print(salida or "(sin salida)", flush=True)
    return {
        "titulo": titulo,
        "comando": " ".join(comando),
        "exit_code": resultado.returncode,
        "salida": salida,
    }


def etapas_ejecutadas(salida: str) -> list[str]:
    """Nombres de las etapas que DVC dice haber ejecutado en esa corrida."""
    return [
        linea.split("'")[1] for linea in salida.splitlines() if linea.startswith("Running stage '")
    ]


def hashes_del_lock() -> dict[str, dict[str, str]]:
    """`{etapa: {ruta_de_salida: md5}}` tal como esta hoy en `dvc.lock`."""
    if not LOCKFILE.is_file():
        return {}
    lock = yaml.safe_load(LOCKFILE.read_text(encoding="utf-8")) or {}
    return {
        etapa: {
            str(salida["path"]): str(salida.get("md5", ""))
            for salida in (detalle.get("outs") or [])
        }
        for etapa, detalle in (lock.get("stages") or {}).items()
    }


def markdown(informe: dict[str, Any]) -> str:
    lineas = [
        "# Reproducibilidad del pipeline DVC",
        "",
        f"Generado por `python scripts/evidencia_dvc.py` el {informe['generado_en']}.",
        "",
        f"Alcance: **{informe['alcance']}**.",
        "",
        "## Veredicto",
        "",
    ]

    if informe["reproducible"]:
        lineas += [
            "**El pipeline es reproducible.** La segunda corrida de `dvc repro` no",
            "ejecuto ninguna etapa y los hashes de `dvc.lock` no se movieron.",
        ]
    else:
        lineas += ["**El pipeline NO es reproducible.** Detalle abajo."]

    primera = ", ".join(informe["etapas_primera"]) or "ninguna"
    segunda = ", ".join(informe["etapas_segunda"]) or "ninguna"
    estables = "si" if informe["hashes_estables"] else "NO"

    lineas += [
        "",
        "| Comprobacion | Resultado |",
        "| --- | --- |",
        f"| Etapas ejecutadas en la 1a corrida | {primera} |",
        f"| Etapas ejecutadas en la 2a corrida | {segunda} |",
        f"| Hashes de `dvc.lock` estables | {estables} |",
    ]
    for remote, estado in informe["remotes"].items():
        lineas.append(f"| Cache local contra remote `{remote}` | {estado} |")

    lineas += [
        "",
        "## Hashes de salida registrados en `dvc.lock`",
        "",
        "Son los mismos en DEV y en PROD porque el hash lo determina el CONTENIDO,",
        "no el destino: `dvc status -r dev` y `-r prod` contrastan este mismo cache",
        "local contra cada remote.",
        "",
        "| Etapa | Salida | md5 |",
        "| --- | --- | --- |",
    ]
    for etapa, salidas in informe["hashes"].items():
        for ruta, md5 in salidas.items():
            lineas.append(f"| {etapa} | `{ruta}` | `{md5}` |")

    lineas += ["", "## Salida cruda de cada comando", ""]
    for paso in informe["pasos"]:
        lineas += [
            f"### {paso['titulo']}",
            "",
            f"`$ {paso['comando']}` (exit {paso['exit_code']})",
            "",
            "```",
            paso["salida"] or "(sin salida)",
            "```",
            "",
        ]

    return "\n".join(lineas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sin-remotes",
        action="store_true",
        help="Salta `dvc status -r dev/prod` (necesitan MinIO levantado y perfil AWS).",
    )
    parser.add_argument(
        "--etapas",
        nargs="+",
        metavar="ETAPA",
        default=None,
        help=(
            "Limita `dvc repro` a estas etapas. Sin esto se reproduce el grafo entero, "
            "que solo es posible donde haya credenciales (ver la nota de `release`)."
        ),
    )
    args = parser.parse_args()

    dvc = [sys.executable, "-m", "dvc"]
    # `release` no es reproducible en cualquier entorno, y no por un defecto:
    # `dq release` empaqueta y SUBE el artefacto, asi que necesita `.env` con
    # las credenciales de MinIO/S3 y los buckets creados. En un job de
    # validacion que solo hace `dvc pull` no hay nada de eso, y la etapa muere
    # al construir `Settings()`. Es la misma razon por la que `dq ingest` nunca
    # fue una etapa del grafo: escribe en servicios externos, no es una funcion
    # pura de archivos a archivos.
    #
    # Por eso CI pasa `--etapas analyze gate split`: las tres deterministas. La
    # reproducibilidad que se puede afirmar en un runner sin llaves es la de
    # esas tres, y afirmar mas seria afirmar algo que no se comprobo.
    objetivo = list(args.etapas) if args.etapas else []
    alcance = f" ({', '.join(objetivo)})" if objetivo else " (grafo completo)"
    pasos: list[dict[str, Any]] = []

    primera = correr(f"Primera corrida{alcance}", [*dvc, "repro", *objetivo])
    pasos.append(primera)

    hashes_antes = hashes_del_lock()

    segunda = correr(f"Segunda corrida{alcance}", [*dvc, "repro", *objetivo])
    pasos.append(segunda)

    hashes_despues = hashes_del_lock()

    # El estado se consulta con el mismo alcance: preguntar por el grafo entero
    # cuando solo se reprodujo una parte reportaria como "cambiada" una etapa
    # que a proposito no se ejecuto, y el informe diria que algo va mal cuando
    # lo que pasa es que no se miro.
    estado = correr(f"Estado del grafo{alcance}", [*dvc, "status", *objetivo])
    pasos.append(estado)

    remotes: dict[str, str] = {}
    if not args.sin_remotes:
        for remote in ("dev", "prod"):
            paso = correr(f"Estado contra el remote {remote}", [*dvc, "status", "-r", remote])
            pasos.append(paso)
            remotes[remote] = (
                "en sincronia"
                if paso["exit_code"] == 0 and "in sync" in paso["salida"]
                else f"NO (exit {paso['exit_code']})"
            )

    etapas_segunda = etapas_ejecutadas(segunda["salida"])
    hashes_estables = hashes_antes == hashes_despues

    reproducible = (
        primera["exit_code"] == 0
        and segunda["exit_code"] == 0
        and estado["exit_code"] == 0
        and not etapas_segunda
        and hashes_estables
        and all(valor == "en sincronia" for valor in remotes.values())
    )

    informe = {
        "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "alcance": objetivo or "grafo completo",
        "reproducible": reproducible,
        "etapas_primera": etapas_ejecutadas(primera["salida"]),
        "etapas_segunda": etapas_segunda,
        "hashes_estables": hashes_estables,
        "hashes": hashes_despues,
        "remotes": remotes,
        "pasos": pasos,
    }

    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "dvc-reproducibilidad.md").write_text(
        markdown(informe), encoding="utf-8", newline="\n"
    )
    (DESTINO / "dvc-reproducibilidad.json").write_text(
        json.dumps(informe, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"\nEvidencia escrita en {DESTINO}")

    if not reproducible:
        print("\nLa reproducibilidad NO se sostiene:", file=sys.stderr)
        if etapas_segunda:
            print(
                f"  - la segunda corrida rehizo: {', '.join(etapas_segunda)}",
                file=sys.stderr,
            )
        if not hashes_estables:
            print("  - los hashes de dvc.lock cambiaron entre corridas", file=sys.stderr)
        for remote, valor in remotes.items():
            if valor != "en sincronia":
                print(f"  - el remote {remote} no esta en sincronia: {valor}", file=sys.stderr)
        return 1

    print("El pipeline es reproducible: la segunda corrida no rehizo ninguna etapa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
