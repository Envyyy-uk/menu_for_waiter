from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.config import settings
from app.db import engine

app = FastAPI(
    title="POS зала",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


@app.get("/health", tags=["ops"])
def health() -> JSONResponse:
    """Health-check с проверкой базы: сервер, который отвечает «ok», пока
    Postgres лежит, хуже сервера, который молчит."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503, content={"status": "degraded", "db": exc.__class__.__name__}
        )
    return JSONResponse({"status": "ok", "db": "ok"})


# Статика без сборки. Монтируется последней, чтобы не перехватить /api и /health.
_frontend = settings.frontend_dir
if _frontend.exists():
    for area in ("station", "admin"):
        path = _frontend / area
        if path.exists():
            app.mount(f"/{area}", StaticFiles(directory=path, html=True), name=area)
    if (_frontend / "assets").exists():
        app.mount("/assets", StaticFiles(directory=_frontend / "assets"), name="assets")
    if (_frontend / "waiter").exists():
        app.mount("/", StaticFiles(directory=_frontend / "waiter", html=True), name="waiter")
