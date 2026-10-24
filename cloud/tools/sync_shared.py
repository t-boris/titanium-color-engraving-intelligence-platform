"""Copy the shared reader of the .tcelab format and its schema from the desktop package into the cloud package (DEC-058): the server
validates releases with the very same code. ``tests/test_cloud_shared.py`` fails when the copies drift.

    python cloud/tools/sync_shared.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = {ROOT / "src" / "titanium_platform" / "lab_format.py": ROOT / "cloud" / "titanium_cloud" / "_lab_format.py",
          ROOT / "src" / "titanium_platform" / "schemas" / "tcelab-1.schema.json": ROOT / "cloud" / "titanium_cloud" / "schemas" / "tcelab-1.schema.json"}


def drifted() -> list[Path]:
    return [target for source, target in SHARED.items() if not target.is_file() or target.read_bytes() != source.read_bytes()]


def main() -> int:
    for source, target in SHARED.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        print(f"{target.relative_to(ROOT)} <- {source.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
