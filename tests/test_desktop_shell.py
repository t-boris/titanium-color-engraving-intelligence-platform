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
