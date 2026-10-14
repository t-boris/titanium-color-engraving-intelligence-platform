"""The application factory: JSON API under /api and the browser UI as static files from the same process."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..db import Store
from . import routes_plans, routes_setup, routes_work
from .common import install_error_handlers

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def create_app(data_dir: str | Path) -> FastAPI:
    app = FastAPI(title="Titanium Color Engraving Intelligence Platform", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store = Store(data_dir)
    install_error_handlers(app)

    @app.get("/api/version")
    def version():
        return {"version": __version__, "data_dir": str(app.state.store.data_dir)}

    @app.get("/api/health")
    def health():
        app.state.store.one("SELECT 1")
        return {"status": "ok"}

    for r in (routes_setup.router, routes_work.router, routes_plans.router):
        app.include_router(r)

    @app.exception_handler(404)
    async def not_found(request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "not found", "kind": "not_found"}, status_code=404)
        index = UI_DIR / "index.html"
        return FileResponse(index) if index.exists() else JSONResponse({"error": "not found"}, status_code=404)

    if UI_DIR.exists():
        app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
    return app
