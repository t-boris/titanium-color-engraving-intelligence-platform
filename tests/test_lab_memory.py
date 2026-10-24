"""Memory of the laboratory exchange (electron REQ-083, REQ-084): reading a release and building its snapshot use the same memory for a
release ten times larger (constant memory), and writing one grows only with the indices it must keep (a few kilobytes per measurement at
most), so the resource policy's limits bound it. ``tools/bench_tcelab.py`` measures the same on the reference hardware."""
from __future__ import annotations

import gc
import sys
import tracemalloc
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import labworld  # noqa: E402
from titanium_platform import lab_export, lab_format as lf, lab_snapshot  # noqa: E402
from titanium_platform.db import Store  # noqa: E402

SMALL, LARGE = 500, 5000
FLOOR = 512 * 1024                  # below this, allocator noise decides; a flat function stays well under it
PER_MEASUREMENT = 4096              # what the writer may keep per measurement: its identity, role and label


def peak(run) -> int:
    gc.collect()
    tracemalloc.start()
    tracemalloc.reset_peak()
    try:
        run()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    out = {}
    for n in (SMALL, LARGE):
        folder = tmp_path_factory.mktemp(f"bulk{n}")
        store = Store(folder / "lab")
        labworld.bulk(store, folder / "lab" / "files", n)
        lab_export.set_public_info(store, {"name": "Bench lab", "author": "B. Bench"})
        path = folder / "release.tcelab"
        written = peak(lambda: lab_export.export(store, path, None, "CC-BY-4.0"))
        store.close()
        out[n] = {"path": path, "folder": folder, "export_peak": written}
    return out


def read_whole(path: Path) -> None:
    with open(path, "rb") as fh:
        for _ in lf.read(fh):
            pass


def build_snapshot(path: Path, folder: Path) -> None:
    with open(path, "rb") as fh:
        lab_snapshot.build(folder / "snapshot", fh)


def test_reading_a_release_ten_times_larger_takes_the_same_memory(releases):
    small, large = (peak(lambda: read_whole(releases[n]["path"])) for n in (SMALL, LARGE))
    assert large < max(2 * small, FLOOR), (small, large)


def test_building_a_snapshot_of_a_release_ten_times_larger_takes_the_same_memory(releases):
    small, large = (peak(lambda: build_snapshot(releases[n]["path"], releases[n]["folder"])) for n in (SMALL, LARGE))
    assert large < max(2 * small, FLOOR), (small, large)


def test_writing_a_release_keeps_at_most_a_few_kilobytes_per_measurement(releases):
    for n in (SMALL, LARGE):
        assert releases[n]["export_peak"] < FLOOR + n * PER_MEASUREMENT, (n, releases[n]["export_peak"])
    assert releases[LARGE]["path"].stat().st_size > 5 * releases[SMALL]["path"].stat().st_size
