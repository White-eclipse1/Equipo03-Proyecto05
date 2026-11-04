"""B1-01: verificar el motor compartido con la configuracion oficial de P5."""

from pathlib import Path

import pytest
import yaml
from p3.policy.config import ConfigPolitica, cargar_config
from p3.policy.politica import PoliticaDecision
from pydantic import ValidationError

CONFIG = Path(__file__).resolve().parents[1] / "config" / "politica.yaml"


def policy(**updates):
    config, sha256 = cargar_config(CONFIG)
    data = config.model_dump()
    data.update(updates)
    return PoliticaDecision(ConfigPolitica.model_validate(data), sha256)


def detection(x1=40, x2=60, *, confidence=0.9, class_name="person", y1=40, y2=90):
    return {
        "class_name": class_name,
        "confidence": confidence,
        "bbox_xyxy": [x1, y1, x2, y2],
    }


def decide(engine, *detections, sequence="s", status="ok"):
    time = (engine.memoria.ultimo_t_ms or 0) + 100
    return engine.decidir_crudo(
        {
            "sequence_id": sequence,
            "frame_id": str(time),
            "t_capture_ms": time,
            "image_width": 100,
            "image_height": 100,
            "status": status,
            "detections": list(detections),
            "error": "detector caido" if status == "error" else None,
        }
    )


def clear(engine):
    return [decide(engine) for _ in range(3)][-1]


def test_clear_path_advances_after_confirmation_and_records_config():
    engine = policy()
    decisions = [decide(engine) for _ in range(4)]
    assert [d.accion for d in decisions] == ["STOP", "STOP", "FORWARD", "FORWARD"]
    assert decisions[-1].estado == "CLEAR"
    assert decisions[-1].velocidad == 0.6
    assert decisions[-1].direccion == 0
    assert decisions[-1].config_sha256 == cargar_config(CONFIG)[1]


@pytest.mark.parametrize("enabled", [False, True])
def test_central_obstruction_stops_or_evades_to_confirmed_free_zone(enabled):
    engine = policy(evasion={"habilitada": enabled, "lado_preferido": "derecha"})
    clear(engine)
    assert decide(engine, detection()).accion == "SLOW"
    result = decide(engine, detection())
    assert result.estado == "BLOCKED"
    assert result.accion == ("EVADE_RIGHT" if enabled else "STOP")
    if not enabled:
        assert (result.velocidad, result.direccion) == (0, 0)


@pytest.mark.parametrize(
    ("lateral", "expected"),
    [(detection(70, 90), "EVADE_LEFT"), (detection(10, 30), "EVADE_RIGHT")],
)
def test_never_turns_toward_a_new_obstacle_even_before_it_is_confirmed(lateral, expected):
    engine = policy()
    clear(engine)
    decide(engine, detection())
    result = decide(engine, detection(), lateral)
    assert result.accion == expected


def test_unknown_or_fully_blocked_destinations_stop():
    engine = policy()
    # No lateral ha completado sus tres cuadros libres.
    decide(engine, detection())
    assert decide(engine, detection()).accion == "STOP"
    clear(engine)
    for _ in range(2):
        result = decide(engine, detection(0, 100))
    assert result.estado == "BLOCKED"
    assert result.accion == "STOP"
    assert all(z.estado == "OCUPADA" for z in result.zonas.values())


@pytest.mark.parametrize(
    ("confidence", "level", "action"),
    [
        (0.299, "ignorada", "FORWARD"),
        (0.30, "debil", "SLOW"),
        (0.499, "debil", "SLOW"),
        (0.50, "firme", "EVADE_RIGHT"),
    ],
)
def test_confidence_boundaries(confidence, level, action):
    engine = policy()
    clear(engine)
    for _ in range(2):
        result = decide(engine, detection(confidence=confidence))
    assert result.detecciones[0].nivel == level
    assert result.accion == action


def test_weak_detection_prevents_releasing_an_occupied_center():
    engine = policy(evasion={"habilitada": False, "lado_preferido": "derecha"})
    clear(engine)
    for _ in range(2):
        decide(engine, detection())
    for _ in range(4):
        assert decide(engine, detection(confidence=0.3)).accion == "STOP"
    assert [decide(engine).accion for _ in range(3)] == ["STOP", "STOP", "FORWARD"]


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        (detection(class_name="bird"), "clase_no_obstaculo"),
        (detection(y1=0, y2=39), "fuera_de_banda"),
        (detection(49, 50, y1=89, y2=90), "area_pequena"),
    ],
)
def test_irrelevant_detections_do_not_block(item, reason):
    engine = policy()
    clear(engine)
    result = decide(engine, item)
    assert result.accion == "FORWARD"
    assert result.detecciones[0].motivo == reason


@pytest.mark.parametrize(
    ("box", "zones"),
    [
        ((0, 35), ("izquierda",)),
        ((35, 65), ("centro",)),
        ((65, 100), ("derecha",)),
        ((0, 100), ("izquierda", "centro", "derecha")),
    ],
)
def test_zone_boundaries_and_boxes_spanning_multiple_zones(box, zones):
    result = decide(policy(), detection(*box))
    assert result.detecciones[0].zonas == zones


def test_error_and_new_sequence_require_confirmation_again():
    engine = policy()
    clear(engine)
    failed = decide(engine, status="error")
    assert (failed.estado, failed.accion, failed.velocidad) == ("FAULT", "STOP", 0)
    assert decide(engine).accion == "STOP"
    clear(engine)
    assert decide(engine, sequence="new").accion == "STOP"


def test_configuration_changes_behavior_and_invalid_values_are_rejected():
    engine = policy(
        comandos={
            "velocidad_crucero": 0.8,
            "velocidad_precaucion": 0.3,
            "velocidad_evasion": 0.2,
            "direccion_evasion": 0.5,
        }
    )
    assert clear(engine).velocidad == 0.8
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    data["confianza"]["umbral_bajo"] = 0.9
    with pytest.raises(ValidationError, match="umbral_bajo"):
        ConfigPolitica.model_validate(data)


def test_cli_defaults_use_the_p5_configuration():
    from p5.benchmark.__main__ import DEFAULT_POLICY_CONFIG as BENCHMARK_CONFIG
    from p5.integration.__main__ import DEFAULT_POLICY_CONFIG as INTEGRATION_CONFIG

    assert BENCHMARK_CONFIG == INTEGRATION_CONFIG == Path("config/politica.yaml")


def test_policy_geometry_and_classes_match_the_frozen_dataset_contract():
    from p5.dataset.paquete import MIN_ZONE_COVERAGE, OBSTACLE_CLASSES, ZONES

    config, _ = cargar_config(CONFIG)
    assert config.clases_obstaculo == OBSTACLE_CLASSES
    assert config.zonas.model_dump() == ZONES
    assert config.geometria.cobertura_min_zona == MIN_ZONE_COVERAGE
