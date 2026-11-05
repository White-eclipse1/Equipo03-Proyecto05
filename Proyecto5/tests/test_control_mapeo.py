"""Mapeo de comandos a las rutas del firmware, sin red ni hardware."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from p5.control.adapter import VirtualControlAdapter
from p5.control.mapeo import MOTION_ROUTES, STOP_ROUTE, route_for
from p5.control.models import Action, ControlCommand, ControlDecision

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "evidencias" / "B1-03-detector" / "c1-c10-sin-filtro" / "decisiones.jsonl"
FIRMWARE_ROUTES = {"/go", "/left", "/right", "/stop"}
NOW_MS = 100.0


def motion(**changes):
    values = {
        "speed": 0.5,
        "direction": "forward",
        "steering": 0.0,
        "timestamp": 0.0,
        "frame_id": "f",
        "decision_id": "d",
        "reason_code": "VIA_LIBRE",
        "valid_until_ms": 800.0,
    }
    return ControlCommand(**{**values, **changes})


@pytest.mark.parametrize(
    ("direction", "steering", "route"),
    [("forward", 0.0, "/go"), ("left", -0.5, "/left"), ("right", 0.5, "/right")],
)
def test_valid_motion_uses_its_route(direction, steering, route):
    decision = route_for(motion(direction=direction, steering=steering), now_ms=NOW_MS)

    assert (decision.route, decision.reason) == (route, "comando")


def test_stop_always_uses_the_stop_route():
    command = VirtualControlAdapter().apply(
        ControlDecision(
            action=Action.STOP,
            requested_speed=0.0,
            frame_id="f",
            decision_id="d",
            reason_code="stop",
        )
    )

    assert route_for(command, now_ms=NOW_MS).route == STOP_ROUTE
    assert route_for(command, now_ms=float("nan")).route == STOP_ROUTE


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"direction": "back"}, "direccion_invalida"),
        ({"speed": 0.0}, "velocidad_invalida"),
        ({"speed": -0.1}, "velocidad_invalida"),
        ({"speed": 1.01}, "velocidad_invalida"),
        ({"speed": float("nan")}, "velocidad_invalida"),
        ({"speed": float("inf")}, "velocidad_invalida"),
        ({"speed": True}, "velocidad_invalida"),
        ({"steering": float("nan")}, "giro_invalido"),
        ({"steering": 0.5}, "giro_invalido"),
        ({"direction": "left", "steering": 0.5}, "giro_invalido"),
        ({"direction": "right", "steering": -0.5}, "giro_invalido"),
        ({"direction": "left", "steering": -1.5}, "giro_invalido"),
        ({"valid_until_ms": None}, "sin_vigencia"),
        ({"valid_until_ms": float("nan")}, "sin_vigencia"),
        ({"valid_until_ms": float("inf")}, "sin_vigencia"),
    ],
)
def test_invalid_values_stop_the_car(changes, reason):
    decision = route_for(motion(**changes), now_ms=NOW_MS)

    assert (decision.route, decision.reason) == (STOP_ROUTE, reason)


@pytest.mark.parametrize("speed", [0.01, 1.0])
def test_speed_limits_are_accepted(speed):
    assert route_for(motion(speed=speed), now_ms=NOW_MS).route == "/go"


@pytest.mark.parametrize(
    ("now_ms", "route", "reason"),
    [
        (799.0, "/go", "comando"),
        (800.0, STOP_ROUTE, "vencido"),
        (801.0, STOP_ROUTE, "vencido"),
        (float("nan"), STOP_ROUTE, "reloj_invalido"),
        (float("inf"), STOP_ROUTE, "reloj_invalido"),
        (None, STOP_ROUTE, "reloj_invalido"),
    ],
)
def test_an_expired_command_or_invalid_clock_stops_the_car(now_ms, route, reason):
    decision = route_for(motion(), now_ms=now_ms)

    assert (decision.route, decision.reason) == (route, reason)


def test_the_clock_cannot_be_left_out():
    with pytest.raises(TypeError, match="now_ms"):
        route_for(motion())


def test_document_says_the_physical_turn_direction_is_not_verified():
    document = (ROOT / "docs" / "B2_MAPEO_CARRO.md").read_text(encoding="utf-8")

    assert "sentido físico de los giros sigue sin verificar" in document


def test_the_reverse_route_is_never_used():
    assert set(MOTION_ROUTES.values()) | {STOP_ROUTE} == FIRMWARE_ROUTES


def test_mapping_does_not_change_the_command():
    command = motion()
    copy = replace(command)

    route_for(command, now_ms=900.0)

    assert command == copy


def test_every_recorded_real_command_has_a_route():
    rows = [json.loads(line) for line in REFERENCE.read_text(encoding="utf-8").splitlines()]
    recorded = [row for row in rows if row.get("comando") and "t_capture_ms" in row]
    commands = [ControlCommand(**row["comando"]) for row in recorded]

    # Cada comando se comprueba en el instante de su cuadro, cuando todavia estaba vigente.
    decisions = [
        route_for(command, now_ms=row["t_capture_ms"])
        for command, row in zip(commands, recorded, strict=True)
    ]

    assert commands
    assert {decision.reason for decision in decisions} == {"comando"}
    expected = {"stop": "/stop", "forward": "/go", "left": "/left", "right": "/right"}
    assert [decision.route for decision in decisions] == [
        expected[command.direction] for command in commands
    ]


def test_readme_identifies_the_eight_people_and_the_two_groups():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Equipo", 1)[1].split("\n## ", 1)[0]

    for login in (
        "White-eclipse1",
        "Sir-roboot",
        "JGO-07",
        "D-Lemus",
        "OmarCTMX",
        "AndresQuiVal",
        "lluisvl",
        "Lanachiza",
    ):
        assert f"@{login}" in section
    assert "Percepción y datos" in section
    assert "Control y verificación" in section
