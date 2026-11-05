"""The desktop shell's own tests (electron REQ-080: `desktop/test`, run by `node --test`): the core's ready line and restart policy, the
window's navigation and link guards, the workshop picker and the update check. Node is part of the development environment (the UI
tests use it too), so a missing node is a failure, not a skip."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_shell_tests_pass_under_node():
    node = shutil.which("node")
    assert node, "node is needed for the desktop shell's tests (desktop/test): install Node.js 20 or later"
    run = subprocess.run([node, "--test", *sorted(str(p) for p in (ROOT / "desktop" / "test").glob("*.test.js"))], cwd=ROOT / "desktop", capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "# fail 0" in run.stdout, run.stdout


def test_the_shell_declares_only_the_approved_dependencies_and_isolates_its_windows():
    package = (ROOT / "desktop" / "package.json").read_text(encoding="utf-8")
    assert '"dependencies"' not in package                      # the shell needs nothing at run time but Electron itself
    for name in ("electron", "@electron-forge/cli", "@electron-forge/maker-squirrel", "@electron-forge/maker-zip"):
        assert f'"{name}"' in package
    assert "electron-updater" not in package
    main = (ROOT / "desktop" / "src" / "main.js").read_text(encoding="utf-8")
    assert "contextIsolation: true" in main and "sandbox: true" in main and "nodeIntegration: false" in main
    assert "requestSingleInstanceLock" in main and "setWindowOpenHandler" in main and "will-navigate" in main
    assert "Content-Security-Policy" in main
    preload = (ROOT / "desktop" / "src" / "preload.js").read_text(encoding="utf-8")
    assert "contextBridge.exposeInMainWorld" in preload and "require('node:fs')" not in preload


def test_the_ui_page_has_no_inline_script_because_the_shells_policy_forbids_them():
    """desktop/src/guards.js gives the core's pages a Content-Security-Policy whose script-src has no 'unsafe-inline'; an inline
    <script> (the start of the application once was one) is blocked there and leaves the shell's window empty. Every script of
    index.html is a file of its own, and no element carries an inline handler."""
    import re
    html = (Path(__file__).parent.parent / "src" / "titanium_platform" / "ui" / "index.html").read_text(encoding="utf-8")
    inline = [m for m in re.finditer(r"<script\b([^>]*)>", html) if "src=" not in m.group(1)]
    assert inline == [], [m.group(0) for m in inline]
    assert not re.search(r"\son[a-z]+=", html) and "javascript:" not in html
    assert '<script src="/boot.js"></script>' in html and html.index("/boot.js") > html.rindex("/screens/")
    guards = (Path(__file__).parent.parent / "desktop" / "src" / "guards.js").read_text(encoding="utf-8")
    assert "script-src 'self'" in guards and "script-src 'self' ${origin} 'unsafe-inline'" not in guards


def test_the_shell_keeps_a_log_outside_the_workshop_and_checks_that_the_window_drew():
    """A window that showed only the skip link left no trace (0.37.0). The shell writes `shell.log` in the operating system's log
    folder, not in the workshop (backups and diagnostics scan that), and after each load of the main window asks whether `#app` has
    children, reloading once when it has none. The two modules hold no Electron, so `node --test` covers them."""
    src = ROOT / "desktop" / "src"
    main = (src / "main.js").read_text(encoding="utf-8")
    assert "app.getPath('logs')" in main and "'shell.log'" in main
    assert "new WindowHealth" in main and "watchWindow(" in main and "reloadIgnoringCache" in main
    assert "addSecret" in main                              # the launch secret is kept out of the log
    for name in ("shell-log.js", "window-health.js"):
        text = (src / name).read_text(encoding="utf-8")
        assert "require('electron')" not in text, name
    assert "/session/" in (src / "shell-log.js").read_text(encoding="utf-8")        # the session address is redacted
