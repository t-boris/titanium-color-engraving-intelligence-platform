"""A portable laboratory release of own results (electron REQ-083, DEC-024, DEC-042): the owner chooses lasers and lenses, titanium and
experiments, reviews what is published and what never is, picks the usage terms, and the release is written as ``.tcelab``
(:mod:`lab_format`) one record at a time.

A record holds numbers, a few enumerations, labels and UUIDs:

* every local record gets a portable UUID once (``portable_id``) and keeps it in every later release, so a connected workshop knows an
  observation it has seen and a saved work keeps its recipe;
* names are not published: layers become ``C01``... (layers of one photograph that share a name share the label), engravings,
  photographs and files have none; the laboratory, its author and its lasers are named by what the owner enters for publication;
* LightBurn settings keep their numbers and enumerations; any other text (a sub-layer's name) becomes ``tok:`` and a keyed hash
  (HMAC-SHA-256 under the workshop's own secret, never exported): equal texts stay equal, so recipes are told apart as before, and the
  text cannot be read back;
* the cleaning witness of each photograph is published as such, also where it was found again from the stored LightBurn file
  (``colormap.references``), and every row length is published with its layer (:mod:`row_length`): a connected workshop needs neither
  file.

Nothing else leaves the workshop: photographs, RAW files, previews, LightBurn geometry, masks, paths and file names, notes,
discrepancies, reasons, AI conversations, serial numbers, the titanium's batch and surface (DEC-024).

A photograph is published with every one of its measured layers and tonal profiles or not at all: the counts of a release are those of
what it holds. Only accepted photographs are published; a connected laboratory's results are not this workshop's to publish (REQ-083).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping

from . import (__version__, color, colormap, experiments, ingest, lab_format as lf, palette, photo_modes, plans as pl, prediction,
               row_length, tasks)
from . import setup as su
from .db import Store, now

PRODUCER = "titanium-platform"
IDENTITY = "lab.identity"            # setting: this workshop's laboratory id and the secret its tokens are made with (never exported)
PUBLIC = "lab.public"                # setting: what the owner publishes about the laboratory, its author and its lasers
WITHDRAWALS = "lab.withdrawals"      # setting: what the owner withdrew from earlier releases, published with every later one
PAGE = 500                           # pairs read at a time
ENUMERATED = frozenset({"ditherMode", "scanOpt", "fgPathAlgorithm", "type", "shape", "mode"})
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
PARAMETERS = ("power", "frequency", "speed", "pulse_width", "line_interval", "passes", "global_passes", "layer_type", "bidirectional",
              "cross_hatch", "scan_angle", "angle_increment", "grayscale", "source_settings")
INTEGERS = ("passes", "global_passes")
NEVER = ("photographs", "raw", "previews", "lightburn_geometry", "masks", "paths", "file_names", "titles", "layer_names", "notes",
         "ai", "credentials", "email", "serial", "batch", "surface", "free_text_settings")


# -- identity ---------------------------------------------------------------------------------------------------------------------
def identity(store: Store) -> dict:
    """This workshop's laboratory: its stable id and the secret of its tokens, made once."""
    found = store.get_setting(IDENTITY)
    if not found:
        found = {"origin_lab_id": str(uuid.uuid4()), "secret": secrets.token_hex(32), "created_at": now()}
        store.set_setting(IDENTITY, found)
    return found


def portable_ids(store: Store, kind: str, keys) -> dict[str, str]:
    """The portable UUID of each local record ``kind``/``key``, given once and kept (DEC-024)."""
    keys = [str(k) for k in keys]
    found = {r["local_key"]: r["uuid"] for r in store.query("SELECT local_key, uuid FROM portable_id WHERE kind=?", (kind,))}
    new = [(kind, key, str(uuid.uuid4()), now()) for key in dict.fromkeys(keys) if key not in found]
    if new:
        with store.transaction():
            store.conn.executemany("INSERT INTO portable_id(kind, local_key, uuid, created_at) VALUES (?,?,?,?)", new)
        found.update({key: value for _, key, value, _ in new})
    return {key: found[key] for key in keys}


def token(secret: str, text: str) -> str:
    """A text of a setting as it is published: equal texts give equal tokens, the text cannot be read back."""
    return "tok:" + hmac.new(bytes.fromhex(secret), text.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _public_key(key: str, secret: str) -> str:
    return key if lf.KEY.fullmatch(key) else "t_" + token(secret, key)[4:]


def public_setting(value, secret: str, tag: str | None = None):
    """A LightBurn setting as it is published: numbers and the words of enumerated settings as they are, any other text a token."""
    if isinstance(value, Mapping):
        return {_public_key(k, secret): public_setting(v, secret, tag if k == "Value" else k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_setting(v, secret, tag) for v in value]
    if isinstance(value, str):
        if NUMBER.fullmatch(value) or (tag in ENUMERATED and WORD.fullmatch(value)):
            return value
        try:
            number = float(value)
        except ValueError:
            number = math.nan
        return repr(number) if math.isfinite(number) else token(secret, value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def public_parameters(parameters: Mapping, secret: str) -> dict:
    """The settings of a measured layer as published: those a recipe is told apart by, present as they are stored."""
    out = {}
    for key in PARAMETERS:
        if key not in parameters:
            continue
        value = parameters[key]
        out[key] = public_setting(value, secret) if key == "source_settings" else value
    if not isinstance(out.get("source_settings", {}), Mapping):
        out["source_settings"] = {}
    return out


def utc(text: str | None) -> str:
    """A stored time as a release writes it: UTC, to the microsecond, so that times keep their order as text."""
    when = datetime.fromisoformat(str(text).replace("Z", "+00:00")) if text else datetime(1970, 1, 1, tzinfo=timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def algorithm_versions() -> dict:
    """The versions of the calculations a release's numbers were made and are to be used with."""
    return {"evidence": colormap.ALGORITHM, "palette": palette.ALGORITHM, "prediction": prediction.ALGORITHM,
            "row_length": row_length.ALGORITHM, "tonal_profile": ingest.TONAL_PROFILE_ALGORITHM, "against_clean": color.AGAINST_CLEAN_ALGORITHM}


# -- what the owner publishes about the laboratory ---------------------------------------------------------------------------
def public_info(store: Store) -> dict:
    """The laboratory's public name, description and link, the author named with every release, and each laser's public name."""
    found = store.get_setting(PUBLIC) or {}
    lasers = {}
    for row in store.query("SELECT id, manufacturer, model, data_json FROM laser_device ORDER BY id"):
        given = (found.get("lasers") or {}).get(str(row["id"])) or {}
        label = " ".join(x for x in (row["manufacturer"], row["model"]) if x).strip()
        lasers[str(row["id"])] = {"public_name": given.get("public_name") or label or f"Laser {len(lasers) + 1}",
                                  "manufacturer": given.get("manufacturer", row["manufacturer"]), "model": given.get("model", row["model"])}
    return {"name": found.get("name") or "", "description": found.get("description") or "", "url": found.get("url"),
            "author": found.get("author") or "", "organization": found.get("organization"), "author_url": found.get("author_url"),
            "lasers": lasers}


def set_public_info(store: Store, info: Mapping) -> dict:
    """Keep what the owner enters for publication, checked as a release checks it."""
    lasers = {str(device_id): {key: _public_text(laser, key, 200 if key == "public_name" else 100) for key in ("public_name", "manufacturer", "model")}
              for device_id, laser in (info.get("lasers") or {}).items()}
    stored = {"name": _public_text(info, "name", 200), "description": _public_text(info, "description", 2000, multiline=True),
              "url": _public_link(info, "url"), "author": _public_text(info, "author", 200),
              "organization": _public_text(info, "organization", 200), "author_url": _public_link(info, "author_url"), "lasers": lasers}
    store.set_setting(PUBLIC, stored)
    return public_info(store)


def _public_text(item: Mapping, key: str, limit: int, multiline: bool = False) -> str | None:
    raw = str(item.get(key) or "")
    value = raw.strip() if multiline else " ".join(raw.split())
    if len(value) > limit:
        raise su.ValidationError(f"the public text {key} is longer than {limit} characters")
    if value:
        try:
            lf.check_text(value, key, multiline)
        except lf.FormatError:
            raise su.ValidationError(f"the public text {key} may hold only plain text: no links, scripts or file paths") from None
    return value or None


def _public_link(item: Mapping, key: str) -> str | None:
    value = str(item.get(key) or "").strip()
    if not value:
        return None
    try:
        lf.check_url(value, key)
    except lf.FormatError:
        raise su.ValidationError(f"the link {key} must be an https address of a named site") from None
    return value


# -- what is chosen ---------------------------------------------------------------------------------------------------------------
WITHDRAWN_KINDS = {"release": None, "measurement": "observation", "tone_profile": "tonal"}   # what can be withdrawn: its portable_id kind


def withdraw(store: Store, target_kind: str, target_id: str, reason: str, replacement_release_id: str | None = None) -> dict:
    """Withdraw a published release, measurement or tonal profile (REQ-084): the statement, with its reason and replacement, goes out
    with every later release of this laboratory; what was published is not changed."""
    if target_kind not in WITHDRAWN_KINDS:
        raise su.ValidationError("only a release, a measurement or a tonal profile can be withdrawn")
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise su.ValidationError("give the reason of the withdrawal")
    if len(reason) > 500:
        raise su.ValidationError("the reason of the withdrawal is longer than 500 characters")
    try:
        lf.check_text(reason, "reason")
    except lf.FormatError:
        raise su.ValidationError("the reason of the withdrawal may hold only plain text: no links, scripts or file paths") from None
    kind = WITHDRAWN_KINDS[target_kind]
    published = (store.one("SELECT 1 FROM lab_export WHERE release_id=?", (target_id,)) if kind is None else
                 store.one("SELECT 1 FROM portable_id WHERE kind=? AND uuid=?", (kind, target_id)))
    if published is None:
        raise su.ValidationError("this laboratory never published what is to be withdrawn")
    if replacement_release_id is not None and store.one("SELECT 1 FROM lab_export WHERE release_id=?", (replacement_release_id,)) is None:
        raise su.ValidationError("the replacement must be a release of this laboratory")
    listed = withdrawals(store)
    if any(w["target_kind"] == target_kind and w["target_id"] == target_id for w in listed):
        raise su.ValidationError("this is withdrawn already")
    item = {"id": str(uuid.uuid4()), "kind": "withdrawal", "target_kind": target_kind, "target_id": target_id, "reason": reason,
            "replacement_release_id": replacement_release_id, "declared_at": lf.utc_now()}
    store.set_setting(WITHDRAWALS, listed + [item])
    store.audit("lab_withdrawn", target_kind=target_kind, target_id=target_id)
    return item


def withdrawals(store: Store) -> list[dict]:
    """What this laboratory withdrew, as it goes out with every later release."""
    return list(store.get_setting(WITHDRAWALS) or [])


def exports(store: Store) -> list[dict]:
    """The releases this workshop wrote, newest first."""
    return [{**dict(r), "manifest": json.loads(r["manifest_json"])}
            for r in store.query("SELECT release_id, content_sha256, created_at, manifest_json, bytes FROM lab_export ORDER BY created_at DESC, release_id")]


def _experiment_kind(plan_mode: str | None) -> str:
    return "test" if plan_mode in colormap.TEST_PLANS else "vector_work" if plan_mode == pl.MODE_VECTOR else "other"


def _pairs(store: Store, selection: Mapping | None) -> list[dict]:
    """The accepted photographs ``selection`` chooses, in the order they were added: ``setups`` (keys of lasers and lenses), ``materials``
    (titanium stock record ids, None for none) and ``exclude`` (experiment keys); a missing choice takes everything."""
    selection = selection or {}
    setups = None if selection.get("setups") is None else set(selection["setups"])
    materials = None if selection.get("materials") is None else set(selection["materials"])
    excluded = set(selection.get("exclude") or ())
    kept = experiments.kept_plan_ids(store)
    out = []
    for row in store.query("SELECT p.id, p.device_id, p.lens_id, p.material_id, p.plan_id, p.engraving_id, p.accepted_at, p.created_at, "
                           "p.lightburn_path, json_extract(p.context_json, '$.batch') AS batch, pl.mode AS plan_mode "
                           "FROM pair p LEFT JOIN plan pl ON pl.id=p.plan_id WHERE p.status='Accepted' ORDER BY p.id"):
        item = dict(row)
        item["setup"] = su.setup_key(row["device_id"], row["lens_id"])
        item["experiment"] = experiments.plan_key(row["plan_id"]) if row["plan_id"] in kept else experiments.engraving_key(row["engraving_id"])
        item["kept"] = row["plan_id"] in kept
        if (setups is not None and item["setup"] not in setups) or (materials is not None and row["material_id"] not in materials):
            continue
        if item["experiment"] in excluded:
            continue
        out.append(item)
    return out


def _checks(store: Store, pair_ids: list[int]) -> Iterator[tuple[int, dict]]:
    for start in range(0, len(pair_ids), PAGE):
        ids = pair_ids[start:start + PAGE]
        for row in store.query(f"SELECT id, data_json FROM pair WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", ids):
            yield row["id"], json.loads(row["data_json"] or "{}").get("check") or {}


def _observations(store: Store, pair_ids: list[int], columns: str, order: str) -> Iterator:
    for start in range(0, len(pair_ids), PAGE):
        ids = pair_ids[start:start + PAGE]
        yield from store.query(f"SELECT {columns} FROM observation WHERE pair_id IN ({','.join('?' * len(ids))}) ORDER BY {order}", ids)


def _label(index: int) -> str:
    return f"C{index:02d}" if index >= 0 else f"C-{-index:02d}"


class _Layers:
    """What the records of the chosen photographs are named and how they relate, read once without their values: each layer name's label
    (the label of its first index, so that layers sharing a name share it), the first observation of each name, each observation's role
    and what the tonal profiles need to be declared."""

    def __init__(self, store: Store, pairs: list[dict]):
        ids = [p["id"] for p in pairs]
        refs = colormap.references(store)
        explicit = {row["pair_id"] for row in refs["rows"]
                    if json.loads(row["evidence_json"] or "{}").get("role") == colormap.WITNESS or row["layer_index"] == -1}
        lowest: dict[int, dict] = {}
        witnessed: set[int] = set()
        self.first: dict[int, dict] = {}
        self.roles: dict[int, str] = {}
        self.tonal: list[str] = []
        self.capabilities = {"measurements"}
        for row in _observations(store, ids, "id, pair_id, layer_index, json_extract(evidence_json, '$.layer_name') AS name, "
                                             "json_extract(evidence_json, '$.role') AS role", "pair_id, layer_index, id"):
            names = lowest.setdefault(row["pair_id"], {})
            names[row["name"]] = min(names.get(row["name"], row["layer_index"]), row["layer_index"])
            self.first.setdefault(row["pair_id"], {}).setdefault(row["name"], row["id"])
            self.roles[row["id"]] = _role(row, explicit, refs["derived"], witnessed)
        self.observations = sorted(self.roles)
        for pair_id, check in _checks(store, ids):
            for rep in check.get("layers", []):
                if not rep.get("tonal"):
                    continue
                names = lowest.setdefault(pair_id, {})
                names[rep.get("name")] = min(names.get(rep.get("name"), rep["index"]), rep["index"])
                self.tonal.append(f"{pair_id}/{rep['index']}")
                self.capabilities.add("tone_profiles")
                seen = photo_modes.mode((rep.get("image") or {}).get("dither"))
                if seen is not None and seen.key != prediction.PREDICTED_MODE:
                    self.capabilities.add("dot_profiles")
                if rep["tonal"].get("measured_by") == "grey ramp":
                    self.capabilities.add("grey_ramps")
        self.labels = {pair_id: {name: _label(index) for name, index in names.items()} for pair_id, names in lowest.items()}


def _role(row, explicit: set, derived: Mapping, witnessed: set) -> str:
    """How a measured layer takes part, as ``colormap.references`` reads it (rows in its order): the cleaning witness (stated, or the
    first measurement of the cleaning layer found from the file of a photograph without one), a service layer, or a test feature."""
    if row["role"] == colormap.WITNESS or row["layer_index"] == -1:
        return "cleaning_witness"
    if row["role"] in colormap.SERVICE:
        return "service"
    if row["pair_id"] not in explicit and derived.get(row["pair_id"]) == row["layer_index"]:
        if row["pair_id"] in witnessed:
            return "service"             # a second measurement of the cleaning layer: left out of the colours, as here
        witnessed.add(row["pair_id"])
        return "cleaning_witness"
    return "test_feature"


def _number(value):
    return None if value is None else float(value)


def _integer(value):
    return None if value is None else int(value)


# -- the records ------------------------------------------------------------------------------------------------------------------
class _Release:
    """The records of a release of ``pairs``, made lazily section by section in the order the file holds them."""

    def __init__(self, store: Store, pairs: list[dict], secret: str):
        self.store, self.pairs, self.secret = store, pairs, secret
        self.layers = _Layers(store, pairs)
        self.lengths = row_length.recorded(store)
        self.setups = list(dict.fromkeys(p["setup"] for p in pairs))
        self.devices = list(dict.fromkeys(p["device_id"] for p in pairs))
        self.lenses = list(dict.fromkeys(p["lens_id"] for p in pairs if p["lens_id"] is not None))
        self.materials = sorted({p["material_id"] for p in pairs if p["material_id"] is not None})
        self.plans = list(dict.fromkeys(p["plan_id"] for p in pairs if p["plan_id"] is not None))
        self.ids = {"setup": portable_ids(store, "setup", self.setups), "laser": portable_ids(store, "laser", self.devices),
                    "lens": portable_ids(store, "lens", self.lenses), "material": portable_ids(store, "material", self.materials),
                    "plan": portable_ids(store, "plan", self.plans),
                    "engraving": portable_ids(store, "engraving", [p["engraving_id"] for p in pairs]),
                    "pair": portable_ids(store, "pair", [p["id"] for p in pairs]),
                    "observation": portable_ids(store, "observation", self.layers.observations),
                    "tonal": portable_ids(store, "tonal", self.layers.tonal)}

    def _id(self, kind: str, key) -> str:
        return self.ids[kind][str(key)]

    def sections(self) -> dict[str, Iterator[dict]]:
        return {"equipment": self.equipment(), "materials": self.material_records(), "captures": self.captures(),
                "measurements": self.measurements(), "tone_profiles": self.tone_profiles(), "provenance": self.provenance()}

    def equipment(self) -> Iterator[dict]:
        lasers = {str(r["id"]): r for r in self.store.query("SELECT id, data_json FROM laser_device")}
        lenses = {str(r["id"]): r for r in self.store.query("SELECT id, focal_length_mm, field_mm, expansion, spot_diameter_um FROM lens")}
        public = public_info(self.store)["lasers"]
        for seq, key in enumerate(self.setups):
            pair = next(p for p in self.pairs if p["setup"] == key)
            passport = json.loads(lasers[str(pair["device_id"])]["data_json"] or "{}")
            named = public[str(pair["device_id"])]
            lens = lenses.get(str(pair["lens_id"]))
            yield {"id": self._id("setup", key), "seq": seq,
                   "laser": {"id": self._id("laser", pair["device_id"]), "public_name": named["public_name"],
                             "manufacturer": named["manufacturer"], "model": named["model"],
                             "rated_power_w": _finite(passport.get("rated_power_w")), "wavelength_nm": _finite(passport.get("wavelength_nm")),
                             "source_type": None},
                   "lens": None if lens is None else {"id": self._id("lens", pair["lens_id"]), "focal_length_mm": lens["focal_length_mm"],
                                                      "field_mm": lens["field_mm"], "expansion": lens["expansion"],
                                                      "spot_diameter_um": lens["spot_diameter_um"]}}

    def material_records(self) -> Iterator[dict]:
        rows = {r["id"]: r for r in self.store.query("SELECT id, family, grade, thickness_mm FROM material_profile")}
        for seq, material_id in enumerate(self.materials):
            row = rows[material_id]
            yield {"id": self._id("material", material_id), "seq": seq, "family": " ".join((row["family"] or "").split()),
                   "grade": " ".join(row["grade"].split()) if row["grade"] else row["grade"], "thickness_mm": row["thickness_mm"]}

    def captures(self) -> Iterator[dict]:
        meta = {p["id"]: p for p in self.pairs}
        for seq, (pair_id, check) in enumerate(_checks(self.store, list(meta))):
            pair = meta[pair_id]
            yield {"id": self._id("pair", pair_id), "seq": seq, "engraving_id": self._id("engraving", pair["engraving_id"]),
                   "equipment_id": self._id("setup", pair["setup"]),
                   "material_id": None if pair["material_id"] is None else self._id("material", pair["material_id"]),
                   "measured_at": utc(pair["accepted_at"] or pair["created_at"]),
                   "basis": "chart" if (check.get("color_measurement") or {}).get("mode") == "reference_chart_corrected" else "relative",
                   "experiment": None if pair["plan_id"] is None else {"id": self._id("plan", pair["plan_id"]),
                                                                       "kind": _experiment_kind(pair["plan_mode"]), "kept": pair["kept"]},
                   "over_fills": bool((check.get("composition") or {}).get("picture_over_fills")), "batch_known": bool(pair["batch"])}

    def measurements(self) -> Iterator[dict]:
        meta = {p["id"]: p for p in self.pairs}
        ids = self.layers.observations
        seq = 0
        for start in range(0, len(ids), PAGE):
            page = ids[start:start + PAGE]
            for row in self.store.query("SELECT id, pair_id, layer_index, lab_json, parameters_json, model_eligible, repeat_eligible, "
                                        f"evidence_json, task_kind FROM observation WHERE id IN ({','.join('?' * len(page))}) ORDER BY id", page):
                evidence = json.loads(row["evidence_json"] or "{}")
                task = tasks.of_observation(row)
                lengths = row_length.of_pair(self.lengths, row["pair_id"], meta[row["pair_id"]]["lightburn_path"])
                yield {"id": self._id("observation", row["id"]), "seq": seq, "capture_id": self._id("pair", row["pair_id"]),
                       "layer": {"index": row["layer_index"], "label": self.layers.labels[row["pair_id"]][evidence.get("layer_name")],
                                 "role": self.layers.roles[row["id"]]},
                       "lab": [float(v) for v in json.loads(row["lab_json"])], "kind": colormap._kind(evidence, row["model_eligible"]),
                       "model_eligible": bool(row["model_eligible"]), "repeat_eligible": bool(row["repeat_eligible"]),
                       "matrix": bool(evidence.get("matrix_cell")), "task": {"kind": task["kind"], "basis": task.get("basis", tasks.DERIVED)},
                       "parameters": public_parameters(json.loads(row["parameters_json"] or "{}"), self.secret),
                       "row_mm": lengths.get(row["layer_index"])}
                seq += 1

    def tone_profiles(self) -> Iterator[dict]:
        meta = {p["id"]: p for p in self.pairs}
        seq = 0
        for pair_id, check in _checks(self.store, list(meta)):
            lengths = row_length.of_pair(self.lengths, pair_id, meta[pair_id]["lightburn_path"])
            for rep in check.get("layers", []):
                tonal = rep.get("tonal")
                if not tonal:
                    continue
                image = rep.get("image") or {}
                seen = photo_modes.mode(image.get("dither"))
                first = self.layers.first.get(pair_id, {}).get(rep.get("name"))
                task = rep.get("task")
                bins = []
                for step in tonal["bins"]:
                    item = {"gray": float(step["gray"]), "L": float(step["L"]), "a": float(step["a"]), "b": float(step["b"])}
                    if step.get("n") is not None:
                        item["n"] = int(step["n"])
                    if "power_pct" in step:
                        item["power_pct"] = _number(step["power_pct"])
                    bins.append(item)
                yield {"id": self._id("tonal", f"{pair_id}/{rep['index']}"), "seq": seq, "capture_id": self._id("pair", pair_id),
                       "layer": {"index": rep["index"], "label": self.layers.labels[pair_id][rep.get("name")]},
                       "measurement_id": None if first is None else self._id("observation", first),
                       "image": {"dither": seen.key if seen else None,
                                 "dot_correction": None if image.get("dot_correction") is None else bool(image["dot_correction"]),
                                 "dot_width_mm": _number(image.get("dot_width_mm"))},
                       "settings": {"power": _number(rep.get("power")), "speed": _number(rep.get("speed")),
                                    "frequency_khz": _number(rep.get("frequency_khz")), "pulse_width": _number(rep.get("pulse_width")),
                                    "pulse_width_effective": _number(ingest.effective_setting(rep, "pulse_width")),
                                    "line_interval": _number(rep.get("line_interval")), "passes": _integer(rep.get("passes")),
                                    "global_passes": _integer(rep.get("global_passes")), "type": rep.get("type")},
                       "power_range": [float(v) for v in tonal["power_range"]] if tonal.get("power_range") else None,
                       "adjustments": public_setting(tonal.get("adjustments") or {}, self.secret),
                       "measured_by": "grey ramp" if tonal.get("measured_by") == "grey ramp" else "tonal profile",
                       "evidence": "clear" if tonal.get("evidence") == "clear" else "weak",
                       "task": {"kind": task["kind"], "basis": task.get("basis", tasks.DERIVED)} if isinstance(task, Mapping) else None,
                       "row_mm": lengths.get(rep["index"]), "bins": bins}
                seq += 1

    def provenance(self) -> Iterator[dict]:
        for seq, item in enumerate(self.store.get_setting(WITHDRAWALS) or []):
            yield {**{k: item[k] for k in ("id", "kind", "target_kind", "target_id", "reason", "replacement_release_id", "declared_at")},
                   "seq": seq}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# -- choosing, previewing and writing ---------------------------------------------------------------------------------------------
def choices(store: Store) -> dict:
    """What can be published: every laser and lens, titanium stock record and experiment with accepted photographs, with how many
    photographs, as the owner sees them here (local names: this is the owner's own screen)."""
    pairs = _pairs(store, None)
    lasers = {r["id"]: r["name"] for r in store.query("SELECT id, name FROM laser_device")}
    lenses = {r["id"]: r["name"] for r in store.query("SELECT id, name FROM lens")}
    materials = {r["id"]: r for r in store.query("SELECT id, name, family, grade FROM material_profile")}
    titles = {r["engraving_id"]: r["title"] for r in store.query(
        "SELECT engraving_id, COALESCE(MAX(engraving_title), MAX(lightburn_name)) AS title FROM pair GROUP BY engraving_id")}
    plans = {r["id"]: r["name"] for r in store.query("SELECT id, name FROM plan")}
    setups, stock, groups = {}, {}, {}
    for p in pairs:
        setups.setdefault(p["setup"], {"key": p["setup"], "laser": lasers.get(p["device_id"]), "lens": lenses.get(p["lens_id"]), "photographs": 0})
        setups[p["setup"]]["photographs"] += 1
        m = materials.get(p["material_id"])
        stock.setdefault(p["material_id"], {"id": p["material_id"], "name": m["name"] if m else None, "grade": m["grade"] if m else None,
                                            "photographs": 0})
        stock[p["material_id"]]["photographs"] += 1
        title = plans.get(p["plan_id"]) if p["kept"] else titles.get(p["engraving_id"])
        groups.setdefault(p["experiment"], {"key": p["experiment"], "title": title, "kind": _experiment_kind(p["plan_mode"]), "photographs": 0})
        groups[p["experiment"]]["photographs"] += 1
    return {"setups": list(setups.values()), "materials": list(stock.values()), "experiments": list(groups.values()),
            "terms": [{"id": k, **v} for k, v in lf.USAGE_TERMS.items()], "public": public_info(store)}


def preview(store: Store, selection: Mapping | None = None) -> dict:
    """What a release of ``selection`` publishes, before anything is written (REQ-083): how many photographs, measured layers and tonal
    profiles of how many engravings, the public text the owner entered, the settings whose text becomes a token, and what is never
    published."""
    pairs = _pairs(store, selection)
    ids = [p["id"] for p in pairs]
    measured = sum(1 for _ in _observations(store, ids, "id", "id"))
    profiles = sum(1 for _, check in _checks(store, ids) for rep in check.get("layers", []) if rep.get("tonal"))
    tokens: dict[str, set] = {}
    for row in _observations(store, ids, "parameters_json", "id"):
        _collect_tokens(json.loads(row["parameters_json"] or "{}").get("source_settings") or {}, None, tokens)
    public = public_info(store)
    devices = {p["device_id"] for p in pairs}
    return {"photographs": len(pairs), "engravings": len({p["engraving_id"] for p in pairs}), "measurements": measured,
            "tone_profiles": profiles, "setups": len({p["setup"] for p in pairs}), "materials": len({p["material_id"] for p in pairs}),
            "public": {**{k: public[k] for k in ("name", "description", "url", "author", "organization", "author_url")},
                       "lasers": {k: v for k, v in public["lasers"].items() if int(k) in devices}},
            "tokenised": {tag: sorted(values) for tag, values in sorted(tokens.items())}, "never": list(NEVER),
            "terms": [{"id": k, **v} for k, v in lf.USAGE_TERMS.items()], "ready": bool(public["name"] and public["author"] and pairs)}


def _collect_tokens(value, tag, out: dict) -> None:
    if isinstance(value, Mapping):
        for k, v in value.items():
            _collect_tokens(v, tag if k == "Value" else k, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _collect_tokens(v, tag, out)
    elif isinstance(value, str) and not NUMBER.fullmatch(value) and not (tag in ENUMERATED and WORD.fullmatch(value)):
        try:
            if math.isfinite(float(value)):
                return
        except ValueError:
            pass
        out.setdefault(tag or "", set()).add(value)


def export(store: Store, path: str | Path, selection: Mapping | None, terms: str, *, release_id: str | None = None,
           release_number: int | None = None, progress: Callable[[str, int], None] | None = None,
           cancelled: Callable[[], bool] | None = None, policy: lf.ResourcePolicy = lf.DEFAULT_POLICY) -> dict:
    """Write a release of ``selection`` under the usage ``terms`` (DEC-042) to ``path`` and return its manifest. ``release_id`` and
    ``release_number`` come from the cloud when it reserved them; a file export makes its own id and has no number (DEC-024). ``policy``
    is the release's resource limits (``tools/bench_tcelab.py`` measures beyond the default ones)."""
    if terms not in lf.USAGE_TERMS:
        raise su.ValidationError("choose usage terms from the approved list")
    public = public_info(store)
    if not public["name"] or not public["author"]:
        raise su.ValidationError("enter the laboratory's public name and the author before publishing")
    if release_id is not None and store.one("SELECT 1 FROM lab_export WHERE release_id=?", (release_id,)) is not None:
        raise su.ValidationError("a release with this identity was published already: a release never changes")
    pairs = _pairs(store, selection)
    if not pairs:
        raise su.ValidationError("nothing is chosen: choose a laser, a titanium or an experiment with accepted photographs")
    own = identity(store)
    release = _Release(store, pairs, own["secret"])
    required = sorted(release.layers.capabilities | ({"withdrawals"} if store.get_setting(WITHDRAWALS) else set()))
    manifest = {"format": lf.FORMAT, "schema_version": lf.SCHEMA_VERSION, "origin_lab_id": own["origin_lab_id"],
                "release_id": release_id or str(uuid.uuid4()), "release_number": release_number, "created_at": lf.utc_now(),
                "producer": {"name": PRODUCER, "version": __version__}, "algorithm_versions": algorithm_versions(),
                "capabilities": {"required": required, "optional": []},
                "usage_terms": {"id": terms, "version": lf.USAGE_TERMS[terms]["version"]},
                "attribution": {"name": public["author"], "organization": public["organization"], "url": public["author_url"]}}
    lab = {"id": own["origin_lab_id"], "name": public["name"], "description": public["description"], "url": public["url"]}
    try:
        written = lf.write(path, manifest, lab, release.sections(), policy=policy, progress=progress, cancelled=cancelled)
    except lf.FormatError as exc:
        raise su.ValidationError(f"the release cannot be written: {exc}") from exc
    store.execute("INSERT INTO lab_export(release_id, content_sha256, created_at, manifest_json, selection_json, bytes) VALUES (?,?,?,?,?,?)",
                  (written["release_id"], written["content_sha256"], now(), json.dumps(written), json.dumps(dict(selection or {})),
                   Path(path).stat().st_size))
    store.audit("lab_exported", release_id=written["release_id"], counts=written["counts"], terms=terms)
    return written
