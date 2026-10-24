import os

import pytest

from font_kit import make_font
from titanium_platform import fonts
from titanium_platform.db import Store


os.environ.setdefault("TCE_ALLOWED_HOSTS", "testserver")        # the test client's host name passes the local API guard (api.security)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    yield s
    s.close()


@pytest.fixture(scope="session", autouse=True)
def system_fonts(tmp_path_factory):
    """The fonts «of this computer» the tests see: two families made by ``font_kit`` (never the fonts installed here), so the inscriptions
    are tested the same everywhere."""
    folder = tmp_path_factory.mktemp("system-fonts")
    make_font(folder / "TestSans.ttf")
    make_font(folder / "TestSans-Bold.ttf", style="Bold", weight=700)
    make_font(folder / "Other.ttf", family="Other Serif")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fonts, "MAC_DIRS", (str(folder),))
        yield folder
