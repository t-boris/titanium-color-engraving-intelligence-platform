"""The application factory: JSON API under /api and the browser UI as static files from the same process."""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, capability_results, cloud_session, findings, lab_import, lan, outbound, research, work_errors
from ..db import open_store
from . import (routes_cloud, routes_devices, routes_findings, routes_fonts, routes_labs, routes_lan, routes_lenses, routes_palette,
               routes_photo_knowledge, routes_photo_work, routes_plans, routes_prediction, routes_recheck, routes_research, routes_setup, routes_vector,
               routes_work, routes_workshop)
from . import security
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """The periodic analysis (REQ-022) runs in one thread of the app: it starts when the operator has set an interval (never
    with the default of 0) and stops with the app."""
    scheduler = findings.Scheduler(app.state.store)
    app.state.analysis_scheduler = scheduler
    scheduler.start_if_enabled()
    app.state.lan.start_if_enabled()               # the LAN server for tablets, only when the operator switched it on (electron REQ-082)
    counting = threading.Thread(target=_count_works, args=(app.state.store,), name="work-attention", daemon=True)
    counting.start()
    try:
        yield
    finally:
        app.state.lan.stop()
        scheduler.stop()
        counting.join(30.0)


def _count_works(store) -> None:
    """Once at start: the works exported before the counts of the work on the errors (DEC-090) were kept get theirs, for the list of works."""
    try:
        work_errors.refresh_missing(store)
    except Exception:                       # a count that fails is made again at the next start; it never stops the app
        pass


def create_app(data_dir: str | Path) -> FastAPI:
    app = FastAPI(title="Laser Workshop", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.store = open_store(data_dir)          # a database the migration refuses ends the start with exit code 2
    capability_results.backfill_findings(app.state.store)
    lab_import.reconcile(app.state.store)          # what an interrupted connection of a laboratory release left (electron REQ-084)
    install_error_handlers(app)
    security.install(app)                           # Host, Origin and body checks; the desktop session cookie (electron DEC-046)
    app.state.guard.callback_check = cloud_session.pending   # the return from the cloud's sign-in page, while a sign-in waits (REQ-086)
    app.state.lan = lan.Lan(app, app.state.store)   # the local network for tablets: certificates, pairing, the TLS server (electron REQ-082)
    outbound.apply(app.state.store)                 # the operator's switches of what may be reached outside this computer

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
              routes_vector.router, routes_palette.router, routes_research.router, routes_prediction.router, routes_photo_work.router,
              routes_photo_knowledge.router,
              routes_findings.router, routes_recheck.router, routes_fonts.router, routes_labs.router, routes_cloud.router, routes_workshop.router, routes_lan.router,
              routes_lan.settings_router, routes_lan.pages):
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
