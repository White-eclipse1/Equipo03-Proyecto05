"""App del servicio `p3-inference` (F4 T24): la unica con PyTorch que atiende HTTP.

    uvicorn p3.inference.app:app --host 0.0.0.0 --port 8010

No se publica al host: el portal (app de P2) le reenvia `/api/p3/inference` y
`/api/p3/models` (versiones de modelo, F7).
"""

from __future__ import annotations

from fastapi import FastAPI

from p3.inference.api import router
from p3.registry.api import router as models_router

app = FastAPI(title="P3 inference", docs_url="/docs")
app.include_router(router)
app.include_router(models_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
