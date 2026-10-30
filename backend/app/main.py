import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.aisaac_sync import worker as sync_worker
from app.api import apple_health, assistant, auth, exercises, health, routines, training
from app.apple_health import worker
from app.config import load_settings
from app.error_log import install as install_error_log

install_error_log()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(worker())
    sync_task = asyncio.create_task(sync_worker())
    yield
    task.cancel()
    sync_task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    with suppress(asyncio.CancelledError):
        await sync_task


app = FastAPI(title="Gym Tracker API", version="0.1.0", lifespan=lifespan)

settings = load_settings()
if settings.app_env == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(routines.router, prefix="/api/v1")
app.include_router(exercises.router, prefix="/api/v1")
app.include_router(assistant.router, prefix="/api/v1")
app.include_router(training.router, prefix="/api/v1")
app.include_router(apple_health.router, prefix="/api/v1")

# Serves the built frontend from the same app/port as the API, so the two no
# longer need separate Fly apps (and browser requests to /api/v1 stay same-origin
# without an nginx reverse proxy). No-op locally, where this directory doesn't
# exist and the Vite dev server is used instead.
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST_DIR", "/app/frontend_dist")).resolve()
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (FRONTEND_DIST / full_path).resolve()
        is_within_dist = candidate == FRONTEND_DIST or FRONTEND_DIST in candidate.parents
        if full_path and is_within_dist and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
