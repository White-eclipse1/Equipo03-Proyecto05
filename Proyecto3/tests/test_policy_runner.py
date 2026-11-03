"""Runner de casos C1-C7 y salida malformada del detector (B1-03; criterios 2.2, 3.2, 5.2)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import yaml

from p3.policy.casos import ejecutar_casos, main
from p3.policy.config import cargar_config
from p3.policy.politica import PoliticaDecision

RAIZ = Path(__file__).resolve().parents[1]
CASOS = RAIZ / "casos" / "politica_c1_c7.yaml"
CONFIG = RAIZ / "config" / "politica.yaml"


def test_los_casos_versionados_pasan_y_dejan_resultados(tmp_path: Path) -> None:
    salida = tmp_path / "corrida"
    codigo = main(["--casos", str(CASOS), "--config", str(CONFIG), "--salida", str(salida)])
    assert codigo == 0
    resultados = json.loads((salida / "resultados.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in resultados["casos"]]
    assert {"C1", "C2", "C3", "C4", "C5", "C6", "C7"} <= set(ids)
    assert all(c["resultado"] == "PASA" for c in resultados["casos"])
    assert resultados["config_sha256"] == cargar_config(CONFIG)[1]
    assert resultados["detecciones"] == "sinteticas"
    lineas = (salida / "decisiones.jsonl").read_text(encoding="utf-8").splitlines()
    primera = json.loads(lineas[0])
    assert {"caso", "frame_id", "accion", "velocidad", "direccion", "reason_code"} <= set(primera)


def test_una_expectativa_contradicha_hace_fallar_al_runner(tmp_path: Path) -> None:
    datos = yaml.safe_load(CASOS.read_text(encoding="utf-8"))
    c1 = next(c for c in datos["casos"] if c["id"] == "C1")
    c1["esperado"][1]["permitidas"] = ["STOP"]  # contradice el avance observado
    casos = tmp_path / "casos.yaml"
    casos.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")
    salida = tmp_path / "corrida"
    assert main(["--casos", str(casos), "--config", str(CONFIG), "--salida", str(salida)]) == 1
    resultados = json.loads((salida / "resultados.json").read_text(encoding="utf-8"))
    c1_res = next(c for c in resultados["casos"] if c["id"] == "C1")
    assert c1_res["resultado"] == "FALLA"
    assert c1_res["fallos"][0]["cuadro"] == 3
    assert c1_res["fallos"][0]["observada"] == "FORWARD"


def test_una_direccion_hacia_el_lado_ocupado_falla(tmp_path: Path) -> None:
    datos = yaml.safe_load(CASOS.read_text(encoding="utf-8"))
    c3 = next(c for c in datos["casos"] if c["id"] == "C3")
    c3["esperado"][0]["direccion_min"] = 0.1  # exige girar a la derecha: no lo hace
    resultados = ejecutar_casos(datos, *cargar_config(CONFIG))
    c3_res = next(c for c in resultados["casos"] if c["id"] == "C3")
    assert c3_res["resultado"] == "FALLA"


def test_la_salida_no_sobrescribe_una_carpeta_existente(tmp_path: Path) -> None:
    salida = tmp_path / "ya_existe"
    salida.mkdir()
    with pytest.raises(SystemExit):
        main(["--casos", str(CASOS), "--config", str(CONFIG), "--salida", str(salida)])


def test_cambiar_la_configuracion_cambia_el_resultado(tmp_path: Path) -> None:
    datos = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    datos["temporal"]["cuadros_para_liberar"] = 6  # C1 ya no avanza en el cuadro 3
    otra = tmp_path / "politica.yaml"
    otra.write_text(yaml.safe_dump(datos), encoding="utf-8")
    salida = tmp_path / "corrida"
    assert main(["--casos", str(CASOS), "--config", str(otra), "--salida", str(salida)]) == 1


# --- salida malformada del detector (apoyo a C9) -------------------------------------


def _valido(i: int) -> dict:
    return {
        "sequence_id": "s1",
        "frame_id": f"s1-{i:04d}",
        "t_capture_ms": i * 100,
        "image_width": 640,
        "image_height": 480,
        "status": "ok",
        "detections": [],
    }


@pytest.mark.parametrize(
    "malo",
    [
        {
            **_valido(4),
            "detections": [
                {"class_name": "person", "confidence": math.nan, "bbox_xyxy": [1, 2, 3, 4]}
            ],
        },
        {
            **_valido(4),
            "detections": [{"class_name": "person", "confidence": 0.9, "bbox_xyxy": [1, 2, 3]}],
        },
        {k: v for k, v in _valido(4).items() if k != "detections"},  # ok sin detections
        {**_valido(4), "detections": None},
        {"frame_id": "s1-0004"},
        "no es un cuadro",
    ],
)
def test_una_salida_malformada_es_un_fallo_y_no_una_via_libre(malo: object) -> None:
    config, sha = cargar_config(CONFIG)
    politica = PoliticaDecision(config, config_sha256=sha)
    for i in range(1, 4):
        assert politica.decidir_crudo(_valido(i)).accion in {"STOP", "FORWARD"}
    d = politica.decidir_crudo(malo)
    assert d.accion == "STOP"
    assert (d.velocidad, d.direccion) == (0, 0)
    assert d.estado == "FAULT"
    assert d.reason_code == "SALIDA_MALFORMADA"
    assert d.error
    # Despues del fallo la via hay que confirmarla de nuevo.
    siguientes = [politica.decidir_crudo(_valido(i)).accion for i in range(5, 8)]
    assert siguientes == ["STOP", "STOP", "FORWARD"]
