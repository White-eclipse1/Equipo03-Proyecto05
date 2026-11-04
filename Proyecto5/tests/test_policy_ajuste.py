"""B1-03: seleccion de umbrales y rachas solo con p5-ajuste-v1, nunca con evaluacion."""

import json
from pathlib import Path

import pytest
from p3.policy.config import cargar_config

from p5.policy.ajuste import (
    GRID,
    candidates,
    check_tuning_package,
    score,
    select,
    tune,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/politica.yaml"

# 400 x 296, como las secuencias capturadas. CENTRO cae en la zona central y en la banda.
CENTRO = [150.0, 20.0, 250.0, 150.0]


@pytest.fixture
def base():
    return cargar_config(CONFIG)[0]


def _row(sequence, number, road_state, allowed, objects=()):
    return {
        "sequence_id": sequence,
        "frame_id": f"{sequence}-{number:04d}",
        "t_capture_ms": 500 * (number - 1),
        "image_width": 400,
        "image_height": 296,
        "road_state": road_state,
        "allowed_actions": list(allowed),
        "annotations": [{"class_name": "person", "bbox_xyxy": box} for box in objects],
    }


def _frame(row, detections):
    return {
        "sequence_id": row["sequence_id"],
        "frame_id": row["frame_id"],
        "t_capture_ms": row["t_capture_ms"],
        "image_width": row["image_width"],
        "image_height": row["image_height"],
        "status": "ok",
        "detections": [
            {"class_name": "person", "confidence": confidence, "bbox_xyxy": box}
            for confidence, box in detections
        ],
        "error": None,
    }


MOVE = ("FORWARD", "SLOW", "STOP")
HALT = ("STOP", "SLOW", "EVADE_LEFT", "EVADE_RIGHT")


def _flicker_sequence():
    """Persona al centro desde el cuadro 5: dos cuadros firmes, uno a 0.2 y despues perdida.

    Libre en 1-4. Con la configuracion actual (0.30, liberar 3), el 0.2 se ignora y el centro
    se libera en el 9: FORWARD en 9, 10 y 11 con la persona delante. Con 0.15 y liberar 5, el
    0.2 cuenta como debil y reinicia la liberacion, que no llega a completarse en el 11.
    """
    rows, frames = [], {}
    pattern = [None] * 4 + [0.9, 0.9] + [0.2, None, None, None, None]
    for number, confidence in enumerate(pattern, start=1):
        blocked = number > 4
        row = _row("aj99", number, "centro" if blocked else "libre", HALT if blocked else MOVE)
        detections = [] if confidence is None else [(confidence, CENTRO)]
        rows.append(row)
        frames[row["frame_id"]] = _frame(row, detections)
    return rows, frames


def test_the_grid_keeps_the_current_values_and_every_candidate_is_valid(base):
    configs = candidates(base)
    assert len(configs) == len(GRID["umbral_bajo"]) * 2 * len(GRID["cuadros_para_liberar"])
    current = (base.confianza.umbral_bajo, 2, 3)
    assert current in {
        (c.confianza.umbral_bajo, c.temporal.cuadros_para_bloquear, c.temporal.cuadros_para_liberar)
        for c in configs
    }
    # Solo cambian umbral_bajo y las rachas; zonas, clases y comandos quedan fijos.
    for config in configs:
        assert config.zonas == base.zonas
        assert config.comandos == base.comandos
        assert config.confianza.umbral_alto == base.confianza.umbral_alto


def test_score_counts_actions_outside_the_allowed_ones_and_frames_without_progress(base):
    rows, frames = _flicker_sequence()
    result = score(base, rows, frames)
    assert result["cuadros"] == 11
    assert result["no_permitidas"] == 3
    assert [(d["frame_id"], d["accion"]) for d in result["detalle"]] == [
        ("aj99-0009", "FORWARD"),
        ("aj99-0010", "FORWARD"),
        ("aj99-0011", "FORWARD"),
    ]
    # Arranque seguro: STOP en 1 y 2 con la via libre; avanzar es posible, pero no ocurre.
    assert result["sin_avance"] == 2


def _tuned(base, bajo, liberar):
    datos = base.model_dump()
    datos["confianza"]["umbral_bajo"] = bajo
    datos["temporal"]["cuadros_para_liberar"] = liberar
    return type(base).model_validate(datos)


def test_a_weak_detection_kept_as_evidence_avoids_the_unsafe_forward(base):
    rows, frames = _flicker_sequence()
    result = score(_tuned(base, 0.15, 5), rows, frames)
    assert result["no_permitidas"] == 0
    assert result["sin_avance"] == 4  # liberar 5 tambien retrasa el primer avance


def test_every_sequence_starts_with_a_fresh_policy(base):
    rows, frames = _flicker_sequence()
    other = [
        dict(row, sequence_id="aj98", frame_id=row["frame_id"].replace("aj99", "aj98"))
        for row in rows
    ]
    frames_other = {
        row["frame_id"]: dict(
            frames[original["frame_id"]], sequence_id="aj98", frame_id=row["frame_id"]
        )
        for row, original in zip(other, rows, strict=True)
    }
    single = score(base, rows, frames)
    double = score(base, rows + other, frames | frames_other)
    assert double["no_permitidas"] == 2 * single["no_permitidas"]


def test_select_prefers_safety_then_progress_then_the_smallest_change(base):
    def entry(bajo, liberar, unsafe, stuck):
        return {
            "umbral_bajo": bajo,
            "cuadros_para_bloquear": 2,
            "cuadros_para_liberar": liberar,
            "no_permitidas": unsafe,
            "sin_avance": stuck,
        }

    results = [
        entry(0.30, 3, 13, 0),
        entry(0.10, 5, 8, 1),
        entry(0.15, 5, 8, 1),
        entry(0.15, 4, 9, 0),
    ]
    chosen = select(results, base)
    assert (chosen["umbral_bajo"], chosen["cuadros_para_liberar"]) == (0.15, 5)


def test_tune_is_deterministic_and_reports_the_current_config(base):
    rows, frames = _flicker_sequence()
    first = tune(rows, frames, base)
    second = tune(rows, frames, base)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["actual"]["umbral_bajo"] == base.confianza.umbral_bajo
    assert first["seleccion"] in first["candidatos"]


def test_only_a_tuning_package_is_accepted():
    check_tuning_package(ROOT / "data/p5-ajuste-v1")
    with pytest.raises(ValueError, match="ajuste"):
        check_tuning_package(ROOT / "data/p5-eval-v1")
