"""The shared context of new work and what a result needs to start (feature ux-work-creation-p0, REQ-001, REQ-002).

**The context** is the laser, the lens, the actual titanium stock, the photography setup (rig) and the source of the measurements that a
new task starts from. It is the workshop's last explicit choice, kept in the ``setting`` table (``creation_context``), so a new work and a
new test start from what the person used last and the choice follows them between the screens that create things. It is only a *start*:

* a work keeps its own laser, lens, stock and source in its record (``plan``), and this module never writes there. Changing the shared
  context changes nothing that was already made, and an opened work shows its own;
* a stored choice whose record is gone (a deleted laser, stock or rig) is not used; the view says which one was lost (``stale``) and
  falls back to the default. Defaults never invent anything: the first laser, the lens installed on it, the first stock, the rig of the
  last photograph.

**Impact** answers, before the person confirms a change, what the change does to what they can start: how many measured colours, scales,
fill and line recipes the new setup has against the present one, whether the chosen laboratory release still serves, an unknown lens, a
lens that is not on the laser, another grade of titanium. Every finding is a structured code with its numbers; the words are the UI's.

**Readiness** says, for one result (``photo``, ``colour``, ``silhouette``, ``lines``), what is missing to start it with the context
(a laser, a titanium stock, a lens for a test, measurements) and, when only measurements are missing, the starter test that gives them:
the same plate the experiment screens offer for that task, and which result becomes available once its measurements are accepted.
"""
from __future__ import annotations

from typing import Any

from . import application_guide, conversion as cv, devices, evidence_source, lenses, palette, prediction_store as ps, setup as su, vector_job
from .db import Store

KEY = "creation_context"
RESULTS = ("photo", "colour", "silhouette", "lines")
MAX_LABEL = 400
SOURCE_KEYS = ("release_id", "laser", "lens", "material")

# What a result is made of, and the task its recipes serve (REQ-020): the vector form's strategies photo / fill / line, and the photo work.
TASK_OF = {"colour": "color_image", "silhouette": "fill", "lines": "line"}
GREY_SCALES = "grey_scales"                  # the plate that measures the scales a photo work stands on (capability_plates)
# What the starter test's accepted measurements give: a measured scale makes a photo work possible at once; a recipe reaches a vector work
# when it is validated or in production (palette.left_out_reason: a provisional colour is in no palette).
BECOMES = {"photo": "measured_scale", "colour": "validated_recipes", "silhouette": "validated_recipes", "lines": "validated_recipes"}


# -- the stored choice ----------------------------------------------------------------------------------------------------------
def _stored(store: Store) -> dict:
    value = store.get_setting(KEY, None)
    return value if isinstance(value, dict) else {}


def _exists(store: Store, table: str, record_id) -> bool:
    return isinstance(record_id, int) and store.one(f"SELECT 1 FROM {table} WHERE id=?", (record_id,)) is not None


def _default_rig(store: Store) -> int | None:
    last = su.last_capture_setup(store)
    if last is not None:
        return last
    real = [r for r in su.list_capture_setups(store) if not r["legacy"]]
    return real[0]["id"] if len(real) == 1 else None


def _material(store: Store, material_id: int | None) -> dict | None:
    row = None if material_id is None else store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
    return None if row is None else dict(row)


def get(store: Store) -> dict:
    """The context as new work starts from it, with the records it names. ``lens_basis`` tells where the lens came from: ``chosen`` (an
    explicit choice), ``installed`` (the lens standing on the laser now) or ``unknown`` (an explicit choice of the unknown lens)."""
    saved, stale = _stored(store), []
    device_id = saved.get("device_id")
    if device_id is not None and not _exists(store, "laser_device", device_id):
        stale.append("device")
        device_id, saved = None, {k: v for k, v in saved.items() if k != "lens_id"}      # a lens chosen for a lost laser is lost with it
    if device_id is None:
        first = store.one("SELECT id FROM laser_device ORDER BY id LIMIT 1")
        device_id = None if first is None else first["id"]
    lens_id, basis = None, "unknown"
    if device_id is not None:
        if "lens_id" in saved and (saved["lens_id"] is None or _exists(store, "lens", saved["lens_id"])):
            lens_id, basis = saved["lens_id"], "unknown" if saved["lens_id"] is None else "chosen"
        else:
            if "lens_id" in saved:
                stale.append("lens")
            installed = lenses.installed(store, device_id)
            lens_id, basis = (None, "unknown") if installed is None else (installed["id"], "installed")
    material_id = saved.get("material_id")
    if material_id is not None and not _exists(store, "material_profile", material_id):
        stale.append("material")
        material_id = None
    if material_id is None:
        first = store.one("SELECT id FROM material_profile ORDER BY id LIMIT 1")
        material_id = None if first is None else first["id"]
    rig = saved.get("capture_setup_id")
    if rig is not None and not _exists(store, "capture_setup", rig):
        stale.append("capture_setup")
        rig = None
    rig = rig if rig is not None else _default_rig(store)
    source = saved.get("source") if isinstance(saved.get("source"), dict) else None
    return {"device_id": device_id, "lens_id": lens_id, "lens_basis": basis, "material_id": material_id, "capture_setup_id": rig,
            "source": source, "stored": bool(saved), "stale": stale,
            "device": None if device_id is None else devices.brief(store, device_id) | {"passport": None},
            "lens": None if lens_id is None else lenses.get_lens(store, lens_id), "material": _material(store, material_id),
            "capture_setup": None if rig is None else su.get_capture_setup(store, rig)}


def _clean_source(store: Store, source) -> dict | None:
    """A source to keep: a connected laboratory release as the pickers give it (``release_id``, ``laser``, ``lens``, ``material``) with the
    label the person saw. It is checked as a work checks it when it is pinned: the release is here, connected, not withdrawn, and it measured
    that laser, lens and titanium. A source that does not serve is refused, never stored."""
    if source is None:
        return None
    if not isinstance(source, dict):
        raise su.ValidationError("choose a laboratory release, its laser, lens and titanium")
    kept = {k: source.get(k) for k in SOURCE_KEYS}
    evidence_source.pin(store, kept, with_material=bool(kept.get("material")))
    label = source.get("label")
    kept["label"] = label.strip()[:MAX_LABEL] if isinstance(label, str) and label.strip() else None
    return kept


def save(store: Store, changes: dict) -> dict:
    """Keep the explicit changes (``device_id``, ``lens_id`` with ``None`` for the unknown lens, ``material_id``, ``capture_setup_id``,
    ``source`` with ``None`` for the own measurements); what is not named stays as it is. Every record must exist. Changing the laser
    without naming a lens takes the lens standing on the new laser."""
    present = get(store)
    saved = _stored(store)
    saved = {k: saved[k] for k in ("device_id", "lens_id", "material_id", "capture_setup_id", "source") if k in saved}
    if "device_id" in changes:
        device = changes["device_id"]
        if not _exists(store, "laser_device", device):
            raise su.ValidationError("the selected laser was not found; choose it again")
        if device != present["device_id"] and "lens_id" not in changes:
            saved.pop("lens_id", None)
        saved["device_id"] = device
    if "lens_id" in changes:
        lens = changes["lens_id"]
        if lens is not None and not _exists(store, "lens", lens):
            raise su.ValidationError("the selected lens was not found; choose it again")
        saved["lens_id"] = lens
    if "material_id" in changes:
        if not _exists(store, "material_profile", changes["material_id"]):
            raise su.ValidationError("the selected titanium stock was not found; choose it again")
        saved["material_id"] = changes["material_id"]
    if "capture_setup_id" in changes:
        rig = changes["capture_setup_id"]
        if rig is not None:
            if not _exists(store, "capture_setup", rig):
                raise su.ValidationError("the selected photography setup was not found; choose it again")
            if su.get_capture_setup(store, rig)["legacy"]:
                raise su.ValidationError("the placeholder capture setup describes only pairs uploaded before every photograph had a rig; choose the rig of this photograph")
        saved["capture_setup_id"] = rig
    if "source" in changes:
        saved["source"] = _clean_source(store, changes["source"])
    store.set_setting(KEY, saved)
    store.audit("creation_context_saved", **{k: v for k, v in saved.items() if k != "source"}, source=bool(saved.get("source")))
    return get(store)


# -- what a setup can start -----------------------------------------------------------------------------------------------------
def measured(store: Store, device_id: int, lens_id: int | None, material_id: int | None) -> dict:
    """How many things each result can start from on this laser, lens and titanium, from the workshop's own measurements: measured scales for
    a photo work, measured fill colours for colour areas, validated or production fill and line recipes for a silhouette and for lines."""
    scales = [m for m in ps.scale_modes(store, device_id, lens_id, material_id) if m.lens_id == lens_id]
    out = {"photo": len(scales), "colour": 0, "silhouette": 0, "lines": 0}
    if material_id is None:
        return out
    out["colour"] = len(palette.vector_palette(store, device_id, lens_id, material_id)["entries"])
    recipes = vector_job.eligible(store, device_id, lens_id, material_id)
    out["silhouette"] = sum(e["mode"] in cv.FILL_MODES for e in recipes)
    out["lines"] = sum(e["mode"] in cv.LINE_MODES for e in recipes)
    return out


def _installed_id(store: Store, device_id: int) -> int | None:
    lens = lenses.installed(store, device_id)
    return None if lens is None else lens["id"]


def impact(store: Store, candidate: dict) -> dict:
    """What it does to start from ``candidate`` (the keys of :func:`save`) instead of the present context. Nothing is changed. ``warnings``
    are structured findings, none of which stops the change: the person reads them and confirms or not."""
    now = get(store)
    wanted = dict(now)
    if "device_id" in candidate:
        if not _exists(store, "laser_device", candidate["device_id"]):
            raise su.ValidationError("the selected laser was not found; choose it again")
        wanted["device_id"] = candidate["device_id"]
        if "lens_id" not in candidate:
            wanted["lens_id"] = _installed_id(store, candidate["device_id"])
    if "lens_id" in candidate:
        if candidate["lens_id"] is not None and not _exists(store, "lens", candidate["lens_id"]):
            raise su.ValidationError("the selected lens was not found; choose it again")
        wanted["lens_id"] = candidate["lens_id"]
    if "material_id" in candidate:
        if not _exists(store, "material_profile", candidate["material_id"]):
            raise su.ValidationError("the selected titanium stock was not found; choose it again")
        wanted["material_id"] = candidate["material_id"]
    if "source" in candidate:
        wanted["source"] = candidate["source"]
    keys = ("device_id", "lens_id", "material_id")
    changed = any(wanted[k] != now[k] for k in keys) or (wanted["source"] or None) != (now["source"] or None)
    out = {"changed": changed, "warnings": [], "now": None, "after": None}
    if wanted["device_id"] is None:
        return out
    after_counts = measured(store, wanted["device_id"], wanted["lens_id"], wanted["material_id"])
    now_counts = None if now["device_id"] is None else measured(store, now["device_id"], now["lens_id"], now["material_id"])
    out["after"], out["now"] = after_counts, now_counts
    if not changed:
        return out
    warnings = out["warnings"]
    if wanted["source"]:                                                  # the colours and scales come from the laboratory, not from here
        try:
            evidence_source.pin(store, wanted["source"], with_material=bool(wanted["source"].get("material")))
        except (su.ValidationError, KeyError) as exc:
            warnings.append({"code": "source_unavailable", "detail": str(exc)})
    elif now["source"]:
        warnings.append({"code": "source_dropped"})
    for result in RESULTS:
        before, after = (None if now_counts is None else now_counts[result]), after_counts[result]
        if wanted["source"] and result in ("photo", "colour"):
            continue                                                       # these two are the laboratory's, counted nowhere here
        if before and after == 0:
            warnings.append({"code": "none_left", "result": result, "now": before})
        elif before and after < before:
            warnings.append({"code": "fewer", "result": result, "now": before, "after": after})
    if (wanted["device_id"], wanted["lens_id"]) != (now["device_id"], now["lens_id"]):         # the lens is told about only when this change is its cause
        if wanted["lens_id"] is None:
            warnings.append({"code": "lens_unknown"})
        elif wanted["lens_id"] != _installed_id(store, wanted["device_id"]):
            warnings.append({"code": "lens_not_installed", "lens_id": wanted["lens_id"]})
    if wanted["material_id"] != now["material_id"] and now["material"] and wanted["material_id"] is not None:
        if su.titanium_key(_material(store, wanted["material_id"])) != su.titanium_key(now["material"]):
            warnings.append({"code": "titanium_differs", "now": now["material"]["id"], "after": wanted["material_id"]})
    return out


# -- what a result needs --------------------------------------------------------------------------------------------------------
def readiness(store: Store, result: str) -> dict:
    """Whether ``result`` can be started with the present context, what is missing if not, and, when only measurements are, the starter test.

    ``missing`` lists, in the order the person can fix them, ``laser``, ``titanium``, ``lens`` (a test is engraved through the lens standing on
    the laser) and ``measurements``. ``starter_test`` is given with ``measurements`` only and names the plate type, whether the photography
    setup it needs is there (``needs_rig``) and what accepted measurements make available (``becomes``)."""
    if result not in RESULTS:
        raise su.ValidationError("choose what the work will be: colour areas, photo engraving, a silhouette or lines")
    context = get(store)
    missing = []
    if context["device_id"] is None:
        missing.append("laser")
    if context["material_id"] is None:
        missing.append("titanium")
    count = None
    if not missing:
        count = measured(store, context["device_id"], context["lens_id"], context["material_id"])[result]
        own = context["source"] is None or result not in ("photo", "colour")
        if own and count == 0:
            if _installed_id(store, context["device_id"]) is None:
                missing.append("lens")
            missing.append("measurements")
    out = {"result": result, "ready": not missing, "missing": missing, "context": context, "measured": count, "starter_test": None}
    if "measurements" in missing and "lens" not in missing:
        out["starter_test"] = starter_test(store, context, result)
    return out


def starter_test(store: Store, context: dict, result: str) -> dict:
    """The test to start from for ``result``: grey scales for a photo work; for the vector results the next plate the experiment guide proposes
    for the task (what it says is the guide's own, nothing is added), so the person is shown the same step the experiment screens give."""
    rig_ready = context["capture_setup_id"] is not None
    base = {"result": result, "needs_rig": not rig_ready, "becomes": BECOMES[result], "device_id": context["device_id"],
            "material_id": context["material_id"], "test_type": None, "guide": None}
    if result == "photo":
        return base | {"test_type": GREY_SCALES}
    guide = application_guide.suggest(store, context["device_id"], context["material_id"], task=TASK_OF[result])
    plate = guide.get("plate")
    kept = {k: guide.get(k) for k in ("status", "message", "next_step", "pending_plan_id")}
    return base | {"test_type": None if plate is None else plate["test_type"], "task": TASK_OF[result], "guide": kept}


def make_starter_plate(store: Store, context: dict, result: str) -> dict:
    """Create the starter test of a vector result as the experiment guide proposes it (the same step as ``/application-guide/next-plate``)
    and return the plate. A photo work's grey scales are made in the plate dialog, which asks for the settings; nothing is chosen for it here."""
    from . import capability_plates
    if result not in TASK_OF:
        raise su.ValidationError("the grey scales are made in the test dialog, which asks for their settings")
    suggestion = application_guide.suggest(store, context["device_id"], context["material_id"], task=TASK_OF[result])
    plate = suggestion["plate"]
    if plate is None:
        raise su.ValidationError(suggestion["message"])
    settings = {**plate["settings"], "research_goal": suggestion["goal"], "source_pair_id": plate["source_pair_id"], "task": TASK_OF[result]}
    return capability_plates.create(store, context["device_id"], context["material_id"], plate["test_type"], settings)
