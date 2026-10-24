"""Command line entry point: one local process, local data, no login (REQ-011).

``titanium-platform [--data-dir DIR] [--host H] [--port P]`` runs the application; ``titanium-platform warm-cache
[--data-dir DIR]`` draws the pictures the experiment screens show by default into the render cache (BUG-001).

Under the desktop shell (feature electron, DEC-046) the same package runs as a hidden child: ``--desktop --port 0 --parent-pid P``
binds a free loopback port, prints one JSON line ``{"ready": true, "port": N, "pid": P}`` to stdout once it serves, takes the session
secret from ``TCE_SESSION_SECRET`` (``api.security``) and stops when the shell's process ``P`` is gone. ``--smoke`` starts the core
that way on a temporary workshop, opens a session and asks ``/api/health``, and exits 0 when it answers: the packaged core is checked
with it on every build.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

from . import __version__
from .api import security

WARM_CACHE = "warm-cache"
LOOPBACK = "127.0.0.1"
PARENT_POLL_S = 1.0
READY_TIMEOUT_S = 120.0


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
    p.add_argument("--data-dir", type=Path, default=None, help="where the database and uploaded files live")
    p.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to reach the UI from a tablet on the local network")
    p.add_argument("--port", type=int, default=8765, help="0: a free port, told on stdout as a JSON line when the core serves")
    p.add_argument("--desktop", action="store_true", help="run under the desktop shell: loopback only, session cookie from TCE_SESSION_SECRET")
    p.add_argument("--parent-pid", type=int, default=None, help="stop when this process is gone (the desktop shell)")
    p.add_argument("--smoke", action="store_true", help="start on a temporary workshop, check /api/health through a session and exit")
    args = p.parse_args(argv)
    if args.smoke:
        return smoke(args.data_dir)
    if args.desktop:
        os.environ["TCE_DESKTOP"] = "1"
        if not os.environ.get(security.SECRET_ENV):
            print("titanium-platform: --desktop needs the session secret in TCE_SESSION_SECRET", file=sys.stderr)
            return 2
        args.host = "127.0.0.1"
    return serve(args.data_dir or default_data_dir(), args.host, args.port, parent_pid=args.parent_pid, announce=args.port == 0 or args.desktop)


def serve(data_dir: Path, host: str, port: int, *, parent_pid: int | None = None, announce: bool = False, ready=None) -> int:
    """Serve the application; with ``port`` 0 on a free port. ``ready(port)`` is called, and the JSON ready line printed when ``announce``,
    once the server accepts connections."""
    from .api.app import create_app
    app = create_app(data_dir)
    sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        print(f"titanium-platform: cannot listen on {host}:{port}: {exc}", file=sys.stderr)
        return 3
    sock.listen(128)
    bound = sock.getsockname()[1]
    if not announce:
        print(f"titanium-platform {__version__}: http://{host}:{bound}  (data: {data_dir})", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=bound, log_level="warning"))
    if parent_pid is not None:
        threading.Thread(target=_watch_parent, args=(parent_pid, server), name="parent-watchdog", daemon=True).start()

    def told() -> None:
        deadline = time.monotonic() + READY_TIMEOUT_S
        while not server.started and not server.should_exit and time.monotonic() < deadline:
            time.sleep(0.02)
        if server.started:
            if announce:
                print(json.dumps({"ready": True, "port": bound, "pid": os.getpid(), "version": __version__}), flush=True)
            if ready is not None:
                ready(bound)
    threading.Thread(target=told, name="ready-line", daemon=True).start()
    server.run(sockets=[sock])
    return 0


def _parent_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        SYNCHRONIZE, WAIT_TIMEOUT = 0x00100000, 0x00000102
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _watch_parent(pid: int, server: uvicorn.Server) -> None:
    """Stop serving when the shell's process is gone, so that no core outlives its window (REQ-080: ports and locks are released)."""
    while True:
        time.sleep(PARENT_POLL_S)
        if not _parent_alive(pid) or (os.name != "nt" and os.getppid() == 1 and pid != 1):
            server.should_exit = True
            time.sleep(5.0)
            os._exit(0)


def smoke(data_dir: Path | None) -> int:
    """Start the core as the shell does, on a temporary workshop unless ``data_dir`` is given, open the session and ask ``/api/health``."""
    import http.cookiejar
    import urllib.request
    secret = secrets.token_urlsafe(24)
    os.environ[security.SECRET_ENV] = secret
    os.environ["TCE_DESKTOP"] = "1"
    folder = Path(data_dir) if data_dir else Path(tempfile.mkdtemp(prefix="titanium-smoke-"))
    outcome: dict = {}
    port_known = threading.Event()

    def ready(port: int) -> None:
        outcome["port"] = port
        port_known.set()

    def run() -> None:
        try:
            outcome["exit"] = serve(folder, "127.0.0.1", 0, ready=ready)
        except BaseException as exc:              # reported below as the smoke's failure
            outcome["error"] = f"{type(exc).__name__}: {exc}"
            port_known.set()
    threading.Thread(target=run, name="smoke-core", daemon=True).start()
    if not port_known.wait(READY_TIMEOUT_S) or "port" not in outcome:
        print(f"smoke: the core did not start: {outcome.get('error', 'no ready line in time')}", file=sys.stderr)
        return 1
    base = f"http://{LOOPBACK}:{outcome['port']}"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        refused = urllib.request.urlopen(urllib.request.Request(base + "/api/health"), timeout=30)   # noqa: S310 - loopback
        print(f"smoke: /api/health answered {refused.status} without a session", file=sys.stderr)
        return 1
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            print(f"smoke: /api/health answered {exc.code} without a session", file=sys.stderr)
            return 1
    try:
        with opener.open(base + security.SESSION_PATH + secret, timeout=30) as page:        # noqa: S310 - loopback
            if page.status != 200 or b"<html" not in page.read(4096).lower():
                print("smoke: the session address did not open the application", file=sys.stderr)
                return 1
        with opener.open(base + "/api/health", timeout=30) as answer:                      # noqa: S310 - loopback
            health = json.loads(answer.read())
    except Exception as exc:
        print(f"smoke: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if health.get("status") != "ok":
        print(f"smoke: /api/health answered {health}", file=sys.stderr)
        return 1
    print(json.dumps({"smoke": "ok", "version": __version__, "port": outcome["port"], "data_dir": str(folder)}), flush=True)
    return 0


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
