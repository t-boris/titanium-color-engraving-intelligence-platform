"""The cloud validates releases with the very reader the desktop uses (DEC-058): the copies under cloud/ are byte-equal to the originals
(``python cloud/tools/sync_shared.py`` refreshes them), and the copy works on its own without the desktop package."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud"))

from tools import sync_shared  # noqa: E402  (cloud/tools)


def test_the_shared_reader_and_schema_are_byte_equal_copies():
    assert sync_shared.drifted() == [], "run python cloud/tools/sync_shared.py"


def test_the_cloud_package_imports_without_the_desktop_package():
    code = ("import sys; sys.modules['titanium_platform'] = None\n"
            "from titanium_cloud import _lab_format as lf, app\n"
            "assert lf.schema()['$defs']['manifest']; print('ok')")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "cloud", capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr
