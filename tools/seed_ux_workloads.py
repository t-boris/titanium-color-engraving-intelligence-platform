"""Fill a THROW-AWAY workshop with synthetic collections for the UX checks (ux-validation-p0, research n56).

    python tools/seed_ux_workloads.py --data-dir /tmp/ux-shop --count 200

The counts 20 / 200 / 2000 are test workloads, not the size of anyone's database. The command refuses a data directory that already
holds a workshop unless ``--force-into-existing`` is given, and never touches the operator's live workshop (~/.titanium-platform).
It writes: ``count`` stock records (materials) and ``count`` works (vector and photo, a third of them photo works), through the same
functions the application uses.
The works are catalogue rows: they have no stored picture or document, so the works catalog, the stock list and the selectors can be
loaded with them, but the vector and photo editors (and their own lists) report “Could not load data” for them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from titanium_platform import conversion as cv, devices, lenses, plans as pl, setup as su      # noqa: E402
from titanium_platform.api.app import create_app                              # noqa: E402

LIVE = Path.home() / ".titanium-platform"


def seed(data_dir: Path, count: int) -> dict:
    app = create_app(data_dir)
    store = app.state.store
    try:
        grades = ("Grade 2", "Grade 5", "Ti-6Al-4V", None)
        lasers = [devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name=name, serial=serial) for name, serial in (("Laser Alpha", "A-1"), ("Laser Beta", "B-1"))]
        lens = [lenses.create_lens(store, name, 174, 170) for name in ("F-Theta 175", "F-Theta 254")]
        with store.transaction():
            stock = [su.save_material(store, f"Sheet {i + 1}", batch=f"B-{i + 1:04d}", grade=grades[i % 4], thickness_mm=0.5 + (i % 5) * 0.5,
                                      surface="sanded" if i % 2 else None, family="Titanium" if i % 7 else "Steel") for i in range(count)]
            for n in range(count):
                stamp = f"2026-10-{1 + n % 28:02d}T{n % 24:02d}:00:00+00:00"
                vector = {"strategy": "photo", "size_mm": {"width": 50, "height": 30}, "document_version": 1, "history": [{"at": stamp}],
                          "colouring": {"photo": [{"number": 1}] if n % 7 == 0 else []}, "exports": []}
                photo = {"image_size": [200, 100], "width_mm": 50, "updated_at": stamp, "texts": [], "scale": {}}
                cv.save_plan(store, None, name=f"Work {n}", mode=pl.MODE_VECTOR if n % 3 else pl.MODE_PHOTO_WORK, status="Draft", device_id=lasers[n % 2]["id"],
                             lens_id=None if n % 5 == 0 else lens[n % 2]["id"], markers=False, identifier=f"W-{n}", band_count=None, data=vector if n % 3 else photo)
        return {"materials": len(stock), "works": count}
    finally:
        app.state.store.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--count", type=int, default=200, help="records of each kind (20, 200 or 2000 are the protocol's loads)")
    parser.add_argument("--force-into-existing", action="store_true")
    args = parser.parse_args(argv)
    target = args.data_dir.expanduser().resolve()
    if target == LIVE.resolve():
        print("refusing: that is the live workshop", file=sys.stderr)
        return 2
    if (target / "titanium.sqlite").exists() and not args.force_into_existing:
        print(f"refusing: {target} already holds a workshop (use --force-into-existing for a throw-away copy)", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    print(seed(target, args.count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
