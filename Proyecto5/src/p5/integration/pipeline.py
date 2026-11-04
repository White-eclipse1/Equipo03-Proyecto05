"""Recorrido completo de un cuadro: imagen -> deteccion -> estado -> decision -> comando.

Ver `docs/B3-01_RECORRIDO.md` y `docs/B2-02_WATCHDOG.md`. Cualquier fallo termina en STOP y
queda registrado con su etapa: un cuadro nunca deja vigente el comando de movimiento anterior,
y tras un fallo la via hay que volver a confirmarla. `tick` hace lo mismo cuando vence un
comando, aunque no llegue ningun cuadro.
"""

import json
import logging
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from p3.policy.politica import Decision, Memoria, PoliticaDecision

from p5.control.adapter import VirtualControlAdapter
from p5.control.models import Action, ControlDecision
from p5.dataset.paquete import load_manifest
from p5.detector.frame import detect_frame
from p5.detector.yolox import YoloxDetector

logger = logging.getLogger(__name__)

FAILSAFE_REASON = "FALLO_INTEGRACION"
# El STOP de respaldo tampoco llego al adaptador: solo consta en la traza.
STOP_NOT_EMITTED_REASON = "STOP_NO_EMITIDO"
WATCHDOG_REASON = "WATCHDOG_VENCIDO"
STALE_FRAME_REASON = "CUADRO_VENCIDO"

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
    # None en este y los demas campos numericos si el valor no era finito: ver `errors`.
    t_capture_ms: float | None
    image: str
    perception: dict[str, Any]
    # None solo si la politica fallo y no llego a decidir.
    decision: dict[str, Any] | None
    command: dict[str, Any]
    errors: tuple[dict[str, str], ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), allow_nan=False)


@dataclass(frozen=True)
class WatchdogEvent:
    """Un comando que vencio sin que llegara un cuadro. No pertenece a ningun cuadro nuevo."""

    # None si el reloj no era finito: ver `errors`.
    t_ms: float | None
    expired_frame_id: str
    expired_decision_id: str
    valid_until_ms: float
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
        valid_until_ms=decision.valido_hasta_ms,
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
        # Verdadero si un STOP no se pudo emitir: este recorrido ya no vuelve a moverse.
        self.halted = False

    def process(self, frame: FrameInput, *, now_ms: float | None = None) -> FrameTrace:
        """Lleva un cuadro por todo el recorrido.

        Con `now_ms`, en el reloj de la secuencia, rechaza el cuadro si ya es demasiado viejo.
        Sin el, se reproduce la secuencia sin comprobar su antiguedad.
        """
        errors: list[dict[str, str]] = []
        if now_ms is not None and self._is_stale(frame, now_ms):
            detail = f"cuadro vencido: capturado en {frame.t_capture_ms}, ahora {now_ms}"
            _record(errors, "stale", frame.frame_id, detail)
            self._restart_confirmation(frame.sequence_id)
            perception = _failed_perception(frame, detail)
            command = self._stop(frame.frame_id, _decision_id(frame), errors, STALE_FRAME_REASON)
            return self._trace(frame, perception, None, command, errors)

        perception = self._perceive(frame, errors)
        decision = self._decide(frame, perception, errors)
        command = self._command(frame, decision, errors)
        return self._trace(frame, perception, decision, command, errors)

    def tick(self, now_ms: float) -> WatchdogEvent | None:
        """Avisa al recorrido que paso el tiempo, llegue o no un cuadro.

        Si el comando de movimiento vigente ya vencio, emite STOP y la via hay que volver a
        confirmarla. Devuelve el evento, o None si no vencio nada.
        """
        if not self.adapter.is_expired(now_ms):
            return None
        expired = self.adapter.last_command
        logger.warning(
            "watchdog_expired frame_id=%s decision_id=%s valid_until_ms=%s now_ms=%s",
            expired.frame_id,
            expired.decision_id,
            expired.valid_until_ms,
            now_ms,
        )
        errors: list[dict[str, str]] = []
        self._restart_confirmation(self._policy.memoria.sequence_id)
        command = self._stop(
            expired.frame_id, f"watchdog:{expired.decision_id}", errors, WATCHDOG_REASON
        )
        replaced: list[str] = []
        fields = _finite_only({"t_ms": now_ms, "command": command}, "", replaced)
        if replaced:
            detail = f"valores no finitos en {', '.join(replaced)}"
            _record(errors, "trace", expired.frame_id, detail)
        return WatchdogEvent(
            expired_frame_id=expired.frame_id,
            expired_decision_id=expired.decision_id,
            valid_until_ms=expired.valid_until_ms,
            errors=tuple(errors),
            **fields,
        )

    def _is_stale(self, frame: FrameInput, now_ms: float) -> bool:
        # Mismo limite que la vigencia de un comando: `vigencia_comando_ms` de la politica.
        limit = self._policy.config.temporal.vigencia_comando_ms
        return not isfinite(now_ms) or now_ms - frame.t_capture_ms >= limit

    def _trace(
        self,
        frame: FrameInput,
        perception: dict[str, Any],
        decision: Decision | None,
        command: dict[str, Any],
        errors: list[dict[str, str]],
    ) -> FrameTrace:
        replaced: list[str] = []
        fields = _finite_only(
            {
                "t_capture_ms": frame.t_capture_ms,
                "perception": perception,
                "decision": None if decision is None else decision.model_dump(mode="json"),
                "command": command,
            },
            "",
            replaced,
        )
        if replaced:
            detail = f"valores no finitos en {', '.join(replaced)}"
            _record(errors, "trace", frame.frame_id, detail)
        return FrameTrace(
            sequence_id=frame.sequence_id,
            frame_id=frame.frame_id,
            image=str(frame.image_path),
            errors=tuple(errors),
            **fields,
        )

    def halt(self, frame: FrameInput) -> None:
        """Termina el recorrido en STOP cuando el fallo ocurre fuera de `process`."""
        self.halted = True
        self._stop(frame.frame_id, _decision_id(frame), [])

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
            perception = _failed_perception(frame, str(failure) or type(failure).__name__)
        if perception["status"] == "error":
            _record(errors, "detector", frame.frame_id, perception["error"])
        return perception

    def _decide(
        self, frame: FrameInput, perception: dict[str, Any], errors: list[dict[str, str]]
    ) -> Decision | None:
        try:
            decision = self._policy.decidir_crudo(perception)
        except Exception as failure:
            _record(errors, "policy", frame.frame_id, str(failure) or type(failure).__name__)
            self._restart_confirmation(frame.sequence_id)
            return None
        stage = _REJECTIONS.get(decision.reason_code)
        if stage is not None:
            _record(errors, stage, frame.frame_id, decision.error or decision.razon)
        return decision

    def _command(
        self, frame: FrameInput, decision: Decision | None, errors: list[dict[str, str]]
    ) -> dict[str, Any]:
        if self.halted:
            detail = "recorrido detenido por un STOP fallido anterior"
            _record(errors, "failsafe", frame.frame_id, detail)
        elif decision is not None:
            try:
                control = to_control_decision(
                    decision, frame_id=frame.frame_id, decision_id=_decision_id(frame)
                )
                return asdict(self.adapter.apply(control))
            except Exception as failure:
                _record(errors, "adapter", frame.frame_id, str(failure) or type(failure).__name__)
                self._restart_confirmation(frame.sequence_id)
        return self._stop(frame.frame_id, _decision_id(frame), errors)

    def _stop(
        self,
        frame_id: str,
        decision_id: str,
        errors: list[dict[str, str]],
        reason: str = FAILSAFE_REASON,
    ) -> dict[str, Any]:
        try:
            return asdict(
                self.adapter.apply(
                    ControlDecision(
                        action=Action.STOP,
                        requested_speed=0.0,
                        frame_id=frame_id,
                        decision_id=decision_id,
                        reason_code=reason,
                    )
                )
            )
        except Exception as failure:
            _record(errors, "failsafe", frame_id, str(failure) or type(failure).__name__)
            self.halted = True
            self.adapter.cancel()
            # El adaptador no lo genero: por eso no tiene hora de emision.
            return {
                "speed": 0.0,
                "direction": "stop",
                "steering": 0.0,
                "timestamp": None,
                "frame_id": frame_id,
                "decision_id": decision_id,
                "reason_code": STOP_NOT_EMITTED_REASON,
                "valid_until_ms": None,
            }

    def _restart_confirmation(self, sequence_id: str | None) -> None:
        """Igual que un error del detector: lo recordado deja de valer para avanzar."""
        self._policy.memoria = Memoria(
            estado="FAULT",
            sequence_id=sequence_id,
            ultimo_t_ms=self._policy.memoria.ultimo_t_ms,
        )


def _decision_id(frame: FrameInput) -> str:
    return f"{frame.sequence_id}:{frame.frame_id}"


def _failed_perception(frame: FrameInput, detail: str) -> dict[str, Any]:
    width, height = frame.image_size
    return {
        "sequence_id": frame.sequence_id,
        "frame_id": frame.frame_id,
        "t_capture_ms": frame.t_capture_ms,
        "image_width": width,
        "image_height": height,
        "status": "error",
        "detections": (),
        "error": detail,
    }


def _finite_only(value: Any, path: str, replaced: list[str]) -> Any:
    """Copia `value` con None en lugar de cada numero no finito, y anota donde estaba."""
    if isinstance(value, dict):
        return {
            key: _finite_only(item, f"{path}.{key}" if path else key, replaced)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_finite_only(item, f"{path}[{i}]", replaced) for i, item in enumerate(value)]
    if isinstance(value, float) and not isfinite(value):
        replaced.append(path)
        return None
    return value


def _record(errors: list[dict[str, str]], stage: str, frame_id: str, detail: str) -> None:
    logger.error("integration_error stage=%s frame_id=%s detail=%s", stage, frame_id, detail)
    errors.append({"stage": stage, "detail": detail})
