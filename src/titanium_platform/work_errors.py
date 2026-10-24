"""Work on the errors, the part that reads and writes the database (DEC-090, proposed).

After the operator reports an engraving (an accepted pair linked to a vector work), the conclusions go into the work itself:

* ``reviews``: for each engraving of the work, the colour every layer promised against the colour the photograph measured
  (:func:`review_pair`, kept by :func:`record`, one per engraving: a new measurement of the same engraving replaces the old one);
* ``attention``: how many layers of the work no longer have the titanium colour its last file promised, counted for the list of works
  (:func:`refresh_work`; the work's own screen computes it live, see :func:`vector_job.photo_view`).

New measurements change the palette of every work of that laser and lens, so :func:`after_change` refreshes them all. Nothing here
edits a colouring: replacements are proposed on the work's screen and applied by the operator as ordinary, undoable edits, and a file
that was engraved is never touched.
"""
from __future__ import annotations

import json

from . import conversion as cv, ingest, palette, plans as pl, render_cache as rc, vector_job as vj, work_review as wr
from .db import Store, now

MEASUREMENT = {"reference_chart_corrected": "calibrated", "raw_camera_relative": "relative"}      # as colormap names them
SKIPPED = (KeyError, OSError, ValueError, cv.ConversionError)


def _work(store: Store, plan_id: int | None) -> dict | None:
    """The plan of a vector work made from a photograph, or None (another kind of plan, deleted, or not there)."""
    if plan_id is None:
        return None
    try:
        plan = pl.get_plan(store, plan_id)
    except KeyError:
        return None
    if plan["status"] == "Deleted" or plan["mode"] != pl.MODE_VECTOR or not vj.is_photo(plan):
        return None
    return plan


def _engraved(store: Store, pair_id: int) -> list[dict]:
    """The layers of the engraving as the photograph measured them: its test features, with their settings and colours."""
    out = []
    for row in store.query("SELECT layer_index, lab_json, parameters_json, evidence_json FROM observation WHERE pair_id=? ORDER BY layer_index", (pair_id,)):
        evidence = json.loads(row["evidence_json"])
        if evidence.get("role", "test feature") != "test feature":                  # the cleaning witness and the markers are not colours
            continue
        mode = (evidence.get("color_measurement") or {}).get("mode")
        out.append({"layer_index": row["layer_index"], "name": evidence.get("layer_name") or f"layer {row['layer_index']}",
                    "settings": wr.settings_of(json.loads(row["parameters_json"])), "lab": json.loads(row["lab_json"]),
                    "basis": "chart" if mode == "reference_chart_corrected" else "as-shot", "measurement": MEASUREMENT.get(mode, "relative")})
    return out


def _promise_for(plan: dict, engraved: list[dict]) -> tuple[int | None, list[dict] | None, bool]:
    """The export whose layers the engraved file matches best (the latest on a tie): its number, its promise and whether the promise is
    only reconstructed. A work exported before promises were kept is set against its layers as it last stored them (approximate) while
    its colouring and split are still the ones its last file was made from (:func:`work_review.baseline_of`); after a recolouring or a
    new split the promise is lost and is None, and a work never exported is set against its layers as they are (approximate)."""
    kept = [(e["number"], e["promised"]) for e in plan["exports"] if e.get("promised")]
    best = max(kept, key=lambda k: (len(wr.match(k[1], engraved)), k[0]), default=None)
    if best is not None:
        return best[0], best[1], False
    if not plan["exports"]:
        return None, wr.promised_layers(plan.get("layers") or []), True
    promise, approximate = wr.baseline_of(plan)
    return plan["exports"][-1]["number"], promise, approximate


def review_pair(store: Store, pair_id: int) -> dict | None:
    """The review of an accepted pair against the work it is linked to; None when it is linked to no vector work made from a photograph."""
    pair = ingest.get_pair(store, pair_id)
    plan = _work(store, pair["plan_id"])
    if pair["status"] != ingest.ST_ACCEPTED or plan is None:
        return None
    engraved = _engraved(store, pair_id)
    number, promise, approximate = _promise_for(plan, engraved)
    residual = ((pair.get("check") or {}).get("chart") or {}).get("residual")
    found = wr.review(promise or [], engraved, chart_residual=residual)
    return {"engraving_id": pair["engraving_id"], "pair_id": pair_id, "photo_name": pair["photo_name"], "reviewed_at": now(),
            "export_number": number, "approximate": approximate, "promise_lost": promise is None, "chart_residual": residual, **found}


def record(store: Store, pair_id: int) -> dict | None:
    """Keep the review of an accepted pair in its work, replacing the earlier review of the same engraving."""
    review = review_pair(store, pair_id)
    if review is None:
        return None
    plan = _work(store, ingest.get_pair(store, pair_id)["plan_id"])
    kept = [r for r in plan.get("reviews") or [] if r["engraving_id"] != review["engraving_id"]]
    plan["reviews"] = wr.newest_first(kept + [review])[:wr.KEPT_REVIEWS]
    cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    return review


def refresh_work(store: Store, plan_id: int) -> dict | None:
    """Count the layers of a work that have drifted since its last file promised them and keep the counts in the work (for the list)."""
    plan = _work(store, plan_id)
    if plan is None:
        return None
    entries = vj._palette(store, plan)
    state = vj._state(plan, vj._document(plan), entries, vj._inscribed(store, plan, entries))
    found = vj._attention(plan, state, entries, plan["colour_settings"])
    attention = None if found is None else wr.attention_of(found, now())
    keep = lambda a: None if a is None else {k: v for k, v in a.items() if k != "checked_at"}      # noqa: E731
    if "attention" not in plan or keep(attention) != keep(plan.get("attention")):
        plan["attention"] = attention
        cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    return found


def refresh_missing(store: Store) -> int:
    """Catch up works and photographs from before the work on the errors: the photographs already accepted for a vector work get their
    review, and the works exported before the counts were kept get theirs. Once, when the app starts. Returns how many things were done."""
    done = 0
    for row in store.query("SELECT p.id FROM pair p JOIN plan w ON w.id=p.plan_id WHERE p.status='Accepted' AND w.mode=? AND w.status!='Deleted' ORDER BY p.id",
                           (pl.MODE_VECTOR,)):
        pair = ingest.get_pair(store, row["id"])
        work = _work(store, pair["plan_id"])
        if work is None or any(r["engraving_id"] == pair["engraving_id"] for r in work.get("reviews") or []):
            continue
        try:
            done += record(store, row["id"]) is not None
        except SKIPPED:
            continue
    for row in store.query("SELECT id, data_json FROM plan WHERE mode=? AND status!='Deleted'", (pl.MODE_VECTOR,)):
        data = json.loads(row["data_json"])
        if "attention" in data or not data.get("exports"):
            continue
        try:
            refresh_work(store, row["id"])
            done += 1
        except SKIPPED:
            continue
    return done


def after_change(store: Store, device_id: int, lens_id: int | None) -> None:
    """New or removed measurements of one laser and lens change the titanium colours of every work made for them: count again."""
    for row in store.query("SELECT id FROM plan WHERE mode=? AND status!='Deleted' AND device_id=? AND lens_id IS ?", (pl.MODE_VECTOR, device_id, lens_id)):
        try:
            refresh_work(store, row["id"])
        except SKIPPED:                                              # one broken work must not stop the acceptance of a photograph
            continue


def after_acceptance(store: Store, pair_id: int) -> dict | None:
    """The conclusions of an accepted pair: its review goes into its work, then every work of the laser and lens is counted again.
    Returns the work and its review (what the screen tells the operator), or None when the pair belongs to no vector work."""
    pair = ingest.get_pair(store, pair_id)
    try:
        review = record(store, pair_id)
    except SKIPPED:
        review = None
    after_change(store, pair["device_id"], pair["lens_id"])
    if review is None:
        return None
    return {"plan_id": pair["plan_id"], "work": pl.get_plan(store, pair["plan_id"])["name"], "review": review}


def after_deletion(store: Store, pair: dict) -> None:
    """A deleted pair takes its review with it unless another photograph of the same engraving is still accepted; the works are counted again."""
    plan = _work(store, pair["plan_id"])
    if plan is not None:
        still = store.one("SELECT 1 FROM pair WHERE engraving_id=? AND status='Accepted'", (pair["engraving_id"],))
        if still is None and any(r["engraving_id"] == pair["engraving_id"] for r in plan.get("reviews") or []):
            plan["reviews"] = [r for r in plan["reviews"] if r["engraving_id"] != pair["engraving_id"]]
            cv._persist(store, plan, plan["status"], plan["markers_enabled"])
    after_change(store, pair["device_id"], pair["lens_id"])


# -- the picture of the result ---------------------------------------------------------------------------------------------------------
def engraved_picture(store: Store, plan_id: int, engraving_id: str, promised: bool = False) -> rc.Picture:
    """The work drawn in the colours its engraving measured: every region of a layer found in the photograph in that layer's measured
    colour; the regions of layers that were not engraved are left empty. With ``promised`` the same regions are drawn in the colours the
    file promised, so the two pictures differ only where the engraving differs from the promise."""
    plan = vj._job(store, plan_id)
    review = next((r for r in plan.get("reviews") or [] if r["engraving_id"] == engraving_id), None)
    if review is None:
        raise KeyError("this work has no review of that engraving")
    exported = next((e for e in plan["exports"] if e["number"] == review["export_number"] and e.get("promised")), None)
    promise = exported["promised"] if exported else wr.promised_layers(plan.get("layers") or [])
    colours = {row["promised_index"]: row["promised_srgb" if promised else "got_srgb"] for row in review["rows"]}
    painted = {region: colours[layer["index"]] for layer in promise if layer["index"] in colours for region in layer["region_ids"]}
    key = rc.key_of({"kind": "vector-engraved", "plan": plan["id"], "px": vj.THUMB_PX, "version": plan["document_version"],
                     "document": rc.file_stamp(plan["document_path"]), "smoothing_mm": plan.get("smoothing_mm", 0.0),
                     "painted": rc.text_digest(json.dumps(painted, sort_keys=True))})
    return rc.Picture(store, f"vector-{plan['id']}-{'promised' if promised else 'engraved'}", key, lambda: vj._draw_thumbnail(plan, painted))
