"""Control C7 configurable: CLEAR -> BLOCKED -> CLEAR con ausencia aislada intermedia."""

from p3.policy.politica import PoliticaDecision


def run_temporal_control(config):
    settings, sha256 = config
    release = settings.temporal.cuadros_para_liberar
    block = settings.temporal.cuadros_para_bloquear
    obstacle = {
        "class_name": "person",
        "confidence": settings.confianza.umbral_alto,
        "bbox_xyxy": [160, 120, 240, 280],
    }
    inputs = [[]] * release + [[obstacle]] * (block + 1) + [[]] + [[obstacle]] + [[]] * release
    states = (
        ["UNKNOWN"] * (release - 1)
        + ["CLEAR"]
        + ["CAUTION"] * (block - 1)
        + ["BLOCKED"] * (release + 3)
        + ["CLEAR"]
    )
    engine = PoliticaDecision(settings, sha256)
    decisions, failures = [], []
    for index, (objects, state) in enumerate(zip(inputs, states, strict=True), start=1):
        frame = {
            "sequence_id": "C7-control",
            "frame_id": f"C7-control-{index:04d}",
            "t_capture_ms": index * 100,
            "image_width": 400,
            "image_height": 296,
            "status": "ok",
            "detections": objects,
        }
        decision = engine.decidir_crudo(frame).model_dump(mode="json")
        decisions.append({**decision, "cuadro": frame})
        if decision["estado"] != state:
            failures.append(
                {
                    "regla": "estado_temporal",
                    "frame_id": frame["frame_id"],
                    "esperado": state,
                    "observado": decision["estado"],
                }
            )
    if decisions[-1]["accion"] != "FORWARD" or decisions[-1]["velocidad"] <= 0:
        failures.append({"regla": "recuperacion_sin_avance"})
    return {
        "origen": "detecciones_sinteticas",
        "esperado": states,
        "resultado": "FALLA" if failures else "PASA",
        "fallos": failures,
        "decisiones": decisions,
    }
