"""Recorrido completo de un cuadro: imagen -> deteccion -> estado -> decision -> comando.

Ver `docs/B3-01_RECORRIDO.md`. Cualquier fallo termina en STOP y queda registrado con su
etapa: un cuadro nunca deja vigente el comando de movimiento anterior.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from p3.policy.politica import Decision, PoliticaDecision

from p5.control.adapter import VirtualControlAdapter
from p5.control.models import Action, ControlCommand, ControlDecision
from p5.dataset.paquete import load_manifest
from p5.detector.frame import detect_frame
from p5.detector.yolox import YoloxDetector

logger = logging.getLogger(__name__)

FAILSAFE_REASON = "FALLO_INTEGRACION"

_ACTIONS = {
    "STOP": Action.STOP,
    "FORWARD": Action.FORWARD,
    "SLOW": Action.FORWARD,
    "EVADE_LEFT": Action.LEFT,
    "EVADE_RIGHT": Action.RIGHT,
}
# Decisiones de la politica que rechazan el cuadro, y la etapa a la que corresponden.
_REJECTIONS = {"SALIDA_MALFORMADA": "contract", "CUADRO_FUERA_DE_ORDEN": "policy"}


@dataclass(frozen=True)
class FrameInput:
    """Lo unico que el recorrido recibe de un cuadro. No incluye etiquetas."""

    sequence_id: str
    frame_id: str
    t_capture_ms: float
    # (ancho, alto) esperado: el contrato exige dimensiones aunque la imagen no se pueda leer.
    image_size: tuple[int, int]
    image_path: Path


@dataclass(frozen=True)
class FrameTrace:
    """Lo que ocurrio con un cuadro en cada etapa."""

    sequence_id: str
    frame_id: str
    t_capture_ms: float
    image: str
    perception: dict[str, Any]
    # None solo si la politica fallo y no llego a decidir.
    decision: dict[str, Any] | None
    command: dict[str, Any]
    errors: tuple[dict[str, str], ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), allow_nan=False)


def frames_from_manifest(manifest: Path, *, sequence_id: str | None = None) -> list[FrameInput]:
    """Lee un manifiesto congelado. Las etiquetas de sus filas no pasan al recorrido."""
    rows = load_manifest(manifest)
    if sequence_id is not None:
        rows = [row for row in rows if row["sequence_id"] == sequence_id]
    if not rows:
        raise ValueError(f"no hay cuadros para la secuencia {sequence_id!r} en {manifest}")
    return [
        FrameInput(
            sequence_id=row["sequence_id"],
            frame_id=row["frame_id"],
            t_capture_ms=row["t_capture_ms"],
            image_size=(row["image_width"], row["image_height"]),
            image_path=manifest.parent / row["image"],
        )
        for row in rows
    ]


def to_control_decision(decision: Decision, *, frame_id: str, decision_id: str) -> ControlDecision:
    """Traduce la salida de B1 a la entrada de B2.

    `frame_id` llega aparte porque una salida malformada puede dejar la decision sin el suyo.
    """
    return ControlDecision(
        action=_ACTIONS[decision.accion],
        requested_speed=decision.velocidad,
        frame_id=frame_id,
        decision_id=decision_id,
        reason_code=decision.reason_code,
        requested_steering=decision.direccion,
    )


class Pipeline:
    """Un objeto por recorrido: la politica recuerda los cuadros anteriores."""

    def __init__(
        self,
        detector: YoloxDetector,
        policy: PoliticaDecision,
        adapter: VirtualControlAdapter,
    ) -> None:
        self._detector = detector
        self._policy = policy
        self.adapter = adapter

    def process(self, frame: FrameInput) -> FrameTrace:
        errors: list[dict[str, str]] = []
        perception = self._perceive(frame, errors)
        decision = self._decide(frame, perception, errors)
        command = self._command(frame, decision, errors)
        return FrameTrace(
            sequence_id=frame.sequence_id,
            frame_id=frame.frame_id,
            t_capture_ms=frame.t_capture_ms,
            image=str(frame.image_path),
            perception=perception,
            decision=None if decision is None else decision.model_dump(mode="json"),
            command=asdict(command),
            errors=tuple(errors),
        )

    def _perceive(self, frame: FrameInput, errors: list[dict[str, str]]) -> dict[str, Any]:
        try:
            perception = detect_frame(
                self._detector,
                frame.image_path,
                sequence_id=frame.sequence_id,
                frame_id=frame.frame_id,
                t_capture_ms=frame.t_capture_ms,
                image_size=frame.image_size,
            ).to_dict()
        except Exception as failure:
            # Tambien pasa por la politica: asi reinicia la confirmacion de la via.
            width, height = frame.image_size
            perception = {
                "sequence_id": frame.sequence_id,
                "frame_id": frame.frame_id,
                "t_capture_ms": frame.t_capture_ms,
                "image_width": width,
                "image_height": height,
                "status": "error",
                "detections": (),
                "error": str(failure) or type(failure).__name__,
            }
        if perception["status"] == "error":
            _record(errors, "detector", frame, perception["error"])
        return perception

    def _decide(
        self, frame: FrameInput, perception: dict[str, Any], errors: list[dict[str, str]]
    ) -> Decision | None:
        try:
            decision = self._policy.decidir_crudo(perception)
        except Exception as failure:
            _record(errors, "policy", frame, str(failure) or type(failure).__name__)
            return None
        stage = _REJECTIONS.get(decision.reason_code)
        if stage is not None:
            _record(errors, stage, frame, decision.error or decision.razon)
        return decision

    def _command(
        self, frame: FrameInput, decision: Decision | None, errors: list[dict[str, str]]
    ) -> ControlCommand:
        decision_id = f"{frame.sequence_id}:{frame.frame_id}"
        if decision is not None:
            try:
                return self.adapter.apply(
                    to_control_decision(decision, frame_id=frame.frame_id, decision_id=decision_id)
                )
            except Exception as failure:
                _record(errors, "adapter", frame, str(failure) or type(failure).__name__)
        return self.adapter.apply(
            ControlDecision(
                action=Action.STOP,
                requested_speed=0.0,
                frame_id=frame.frame_id,
                decision_id=decision_id,
                reason_code=FAILSAFE_REASON,
            )
        )


def _record(errors: list[dict[str, str]], stage: str, frame: FrameInput, detail: str) -> None:
    logger.error("integration_error stage=%s frame_id=%s detail=%s", stage, frame.frame_id, detail)
    errors.append({"stage": stage, "detail": detail})
