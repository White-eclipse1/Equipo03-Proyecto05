"""Punto de entrada HTTP de la plataforma de calidad de datasets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from p3.data.api import router as p3_releases_router
from p3.data.manifests_api import router as p3_manifests_router
from p3.eval.api import router as p3_evaluation_router
from p3.inference.proxy import router as p3_inference_router
from p3.registry.proxy import router as p3_models_router
from p3.train.runs_api import router as p3_runs_router
from p3.train.selection import router as p3_selection_router
from p3.worker.api import router as p3_training_router
from p4.capturas.api import router as p4_capturas_router

from dataset_quality import __version__
from dataset_quality.api.artifacts import router as artifacts_router
from dataset_quality.api.copilot import router as copilot_router
from dataset_quality.api.duplicates import router as duplicates_router
from dataset_quality.api.pipeline import router as pipeline_router
from dataset_quality.api.policy import router as policy_router
from dataset_quality.db import check_database
from dataset_quality.storage import check_object_storage

# Donde vive el build de Vite. Por defecto, dentro del paquete: es donde lo
# deja `npm run build` en el host y donde lo espera una instalacion normal.
#
# `DQ_STATIC_DIR` existe por el contenedor, y no es un lujo de configuracion:
# compose monta `./src` en vivo para recargar uvicorn al editar, y ese montaje
# TAPA cualquier cosa que la imagen haya dejado bajo `src/`. Como el build esta
# en `.gitignore`, quien clona el repositorio no lo tiene en el host, y la
# carpeta que el montaje pone encima del build de la imagen esta vacia: la
# imagen trae la web compilada y aun asi el contenedor sirve un 404. Sacando el
# build fuera de `src/` los dos montajes dejan de estorbarse.
STATIC_DIR = Path(os.environ.get("DQ_STATIC_DIR") or Path(__file__).parent / "static")


def _run_check(name: str, check: Any) -> dict[str, str]:
    """Ejecuta una comprobacion y la traduce a un resultado serializable."""
    try:
        check()
    # Se captura ancho a proposito: /health debe reportar el fallo, no propagarlo.
    except Exception as error:
        return {"name": name, "status": "down", "detail": f"{type(error).__name__}: {error}"}
    return {"name": name, "status": "up"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dataset Quality & Versioning",
        version=__version__,
        docs_url="/docs",
    )

    @app.get("/health", tags=["infra"])
    def health() -> JSONResponse:
        """Verifica que la app, MariaDB y MinIO esten realmente arriba."""
        checks = [
            _run_check("mariadb", check_database),
            _run_check("minio", check_object_storage),
        ]
        healthy = all(check["status"] == "up" for check in checks)
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "degraded",
                "version": __version__,
                "checks": checks,
            },
        )

    @app.get("/api/config", tags=["infra"])
    def config() -> dict[str, object]:
        """Configuracion efectiva SIN secretos (util para depurar el entorno)."""
        from dataset_quality.settings import get_settings

        return get_settings().public_summary()

    app.include_router(artifacts_router)
    app.include_router(copilot_router)
    app.include_router(duplicates_router)
    app.include_router(pipeline_router)
    app.include_router(policy_router)
    # Proyecto 3 (`Proyecto3/src/p3`): mismo portal, rutas bajo `/api/p3/`.
    app.include_router(p3_training_router)
    app.include_router(p3_releases_router)
    app.include_router(p3_manifests_router)
    app.include_router(p3_inference_router)
    app.include_router(p3_selection_router)
    app.include_router(p3_runs_router)
    app.include_router(p3_evaluation_router)
    app.include_router(p3_models_router)
    # Proyecto 4 (`Proyecto4/src/p4`): capturas del dispositivo edge bajo `/api/p4/capturas`.
    app.include_router(p4_capturas_router)

    # El build de Vite (si existe). En desarrollo puede no estar compilado
    # todavia: la API sigue respondiendo y /docs tambien.
    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    index_html = STATIC_DIR / "index.html"

    # `response_model=None`: el retorno es una union de Response y FastAPI
    # intentaria construir un modelo Pydantic a partir de ella.
    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    def spa(full_path: str) -> FileResponse | JSONResponse:
        """Cualquier ruta de navegacion devuelve el index de la SPA."""
        del full_path
        if index_html.is_file():
            return FileResponse(index_html)
        return JSONResponse(
            content={
                "mensaje": "La app web no esta compilada.",
                "como": "npm --prefix web ci && npm --prefix web run build",
                "api": "/docs",
            }
        )

    return app


app = create_app()
