"""The fonts of the inscriptions (feature inscriptions-in-works, REQ-001, DEC-001): the catalogue of this computer's fonts (the test fonts of
``font_kit``, see ``conftest``), the operator's own font files and Google Fonts (here a fake Google: its metadata, its repository's tree
and its files are served by the test), with the routes the font window uses."""
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from fontTools.ttLib import TTFont

from font_kit import make_font
from titanium_platform import fonts
from titanium_platform.api.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as c:
        yield c


@pytest.fixture
def google(tmp_path, monkeypatch):
    """A fake Google Fonts of three families: a Cyrillic sans serif with two files, a Latin handwriting and a Hebrew serif."""
    files = {"ofl/alpha/Alpha-Regular.ttf": make_font(tmp_path / "g1.ttf", family="Alpha", style="Regular").read_bytes(),
             "ofl/alpha/Alpha-Bold.ttf": make_font(tmp_path / "g2.ttf", family="Alpha", style="Bold", weight=700).read_bytes(),
             "ofl/betahand/BetaHand-Regular.ttf": make_font(tmp_path / "g3.ttf", family="Beta Hand").read_bytes(),
             "apache/gamma/Gamma.ttf": make_font(tmp_path / "g4.ttf", family="Gamma").read_bytes()}
    metadata = {"familyMetadataList": [
        {"family": "Alpha", "category": "Sans Serif", "subsets": ["menu", "latin", "cyrillic"], "popularity": 3},
        {"family": "Beta Hand", "category": "Handwriting", "subsets": ["latin"], "popularity": 9},
        {"family": "Gamma", "category": "Serif", "subsets": ["latin", "hebrew"], "popularity": 1},
        {"family": "No Files", "category": "Display", "subsets": ["latin"], "popularity": 5}]}
    tree = {"tree": [{"path": p, "type": "blob", "size": len(b)} for p, b in files.items()] + [{"path": "ofl/alpha", "type": "tree"}]}
    asked = []

    def get(url):
        asked.append(url)
        if url == fonts.GOOGLE_METADATA:
            return b")]}'\n" + json.dumps(metadata).encode()
        if url == fonts.GOOGLE_TREE:
            return json.dumps(tree).encode()
        return files[url.removeprefix(fonts.GOOGLE_RAW)]
    monkeypatch.setattr(fonts, "_get", get)
    return asked


def test_the_catalogue_lists_this_computers_fonts_by_family(client):
    listed = client.get("/api/fonts").json()
    sans = next(f for f in listed["families"] if f["family"] == "Test Sans")
    assert sans["source"] == "mac" and sans["scripts"] == ["latin", "cyrillic", "hebrew"] and sans["kind"] == "sans"
    assert [f["style"] for f in sans["faces"]] == ["Regular", "Bold"]                         # the lightest first
    assert sans["regular"] == sans["faces"][0]["id"]
    assert listed["google"]["listed"] is False and "cyrillic" in listed["scripts"]


def test_hidden_system_fonts_fonts_without_outlines_and_unreadable_files_are_left_out(tmp_path, monkeypatch):
    folder = tmp_path / "mac"
    make_font(folder / "Hidden.ttf", family=".Hidden UI")              # macOS hides its system fonts by a name with a dot
    make_font(folder / "LastResort.ttf", family="LastResort")          # the font macOS draws a missing letter with
    bitmap = TTFont(str(make_font(tmp_path / "outlined.ttf", family="Bitmap Only")))
    del bitmap["glyf"], bitmap["loca"]                                  # no outlines: nothing to engrave
    bitmap.save(str(folder / "Bitmap.ttf"))
    (folder / "Broken.ttf").write_bytes(b"not a font")
    make_font(folder / "Shown.ttf", family="Shown Sans")
    monkeypatch.setattr(fonts, "MAC_DIRS", (str(folder),))
    with TestClient(create_app(tmp_path / "data")) as c:
        listed = c.get("/api/fonts").json()["families"]
    assert [f["family"] for f in listed if f["source"] == "mac"] == ["Shown Sans"]


def test_a_second_listing_reads_only_new_or_changed_font_files(tmp_path, monkeypatch):
    data = tmp_path / "data"
    folder = fonts.own_dir(data)
    make_font(folder / "A.ttf", family="Alpha One")
    changed = make_font(folder / "B.ttf", family="Beta Two")
    read, real = [], fonts._faces_of
    monkeypatch.setattr(fonts, "_faces_of", lambda source, root, path: read.append(path.name) or real(source, root, path))

    def listing():
        fonts._forget(data)                                             # the listing kept in memory for a few seconds is let go
        return {f["family"]: f["style"] for f in fonts.faces(data).values() if f["source"] == "own"}

    assert listing() == {"Alpha One": "Regular", "Beta Two": "Regular"} and {"A.ttf", "B.ttf"} <= set(read)
    read.clear()
    assert listing() == {"Alpha One": "Regular", "Beta Two": "Regular"} and read == []      # from the catalogue on disk, no file read
    make_font(folder / "C.ttf", family="Gamma Three")
    make_font(changed, family="Beta Two", style="Bold", weight=700)
    stat = changed.stat()
    os.utime(changed, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))               # changed: its stamp is not the one kept
    assert listing() == {"Alpha One": "Regular", "Beta Two": "Bold", "Gamma Three": "Regular"} and sorted(read) == ["B.ttf", "C.ttf"]


def test_a_family_opens_on_its_regular_face(client, tmp_path):
    folder = fonts.own_dir(tmp_path / "data")
    make_font(folder / "Thin.ttf", family="Wide Range", style="Thin", weight=100)
    make_font(folder / "Regular.ttf", family="Wide Range", style="Regular", weight=400)
    make_font(folder / "Italic.ttf", family="Wide Range", style="Italic", weight=400)
    wide = next(f for f in client.get("/api/fonts").json()["families"] if f["family"] == "Wide Range")
    assert [f["style"] for f in wide["faces"]] == ["Thin", "Regular", "Italic"]               # the lightest upright first, as the list shows them
    assert wide["regular"] == wide["faces"][1]["id"]                                          # but the window opens it on its regular face


def test_a_preview_draws_the_text_in_the_font(client):
    face = client.get("/api/fonts").json()["families"][0]["faces"][0]["id"]
    answer = client.get("/api/fonts/preview.svg", params={"face": face, "text": "HП"})
    assert answer.status_code == 200 and answer.headers["content-type"].startswith("image/svg+xml") and "<path" in answer.text
    assert client.get("/api/fonts/preview.svg", params={"face": "nope"}).status_code == 404


def test_the_operators_own_font_is_added_and_removed(client, tmp_path):
    data = make_font(tmp_path / "mine.ttf", family="My Own").read_bytes()
    added = client.post("/api/fonts/own", files={"font": ("My Font.ttf", data, "font/ttf")})
    assert added.status_code == 201 and added.json()["faces"][0]["family"] == "My Own"
    family = next(f for f in client.get("/api/fonts").json()["families"] if f["family"] == "My Own")
    assert family["source"] == "own"
    refused = client.post("/api/fonts/own", files={"font": ("notes.txt", b"hello", "text/plain")})
    assert refused.status_code == 422 and refused.json()["error"] == "a font file must be TTF, OTF or TTC"
    broken = client.post("/api/fonts/own", files={"font": ("broken.ttf", b"not a font at all", "font/ttf")})
    assert broken.json()["error"] == "this file is not a font that can be engraved: it has no outlines or cannot be read"
    mac = next(f for f in client.get("/api/fonts").json()["families"] if f["family"] == "Test Sans")["faces"][0]["id"]
    assert client.delete(f"/api/fonts/own/{mac}").json()["error"] == "only a font you added can be removed here"
    assert client.delete(f"/api/fonts/own/{family['faces'][0]['id']}").status_code == 200
    assert not any(f["family"] == "My Own" for f in client.get("/api/fonts").json()["families"])


def test_google_families_are_listed_and_downloaded_when_chosen(client, google):
    assert client.post("/api/fonts/google/index").json()["families"] == 3                    # a family without files is left out
    listed = client.get("/api/fonts").json()
    alpha = next(f for f in listed["families"] if f["family"] == "Alpha")
    assert alpha["downloaded"] is False and alpha["scripts"] == ["latin", "cyrillic"] and alpha["kind"] == "sans" and alpha["faces"] == []
    got = client.post("/api/fonts/google/family", json={"family": "Alpha"}).json()["faces"]
    assert sorted(f["style"] for f in got) == ["Bold", "Regular"]
    alpha = next(f for f in client.get("/api/fonts").json()["families"] if f["family"] == "Alpha")
    assert alpha["downloaded"] is True and alpha["source"] == "google" and len(alpha["faces"]) == 2
    before = len(google)
    client.post("/api/fonts/google/family", json={"family": "Alpha"})
    assert len(google) == before                                                              # here already: nothing is fetched again
    assert client.post("/api/fonts/google/family", json={"family": "Zeta"}).json()["error"] == "Google Fonts has no family 'Zeta'"


def test_many_google_families_are_downloaded_in_the_background(client, google):
    status = client.post("/api/fonts/google/download", json={"script": "hebrew"}).json()
    assert status["total"] == 1
    for _ in range(100):
        status = client.get("/api/fonts/google/status").json()
        if not status["running"]:
            break
        time.sleep(0.05)
    assert status["done"] == 1 and status["failed"] == []
    assert next(f for f in client.get("/api/fonts").json()["families"] if f["family"] == "Gamma")["downloaded"] is True
    refused = client.post("/api/fonts/google/download", json={"script": "klingon"})
    assert refused.json()["error"] == "unknown script 'klingon'"
