"""Registro estructurado de las decisiones del motor, sin cambiar su estado."""

import logging
from typing import Any

from p3.policy.politica import Decision

logger = logging.getLogger(__name__)


def transition_record(decision: Decision) -> dict[str, Any]:
    return decision.model_dump(
        mode="json",
        include={
            "sequence_id",
            "frame_id",
            "t_capture_ms",
            "estado_anterior",
            "estado",
            "cambio_estado",
            "accion",
            "reason_code",
            "razon",
            "config_sha256",
        },
    )


def log_decision(decision: Decision) -> None:
    if decision.cambio_estado:
        logger.info(
            "policy_transition sequence_id=%s frame_id=%s %s -> %s reason_code=%s",
            decision.sequence_id,
            decision.frame_id,
            decision.estado_anterior,
            decision.estado,
            decision.reason_code,
            extra={"policy_transition": transition_record(decision)},
        )
