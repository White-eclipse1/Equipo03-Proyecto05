"""Runner de los casos de politica C1-C7 con detecciones sinteticas (B1-03; E5, 2.2, 5.2).

Separa entrada de expectativa: la politica solo recibe los cuadros construidos de
`escenas`; `esperado` se usa DESPUES para comparar la decision observada. Sale con
codigo 1 si una sola expectativa falla.

    python -m p3.policy.casos --casos casos/politica_c1_c7.yaml \
        --config config/politica.yaml --salida <carpeta-nueva>
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from p3.policy.config import ConfigPolitica, cargar_config
from p3.policy.contrato import Cuadro
from p3.policy.politica import Decision, PoliticaDecision


def _fusionar(base: dict[str, Any], cambios: dict[str, Any]) -> dict[str, Any]:
    resultado = copy.deepcopy(base)
    for clave, valor in cambios.items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = _fusionar(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado


def construir_cuadros(caso: dict[str, Any], datos: dict[str, Any]) -> list[Cuadro]:
    """Expande `escenas` a cuadros del contrato A -> B. No toca `esperado`."""
    ancho, alto = datos["imagen"]["ancho"], datos["imagen"]["alto"]
    cajas, periodo = datos["cajas"], datos["periodo_ms"]
    cuadros: list[Cuadro] = []
    for escena in caso["escenas"]:
        detecciones = [
            {
                "class_name": obj.get("clase", "person"),
                "confidence": obj.get("conf", 0.9),
                "bbox_xyxy": cajas[obj["caja"]] if isinstance(obj["caja"], str) else obj["caja"],
            }
            for obj in escena["objetos"]
        ]
        for _ in range(escena.get("repetir", 1)):
            i = len(cuadros) + 1
            cuadros.append(
                Cuadro.model_validate(
                    {
                        "sequence_id": caso["id"],
                        "frame_id": f"{caso['id']}-{i:04d}",
                        "t_capture_ms": i * periodo,
                        "image_width": ancho,
                        "image_height": alto,
                        "status": "ok",
                        "detections": detecciones,
                    }
                )
            )
    return cuadros


def _comparar(decisiones: list[Decision], esperado: list[dict[str, Any]]) -> list[dict]:
    fallos = []
    for regla in esperado:
        ini, fin = regla["cuadros"]
        for n in range(ini, fin + 1):
            if n > len(decisiones):
                fallos.append({"cuadro": n, "motivo": "el caso no tiene ese cuadro"})
                continue
            d = decisiones[n - 1]
            if d.accion not in regla["permitidas"]:
                fallos.append(
                    {
                        "cuadro": n,
                        "observada": d.accion,
                        "permitidas": regla["permitidas"],
                        "reason_code": d.reason_code,
                    }
                )
            elif (
                not regla.get("direccion_min", -1.0)
                <= d.direccion
                <= regla.get("direccion_max", 1.0)
            ):
                fallos.append(
                    {
                        "cuadro": n,
                        "observada": d.accion,
                        "direccion": d.direccion,
                        "motivo": "direccion fuera del rango permitido",
                    }
                )
    return fallos


def ejecutar_casos(datos: dict[str, Any], config: ConfigPolitica, config_sha256: str) -> dict:
    base = config.model_dump(mode="json")
    casos = []
    for caso in datos["casos"]:
        config_caso = ConfigPolitica.model_validate(_fusionar(base, caso.get("config", {})))
        politica = PoliticaDecision(config_caso, config_sha256=config_sha256)
        decisiones = [politica.decidir(c) for c in construir_cuadros(caso, datos)]
        fallos = _comparar(decisiones, caso["esperado"])
        casos.append(
            {
                "id": caso["id"],
                "nombre": caso["nombre"],
                "justificacion": caso["justificacion"],
                "config_cambios": caso.get("config", {}),
                "plazo_cuadros": caso.get("plazo_cuadros"),
                "esperado": caso["esperado"],
                "resultado": "FALLA" if fallos else "PASA",
                "fallos": fallos,
                "decisiones": [d.model_dump(mode="json") for d in decisiones],
            }
        )
    return {
        "detecciones": "sinteticas",
        "config_sha256": config_sha256,
        "total": len(casos),
        "pasan": sum(c["resultado"] == "PASA" for c in casos),
        "casos": casos,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--casos", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--salida", type=Path, required=True, help="carpeta nueva")
    args = parser.parse_args(argv)
    if args.salida.exists():
        parser.error(f"--salida ya existe: {args.salida} (usa una carpeta nueva)")

    config, sha = cargar_config(args.config)
    datos = yaml.safe_load(args.casos.read_text(encoding="utf-8"))
    resultados = ejecutar_casos(datos, config, sha)
    resultados["casos_archivo"] = str(args.casos)
    resultados["config_archivo"] = str(args.config)

    args.salida.mkdir(parents=True)
    (args.salida / "resultados.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    with (args.salida / "decisiones.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for caso in resultados["casos"]:
            for d in caso["decisiones"]:
                f.write(json.dumps({"caso": caso["id"], **d}, ensure_ascii=False) + "\n")

    for caso in resultados["casos"]:
        print(f"{caso['id']:<16} {caso['resultado']}  {caso['nombre']}")
        for fallo in caso["fallos"]:
            print(f"    cuadro {fallo['cuadro']}: {fallo}")
    print(f"{resultados['pasan']}/{resultados['total']} casos pasan -> {args.salida}")
    return 0 if resultados["pasan"] == resultados["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
