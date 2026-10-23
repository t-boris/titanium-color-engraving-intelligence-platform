"""Move the colours the works chose to the names their recipes have from 0.25.2, where a layer's Show and Output switches are not
part of a recipe (DEC-119).

    python tools/forget_layer_switches.py --data-dir ~/.titanium-platform            # what would change, nothing is written
    python tools/forget_layer_switches.py --data-dir ~/.titanium-platform --apply    # change it, after a backup copy

Up to 0.25.1 the same settings measured on a hidden layer (LightBurn's Show switch off) and on a shown one were two recipes, and the
colour map entry of each had its own id. From 0.25.2 the switches are the job's (``lightburn.LAYER_SWITCH_TAGS``), so the entries
measured on hidden layers get other ids, and a work that chose one of them would find that colour missing. The tool computes the
palette id of every measured colour as 0.25.1 did and as this version does, for the laser, lens and titanium of each work, and
replaces each old id that changed by its new one wherever the work keeps it: its colouring, variants, undo steps, layers and exports.
Then it refreshes the knowledge of each laser and lens, as the application does after any change, so an entry that gets its evidence
back is promoted as its evidence supports.

It refuses, and changes nothing, when an old id would become two ids, or when an old id would still be in a work after the change.
Stop the application first: a work saved while the tool runs could keep an old id.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from titanium_platform import colormap, knowledge, model, palette  # noqa: E402
from titanium_platform import setup as su                          # noqa: E402
from titanium_platform.db import Store, open_store                 # noqa: E402


class Refused(Exception):
    """The works cannot be moved without losing or confusing a colour; nothing was changed."""


@contextmanager
def keys_of_0_25_1():
    """Recipe keys as 0.25.1 had them, with the layer's Show and Output switches in them."""
    current = model.parameters_key
    model.parameters_key = lambda p: model._parameters_key(p, ())
    try:
        yield
    finally:
        model.parameters_key = current


def _ids(store: Store, setup: str, material_id: int) -> dict[int, str]:
    """The palette id of the recipe of each observation of the colour map, for a work of laser and lens ``setup`` on ``material_id``
    (:func:`palette.pooled_ids`: the recipe's id across the plates of that titanium)."""
    plates = set(su.same_titanium(store, material_id))
    points = [p for p in colormap.collect(store, setup=setup)["points"] if p["material_id"] in plates]
    ids = palette.pooled_ids(points, material_id)
    return {oid: ids[p["group"]] for p in points for oid in p["observation_ids"]}


def moves(store: Store, setup: str, material_id: int) -> dict[str, str]:
    """Each palette id of 0.25.1 that is another id now, for a work of laser and lens ``setup`` on ``material_id``."""
    with keys_of_0_25_1():
        old = _ids(store, setup, material_id)
    new = _ids(store, setup, material_id)
    found: dict[str, set[str]] = {}
    for oid, was in old.items():
        if new.get(oid) != was:
            found.setdefault(was, set()).add(new.get(oid))
    split = {was: sorted(map(str, now)) for was, now in found.items() if len(now) != 1 or None in now}
    if split:
        raise Refused(f"the colours {sorted(split)} of {setup} on titanium {material_id} would not become one colour each: {split}")
    return {was: next(iter(now)) for was, now in found.items()}


def renamed(value, ids: dict[str, str]):
    """``value`` (a work's stored data) with every id in ``ids`` replaced, as it is or as a layer key ``e<id>``."""
    if isinstance(value, dict):
        return {renamed(k, ids): renamed(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [renamed(v, ids) for v in value]
    if isinstance(value, str):
        if value in ids:
            return ids[value]
        if value[:1] == "e" and value[1:] in ids:
            return "e" + ids[value[1:]]
    return value


def plan(store: Store) -> list[dict]:
    """What the tool would change: one item per work that keeps an id that changed, with the ids it keeps and their new names."""
    scopes: dict[tuple[str, int], dict[str, str]] = {}
    out = []
    for row in store.query("SELECT id, name, device_id, lens_id, data_json FROM plan ORDER BY id"):
        data = json.loads(row["data_json"] or "{}")
        material_id = data.get("material_id")
        if material_id is None:
            continue
        scope = (su.setup_key(row["device_id"], row["lens_id"]), material_id)
        if scope not in scopes:
            scopes[scope] = moves(store, *scope)
        text = row["data_json"]
        kept = {was: now for was, now in scopes[scope].items() if was in text}
        if not kept:
            continue
        data_after = renamed(data, kept)
        after = json.dumps(data_after)
        left = sorted(was for was in kept if was in after)
        if left:
            raise Refused(f"work {row['id']} «{row['name']}» would still keep {left} in a form the tool does not rename")
        out.append({"plan_id": row["id"], "name": row["name"], "ids": kept, "times": {was: text.count(was) for was in kept},
                    "data": data_after})
    return out


def backup(data_dir: Path) -> Path:
    """A consistent copy of the database, beside the backups made before each release."""
    folder = data_dir / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"titanium-before-forget-layer-switches-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite"
    src, dst = sqlite3.connect(data_dir / "titanium.sqlite"), sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return target


def apply(store: Store, changes: list[dict]) -> list[dict]:
    """Write the works' new data and an audit entry in one transaction, then refresh the knowledge of every laser and lens."""
    with store.transaction():
        for change in changes:
            store.execute("UPDATE plan SET data_json=? WHERE id=?", (json.dumps(change["data"]), change["plan_id"]))
        store.audit("layer_switches_forgotten", works={c["plan_id"]: c["ids"] for c in changes})
    refreshed = []
    for row in store.query("SELECT DISTINCT device_id, lens_id FROM observation ORDER BY device_id, lens_id"):
        refreshed += knowledge.refresh(store, row["device_id"], row["lens_id"])
    return refreshed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--apply", action="store_true", help="change the works (without it the tool only says what it would change)")
    a = ap.parse_args(argv)
    store = open_store(a.data_dir, "forget_layer_switches")
    try:
        changes = plan(store)
    except Refused as exc:
        print("refused, nothing changed:", exc, file=sys.stderr)
        return 2
    for c in changes:
        print(f"work {c['plan_id']} «{c['name']}»:", ", ".join(f"{was} -> {now} ({c['times'][was]}x)" for was, now in c["ids"].items()))
    if not changes:
        print("no work keeps a colour whose id changed")
    if not a.apply:
        print("dry run: nothing changed (add --apply to change it)")
        return 0
    print("backup:", backup(a.data_dir))
    for r in apply(store, changes):
        print("knowledge", r["id"], f"{r['from']} -> {r['to']}" if "to" in r else "questioned")
    print("done:", len(changes), "works changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
