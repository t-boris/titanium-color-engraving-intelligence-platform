"""BUG-001: the pictures drawn from a photograph are cached on disk by a key of all their inputs, revalidated by ETag, and can
be asked for small."""
import os

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import synth
from test_ingest import make_pair, make_world, png
from titanium_platform import ingest as ig
from titanium_platform import photo as ph
from titanium_platform import render_cache as rc
from titanium_platform import setup as su
from titanium_platform.api.app import create_app


@pytest.fixture
def world(store):
    return make_world(store)


@pytest.fixture
def decodes(monkeypatch):
    """Count the decodes of a photograph: a picture served from the cache decodes nothing."""
    calls = []
    real = ph.decode_image
    monkeypatch.setattr(ph, "decode_image", lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    return calls


def checked_pair(world) -> int:
    pid = make_pair(world)
    ig.check_pair(world["store"], pid)
    return pid


def side(data: bytes) -> int:
    return max(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED).shape[:2])


def test_a_cached_picture_is_the_same_bytes_and_is_not_drawn_again(world, decodes):
    s = world["store"]
    pid = checked_pair(world)
    decodes.clear()
    overlay = ig.overlay_png(s, pid, corrected=True, visibility="lifted")
    per_overlay = len(decodes)                                      # the 8-bit decode and, for the correction, the linear one
    photo = ig.photo_preview_png(s, pid, visibility="lifted")
    drawn = len(decodes)
    assert per_overlay >= 1 and drawn == per_overlay + 1
    assert ig.overlay_png(s, pid, corrected=True, visibility="lifted") == overlay
    assert ig.photo_preview_png(s, pid, visibility="lifted") == photo
    assert len(decodes) == drawn                                    # both answered from the cache
    picture = ig.overlay_picture(s, pid, corrected=True, visibility="lifted")
    stored = rc.root(s) / str(pid) / f"{picture.key}.png"
    assert stored.read_bytes() == overlay and picture.cached()
    stored.write_bytes(overlay[:len(overlay) // 2])                 # a damaged file is drawn again, never served
    assert ig.overlay_png(s, pid, corrected=True, visibility="lifted") == overlay and len(decodes) == drawn + per_overlay
    stored.unlink()                                                 # so is a missing one
    assert ig.overlay_png(s, pid, corrected=True, visibility="lifted") == overlay and len(decodes) == drawn + 2 * per_overlay
    assert not [p for p in stored.parent.iterdir() if not p.name.endswith(".png")]   # no temporary file is left behind


def test_the_key_changes_with_every_input_of_the_picture(world):
    s = world["store"]
    pid = checked_pair(world)
    layer = next(rep["index"] for rep in ig.get_pair(s, pid)["check"]["layers"] if rep["measured_lab"] is not None)
    views = [{}, {"corrected": False}, {"layer_index": layer}, {"visibility": "lifted"}, {"full": True}, {"size": 480},
             {"transparent": True}]
    keys = [ig.overlay_picture(s, pid, **v).key for v in views]
    assert len(set(keys)) == len(views) and ig.overlay_picture(s, pid).key == keys[0]        # same inputs, same key
    photos = [{}, {"corrected": True}, {"visibility": "lifted"}, {"full": True}, {"size": 480}]
    photo_keys = [ig.photo_preview_picture(s, pid, **v).key for v in photos]
    assert len(set(photo_keys)) == len(photos) and not set(photo_keys) & set(keys)

    def now():
        return ig.overlay_picture(s, pid).key, ig.photo_preview_picture(s, pid).key, ig.photo_preview_picture(s, pid, corrected=True).key

    before = now()
    ig.check_pair(s, pid, translation_fraction=[.002, -.002])      # the alignment moves: only the overlay changes
    moved = now()
    assert moved[0] != before[0] and moved[1:] == before[1:]
    reference = su.get_capture_setup(s, world["stand"]["id"])["chart_reference"]["patches_lab"]
    su.save_chart_reference(s, world["stand"]["id"], [[lab[0] * .98, lab[1], lab[2]] for lab in reference], "D65", "2°", "measured")
    charted = now()                                                 # the chart reference: only corrected pictures change
    assert charted[0] != moved[0] and charted[2] != moved[2] and charted[1] == moved[1]
    assert ig.overlay_picture(s, pid, transparent=True).key == ig.overlay_picture(s, pid, transparent=True).key
    path = ig.get_pair(s, pid)["photo_path"]
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    touched = now()                                                 # the photograph file: every picture changes
    assert all(a != b for a, b in zip(touched, charted))
    with open(path, "ab") as photo:
        photo.write(b"\0")
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    grown = now()                                                   # same modification time, another size
    assert all(a != b for a, b in zip(grown, touched))
    s.set_setting("allow_non_raw_photos", False)
    assert all(a != b for a, b in zip(now(), grown))


def test_a_size_is_the_longest_side_and_an_impossible_one_is_refused(world):
    s = world["store"]
    pid = checked_pair(world)
    assert side(ig.photo_preview_png(s, pid)) == 1400 and side(ig.photo_preview_png(s, pid, size=480)) == 480
    assert side(ig.overlay_png(s, pid, size=300)) == 300 and side(ig.photo_preview_png(s, pid, size=4000)) == 1900   # never enlarged
    for size in (63, 5001):
        with pytest.raises(ig.IngestError, match="the picture size must be from 64 to 5000 pixels"):
            ig.photo_preview_png(s, pid, size=size)
        with pytest.raises(ig.IngestError, match="the picture size must be from 64 to 5000 pixels"):
            ig.overlay_png(s, pid, size=size)


def test_deleting_a_pair_removes_its_pictures_only(world):
    s = world["store"]
    gone, kept = checked_pair(world), checked_pair(world)
    for pid in (gone, kept):
        ig.overlay_png(s, pid)
        ig.photo_preview_png(s, pid, size=480)
    assert len(list((rc.root(s) / str(gone)).iterdir())) == 2
    ig.delete_pair(s, gone)
    assert not (rc.root(s) / str(gone)).exists() and len(list((rc.root(s) / str(kept)).iterdir())) == 2


def test_the_cache_keeps_under_its_limit_by_removing_the_pictures_used_longest_ago(store):
    picture = rc.PNG_START + b"x" * 1000 + rc.PNG_END
    for n, key in enumerate(("old", "used", "new")):
        rc.write(store, 1, key, picture)
        os.utime(rc.root(store) / "1" / f"{key}.png", ns=(0, (n + 1) * 1_000_000_000))
    assert rc.read(store, 1, "used") == picture                     # reading counts as a use
    rc.write(store, 2, "newest", picture, limit=3 * len(picture))
    assert sorted(p.name for p in rc.root(store).rglob("*.png")) == ["new.png", "newest.png", "used.png"]
    assert rc.trim(store, limit=len(picture)) == 2 * len(picture)
    assert [p.name for p in rc.root(store).rglob("*.png")] == ["newest.png"]


@pytest.fixture
def client(store):
    with TestClient(create_app(store.data_dir)) as c:
        yield c


def test_a_picture_carries_its_key_as_etag_and_an_unchanged_one_is_not_sent_again(world, client, decodes):
    s = world["store"]
    pid = checked_pair(world)
    for url in (f"/api/pairs/{pid}/photo.png?visibility=lifted&size=480", f"/api/pairs/{pid}/overlay.png?corrected=true&full=false",
                f"/api/pairs/{pid}/vector-overlay.png"):
        first = client.get(url)
        etag = first.headers["etag"]
        assert first.status_code == 200 and first.headers["content-type"] == "image/png"
        assert first.headers["cache-control"] == "private, max-age=0, must-revalidate" and len(etag) == 66 and etag[0] == etag[-1] == '"'
        drawn = len(decodes)
        for sent in (etag, f'W/{etag}', f'"other", {etag}', "*"):
            again = client.get(url, headers={"If-None-Match": sent})
            assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == etag
        stale = client.get(url, headers={"If-None-Match": '"other"'})
        assert stale.status_code == 200 and stale.content == first.content and stale.headers["etag"] == etag
        assert len(decodes) == drawn                                # neither the 304s nor the cached answer decoded anything
    big = make_pair(world, photo=png(synth.scene(width=3000, height=2000)))
    assert side(client.get(f"/api/pairs/{big}/photo.png?size=480").content) == 480
    refused = client.get(f"/api/pairs/{big}/photo.png?size=10")
    assert refused.status_code == 422 and refused.json()["error"] == "the picture size must be from 64 to 5000 pixels"
    assert client.get(f"/api/pairs/{pid}/overlay.png?size=9000").status_code == 422
    assert client.get("/api/pairs/999/photo.png", headers={"If-None-Match": "*"}).status_code == 404   # no 304 for nothing
