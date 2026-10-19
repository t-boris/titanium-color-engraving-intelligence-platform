"""Command line entry point: one local process, local data, no login (REQ-011).

``titanium-platform [--data-dir DIR] [--host H] [--port P]`` runs the application; ``titanium-platform warm-cache
[--data-dir DIR]`` draws the pictures the experiment screens show by default into the render cache (BUG-001).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import uvicorn

from . import __version__
from .api.app import create_app

WARM_CACHE = "warm-cache"


def default_data_dir() -> Path:
    return Path(os.environ.get("TITANIUM_DATA_DIR", Path.home() / ".titanium-platform"))


def main(argv: list[str] | None = None) -> int | None:
    """Run the application, or the command named first (its exit code is returned)."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == [WARM_CACHE]:
        return warm_cache(argv[1:])
    p = argparse.ArgumentParser(prog="titanium-platform", description="Local titanium color engraving platform",
                                epilog=f"command: titanium-platform {WARM_CACHE} --data-dir DIR draws the pictures the experiment "
                                       "screens show by default into the render cache")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--data-dir", type=Path, default=default_data_dir(), help="where the database and uploaded files live")
    p.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to reach the UI from a tablet on the local network")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)
    app = create_app(args.data_dir)
    print(f"titanium-platform {__version__}: http://{args.host}:{args.port}  (data: {args.data_dir})", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def warm_cache(argv: list[str]) -> int:
    """Draw, for every check in active use, the pictures the experiment screens ask for by default (the list thumbnail and
    the experiment page's photograph) into the render cache, so that the screens open at once. The database is only read;
    a picture already cached is not drawn again. A check whose picture cannot be drawn is reported and skipped; the exit
    code is then 1."""
    from . import experiments, render_cache
    from .db import open_store

    p = argparse.ArgumentParser(prog=f"titanium-platform {WARM_CACHE}",
                                description="Draw the pictures the experiment screens show by default into the render cache")
    p.add_argument("--data-dir", type=Path, default=default_data_dir(), help="where the database and uploaded files live")
    args = p.parse_args(argv)
    store = open_store(args.data_dir, f"titanium-platform {WARM_CACHE}")
    drawn = kept = failed = 0
    started = time.perf_counter()
    try:
        for row in store.query("SELECT id FROM pair WHERE status!='Deleted' ORDER BY id"):
            try:
                for picture in experiments.screen_pictures(store, row["id"]):
                    if picture.cached():
                        kept += 1
                        continue
                    picture.png()
                    drawn += 1
            except Exception as exc:        # one unreadable photograph must not stop the others
                failed += 1
                print(f"check {row['id']}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    finally:
        store.close()
    print(f"{drawn} pictures drawn, {kept} already cached, {failed} checks failed in {time.perf_counter() - started:.1f} s "
          f"(cache: {render_cache.root(store)})", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
