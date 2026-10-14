"""Import one physical laser (passport sections + its source photographs) into a data directory.

    python tools/import_unit.py --data-dir ~/.titanium-platform --photos ~/Downloads \\
        --unit tools/units/jpt-ydflp-e-60-m7-m-r-mc2bdjd71684.json [--link-profile NAME]

The unit file holds what was read from the photographs (REQ-017, DEC-037 to DEC-039). The command is repeatable:
a device with the same serial number is updated in place, and a photograph already attached is not attached twice.
Stop the application first, or let it run: SQLite is opened in WAL mode, and a backup copy is made before any write.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from titanium_platform import devices, profiles as pf   # noqa: E402
from titanium_platform.db import Store                  # noqa: E402


def backup(data_dir: Path) -> Path | None:
    db = data_dir / "titanium.sqlite"
    if not db.exists():
        return None
    base = f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    target, n = data_dir / base, 1
    while target.exists():   # two imports within one second must not collide
        n += 1
        target = data_dir / f"{base}-{n}"
    target.mkdir()
    import sqlite3
    src, dst = sqlite3.connect(db), sqlite3.connect(target / "titanium.sqlite")
    with dst:
        src.backup(dst)                       # a consistent copy even while the application writes
    src.close()
    dst.close()
    return target


def find_device(store: Store, serial: str) -> dict | None:
    """The device of this unit: by its serial number, or by the serial of its test report.

    The operator may replace the serial number (for instance with the machine number), so the serial printed in the
    test report is the second key; otherwise a second import would create a duplicate device.
    """
    for d in devices.list_devices(store):
        if d["serial"] == serial or ((d["passport"].get("test_report") or {}).get("serial") == serial):
            return d
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--unit", type=Path, required=True)
    ap.add_argument("--photos", type=Path, required=True, help="folder that holds the photographs named in the unit file")
    ap.add_argument("--link-profile", help="link the laser profile with this name (its latest version) to the device")
    a = ap.parse_args(argv)
    unit = json.loads(a.unit.read_text(encoding="utf-8"))
    missing = [d["file"] for d in unit["documents"] if not (a.photos / d["file"]).is_file()]
    if missing:
        print("photographs not found in", a.photos, ":", ", ".join(missing), file=sys.stderr)
        return 2
    saved = backup(a.data_dir)
    if saved:
        print("backup:", saved)
    store = Store(a.data_dir)
    try:
        device = find_device(store, unit["serial"])
        if device is None:
            device = devices.create_from_template(store, unit["template"], unit["name"], unit["serial"])
            print("created device", device["id"], device["name"])
        else:
            print("device", device["id"], "already exists: updating")
        # Only sections the device does not have yet are filled in: what the operator confirmed, corrected, removed or
        # added is never overwritten by what was read from the photographs (DEC-039).
        old_format = unit["serial"] in device["name"] or bool(device["serial"] and device["serial"] in device["name"])
        if old_format and unit["name"] != device["name"]:
            device = devices.update_device(store, device["id"], name=unit["name"])      # the title adds the current serial itself
            print("renamed to", unit["name"], "(the serial number is shown by the title)")
        passport, filled = dict(device["passport"]), []
        for key, value in unit["passport"].items():
            if passport.get(key) in (None, [], {}):
                passport[key] = value
                filled.append(key)
        if filled:
            device = devices.update_device(store, device["id"], passport=passport)
            print("filled in:", ", ".join(filled))
        else:
            print("nothing to fill in: the operator's data is kept as it is")
        have = {d["filename"] for d in device["documents"]}
        for doc in unit["documents"]:
            if doc["file"] in have:
                continue
            devices.add_document(store, device["id"], doc["kind"], doc["title"], doc["file"], (a.photos / doc["file"]).read_bytes())
            print("attached", doc["file"], "-", doc["title"])
        if a.link_profile:
            profile = [p for p in pf.list_profiles(store) if p["name"] == a.link_profile][-1:]
            if not profile:
                print("no laser profile named", a.link_profile, file=sys.stderr)
                return 3
            linked = pf.update_profile(store, profile[0]["id"], device_id=device["id"])
            print("profile", linked["name"], "version", linked["version"], "linked to the device (no new version)")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
