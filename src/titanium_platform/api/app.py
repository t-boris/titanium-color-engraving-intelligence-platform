"""The application factory: JSON API under /api and the browser UI as static files from the same process."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, capability_results, research
from ..db import open_store
from . import routes_devices, routes_lenses, routes_plans, routes_prediction, routes_research, routes_setup, routes_vector, routes_work
from .common import install_error_handlers

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


class UIFiles(StaticFiles):
    """Static UI files that the browser must revalidate on every load.

    Without a Cache-Control header browsers apply heuristic caching to the scripts, so after an upgrade a
    tablet or a reloaded tab can keep running old screens against the new API. ``no-cache`` still allows the
    cached copy, but only after a cheap ETag check, so an upgrade takes effect on the next reload.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(data_dir: str | Path) -> FastAPI:
    app = FastAPI(title="Laser Workshop", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store = open_store(data_dir)          # a database the migration refuses ends the start with exit code 2
    capability_results.backfill_findings(app.state.store)
    install_error_handlers(app)

    @app.exception_handler(research.ResearchError)
    async def research_error(_, exc):
        return JSONResponse({"error": str(exc), "kind": "invalid"}, status_code=422)

    @app.get("/api/version")
    def version():
        return {"version": __version__, "data_dir": str(app.state.store.data_dir)}

    @app.get("/api/health")
    def health():
        app.state.store.one("SELECT 1")
        return {"status": "ok"}

    for r in (routes_setup.router, routes_devices.router, routes_lenses.router, routes_work.router, routes_plans.router,
              routes_vector.router, routes_research.router, routes_prediction.router):
        app.include_router(r)

    @app.exception_handler(404)
    async def not_found(request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "not found", "kind": "not_found"}, status_code=404)
        index = UI_DIR / "index.html"
        if not index.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    if UI_DIR.exists():
        app.mount("/", UIFiles(directory=UI_DIR, html=True), name="ui")
    return app
