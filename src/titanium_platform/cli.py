"""Command line entry point: one local process, local data, no login (REQ-011)."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from . import __version__
from .api.app import create_app


def default_data_dir() -> Path:
    return Path(os.environ.get("TITANIUM_DATA_DIR", Path.home() / ".titanium-platform"))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="titanium-platform", description="Local titanium color engraving platform")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--data-dir", type=Path, default=default_data_dir(), help="where the database and uploaded files live")
    p.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to reach the UI from a tablet on the local network")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)
    app = create_app(args.data_dir)
    print(f"titanium-platform {__version__}: http://{args.host}:{args.port}  (data: {args.data_dir})", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
