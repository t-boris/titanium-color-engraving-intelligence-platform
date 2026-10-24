"""A connected release gives the author's numbers (electron REQ-083: the same Lab values and curve points within 1e-6 for the same data
and algorithm versions): the laboratory test workshop (``labworld``) is published, its files are taken away, and the colour map, the
palettes, the tonal curves, the scales and the engraving checks made from the release's snapshot are compared with the author's, record
by record through the release's UUIDs."""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import evidence_summary as summary  # noqa: E402
import labworld  # noqa: E402
from titanium_platform import lab_export, lab_snapshot, prediction_store as ps  # noqa: E402
from titanium_platform.db import Store  # noqa: E402

TOLERANCE = 1e-6


def publish(tmp_path: Path) -> tuple[Store, dict, Path]:
    author = Store(tmp_path / "author")
    ids = labworld.build(author, tmp_path / "author" / "files")
    lab_export.set_public_info(author, {"name": "Test laboratory", "author": "Test author", "description": "Numbers only."})
    path = tmp_path / "out" / "lab.tcelab"
    lab_export.export(author, path, None, "CC-BY-4.0")
    return author, ids, path


def connect(tmp_path: Path, path: Path) -> Store:
    with open(path, "rb") as fh:
        lab_snapshot.build(tmp_path / "snapshot", fh)
    return lab_snapshot.open_snapshot(tmp_path / "snapshot")


class Ids:
    """The release UUID of every author id and snapshot id, so the two sides compare record by record."""

    def __init__(self, author: Store, snapshot: Store):
        self.author = {kind: {r["local_key"]: r["uuid"] for r in author.query("SELECT local_key, uuid FROM portable_id WHERE kind=?", (kind,))}
                       for kind in ("pair", "observation", "engraving", "laser", "lens", "material")}
        self.snapshot = {kind: {r["local_id"]: r["uuid"] for r in snapshot.query("SELECT local_id, uuid FROM release_record WHERE kind=?", (kind,))}
                         for kind in ("capture", "measurement")}

    def snapshot_id(self, kind: str, author_id) -> int:
        return lab_snapshot.local_id(self.author[kind][str(author_id)])


def portable(value, ids: Ids, side: str):
    """``value`` (a summary) with pair, observation and engraving ids replaced by the release's UUIDs."""
    def pair(i):
        return ids.author["pair"][str(i)] if side == "author" else ids.snapshot["capture"][i]

    def observation(i):
        return ids.author["observation"][str(i)] if side == "author" else ids.snapshot["measurement"][i]

    if isinstance(value, list):
        return [portable(v, ids, side) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if key == "pair_id" and item is not None:
            out[key] = pair(item)
        elif key == "pairs":
            out[key] = sorted(pair(i) for i in item)
        elif key in ("observations", "observation_ids"):
            out[key] = sorted(observation(i) for i in item)
        elif key == "engraving_id" and item is not None:
            out[key] = ids.author["engraving"][item] if side == "author" else item
        elif key == "id" and isinstance(item, str) and item.startswith("tonal-"):
            _, pair_id, rest = item.split("-", 2)
            out[key] = f"tonal-{pair(int(pair_id))}-{rest}"
        elif key == "id" and isinstance(item, str) and item.isdigit():
            out[key] = observation(int(item))
        else:
            out[key] = portable(item, ids, side)
    return out


def assert_close(a, b, where="$"):
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f"{where}: keys {sorted(set(a) ^ set(b))}"
        for k in a:
            assert_close(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), f"{where}: {len(a)} against {len(b)} items"
        for i, (x, y) in enumerate(zip(a, b)):
            assert_close(x, y, f"{where}[{i}]")
    elif isinstance(a, float) or isinstance(b, float):
        assert a is not None and b is not None and math.isclose(a, b, rel_tol=0, abs_tol=TOLERANCE), f"{where}: {a} against {b}"
    else:
        assert a == b, f"{where}: {a!r} against {b!r}"


def _sorted_points(points):
    return sorted(points, key=lambda p: (str(p["pair_id"]), p["layer_index"], str(p["id"])))


def results(store: Store, laser: int, lens: int, other: int, materials: dict, p7: int) -> dict:
    """Everything a connected release is used for, from ``store``, with its own ids."""
    cmap = summary.colour_map(store)
    grey = ps.mode_of(labworld.PICTURE, laser, lens, materials["m1"])
    dots = ps.mode_of({**labworld.PICTURE, "max_power": 45.0, "dot_width": 0.05}, laser, lens, materials["m1"], dither="jarvis")
    return {"nominal_clean": cmap["nominal_clean"], "points": [p for p in cmap["points"] if not p["provisional"]],
            "palettes": {m: summary.vector_palette(store, laser, lens, materials[m]) for m in ("m1", "m2", "m0")}
            | {"m5": summary.vector_palette(store, other, None, materials["m5"])},
            "curves": {str(row): summary.curve(store, grey, row) for row in (None, 20.0, 30.0, 40.0, 80.0)} | {"dots": summary.curve(store, dots)},
            "scales": summary.scales(store), "check": summary.plain(ps.engraving_check(store, grey, p7))}


def comparable(found: dict, ids: Ids, side: str) -> dict:
    out = portable(found, ids, side)
    out["points"] = _sorted_points(out["points"])
    return out


def test_a_release_gives_the_authors_numbers_without_the_authors_files(tmp_path):
    author, ids, path = publish(tmp_path)
    materials = {m: ids[m] for m in ("m1", "m2", "m5", "m0")}
    expected = results(author, ids["laser"], ids["lens"], ids["other"], materials, ids["pairs"]["p7"])
    shutil.rmtree(tmp_path / "author" / "files")          # a connected workshop has none of the author's files
    snapshot = connect(tmp_path, path)
    map_ = Ids(author, snapshot)
    p7 = next(local for local, value in map_.snapshot["capture"].items() if value == map_.author["pair"][str(ids["pairs"]["p7"])])
    found = results(snapshot, map_.snapshot_id("laser", ids["laser"]), map_.snapshot_id("lens", ids["lens"]),
                    map_.snapshot_id("laser", ids["other"]), {m: map_.snapshot_id("material", i) for m, i in materials.items()}, p7)
    assert len(found["points"]) == len(expected["points"]) > 40
    # a check not accepted yet is never published: the author's palettes count its colour as left out, the release has none to count
    assert expected["palettes"]["m1"]["left_out"]["provisional"] == 1
    for palette in expected["palettes"].values():
        palette["left_out"]["provisional"] = 0
    assert_close(comparable(found, map_, "snapshot"), comparable(expected, map_, "author"))
