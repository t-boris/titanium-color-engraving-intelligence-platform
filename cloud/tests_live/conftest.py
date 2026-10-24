"""The live tests of the cloud API run the main suite's contract tests (``tests/test_cloud_api.py``) against the real database, and check
the row-level security that the in-memory repository cannot show. They are not collected by the main suite (``testpaths = ["tests"]``);
run them by hand with ``.venv/bin/python -m pytest -q cloud/tests_live``. They need ``APP_API_DATABASE_URL`` (the API's role) and
``DATABASE_URL`` (the owner, for the cleanup) in the environment or in ``~/.titanium-cloud.env``; without them every test is skipped,
which is why they live outside the main suite, where no test may be skipped."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT / "tests", ROOT / "cloud", ROOT / "src"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from font_kit import make_font  # noqa: E402  (tests/)
from titanium_platform import fonts  # noqa: E402

os.environ.setdefault("TCE_ALLOWED_HOSTS", "testserver")


def load_env(path: Path) -> None:
    """KEY=VALUE lines of an environment file outside the repository into os.environ (values are never printed); a value may be quoted
    as a shell would quote it, since the same file is sourced by the shell."""
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not line.lstrip().startswith("#"):
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                os.environ.setdefault(key.strip(), value)


load_env(Path.home() / ".titanium-cloud.env")

APP_URL = os.environ.get("APP_API_DATABASE_URL")
OWNER_URL = os.environ.get("DATABASE_URL")


def pytest_collection_modifyitems(config, items):
    if APP_URL and OWNER_URL:
        return
    skip = pytest.mark.skip(reason="APP_API_DATABASE_URL and DATABASE_URL are not set: no database to test against")
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def system_fonts(tmp_path_factory):
    """As in the main suite: the fonts «of this computer» are two families made by ``font_kit``."""
    folder = tmp_path_factory.mktemp("system-fonts")
    make_font(folder / "TestSans.ttf")
    make_font(folder / "TestSans-Bold.ttf", style="Bold", weight=700)
    make_font(folder / "Other.ttf", family="Other Serif")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fonts, "MAC_DIRS", (str(folder),))
        yield folder
