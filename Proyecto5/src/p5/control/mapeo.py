"""Traduce un comando virtual a la ruta del firmware del carro. Ver `docs/B2_MAPEO_CARRO.md`.

Solo calcula la ruta: no abre conexiones ni activa motores. Ante cualquier duda devuelve `/stop`,
porque las rutas de movimiento del firmware siguen activas hasta recibir otra orden.
"""

from dataclasses import dataclass
from math import isfinite

from p5.control.models import ControlCommand

STOP_ROUTE = "/stop"
MOTION_ROUTES = {"forward": "/go", "left": "/left", "right": "/right"}
MAX_SPEED = 1.0
MAX_STEERING = 1.0


@dataclass(frozen=True)
class RouteDecision:
    route: str
    # "comando" si la ruta sale del comando; si no, por que se cambio a STOP.
    reason: str


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _unsafe_reason(command: ControlCommand, now_ms: float) -> str | None:
    if not isinstance(command.direction, str) or command.direction not in MOTION_ROUTES:
        return "direccion_invalida"
    if not _is_number(command.speed) or not 0.0 < command.speed <= MAX_SPEED:
        return "velocidad_invalida"
    if not _is_number(command.steering) or abs(command.steering) > MAX_STEERING:
        return "giro_invalido"
    wanted_sign = {"forward": 0, "left": -1, "right": 1}[command.direction]
    if (command.steering > 0) - (command.steering < 0) != wanted_sign:
        return "giro_invalido"
    if not _is_number(command.valid_until_ms):
        return "sin_vigencia"
    if not _is_number(now_ms):
        return "reloj_invalido"
    if now_ms >= command.valid_until_ms:
        return "vencido"
    return None


def route_for(command: ControlCommand, *, now_ms: float) -> RouteDecision:
    """Ruta de un comando en el instante `now_ms`, en el reloj de la secuencia.

    `now_ms` es obligatorio: ninguna ruta de movimiento sale sin comprobar la vigencia.
    """
    if command.direction == "stop":
        return RouteDecision(STOP_ROUTE, "comando")
    reason = _unsafe_reason(command, now_ms)
    if reason is not None:
        return RouteDecision(STOP_ROUTE, reason)
    return RouteDecision(MOTION_ROUTES[command.direction], "comando")
