"""The application: settings, the token verifier, the repository, the routes and the error shape ``{"error", "code"}``."""
from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .auth import Verifier
from .errors import ApiError
from .repository import InMemoryRepository
from .routes import router
from .settings import Settings


def create_app(settings: Settings | None = None, *, repository: InMemoryRepository | None = None, verifier: Verifier | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    app = FastAPI(title="Titanium laboratories", version=__version__, docs_url=None, redoc_url=None)
    app.state.settings = settings
    if verifier is None and (settings.jwks_url or settings.jwks_json):
        verifier = Verifier(jwks_url=settings.jwks_url, jwks=json.loads(settings.jwks_json) if settings.jwks_json else None,
                            issuer=settings.issuer, audience=settings.audience)
    app.state.verifier = verifier
    app.state.memory = repository or (InMemoryRepository() if settings.repository == "memory" else None)
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return JSONResponse({"error": str(exc), "code": exc.code}, status_code=exc.status, headers={"Cache-Control": "no-store"})

    @app.exception_handler(RequestValidationError)
    async def body_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        return JSONResponse({"error": f"{where}: {first.get('msg', 'invalid')}".strip(": "), "code": "invalid"}, status_code=422)

    return app
