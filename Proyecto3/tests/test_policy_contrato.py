"""Contrato A -> B: el cuadro con detecciones que consume la politica (B1-02; A1-03)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from p3.policy.contrato import Cuadro

VALIDO = {
    "sequence_id": "s1",
    "frame_id": "s1-0001",
    "t_capture_ms": 100,
    "image_width": 640,
    "image_height": 480,
    "status": "ok",
    "detections": [{"class_name": "person", "confidence": 0.9, "bbox_xyxy": [10, 20, 110, 220]}],
}


def test_un_cuadro_valido_se_acepta() -> None:
    cuadro = Cuadro.model_validate(VALIDO)
    assert cuadro.detections[0].bbox_xyxy == (10, 20, 110, 220)
    assert cuadro.error is None


def test_un_cuadro_sin_objetos_es_una_lista_vacia_valida() -> None:
    cuadro = Cuadro.model_validate({**VALIDO, "detections": []})
    assert cuadro.status == "ok"
    assert cuadro.detections == ()


def test_un_error_del_detector_es_un_estado_explicito() -> None:
    cuadro = Cuadro.model_validate(
        {**VALIDO, "status": "error", "detections": [], "error": "timeout del detector"}
    )
    assert cuadro.status == "error"


@pytest.mark.parametrize(
    "cambio",
    [
        {"status": "error", "error": "fallo"},  # error con detecciones
        {"status": "error", "detections": []},  # error sin mensaje
        {"error": "no deberia estar"},  # ok con mensaje de error
        {"status": "desconocido"},
        {"t_capture_ms": -1},
        {"image_width": 0},
        {"sequence_id": ""},
        {"extra": 1},
    ],
)
def test_un_cuadro_incoherente_se_rechaza(cambio: dict) -> None:
    with pytest.raises(ValidationError):
        Cuadro.model_validate({**VALIDO, **cambio})


@pytest.mark.parametrize(
    "deteccion",
    [
        {"class_name": "person", "confidence": math.nan, "bbox_xyxy": [10, 20, 110, 220]},
        {"class_name": "person", "confidence": 1.2, "bbox_xyxy": [10, 20, 110, 220]},
        {"class_name": "person", "confidence": -0.1, "bbox_xyxy": [10, 20, 110, 220]},
        {"class_name": "person", "confidence": 0.9, "bbox_xyxy": [110, 20, 10, 220]},
        {"class_name": "person", "confidence": 0.9, "bbox_xyxy": [10, 220, 110, 20]},
        {"class_name": "person", "confidence": 0.9, "bbox_xyxy": [10, 20, 700, 220]},
        {"class_name": "person", "confidence": 0.9, "bbox_xyxy": [-5, 20, 110, 220]},
        {"class_name": "person", "confidence": 0.9, "bbox_xyxy": [10, 20, math.inf, 220]},
        {"class_name": "person", "confidence": 0.9, "bbox_xyxy": [10, 20, 110]},
        {"class_name": "", "confidence": 0.9, "bbox_xyxy": [10, 20, 110, 220]},
    ],
)
def test_una_deteccion_malformada_se_rechaza(deteccion: dict) -> None:
    with pytest.raises(ValidationError):
        Cuadro.model_validate({**VALIDO, "detections": [deteccion]})


def test_se_tolera_un_pixel_de_redondeo_en_el_borde() -> None:
    det = {"class_name": "person", "confidence": 0.9, "bbox_xyxy": [-0.5, 0, 640.5, 480]}
    Cuadro.model_validate({**VALIDO, "detections": [det]})
