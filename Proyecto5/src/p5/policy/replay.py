"""C1-C7 sobre cuadros A -> B sinteticos; no requiere detector ni reloj de pared."""

import hashlib
import json
from typing import Any

from p3.policy.casos import construir_cuadros
from p3.policy.config import ConfigPolitica
from p3.policy.politica import PoliticaDecision

from p5.policy.events import log_decision, transition_record

CASE_IDS = tuple(f"C{i}" for i in range(1, 8))


def run_cases(data: dict[str, Any], config: ConfigPolitica, config_sha256: str) -> dict[str, Any]:
    cases = data["casos"]
    if sorted(case["id"] for case in cases) != list(CASE_IDS):
        raise ValueError("se requieren exactamente C1-C7, sin duplicados")
    results = []
    for case in cases:
        # Solo se permiten cambios de evasion por caso; el resto viene del YAML oficial.
        changes = case.get("config", {})
        if set(changes) - {"evasion"}:
            raise ValueError("los casos solo pueden modificar evasion")
        effective = config.model_dump(mode="json")
        effective["evasion"].update(changes.get("evasion", {}))
        settings = ConfigPolitica.model_validate(effective)
        canonical = json.dumps(settings.model_dump(mode="json"), sort_keys=True).encode()
        effective_sha256 = hashlib.sha256(canonical).hexdigest()
        engine = PoliticaDecision(settings, config_sha256=effective_sha256)
        decisions = []
        transitions = []
        for frame in construir_cuadros(case, data):
            # Revalidar el formato publicado por A, no saltar el contrato usando objetos internos.
            decision = engine.decidir_crudo(frame.model_dump(mode="json"))
            log_decision(decision)
            decisions.append(decision.model_dump(mode="json"))
            if decision.cambio_estado:
                transitions.append(transition_record(decision))
        failures = []
        covered = set()
        for rule in case["esperado"]:
            start, end = rule["cuadros"]
            if not 1 <= start <= end <= len(decisions):
                raise ValueError(f"{case['id']}: rango de expectativa invalido")
            for number in range(start, end + 1):
                covered.add(number)
                actual = decisions[number - 1]
                if any(actual.get(key) != value for key, value in rule.items() if key != "cuadros"):
                    failures.append({"cuadro": number, "esperado": rule, "observado": actual})
        if covered != set(range(1, len(decisions) + 1)):
            raise ValueError(f"{case['id']}: hay cuadros sin expectativas")
        results.append(
            {
                "id": case["id"],
                "resultado": "FALLA" if failures else "PASA",
                "config_efectiva": settings.model_dump(mode="json"),
                "config_efectiva_sha256": effective_sha256,
                "fallos": failures,
                "decisiones": decisions,
                "transiciones": transitions,
            }
        )
    return {
        "detecciones": "sinteticas",
        "config_archivo_sha256": config_sha256,
        "total": len(results),
        "pasan": sum(r["resultado"] == "PASA" for r in results),
        "casos": results,
    }
