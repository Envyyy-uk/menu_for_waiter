import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import admin as admin_api
from app.api import auth as auth_api
from app.api import checks as checks_api
from app.api import menu as menu_api
from app.api import push as push_api
from app.api import station as station_api
from app.api import tables as tables_api
from app.api import ws as ws_api
from app.core.config import settings
from app.db import engine
from app.services import realtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Реалтайм зовётся из синхронных обработчиков, живущих в пуле потоков.
    # Чтобы класть события в очередь, ему нужен цикл событий сервера.
    realtime.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(
    title="POS зала",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.include_router(auth_api.router)
app.include_router(admin_api.router)
app.include_router(menu_api.router)
app.include_router(tables_api.router)
app.include_router(checks_api.router)
app.include_router(push_api.router)
app.include_router(station_api.router)
app.include_router(ws_api.router)


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
