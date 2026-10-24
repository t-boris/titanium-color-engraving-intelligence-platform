"""The local results of the colour map, the palettes and the tonal curves on the laboratory test workshop (``labworld``), recorded in
``fixtures/evidence_golden.json`` (electron A1): a change to how evidence is gathered must leave them as they are, and a deliberate change
of an algorithm rewrites the record in the same commit, so its numbers show in the diff.

Rewrite the record with ``.venv/bin/python tests/test_evidence_golden.py --write``."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
GOLDEN = HERE / "fixtures" / "evidence_golden.json"
sys.path.insert(0, str(HERE))

import evidence_summary as summary  # noqa: E402
import labworld  # noqa: E402
from titanium_platform import prediction_store as ps  # noqa: E402
from titanium_platform.db import Store  # noqa: E402


def results(data_dir: Path) -> dict:
    store = Store(data_dir)
    ids = labworld.build(store, data_dir / "files")
    grey = ps.mode_of(labworld.PICTURE, ids["laser"], ids["lens"], ids["m1"])
    dots = ps.mode_of({**labworld.PICTURE, "max_power": 45.0, "dot_width": 0.05}, ids["laser"], ids["lens"], ids["m1"], dither="jarvis")
    out = {"colour_map": summary.colour_map(store),
           "palettes": {"laser-lens-grade2": summary.vector_palette(store, ids["laser"], ids["lens"], ids["m1"]),
                        "laser-lens-grade2-sheetB": summary.vector_palette(store, ids["laser"], ids["lens"], ids["m2"]),
                        "laser-lens-nograde": summary.vector_palette(store, ids["laser"], ids["lens"], ids["m0"]),
                        "other-grade5": summary.vector_palette(store, ids["other"], None, ids["m5"])},
           "curves": {f"grey@{row}": summary.curve(store, grey, row) for row in (None, 20.0, 30.0, 40.0, 80.0)}
           | {"dots": summary.curve(store, dots)},
           "scales": summary.scales(store),
           "checks": {name: summary.plain(ps.engraving_check(store, grey, ids["pairs"][name])) for name in ("p7", "p8")}}
    store.close()
    return out


def test_the_local_results_are_as_recorded(tmp_path):
    assert results(tmp_path / "data") == json.loads(GOLDEN.read_text())


def test_re_photographs_of_one_engraving_are_one_engraving():
    """electron DEC-045: p8 re-photographs p7. The check of either is the check of their engraving against the other engravings only,
    and the curve counts the two photographs once."""
    recorded = json.loads(GOLDEN.read_text())
    assert recorded["checks"]["p7"] == recorded["checks"]["p8"]
    assert recorded["checks"]["p7"]["others"] == 1 and not recorded["checks"]["p7"]["confirmed"]
    assert {point["engravings"] for point in recorded["curves"]["grey@None"]["points"]} == {2}


if __name__ == "__main__" and "--write" in sys.argv:
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        GOLDEN.write_text(json.dumps(results(Path(folder) / "data"), indent=1, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN}")
