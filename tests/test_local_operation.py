"""The application works without internet access (REQ-043 AC1): the browser UI loads nothing from the network, the server
opens no outbound connection in its core workflows, and the only adapters that may reach a network service (the optional
AI researcher and the designer's explanation, REQ-006) are off without an OpenAI key.

The scans are static; every exception is named in an allowlist with the reason it is not a network resource or request."""
import ast
import re
import socket
from pathlib import Path

import pytest

from titanium_platform import colormap, experiments, research
from titanium_platform import ingest as ig
from titanium_platform.api.app import UI_DIR

PACKAGE = Path(research.__file__).resolve().parent
# an absolute URL anywhere, or a protocol-relative one where a URL starts ("//cdn.example.org/x.js", url(//...))
URL = re.compile(r"""https?://[^\s"'`)<>]+|(?<=["'(`])//[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+[^\s"'`)<>]*""")
# URLs that may appear in the UI files, and why they are not loaded from the network.
UI_URLS = {"http://www.w3.org/2000/svg": "the SVG namespace: a name passed to createElementNS and xmlns, never fetched"}
# URLs that may appear in the server code, and why no request is made to them.
SERVER_URLS = {"http://www.w3.org/2000/svg": "the SVG namespace written into generated SVG files",
               "http://{args.host}:{args.port}": "the local address the launcher prints for the operator's browser",
               "https://docs.lightburnsoftware.com/latest/Reference/CutSettingsEditor/ImageMode/": "a source cited in the docstring of dots.py",
               "https://forum.lightburnsoftware.com/t/halftone-questions-angle/16438": "a source cited in the docstring of dots.py"}
# Modules that can open a network connection; ``urllib.parse`` only builds strings and is not among them.
NETWORK_MODULES = ("socket", "ssl", "http.client", "urllib.request", "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
                   "websocket", "websockets", "openai", "anthropic")
# (file, module) pairs allowed to import one, and why.
NETWORK_IMPORTS = {("research.py", "openai"): "the optional AI researcher and proposal explanation; built only with OPENAI_API_KEY"}


def test_the_ui_loads_no_script_style_font_or_data_from_the_network():
    files = [p for p in UI_DIR.rglob("*") if p.suffix in (".html", ".js", ".css")]
    assert len(files) > 40
    found = {}
    for path in files:
        for url in URL.findall(path.read_text(encoding="utf-8")):
            found.setdefault(url, []).append(path.name)
    unexpected = {url: names for url, names in found.items() if url not in UI_URLS}
    assert unexpected == {}, unexpected
    assert set(UI_URLS) <= set(found)                                        # the scan sees them: the allowlist is not stale
    page = (UI_DIR / "index.html").read_text(encoding="utf-8")
    for target in re.findall(r'(?:src|href)="([^"]+)"', page):         # every script and style of the page is served locally
        assert target.startswith(("/", "#")) and not target.startswith("//"), target
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "@import" not in text, path.name                              # no stylesheet or font pulled in from elsewhere
        for call in re.findall(r"fetch\(\s*([`'\"][^`'\"]*)", text):          # the API of this process only
            assert call[1:].startswith("/api"), (path.name, call)


def _imports(tree: ast.AST) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append(node.module)
    return out


def test_the_server_code_opens_no_network_connection_except_the_optional_openai_adapters():
    sources = sorted(PACKAGE.rglob("*.py"))
    assert len(sources) > 40
    imports, urls = {}, {}
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for module in _imports(ast.parse(text)):
            for network in NETWORK_MODULES:
                if module == network or module.startswith(network + "."):
                    imports[(path.name, network)] = str(path.relative_to(PACKAGE))
        for url in URL.findall(text):
            urls.setdefault(url, []).append(path.name)
    assert {key for key in imports if key not in NETWORK_IMPORTS} == set(), imports
    assert {url: names for url, names in urls.items() if url not in SERVER_URLS} == {}
    assert set(NETWORK_IMPORTS) <= set(imports) and set(SERVER_URLS) <= set(urls)      # the scan sees them: the allowlist is not stale


def test_without_a_key_the_openai_adapters_are_off(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)                                                # no .env.local in the working directory ...
    monkeypatch.setattr(research, "__file__", str(tmp_path / "src" / "titanium_platform" / "research.py"))   # ... nor at the root
    assert research.ai_available() is False
    assert research.openai_client() is None and research.proposal_explainer() is None


@pytest.fixture
def offline(monkeypatch):
    """Any attempt to reach another host fails the test: no name lookup, no outbound connection."""
    def refuse(*args, **kwargs):
        raise AssertionError(f"a network request was made: {args[:2]}")
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def test_a_plate_is_made_photographed_checked_accepted_and_found_on_the_colour_map_without_network(store, offline):
    from test_ingest import CELLS, make_pair, make_world
    world = make_world(store)
    pid = make_pair(world)
    report = ig.check_pair(store, pid)
    assert report["problems"] == [] and report["alignment"]["valid"]
    ig.review_masks(store, pid)
    assert ig.accept_pair(store, pid)
    assert {p["layer_name"] for p in colormap.collect(store)["points"]} >= set(CELLS)
    assert [e["status"] for e in experiments.list_experiments(store)] == ["accepted"]
