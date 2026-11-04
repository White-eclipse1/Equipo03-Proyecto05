"""C6 sintetico en torno a los umbrales configurados, sin inferencia ni etiquetas reales."""

from p3.policy.politica import PoliticaDecision


def run_confidence_case(case, config):
    settings, sha256 = config
    low, high = settings.confianza.umbral_bajo, settings.confianza.umbral_alto
    release, block = settings.temporal.cuadros_para_liberar, settings.temporal.cuadros_para_bloquear
    phases = [
        ("libre", None, release),
        ("ignorada", low / 2, 2),
        ("debil", (low + high) / 2, 2),
        ("firme", high, block),
    ]
    engine = PoliticaDecision(settings, sha256)
    decisions, expectations, failures = [], [], []
    for name, confidence, length in phases:
        for index in range(length):
            number = len(decisions) + 1
            frame = {
                "sequence_id": "C6",
                "frame_id": f"C6-{number:04d}",
                "t_capture_ms": number * 100,
                "image_width": 400,
                "image_height": 296,
                "status": "ok",
                "detections": []
                if confidence is None
                else [
                    {
                        "class_name": "person",
                        "confidence": confidence,
                        "bbox_xyxy": [160, 120, 240, 280],
                    }
                ],
            }
            if name == "libre":
                expected_state = "UNKNOWN" if index < release - 1 else "CLEAR"
                actions = ["STOP"] if index < release - 1 else ["FORWARD"]
            elif name == "ignorada":
                expected_state, actions = "CLEAR", ["FORWARD"]
            elif name == "debil" or index < block - 1:
                expected_state, actions = "CAUTION", ["SLOW"]
            else:
                expected_state, actions = "BLOCKED", ["STOP", "EVADE_LEFT", "EVADE_RIGHT"]
            # Expectativa construida solo con fase y configuracion, ANTES de decidir.
            expectation = {
                "cuadro": number,
                "fase": name,
                "confidence": confidence,
                "estado": expected_state,
                "acciones": actions,
            }
            expectations.append(expectation)
            decision = engine.decidir_crudo(frame).model_dump(mode="json")
            decisions.append({**decision, "cuadro": frame})
            if decision["estado"] != expected_state or decision["accion"] not in actions:
                failures.append(
                    {
                        "regla": "confianza",
                        "frame_id": frame["frame_id"],
                        "esperado": expectation,
                        "observado": decision,
                    }
                )
            if confidence is not None and decision["detecciones"][0]["nivel"] != name:
                failures.append(
                    {
                        "regla": "nivel_confianza",
                        "frame_id": frame["frame_id"],
                        "esperado": name,
                        "observado": decision["detecciones"][0],
                    }
                )
    return {
        "id": case["id"],
        "tipo": "sintetico",
        "nombre": case["nombre"],
        "entrada": {"detecciones": "sinteticas", "confianza": settings.confianza.model_dump()},
        "esperado": expectations,
        "resultado": "FALLA" if failures else "PASA",
        "fallos": failures,
        "decisiones": decisions,
    }
