"""How a picture is engraved on a measured scale as the operator chooses it, one core for a photo engraving work (:mod:`photo_work`,
REQ-061) and a photo zone of a vector work (:mod:`photo_zones`, REQ-073): the kind of engraving and its powers, how the greys are chosen
for the picture's colours, the contours, the main colours of the picture's objects, the rules of its parts and what the AI answered.

A state is a mapping with :data:`SETTINGS` and the AI's last answers (missing ones read as :data:`DEFAULTS`):

* ``min_power`` and ``max_power``: grayscale's white and black;
* ``by_colour``: the greys are chosen for the picture's colours, and how (``colour_choice``, DEC-108, DEC-109: keeping the drawing, the
  nearest colour or colouring the objects); ``contours``: the edges the engraving would lose are drawn in (only with ``by_colour``);
* ``colouring``: the main colours of the picture's objects (0.21.0, :mod:`objects`, :mod:`colouring`): an object's key to its
  ``power`` and ``shift``, used with ``colour_choice`` "objects";
* ``rules``: the rules of the picture's parts (REQ-062, :mod:`picture_rules`), found by the people model (:mod:`people`);
* ``kind``: grayscale or one of LightBurn's dot kinds (:data:`KINDS`), whose dots all fire at ``dot_power``; a dot kind engraves the
  picture as it is (the greys chosen for colours, the contours and the rules are grayscale's and wait for it);
* ``ai_photo``: whether a reduced copy of the picture may be sent to the AI; ``ai`` and ``ai_theme``: its last answers.

The owner keeps the rest: the picture (``upload``, as ``prediction_store.decode_upload`` makes it), the scale's mode, the width its rows
are as long as (DEC-107), and how a change is saved and undone. Nothing here reads or writes the store's works.
"""
from __future__ import annotations

import re
from typing import Callable, Mapping

import cv2
import numpy as np

from . import (ai_colouring as ai, ai_picture, color, colouring as co, conversion as cv, drawing, grayscale, objects as ob, people, photo_modes,
               picture_rules, prediction, prediction_store as ps, research, setup as su)
from .db import Store, now
from .prediction import PredictionError

GRAYSCALE = prediction.PREDICTED_MODE
# every kind of photo engraving that colours titanium: LightBurn's image modes (``photo_modes``) but 3D slice, which engraves relief
KINDS = tuple(key for key, kind in photo_modes.MODES.items() if kind.family != photo_modes.DEPTH)
MAX_COLOURED = 32                   # main colours a state keeps at most: one per object
PART_MIN_SHARE = 0.005              # a part covering less of the picture is not offered (to the operator or the AI): it is noise of the model
SETTINGS = ("min_power", "max_power", "by_colour", "colour_choice", "contours", "rules", "colouring", "kind", "dot_power", "ai_photo")
# what a state made before the rules of parts (0.19.0), the drawing kept (0.20.1) or the kinds and objects (0.21.0) has
DEFAULTS = {"colour_choice": drawing.CHOICES[0], "contours": False, "rules": [], "colouring": {}, "kind": GRAYSCALE, "dot_power": None,
            "ai_photo": False, "ai": None, "ai_theme": None}


def dotted(state: Mapping) -> bool:
    """Whether the picture is engraved in a dot kind: every dot at one power, the tone by how many dots there are."""
    return state["kind"] != GRAYSCALE


# -- the picture as it is engraved ------------------------------------------------------------------------------------------------
def item(store: Store, mode: ps.Mode, upload: dict, state: Mapping, name: str, width_mm: float) -> dict:
    """The picture prepared on the scale ``mode`` at ``width_mm``; in a dot kind as it is (its greys are not chosen, its parts not ruled).
    The objects and the people model's scores are found once per decoded picture and kept with it."""
    toned = not dotted(state)
    out = ps.picture_item(store, mode, upload, name, toned and state["by_colour"], width_mm, state["colour_choice"], toned and state["contours"],
                          state["colouring"])
    if toned and state["by_colour"] and state["colour_choice"] == "objects" and state["colouring"]:
        out["objects"] = objects(upload)
    if toned and state["rules"]:
        out["part_scores"] = ps.part_scores(upload)
    return out


def engraved(prepared: dict, state: Mapping) -> dict:
    """The prepared picture (:func:`item`) as it is engraved: its own greys, the greys chosen for its colours (``by_colour``), inside each
    part with a rule that rule's greys, and the lost edges drawn in (``prediction_store.engraved``)."""
    return ps.engraved(prepared, state["min_power"], state["max_power"], state["rules"])


def reduced(upload: Mapping, px: int) -> tuple[np.ndarray, np.ndarray]:
    """The picture's grey and opacity with the longer side at most ``px``."""
    grey, alpha = upload["picture"], upload["alpha"]
    rows, cols = grey.shape
    scale = min(1.0, px / max(rows, cols))
    if scale >= 1:
        return grey, alpha
    size = (max(1, round(cols * scale)), max(1, round(rows * scale)))
    return cv2.resize(grey, size, interpolation=cv2.INTER_AREA), cv2.resize(alpha, size, interpolation=cv2.INTER_AREA)


def dot_look(store: Store, mode: ps.Mode, grey: np.ndarray, alpha: np.ndarray, state: Mapping, width_mm: float, curve: prediction.Curve,
             measured: prediction.Curve | None = None) -> tuple[np.ndarray, dict]:
    """The picture (``grey`` and ``alpha``) in the state's dot kind seen from a distance: the look (RGB uint8) and the dots
    (``prediction_store.dots_at`` at the state's ``dot_power`` on the scale's ``curve``). With the ``measured`` tones of the kind each tone
    takes its photographed colour (``prediction.render``); without, it is estimated from the scale (``prediction_store.dot_look``) with the
    share of the picture the dots strike."""
    dots = ps.dots_at(store, state["dot_power"], curve)
    if measured is not None:
        rendered = prediction.render(grey, None, None, measured, None, alpha=alpha)
        return rendered["rgb8"], {**dots, "struck_share": None, "measured": {"tones": len(measured.points), "span": list(measured.span),
                                                                            "outside_share": rendered["outside_share"], "notes": rendered["notes"]}}
    rgb8, share = ps.dot_look(grey, alpha, state["kind"], dots["lab"], dots["clean_lab"], width_mm, grayscale.image_dpi(mode.line_interval))
    opaque = np.asarray(alpha) >= photo_modes.ALPHA_MIN
    return rgb8, {**dots, "struck_share": round(float(share[opaque].mean()), 4) if opaque.any() else 0.0, "measured": None}


# -- a change of the state ----------------------------------------------------------------------------------------------------------
def change(store: Store, state: dict, changes: Mapping, mode: ps.Mode, width_mm: float, moved: bool = False) -> None:
    """Make the ``changes`` of :data:`SETTINGS` in ``state``, each checked: Min and Max, ``by_colour`` and ``colour_choice``, ``contours``, the
    ``rules`` of the parts, the main colours of the objects (``colouring``), the ``kind`` and the power of a dot kind's dots (``dot_power``,
    inside the scale's measured powers at ``width_mm``), whether the picture may go to the AI (``ai_photo``). ``mode`` is the scale after
    the change; with ``moved`` the owner changed the scale or the width: a dot kind's power is kept while the scale is measured there,
    otherwise it goes where its colour stands out most (as after a change of the kind)."""
    if "min_power" in changes or "max_power" in changes:
        state["min_power"], state["max_power"] = ps.check_power_range(changes.get("min_power", state["min_power"]),
                                                                      changes.get("max_power", state["max_power"]))
    if "by_colour" in changes:
        if not isinstance(changes["by_colour"], bool):
            raise su.ValidationError("the colour choice must be on or off")
        state["by_colour"] = changes["by_colour"]
    if "colour_choice" in changes:
        if changes["colour_choice"] not in drawing.CHOICES:
            raise su.ValidationError("the colour choice must keep the drawing, take the nearest colour or colour the objects")
        state["colour_choice"] = changes["colour_choice"]
    if "contours" in changes:
        if not isinstance(changes["contours"], bool):
            raise su.ValidationError("the contours must be on or off")
        state["contours"] = changes["contours"]
    if "rules" in changes:
        state["rules"] = rules_in(changes["rules"])
    if "colouring" in changes:
        state["colouring"] = colouring_in(changes["colouring"])
    if "kind" in changes:
        if changes["kind"] not in KINDS:
            raise su.ValidationError("the kind of engraving must be one of " + ", ".join(KINDS))
        state["kind"] = changes["kind"]
    if "dot_power" in changes:
        power = None if isinstance(changes["dot_power"], bool) else ps._number(changes["dot_power"])
        lo, hi = ps.curve_for(store, mode, width_mm)[0].span
        if power is None or not lo <= power <= hi:
            raise su.ValidationError(f"the dots' power must be a number inside the scale's measured powers {lo:g}..{hi:g} % at the work's width")
        state["dot_power"] = power
    elif dotted(state) and ("kind" in changes or moved):
        state["dot_power"] = ps.dot_power_at(store, mode, width_mm, state["dot_power"])
    if "ai_photo" in changes:
        if not isinstance(changes["ai_photo"], bool):
            raise su.ValidationError("the permission to send the photograph must be on or off")
        state["ai_photo"] = changes["ai_photo"]


def hex_of(lab) -> str:
    rgb = np.clip(color.lab_to_srgb8(np.asarray([lab], float)), 0, 255).round().astype(int)[0]
    return "#%02x%02x%02x" % tuple(rgb)


def shown_rule(rule: Mapping) -> dict:
    """A rule as the screen shows it: with its target colour also as #rrggbb, for the colour picker."""
    return {**rule, "hex": hex_of(rule["lab"])} if "lab" in rule else dict(rule)


def with_lab(rule):
    """A rule whose target colour is given by hand as ``hex`` (#rrggbb), with it as L*a*b*, as the rules keep it."""
    if not isinstance(rule, Mapping) or "hex" not in rule or "lab" in rule:
        return rule
    hexed = rule["hex"]
    if not isinstance(hexed, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", hexed):
        raise su.ValidationError("a target colour must be given as #rrggbb")
    lab = color.srgb8_to_lab(np.array([[int(hexed[i:i + 2], 16) for i in (1, 3, 5)]], float))[0]
    return {**{k: v for k, v in rule.items() if k != "hex"}, "lab": [round(float(v), 2) for v in lab]}


def colouring_in(colouring) -> dict:
    """The main colours of the objects as a state keeps them: an object's key (``colouring.key_of``) to ``{"power": 0..100, "shift": -1..1}``."""
    if not isinstance(colouring, Mapping) or len(colouring) > MAX_COLOURED:
        raise su.ValidationError(f"the colours of the objects must be a mapping of at most {MAX_COLOURED} objects")
    out = {}
    for key, chosen in colouring.items():
        kind, _, piece = str(key).partition("-")
        if kind not in ob.KINDS or (piece and not piece.isdigit()):
            raise su.ValidationError("an object is named by its kind (" + ", ".join(ob.KINDS) + "), a background piece also by its number")
        power = None if not isinstance(chosen, Mapping) or isinstance(chosen.get("power"), bool) else ps._number(chosen.get("power"))
        shift = 0.0 if not isinstance(chosen, Mapping) or chosen.get("shift") is None else ps._number(chosen.get("shift"))
        if power is None or not 0 <= power <= 100 or shift is None or not -1 <= shift <= 1:
            raise su.ValidationError("an object's colour is a power 0..100 % with lighter or darker -1..1")
        out[str(key)] = {"power": power, "shift": shift}
    return out


def rules_in(rules) -> list[dict]:
    """The rules of the parts as given by hand, checked (``picture_rules.check``); ``as_is`` is a part without a rule."""
    try:
        checked = picture_rules.check([with_lab(r) for r in rules] if isinstance(rules, list) else rules)
    except picture_rules.RuleError as exc:
        raise su.ValidationError(str(exc)) from None
    return [r for r in checked if r["kind"] != "as_is"]


# -- the parts of the picture (REQ-062) ------------------------------------------------------------------------------------------------
def parts_found(upload: dict) -> list[dict]:
    """The parts the people model finds in the picture, each covering at least PART_MIN_SHARE of it; the model runs once per picture."""
    ps.part_scores(upload)
    return [p for p in ps.parts_of(upload) if p["share"] >= PART_MIN_SHARE]


def parts_listed(upload: dict) -> list[dict]:
    """:func:`parts_found` with the colour each part is tinted in on the picture of the parts (``prediction_store.PART_COLOURS``)."""
    tint = {name: "#%02x%02x%02x" % rgb for name, rgb in zip(people.PARTS, ps.PART_COLOURS)}
    return [{**p, "tint": tint[p["part"]]} for p in parts_found(upload)]


# -- the objects of the picture and their colours (0.21.0) ----------------------------------------------------------------------------
def objects(upload: dict) -> dict:
    """The objects of the decoded picture (``objects.find``), found once and kept with it."""
    if "objects" not in upload:
        upload["objects"] = ob.find(upload)
    return upload["objects"]


def options(store: Store, mode: ps.Mode, state: Mapping, width_mm: float) -> list[dict]:
    """The scale's colours a main colour is chosen from at the state's Min and Max (``colouring.candidates``)."""
    return co.candidates(ps.curve_for(store, mode, width_mm)[0], state["min_power"], state["max_power"])


def objects_listed(store: Store, mode: ps.Mode, upload: dict, state: Mapping, width_mm: float) -> dict:
    """The objects of the picture to colour: each one's key, kind, piece, share, own colour and box, the colour it is tinted in on the
    picture of the objects and its main colour (or None: «Авто»), the scale's colours to choose from (none while the scale is not measured)
    and the themes, whether the objects are coloured now (``active``) and why lips or eyes are missing (``notes``)."""
    found = objects(upload)
    tints = {o["id"]: (ob.PIECE_TINTS[(o["piece"] - 1) % len(ob.PIECE_TINTS)] if o["piece"] else ob.TINTS[o["kind"]]) for o in found["objects"]}
    listed = [{**{k: o[k] for k in ("id", "kind", "piece", "share", "lab", "hex", "box")}, "key": co.key_of(o), "tint": "#%02x%02x%02x" % tints[o["id"]],
               "colour": state["colouring"].get(co.key_of(o))} for o in found["objects"]]
    try:
        offered = options(store, mode, state, width_mm)
    except PredictionError:
        offered = []
    return {"objects": listed, "faces": found["faces"], "notes": found["notes"], "options": offered, "themes": list(co.THEMES),
            "active": state["by_colour"] and state["colour_choice"] == "objects" and not dotted(state)}


def theme_checked(name, seed) -> None:
    if name not in co.THEMES:
        raise su.ValidationError("a theme is one of " + ", ".join(co.THEMES))
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise su.ValidationError("the seed of a random theme is a whole number from 0")


def theme(store: Store, mode: ps.Mode, upload: dict, state: Mapping, width_mm: float, name, seed=0) -> dict:
    """The changes that colour every object of the picture by the theme ``name`` (``colouring.theme``: warm, cool, contrast or random by
    ``seed``) on the scale's colours at the state's Min and Max: the greys are then chosen for the objects."""
    theme_checked(name, seed)
    if dotted(state):
        raise su.ValidationError("the objects are coloured in grayscale only: a dot kind fires every dot at one power")
    offered = options(store, mode, state, width_mm)
    return {"by_colour": True, "colour_choice": "objects", "colouring": co.theme(name, objects(upload)["objects"], offered, seed)}


# -- the AI (REQ-062, DEC-105) ---------------------------------------------------------------------------------------------------------
def ai_missing() -> str | None:
    """Why the AI cannot run on this computer: ``library`` (the client library is not installed), ``key`` (no key is set) or None."""
    if not research.ai_library():
        return "library"
    return None if research.ai_available() else "key"


def ai_client():
    """The language model's client, or the reason the AI cannot answer on this computer."""
    if not research.ai_available():
        raise cv.ConversionError("the AI is off: no key for the language model is set (OPENAI_API_KEY)")
    try:
        return research.openai_client()
    except Exception:                        # a missing or broken library: its own text names paths and is of no use to the operator
        raise cv.ConversionError("the AI could not be started on this computer: a library it needs is missing or broken, install the app's dependencies (see README)") from None


def ai_theme(store: Store, mode: ps.Mode, upload: dict, state: Mapping, width_mm: float, wish, photo: Callable[[], bytes]) -> tuple[dict, dict]:
    """Ask the AI for the main colours of the picture's objects after the operator's ``wish`` (``ai_picture.ask_objects``: it sees the
    objects, the scale's colours at the state's Min and Max and the colours the objects have now; the picture, ``photo()``, only with
    ``ai_photo``). The changes that colour the objects so and the AI's answer to keep as ``ai_theme``; a refused answer raises."""
    text = ai_picture.request(wish)
    if dotted(state):
        raise su.ValidationError("the objects are coloured in grayscale only: a dot kind fires every dot at one power")
    client = ai_client()
    found = objects(upload)
    offered = options(store, mode, state, width_mm)
    listed = [{**o, "key": co.key_of(o)} for o in found["objects"]]
    what = ai_picture.objects_brief(text, listed, offered, state["colouring"])
    sent = ai.photo_data_url(photo()) if state["ai_photo"] else None
    colours, note = ai_picture.ask_objects(client, what, sent, {o["key"] for o in listed}, [c["power"] for c in offered])
    return ({"by_colour": True, "colour_choice": "objects", "colouring": colours},
            {"wish": text, "photo": sent is not None, "note": note, "at": now()})


def ai_rules(store: Store, mode: ps.Mode, upload: dict, state: Mapping, width_mm: float, name: str, wish, fresh,
             photo: Callable[[], bytes]) -> tuple[list[dict], dict]:
    """Ask the AI for the rules of the parts after the operator's ``wish``: it sees the parts, the scale's greys at Min and Max and the
    present rules and changes what the wish asks, or with ``fresh`` starts from the plain picture (``ai_picture.ask``). The rules and the
    AI's answer to keep as ``ai`` (the owner adds the rules before them); a refused answer raises."""
    text = ai_picture.request(wish)
    if not isinstance(fresh, bool):
        raise su.ValidationError("starting again from the picture must be on or off")
    client = ai_client()
    prepared = ps.picture_item(store, mode, upload, name, state["by_colour"], width_mm)
    low, high = ps.check_power_range(state["min_power"], state["max_power"])
    found = parts_found(upload)
    what = ai_picture.brief(text, found, grayscale.scale_of_greys(prepared["curve"], low, high), [] if fresh else state["rules"])
    sent = ai.photo_data_url(photo()) if state["ai_photo"] else None
    rules, note = ai_picture.ask(client, what, sent, {p["part"] for p in found})
    return rules, {"wish": text, "photo": sent is not None, "fresh": fresh, "note": note, "at": now()}
