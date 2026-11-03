"""Lectura y escritura de la politica de calidad desde la app web.

Settings ensenaba la configuracion del entorno y, de los umbrales, solo la
frase "viven en quality.yaml". Eso deja la pantalla a medias: se puede ver que
la compuerta bloquea por `min_images_per_class` pero no ajustar el umbral sin
abrir una terminal.

Estos dos endpoints cierran el circulo:

    GET /api/policy   la politica vigente, leida del archivo
    PUT /api/policy   la reescribe, conservando sus comentarios

El cuerpo del PUT es un `QualityConfig` completo: FastAPI lo valida antes de
que llegue una sola linea al disco, asi que un umbral fuera de rango se rechaza
con un 422 que nombra el campo, no con un archivo corrupto.

Lo que NO hace: recalcular. Cambiar la politica no vuelve a medir el dataset —
son cosas distintas y mezclarlas escondería cuál de las dos falló. La respuesta
lo dice (`stale_reports`) y la pantalla ofrece el boton de recalcular al lado.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException

from dataset_quality import policy
from dataset_quality.models.errors import DatasetValidationError
from dataset_quality.models.quality import QualityConfig

# Minimo que exige el curso (compuerta M3). Bajarlo desde la app se permite —
# para probar la compuerta hay que poder moverlo — pero no en silencio.
MINIMO_DEL_CURSO = 300

# Dos guardados a la vez reescribirian el archivo entrelazado.
LOCK = threading.Lock()

router = APIRouter(prefix="/api/policy", tags=["politica"])


def _leer() -> QualityConfig:
    if not policy.CONFIG_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Falta `quality.yaml` en {policy.CONFIG_PATH.parent}: "
                "sin politica no hay umbrales."
            ),
        )
    try:
        return QualityConfig.from_yaml(policy.CONFIG_PATH)
    except DatasetValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _avisos(config: QualityConfig) -> list[str]:
    """Incoherencias entre la politica guardada y lo que exige el curso."""
    check = config.min_images_per_class
    avisos = []
    if check.enabled and check.min_images < MINIMO_DEL_CURSO:
        avisos.append(
            f"`min_images_per_class.min_images` quedo en {check.min_images}, por debajo de las "
            f"{MINIMO_DEL_CURSO} imagenes que exige el curso. `tests/test_min_images.py` "
            f"pondra la suite en rojo hasta que vuelva a subir."
        )
    if not check.enabled:
        avisos.append(
            "`min_images_per_class` quedo desactivado: el volumen minimo deja de comprobarse."
        )
    if check.enabled and check.severity != "error":
        avisos.append(
            f"`min_images_per_class.severity` quedo en `{check.severity}`: "
            "no bloquearia el release."
        )
    return avisos


@router.get("")
def get_policy() -> dict[str, Any]:
    """La politica vigente, tal como la lee la compuerta."""
    config = _leer()
    return {
        "source": "quality.yaml",
        "path": policy.CONFIG_PATH.name,
        "data": config.model_dump(),
        "warnings": _avisos(config),
    }


@router.put("")
def put_policy(nueva: QualityConfig) -> dict[str, Any]:
    """Guarda la politica en `quality.yaml` y dice que umbrales cambiaron."""
    if not policy.CONFIG_PATH.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"Falta `quality.yaml` en {policy.CONFIG_PATH.parent}: no hay nada que editar.",
        )

    if not LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ya hay un guardado en curso.")
    try:
        cambios = policy.save(nueva, policy.CONFIG_PATH)
    except policy.PolicyWriteError as error:
        # 409: el archivo en disco impide la edicion. La peticion es valida
        # — el modelo ya la valido — y el fallo no es del servidor.
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DatasetValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        LOCK.release()

    return {
        "changed": cambios,
        "data": nueva.model_dump(),
        "warnings": _avisos(nueva),
        # La compuerta lee el archivo en cada corrida: el cambio ya esta, pero
        # `quality.json` sigue siendo el de la politica anterior hasta que se
        # vuelva a medir.
        "stale_reports": bool(cambios),
        "next_steps": ["POST /api/pipeline/refresh (o `dq gate`) para aplicar los umbrales nuevos"]
        if cambios
        else [],
    }
