"""Inscriptions (feature inscriptions-in-works, REQ-002..REQ-005, DEC-002, DEC-003): a text set in a font, laid out straight, on an arc,
around a circle or along a path, and what it does to the picture of a work.

An inscription is an object of a work (a vector work keeps its list in ``colouring["texts"]``, a photo work in its state ``texts``): its
text, font, letter height, width, spacing, layout, place, colour, gap and backing (:data:`DEFAULTS`). Nothing of the work is changed by
it; :func:`geometry` computes from it, in the work's millimetres (x right, y down):

* ``letters``: the outline of the text, closed polygons with their holes, the letters that touch or overlap made one shape;
* ``backing``: the shape under the letters filled with the backing's colour (a rectangle or an oval around the text, bent with it on a
  curve, or the letters' outline widened by the padding), the letters and the gap left out of it; None without a backing colour;
* ``cut``: what is taken out of the picture: the letters widened by the gap, or the backing (widened by the gap when it is engraved);

each clipped to the work's rectangle. The text is shaped by HarfBuzz run by run (kerning, ligatures, marks; a run of Hebrew or Arabic
right to left, the runs of a line in the order a reader sees them), every glyph drawn from the font with the face's variable axes set,
its curves flattened to ``FLAT_MM``. The letter height is the height of the capitals (the font's cap height, else its «H»).

The layout maps a line's coordinates (x along the line, y up from the baseline) onto a curve with a frame at every point (where it is,
its direction and the direction up from it): a straight line; an arc whose bend (-100..100 %) makes the longest line sweep up to a half
circle; a circle of a radius, the text outside it reading clockwise or inside it reading anticlockwise, centred at a start angle (0 at
the top, clockwise); a path through the operator's points (smooth, Catmull-Rom), from an offset along it. Every line below the first runs
on its own curve, parallel to the first at the line spacing (on an arc or a circle, the circle about the same centre), its letters spaced
along it as on a straight line; a text longer than its circle, or reaching past its centre, is said so (``overflow``). On a curve the
letters stand upright on it (each turned to the curve at its middle) or are bent with it (every point of the letter follows the curve,
the backing about all the lines bent with the first). Then the whole
is turned about its anchor and put where the inscription is: the middle of the text for a line or an arc, the centre for a circle, the
first point for a path (whose points are kept relative to it); on a path the text stands at ``offset_pct`` of its length (the middle by
default), its start, middle or end there as it is aligned.
"""
from __future__ import annotations

import copy
import json
import math
import re
import threading
import unicodedata
from collections import OrderedDict
from pathlib import Path

import numpy as np
import shapely
from fontTools.pens.basePen import BasePen
from shapely.geometry import MultiPolygon, Polygon, box as shapely_box

from . import fonts, setup as su

LAYOUTS = ("line", "arc", "circle", "path")
LETTERS = ("upright", "bent")
ALIGNS = ("left", "center", "right")
BACKINGS = ("none", "rect", "oval", "outline")
FLAT_MM = 0.01                  # how far a flattened curve of a letter may stray from the font's curve
BEND_MM = 0.2                   # the longest piece of an outline bent with its curve
MAX_TEXT = 2000
MAX_LINES = 50
MAX_POINTS = 400
DECIMALS = 3                    # mm in the paths sent to the screen
KEEP = 128                      # geometries kept, by everything they are computed from
# number fields: (least, most, default)
NUMBERS = {"height_mm": (0.3, 500.0, 5.0), "width_pct": (10.0, 400.0, 100.0), "spacing_mm": (-50.0, 200.0, 0.0), "line_pct": (50.0, 400.0, 100.0),
           "rotation": (-3600.0, 3600.0, 0.0), "bend": (-100.0, 100.0, 40.0), "radius_mm": (0.5, 5000.0, 20.0), "start_deg": (-3600.0, 3600.0, 0.0),
           "offset_pct": (0.0, 100.0, 50.0), "gap_mm": (0.0, 20.0, 0.3), "padding_mm": (0.0, 200.0, 1.0), "corner_mm": (0.0, 200.0, 0.0),
           "x": (-100000.0, 100000.0, 0.0), "y": (-100000.0, 100000.0, 0.0)}
CHOICES = {"align": ALIGNS, "layout": LAYOUTS, "letters": LETTERS, "backing": BACKINGS}
FLAGS = ("inside", "flip")
ENTRIES = ("entry_id", "backing_entry_id")
DEFAULTS = {"text": "Надпись", "font": None, **{k: v[2] for k, v in NUMBERS.items()}, "align": "center", "layout": "line", "letters": "upright",
            "inside": False, "flip": False, "points": [], "entry_id": None, "gap_mm": 0.3, "backing": "none", "backing_entry_id": None}
FIELDS = tuple(DEFAULTS)
OPS = ("text_add", "text_set", "text_delete", "text_copy")
COPY_SHIFT_MM = 3.0
SAMPLE = "Надпись Abc"

_lock = threading.Lock()
_memo: OrderedDict = OrderedDict()
_glyphs: OrderedDict = OrderedDict()


# -- the inscription checked ---------------------------------------------------------------------------------------------------------
def _number(value, name: str) -> float:
    low, high, _ = NUMBERS[name]
    try:
        number = math.nan if isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number) or not low <= number <= high:
        raise su.ValidationError(f"{FIELD_NAMES[name]} of an inscription must be a number from {low:g} to {high:g}")
    return number


FIELD_NAMES = {"height_mm": "the letter height (mm)", "width_pct": "the width (%)", "spacing_mm": "the letter spacing (mm)",
               "line_pct": "the line spacing (%)", "rotation": "the rotation (degrees)", "bend": "the bend (%)", "radius_mm": "the radius (mm)",
               "start_deg": "the start angle (degrees)", "offset_pct": "the place along the path (%)", "gap_mm": "the gap (mm)",
               "padding_mm": "the backing's margin (mm)", "corner_mm": "the backing's corner radius (mm)", "x": "the position x (mm)",
               "y": "the position y (mm)", "align": "the alignment", "layout": "the layout", "letters": "the letters on a curve",
               "backing": "the backing", "inside": "the switch «inside the circle»", "flip": "the switch «reverse the path»"}


def _points(value) -> list[list[float]]:
    if not isinstance(value, list) or len(value) > MAX_POINTS:
        raise su.ValidationError(f"the path of an inscription must be a list of at most {MAX_POINTS} points")
    out = []
    for p in value:
        try:
            x, y = (float(v) for v in p)
        except (TypeError, ValueError):
            raise su.ValidationError("every point of the path of an inscription must be two numbers (mm)") from None
        if not (math.isfinite(x) and math.isfinite(y)) or abs(x) > 100000 or abs(y) > 100000:
            raise su.ValidationError("every point of the path of an inscription must be two numbers (mm)")
        out.append([round(x, 4), round(y, 4)])
    return out


def checked(spec) -> dict:
    """An inscription with every field present and in range (missing fields take :data:`DEFAULTS`); ValidationError names the first field
    that is not. The colours are checked by the work (they must be measured colours of its laser, lens and titanium)."""
    if not isinstance(spec, dict):
        raise su.ValidationError("an inscription must be an object")
    unknown = sorted(set(spec) - set(FIELDS) - {"id"})
    if unknown:
        raise su.ValidationError(f"an inscription has no field {unknown[0]!r}")
    out = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(spec)}
    text = out["text"]
    if not isinstance(text, str):
        raise su.ValidationError("the text of an inscription must be text")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT or text.count("\n") >= MAX_LINES:
        raise su.ValidationError(f"the text of an inscription may have at most {MAX_TEXT} characters in {MAX_LINES} lines")
    out["text"] = text
    for name in NUMBERS:
        out[name] = round(_number(out[name], name), 4)
    for name, allowed in CHOICES.items():
        if out[name] not in allowed:
            raise su.ValidationError(f"{FIELD_NAMES[name]} of an inscription must be one of {', '.join(allowed)}")
    for name in FLAGS:
        if not isinstance(out[name], bool):
            raise su.ValidationError(f"{FIELD_NAMES[name]} of an inscription must be true or false")
    out["points"] = _points(out["points"])
    if out["layout"] == "path" and len(out["points"]) < 2:
        raise su.ValidationError("draw the path of the inscription: two points or more")
    for name in ENTRIES:
        if out[name] is not None and not isinstance(out[name], str):
            raise su.ValidationError("the colour of an inscription must be a measured colour")
    font = out["font"]
    if font is not None and (not isinstance(font, dict) or not all(isinstance(font.get(k), str) for k in ("face", "family", "style"))):
        raise su.ValidationError("choose the font of the inscription")
    if "id" in spec:
        if not isinstance(spec["id"], str) or not re.fullmatch(r"t\d+", spec["id"]):
            raise su.ValidationError("an inscription is named t1, t2 ...")
        out["id"] = spec["id"]
    return out


# -- operations on a work's list ------------------------------------------------------------------------------------------------------
def find(texts: list[dict], text_id) -> dict:
    found = next((t for t in texts if t.get("id") == text_id), None)
    if found is None:
        raise su.ValidationError(f"there is no inscription {text_id!r}")
    return found


def _new_id(texts: list[dict]) -> str:
    return f"t{1 + max((int(t['id'][1:]) for t in texts), default=0)}"


def operate(data_dir: Path, texts: list[dict] | None, op: dict, size_mm: dict, colour_ok, default_entry) -> list[dict]:
    """The work's inscriptions after one operation, a new list (the old one is not changed):

    * ``{"op": "text_add", "text": {...}}`` a new inscription (fields not given take the defaults; it stands in the middle of the work, in the
      default font, in ``default_entry()``'s colour unless given);
    * ``{"op": "text_set", "id", "changes": {...}}`` changes fields of one;
    * ``{"op": "text_copy", "id"}`` a copy of one, a little to the right and down;
    * ``{"op": "text_delete", "id"}`` takes one away.

    ``colour_ok(entry_id)`` tells whether a colour may be chosen (a measured colour of the work); the font must be one of :mod:`fonts`."""
    texts = copy.deepcopy(list(texts or []))
    kind = op.get("op")
    if kind == "text_add":
        given = op.get("text") or {}
        if not isinstance(given, dict):
            raise su.ValidationError("an inscription must be an object")
        spec = {"x": round(size_mm["width"] / 2, 3), "y": round(size_mm["height"] / 2, 3), "height_mm": _default_height(size_mm), **given}
        spec.pop("id", None)
        if spec.get("font") is None:
            spec["font"] = fonts.described(default_face(data_dir))
        if spec.get("entry_id") is None:
            spec["entry_id"] = default_entry()
        made = {**checked(spec), "id": _new_id(texts)}
        _check_colours(made, colour_ok)
        fonts.resolve(data_dir, made["font"])
        return texts + [made]
    if kind == "text_set":
        target = find(texts, op.get("id"))
        changes = op.get("changes")
        if not isinstance(changes, dict) or not changes:
            raise su.ValidationError("say what to change in the inscription")
        if "id" in changes:
            raise su.ValidationError("an inscription keeps its name")
        made = checked({**target, **changes})
        _check_colours({k: changes.get(k) for k in ENTRIES if k in changes}, colour_ok)
        if "font" in changes:
            fonts.resolve(data_dir, made["font"])
        texts[texts.index(target)] = made
        return texts
    if kind == "text_copy":
        target = find(texts, op.get("id"))
        made = {**copy.deepcopy(target), "id": _new_id(texts), "x": target["x"] + COPY_SHIFT_MM, "y": target["y"] + COPY_SHIFT_MM}
        return texts + [checked(made)]
    if kind == "text_delete":
        target = find(texts, op.get("id"))
        texts.remove(target)
        return texts
    raise su.ValidationError(f"unknown inscription operation {kind!r}")


SCALED = ("height_mm", "spacing_mm", "radius_mm", "padding_mm", "corner_mm", "x", "y")     # the gap is the laser's margin: it stays


def scaled(texts: list[dict] | None, factor: float) -> list[dict]:
    """The inscriptions of a work whose picture is engraved ``factor`` times as large (DEC-004): each keeps its place on the picture and its
    size against it, as a group scaled in LightBurn; its gap stays the same in mm. A size that would leave its range stays at its end."""
    out = []
    for spec in copy.deepcopy(list(texts or [])):
        for name in SCALED:
            low, high, _ = NUMBERS[name]
            spec[name] = round(min(high, max(low, spec[name] * factor)), 4)
        spec["points"] = [[round(x * factor, 4), round(y * factor, 4)] for x, y in spec["points"]]
        out.append(spec)
    return out


def _check_colours(spec: dict, colour_ok) -> None:
    for name in ENTRIES:
        value = spec.get(name)
        if value is not None and not colour_ok(value):
            raise su.ValidationError("the colour of an inscription must be a measured colour of this laser, lens and titanium stock")


def _default_height(size_mm: dict) -> float:
    """A new inscription's letters: a tenth of the work's shorter side, from 2 to 20 mm."""
    return round(min(20.0, max(2.0, min(size_mm["width"], size_mm["height"]) / 10)), 1)


PREFERRED = ("Arial", "Helvetica", "Helvetica Neue", "Roboto", "Noto Sans")


def darkest(entries: list[dict]) -> str | None:
    """The id of the darkest of the palette's ``entries``, the colour that stands out most on clean titanium (None without one)."""
    return min(entries, key=lambda e: (e["lab"][0], e["id"]))["id"] if entries else None


def default_face(data_dir: Path) -> dict:
    """The font a new inscription takes: a common sans serif with Latin and Cyrillic, else any face that has both, else any face."""
    known = list(fonts.faces(data_dir).values())
    if not known:
        raise fonts.FontError("no font is found on this computer: add a font file")
    for family in PREFERRED:
        same = [f for f in known if f["family"] == family]
        if same:
            return fonts._regular(same)
    both = [f for f in known if {"latin", "cyrillic"} <= set(f["scripts"])]
    return fonts._regular(both or known)


# -- shaping and glyphs ----------------------------------------------------------------------------------------------------------------
class _Flat(BasePen):
    """The contours of a glyph as closed point lists (font units), curves flattened to ``tol`` units."""

    def __init__(self, tol: float):
        super().__init__(None)
        self.tol, self.contours, self.current = tol, [], None

    def _moveTo(self, p):
        self.current = [p]

    def _lineTo(self, p):
        self.current.append(p)

    def _curveToOne(self, p1, p2, p3):
        p0 = self.current[-1]
        dd = max(math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1]), math.hypot(p1[0] - 2 * p2[0] + p3[0], p1[1] - 2 * p2[1] + p3[1]))
        n = max(1, min(100, math.ceil(math.sqrt(0.75 * dd / self.tol))))
        for i in range(1, n + 1):
            t = i / n
            u = 1 - t
            self.current.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                                 u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))

    def _qCurveToOne(self, p1, p2):
        p0 = self.current[-1]
        dd = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
        n = max(1, min(100, math.ceil(math.sqrt(dd / (4 * self.tol)))))
        for i in range(1, n + 1):
            t = i / n
            u = 1 - t
            self.current.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))

    def _closePath(self):
        if self.current and len(self.current) >= 3:
            ring = self.current[:-1] if self.current[0] == self.current[-1] else self.current
            if len(ring) >= 3:
                self.contours.append(np.asarray(ring, np.float64))
        self.current = None

    _endPath = _closePath


def _glyph(font, key: tuple, gid: int, tol: float) -> list[np.ndarray]:
    """A glyph's contours in font units, kept by font, glyph and tolerance."""
    known = (key, gid, round(tol, 3))
    with _lock:
        if known in _glyphs:
            _glyphs.move_to_end(known)
            return _glyphs[known]
    pen = _Flat(tol)
    font.draw_glyph_with_pen(gid, pen)
    with _lock:
        _glyphs[known] = pen.contours
        while len(_glyphs) > 4096:
            _glyphs.popitem(last=False)
    return pen.contours


def _direction(char: str) -> str | None:
    kind = unicodedata.bidirectional(char)
    if kind in ("R", "AL"):
        return "rtl"
    if kind == "L":
        return "ltr"
    if kind in ("EN", "AN"):
        return "num"
    return None


def runs(line: str) -> list[tuple[str, str]]:
    """The line cut into runs of one writing direction, in the order a reader sees them: (text, "ltr" | "rtl"). The line's direction is
    its first strong letter's; a neutral character (space, punctuation) between two runs of one direction belongs to them, else to the
    line's direction; digits are written left to right inside right-to-left text."""
    kinds = [_direction(c) for c in line]
    strong = next((k for k in kinds if k in ("ltr", "rtl")), "ltr")
    resolved = []
    for i, k in enumerate(kinds):
        if k == "num":
            resolved.append("ltr")
            continue
        if k is not None:
            resolved.append(k)
            continue
        before = next((kinds[j] for j in range(i - 1, -1, -1) if kinds[j] in ("ltr", "rtl")), None)
        after = next((kinds[j] for j in range(i + 1, len(kinds)) if kinds[j] in ("ltr", "rtl")), None)
        resolved.append(before if before is not None and before == after else strong)
    out = []
    for char, k in zip(line, resolved):
        if out and out[-1][1] == k:
            out[-1][0] += char
        else:
            out.append([char, k])
    ordered = [tuple(r) for r in out]
    return ordered[::-1] if strong == "rtl" else ordered


def _shaped(font, text: str, direction: str):
    import uharfbuzz as hb
    buf = hb.Buffer()
    buf.add_str(text)
    buf.direction = direction
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True})
    return buf.glyph_infos, buf.glyph_positions


def _face_metrics(face: dict, font) -> tuple[float, float]:
    """The face's cap height and line height in font units (the cap height measured on «H» when the font does not give it)."""
    cap = face.get("cap")
    if not cap:
        for char in "HНאA":
            gid = font.get_nominal_glyph(ord(char))
            if gid:
                extents = font.get_glyph_extents(gid)
                if extents and extents.y_bearing > 0:
                    cap = extents.y_bearing
                    break
    return float(cap or 0.7 * face["upem"]), float(face.get("line") or 1.2 * face["upem"])


def _lines(face: dict, spec: dict, *, notdef: bool = False) -> dict:
    """Every line of the text set in the face, on its own baseline: the glyph contours in mm (x along the line, y up, the first baseline at
    y 0), each glyph's middle and baseline, the line widths and the characters the font lacks. Letter spacing goes after every glyph that
    advances, but the last of a line; ``notdef`` keeps the glyph a font draws for a missing letter (the font window shows it)."""
    font = fonts.hb_font(face)
    key = (face["path"], face["index"], json.dumps(face.get("coords"), sort_keys=True))
    cap, line_units = _face_metrics(face, font)
    s = spec["height_mm"] / cap
    sx = s * spec["width_pct"] / 100.0
    tol = min(face["upem"] / 2000.0, FLAT_MM / s)
    line_step = line_units * s * spec["line_pct"] / 100.0
    glyphs, widths, missing = [], [], []
    for n, line in enumerate(spec["text"].split("\n")):
        placed, pen = [], 0.0
        for text, direction in runs(line):
            infos, positions = _shaped(font, text, direction)
            for info, pos in zip(infos, positions):
                if info.codepoint == 0:
                    char = text[info.cluster] if info.cluster < len(text) else "?"
                    if not char.isspace() and char not in missing:
                        missing.append(char)
                placed.append((info.codepoint, pen, pos))
                pen += pos.x_advance * sx
                if pos.x_advance:
                    pen += spec["spacing_mm"]
        if placed and placed[-1][2].x_advance:
            pen -= spec["spacing_mm"]
        baseline = -n * line_step
        for gid, x, pos in placed:
            if gid == 0 and not notdef:
                continue
            contours = [np.column_stack([x + (c[:, 0] + pos.x_offset) * sx, baseline + (c[:, 1] + pos.y_offset) * s])
                        for c in _glyph(font, key, gid, tol)]
            if contours:
                glyphs.append({"contours": contours, "middle": x + pos.x_advance * sx / 2, "baseline": baseline, "line": n, "notdef": gid == 0})
        widths.append(max(0.0, pen))
    missing.sort(key=spec["text"].index)                  # in the order of the text: a right-to-left run is shaped in the order it is seen
    return {"glyphs": glyphs, "widths": widths, "missing": missing, "line_step": line_step, "cap": spec["height_mm"]}


# -- the curve the lines are laid on -------------------------------------------------------------------------------------------------
# Every curve gives its frame at a length s along it (where it is, its direction, the direction up from it) and, for a line at a height b
# over it (the lines below the first are at negative heights), the length along the curve under a length x along that line (``along``),
# both measured from the curve's anchor: a line runs on the curve parallel to it at its height, so its letters keep their spacing on it.
TIGHT = 0.05                    # the least share of its length a line keeps on a curve: a line past the centre (overflow) is not spread
CROWD_SHARE = 0.05              # neighbours on a path crowd when they overlap by more than this share of the smaller beyond their overlap straight


class _Straight:
    closed = False
    anchor = 0.0

    def frame(self, s):
        s = np.asarray(s, np.float64)
        return np.column_stack([s, np.zeros_like(s)]), np.tile([1.0, 0.0], (s.size, 1)), np.tile([0.0, 1.0], (s.size, 1))

    def along(self, x, b: float):
        return np.asarray(x, np.float64)


class _Round:
    """A curve of one curvature ``k`` (1/radius, negative where the letters stand outside it): a line at a height b over it runs on the
    circle about the same centre, 1 - b·k times as long."""
    closed = False
    anchor = 0.0
    k = 0.0

    def along(self, x, b: float):
        return np.asarray(x, np.float64) / max(1.0 - b * self.k, TIGHT)


class _Arc(_Round):
    """A circle through the origin at its top (bend > 0, the text bowed up) or its bottom (bend < 0), the text running to the right."""

    def __init__(self, radius: float, up: bool):
        self.r, self.up = radius, up
        self.k = -1.0 / radius if up else 1.0 / radius

    def frame(self, s):
        t = np.asarray(s, np.float64) / self.r
        sin, cos = np.sin(t), np.cos(t)
        if self.up:
            return np.column_stack([self.r * sin, self.r * cos - self.r]), np.column_stack([cos, -sin]), np.column_stack([sin, cos])
        return np.column_stack([self.r * sin, self.r - self.r * cos]), np.column_stack([cos, sin]), np.column_stack([-sin, cos])


class _Circle(_Round):
    """A circle about the origin: outside, the text reads clockwise standing on it; inside, it reads anticlockwise hanging inside it. The
    text's anchor is at the start angle (0 at the top, clockwise)."""
    closed = True

    def __init__(self, radius: float, start_deg: float, inside: bool):
        self.r, self.a0, self.inside = radius, math.radians(start_deg), inside
        self.k = 1.0 / radius if inside else -1.0 / radius

    def frame(self, s):
        s = np.asarray(s, np.float64)
        a = self.a0 + (-s if self.inside else s) / self.r
        sin, cos = np.sin(a), np.cos(a)
        p = np.column_stack([self.r * sin, self.r * cos])
        if self.inside:
            return p, np.column_stack([-cos, sin]), np.column_stack([-sin, -cos])
        return p, np.column_stack([cos, -sin]), np.column_stack([sin, cos])


class _Path:
    """A smooth curve through points (centripetal Catmull-Rom), walked by its length, its anchor at a share of it; beyond its ends it goes
    on straight."""
    closed = False

    def __init__(self, points: np.ndarray, offset_pct: float):
        self.q = _catmull_rom(points)
        steps = np.hypot(*np.diff(self.q, axis=0).T)
        keep = np.concatenate([[True], steps > 1e-9])
        self.q = self.q[keep]
        steps = np.hypot(*np.diff(self.q, axis=0).T)
        self.s = np.concatenate([[0.0], np.cumsum(steps)])
        self.length = float(self.s[-1])
        d = np.gradient(self.q, axis=0) if len(self.q) > 2 else np.diff(self.q, axis=0).repeat(2, axis=0)[: len(self.q)]
        self.t = d / np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-12)[:, None]
        self.turn = np.unwrap(np.arctan2(self.t[:, 1], self.t[:, 0]))          # the direction's angle: its change is the curvature
        self.anchor = offset_pct / 100.0 * self.length

    def along(self, x, b: float):
        """A line at height b is as long as the curve less b times its turn (1 - b·curvature at every point); where it would run back
        (past the centre of a tight bend) it stops."""
        x = np.asarray(x, np.float64)
        if b == 0:
            return x
        run = np.maximum.accumulate(self.s - b * (self.turn - np.interp(self.anchor, self.s, self.turn)))
        s = np.interp(x, run, self.s)
        return np.where(x < run[0], x - run[0], np.where(x > run[-1], self.length + x - run[-1], s))

    def frame(self, s):
        s = np.asarray(s, np.float64)
        inside = np.clip(s, 0.0, self.length)
        tx = np.interp(inside, self.s, self.t[:, 0])
        ty = np.interp(inside, self.s, self.t[:, 1])
        norm = np.maximum(np.hypot(tx, ty), 1e-12)
        tx, ty = tx / norm, ty / norm
        px = np.interp(inside, self.s, self.q[:, 0]) + (s - inside) * tx
        py = np.interp(inside, self.s, self.q[:, 1]) + (s - inside) * ty
        return np.column_stack([px, py]), np.column_stack([tx, ty]), np.column_stack([-ty, tx])


def _catmull_rom(points: np.ndarray, step_mm: float = 0.25) -> np.ndarray:
    """A smooth curve through the points: centripetal Catmull-Rom, every piece cut into steps of at most ``step_mm``."""
    p = np.asarray(points, np.float64)
    if len(p) == 2:
        n = max(2, math.ceil(np.hypot(*(p[1] - p[0])) / step_mm) + 1)
        return np.linspace(p[0], p[1], n)
    ext = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = [p[:1]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t0 = 0.0
        t1 = t0 + max(np.hypot(*(p1 - p0)), 1e-9) ** 0.5
        t2 = t1 + max(np.hypot(*(p2 - p1)), 1e-9) ** 0.5
        t3 = t2 + max(np.hypot(*(p3 - p2)), 1e-9) ** 0.5
        n = max(2, math.ceil(np.hypot(*(p2 - p1)) / step_mm))
        t = np.linspace(t1, t2, n + 1)[1:, None]
        a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
        b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
        out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    return np.vstack(out)


def _densified(ring: np.ndarray, step: float) -> np.ndarray:
    """A closed ring with every edge cut into pieces of at most ``step``, so that bending it follows the curve."""
    nxt = np.roll(ring, -1, axis=0)
    lengths = np.hypot(*(nxt - ring).T)
    counts = np.maximum(1, np.ceil(lengths / step).astype(int))
    if counts.max() == 1:
        return ring
    parts = [ring[i] + (nxt[i] - ring[i]) * (np.arange(k)[:, None] / k) for i, k in enumerate(counts)]
    return np.vstack(parts)


# -- the geometry ------------------------------------------------------------------------------------------------------------------
def _curve(spec: dict, widths: list[float]):
    layout = spec["layout"]
    longest = max(widths, default=0.0)
    if layout == "arc" and abs(spec["bend"]) >= 0.5 and longest > 0:
        return _Arc(longest / (math.pi * abs(spec["bend"]) / 100.0), spec["bend"] > 0)
    if layout == "circle":
        return _Circle(spec["radius_mm"], spec["start_deg"], spec["inside"])
    if layout == "path" and len(spec["points"]) >= 2:
        pts = np.asarray(spec["points"], np.float64) * [1.0, -1.0]          # the work's y down, the line's y up
        return _Path(pts[::-1] if spec["flip"] else pts, spec["offset_pct"])
    return _Straight()


def _starts(spec: dict, widths: list[float], curve) -> list[float]:
    """Where each line starts, along itself: a line or an arc aligns its lines in a block about its middle; a circle and a path align
    every line on the anchor (the start angle, the offset along the path)."""
    longest = max(widths, default=0.0)
    align = spec["align"]
    if isinstance(curve, (_Straight, _Arc)):
        return [-longest / 2 + {"left": 0.0, "center": (longest - w) / 2, "right": longest - w}[align] for w in widths]
    return [curve.anchor + {"left": 0.0, "center": -w / 2, "right": -w}[align] for w in widths]


def _placed(spec: dict, laid: dict):
    """The glyphs' contours on the curve (mm, y up, about the anchor before the turn), each line on its own curve parallel to the first
    (:meth:`along`), the curve, where the lines start and a function that bends a ring of coordinates along the curve (x along the first
    line, y up) the same way (the backing)."""
    curve = _curve(spec, laid["widths"])
    starts = _starts(spec, laid["widths"], curve)
    step = max(0.02, min(BEND_MM, spec["height_mm"] / 25))
    straight = isinstance(curve, _Straight)

    def bend(ring: np.ndarray, b: float = 0.0) -> np.ndarray:
        if straight:
            return ring
        r = _densified(ring, step)
        p, _, n = curve.frame(curve.along(r[:, 0], b))
        return p + n * r[:, 1:2]

    shapes = []
    for g in laid["glyphs"]:
        dx = starts[g["line"]]
        moved = [c + [dx, 0.0] for c in g["contours"]]
        if straight:
            shapes.append(moved)
        elif spec["letters"] == "bent":
            shapes.append([bend(c, g["baseline"]) for c in moved])
        else:
            p, t, n = curve.frame(curve.along([g["middle"] + dx], g["baseline"]))
            base = p[0] + n[0] * g["baseline"]
            shapes.append([base + t[0] * (c[:, 0:1] - g["middle"] - dx) + n[0] * (c[:, 1:2] - g["baseline"]) for c in moved])
    return shapes, curve, starts, bend


def _area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _glyph_shape(rings: list[np.ndarray]):
    """One glyph as a polygon: its contours turning like its largest one are filled, the others are holes (the non-zero rule of fonts for
    the contours fonts draw); overlapping contours of a glyph become one."""
    rings = [r for r in rings if len(r) >= 3]
    if not rings:
        return None
    areas = [_area(r) for r in rings]
    sign = math.copysign(1.0, areas[int(np.argmax(np.abs(areas)))])
    fill = [shapely.make_valid(Polygon(r)) for r, a in zip(rings, areas) if a * sign > 0]
    holes = [shapely.make_valid(Polygon(r)) for r, a in zip(rings, areas) if a * sign < 0]
    shape = shapely.union_all(fill) if fill else None
    if shape is None or shape.is_empty:
        return None
    if holes:
        shape = shape.difference(shapely.union_all(holes))
    return _polygons(shape)


def _polygons(geom):
    """Only the areas of a geometry (lines and points a boolean operation leaves are dropped), as a MultiPolygon."""
    if geom is None or geom.is_empty:
        return MultiPolygon()
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    flat = [p for g in parts for p in (g.geoms if isinstance(g, MultiPolygon) else [g]) if not p.is_empty]
    return MultiPolygon(flat)


def minus(a, b):
    """The areas of ``a`` outside ``b`` (MultiPolygon)."""
    if a is None or a.is_empty or b is None or b.is_empty:
        return _polygons(a)
    return _polygons(a.difference(b))


def polygon(loops) -> MultiPolygon:
    """A shape given as its closed loops in mm (outline, then holes) as a valid MultiPolygon."""
    rings = [np.asarray(loop, np.float64) for loop in loops if len(loop) >= 3]
    if not rings:
        return MultiPolygon()
    return _polygons(shapely.make_valid(Polygon(rings[0], rings[1:])))


def _rounded(x0: float, y0: float, x1: float, y1: float, corner: float) -> np.ndarray:
    r = max(0.0, min(corner, (x1 - x0) / 2, (y1 - y0) / 2))
    rect = shapely_box(x0, y0, x1, y1)
    if r > 1e-6:
        rect = rect.buffer(-r, quad_segs=8).buffer(r, quad_segs=8)
    return np.asarray(rect.exterior.coords[:-1], np.float64)


def _oval(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    """An ellipse through the rectangle's corners' directions, large enough to hold the whole rectangle (the axes √2 times its half sides)."""
    cx, cy, a, b = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 * math.sqrt(2), (y1 - y0) / 2 * math.sqrt(2)
    t = np.linspace(0, 2 * math.pi, 129)[:-1]
    return np.column_stack([cx + a * np.cos(t), cy + b * np.sin(t)])


def _transform(spec: dict, centre: tuple[float, float]):
    """Line coordinates (y up, about the anchor) to the work's mm: the middle ``centre`` moved to the anchor, turned clockwise by the
    rotation, put at (x, y), y down."""
    a = math.radians(spec["rotation"])
    cos, sin = math.cos(a), math.sin(a)

    def to_work(p: np.ndarray) -> np.ndarray:
        u, v = p[:, 0] - centre[0], -(p[:, 1] - centre[1])
        return np.column_stack([spec["x"] + u * cos - v * sin, spec["y"] + u * sin + v * cos])
    return to_work


def _memo_key(spec: dict, face: dict, size_mm: dict | None) -> str:
    try:
        stamp = list(fonts._stamp(Path(face["path"])))
    except OSError:
        stamp = None
    keep = {k: spec[k] for k in FIELDS if k not in ("entry_id", "backing_entry_id", "font")}
    return json.dumps({"spec": keep, "backing_on": spec["backing_entry_id"] is not None, "face": [face["path"], face["index"], face.get("coords"), stamp],
                       "size": size_mm}, sort_keys=True)


def geometry(data_dir: Path, spec: dict, size_mm: dict | None) -> dict:
    """What an inscription engraves and cuts, in the work's mm (module docstring): ``letters``, ``backing`` (None without a backing
    colour), ``cut``; the characters its font lacks (``missing``), whether a part of it fell outside the work (``clipped``), whether the
    text does not fit its arc or circle (``overflow``), the lines whose letters crowd on a tight bend of a path (``crowded``), the curve
    it is laid on (``guide``: points in mm, for the screen) and the frame of the text for the handles on the screen (``frame``: the anchor,
    the four corners of its box and the rotation). ``size_mm`` None: nothing is clipped (the font window). Kept by everything it is
    computed from."""
    face = fonts.resolve(data_dir, spec["font"]) if spec.get("font") else default_face(data_dir)
    key = _memo_key(spec, face, size_mm)
    with _lock:
        if key in _memo:
            _memo.move_to_end(key)
            return _memo[key]
    found = _geometry(face, spec, size_mm)
    with _lock:
        _memo[key] = found
        while len(_memo) > KEEP:
            _memo.popitem(last=False)
    return found


def _geometry(face: dict, spec: dict, size_mm: dict | None) -> dict:
    laid = _lines(face, spec)
    shapes, curve, starts, bend = _placed(spec, laid)
    points = [p for rings in shapes for r in rings for p in r]
    if points:
        pts = np.asarray(points)
        lo, hi = pts.min(axis=0), pts.max(axis=0)
    else:
        lo = hi = np.zeros(2)
    centre = (float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2)) if isinstance(curve, (_Straight, _Arc)) else (0.0, 0.0)
    to_work = _transform(spec, centre)
    glyphs = [_glyph_shape([to_work(r) for r in rings]) for rings in shapes]
    letters = shapely.union_all([g for g in glyphs if g is not None and not g.is_empty]) if shapes else MultiPolygon()
    letters = _polygons(letters)
    crowded = _crowded(curve, laid, glyphs, letters)
    # the backing: a rectangle or an oval about the lines' outlines (bent with them), or the letters' outline widened
    backing_shape = None
    if spec["backing"] != "none" and not letters.is_empty:
        if spec["backing"] == "outline":
            grown = letters.buffer(spec["padding_mm"], quad_segs=8)
            backing_shape = _polygons(shapely.union_all([Polygon(p.exterior) for p in _polygons(grown).geoms]))
        else:
            line_pts = np.vstack([np.column_stack([curve.along(c[:, 0] + starts[g["line"]], g["baseline"]), c[:, 1]])
                                  for g in laid["glyphs"] for c in g["contours"]])          # along the first line, to hold every line
            x0, y0 = line_pts.min(axis=0) - spec["padding_mm"]
            x1, y1 = line_pts.max(axis=0) + spec["padding_mm"]
            ring = _rounded(x0, y0, x1, y1, spec["corner_mm"]) if spec["backing"] == "rect" else _oval(x0, y0, x1, y1)
            backing_shape = _polygons(shapely.make_valid(Polygon(to_work(bend(ring)))))
    gap = spec["gap_mm"]
    widened = letters.buffer(gap, quad_segs=8) if gap > 0 and not letters.is_empty else letters
    if backing_shape is not None and not backing_shape.is_empty:
        engraved = spec["backing_entry_id"] is not None
        backing = _polygons(backing_shape.difference(widened)) if engraved else None
        cut = _polygons(backing_shape.buffer(gap, quad_segs=8) if engraved and gap > 0 else backing_shape)
    else:
        backing, cut = None, _polygons(widened)
    clipped = False
    if size_mm is not None:
        work = shapely_box(0.0, 0.0, size_mm["width"], size_mm["height"])
        whole = cut.area
        letters, cut = _polygons(letters.intersection(work)), _polygons(cut.intersection(work))
        backing = None if backing is None else _polygons(backing.intersection(work))
        clipped = cut.area < whole - 1e-6
    spans = [curve.along([a, a + w], -n * laid["line_step"]) for n, (a, w) in enumerate(zip(starts, laid["widths"]))]
    return {"letters": letters, "backing": backing, "cut": cut, "missing": laid["missing"], "clipped": clipped, "overflow": _overflow(curve, laid),
            "crowded": crowded, "guide": _guide(curve, to_work, spans), "frame": _frame(spec, to_work, lo, hi, centre, curve)}


def _overflow(curve, laid: dict) -> bool:
    """Whether a text does not fit on its arc or circle: a line longer than the circle it runs on (its ends overlap), or letters reaching
    past the centre. A path is looked at letter by letter (:func:`_crowded`)."""
    k = getattr(curve, "k", 0.0)
    if not k:
        return False
    heights = [c[:, 1] for g in laid["glyphs"] for c in g["contours"]]
    if heights and float((1.0 - np.concatenate(heights) * k).min()) <= 0.0:
        return True
    return any(w > 2 * math.pi * (1.0 + n * laid["line_step"] * k) / abs(k) for n, w in enumerate(laid["widths"]))


def _crowded(curve, laid: dict, glyphs: list, letters) -> list[int]:
    """The lines of a text on a path (numbered from 1) whose letters crowd on a tight bend: its letters on the curve overlap one another
    (the sum of their areas less the area of their union) by more than ``CROWD_SHARE`` of its smallest letter beyond what they overlap
    written straight, so letters a font joins by design are no crowd. Upright letters meet on the inside of a bend tighter than about their
    height over the gap between them; bent ones when their tops pass the bend's centre and meet the letters across it, or where a line under
    the first runs past it. ``glyphs``: the letters as placed, in the work (the turn to it keeps their areas); ``letters``: their union,
    which tells at once that no line crowds when all the letters together overlap less than that. An arc and a circle say ``overflow``
    instead (:func:`_overflow`)."""
    if not isinstance(curve, _Path):
        return []
    lines: dict[int, list] = {}
    for g, placed in zip(laid["glyphs"], glyphs):
        if placed is not None and not placed.is_empty:
            lines.setdefault(g["line"], []).append((g["contours"], placed))
    areas = [p.area for line in lines.values() for _, p in line]
    if len(areas) < 2 or sum(areas) - letters.area <= CROWD_SHARE * min(areas):     # a line overlaps no more than all the letters do
        return []
    crowded = []
    for n in sorted(lines):
        contours, placed = zip(*lines[n])
        least = max(CROWD_SHARE * min(p.area for p in placed), 1e-9)
        overlap = sum(p.area for p in placed) - shapely.union_all(placed).area
        if len(placed) < 2 or overlap <= least:
            continue
        straight = [s for s in (_glyph_shape(c) for c in contours) if s is not None]
        if overlap - (sum(s.area for s in straight) - shapely.union_all(straight).area) > least:
            crowded.append(n + 1)
    return crowded


def _guide(curve, to_work, spans: list) -> list[list[float]] | None:
    """The curve a text is laid on, in the work's mm, for the screen: the whole circle, the path, the arc over the text (``spans``: where
    each line starts and ends along it) and a little more."""
    if isinstance(curve, _Straight):
        return None
    if isinstance(curve, _Circle):
        s = np.linspace(0, 2 * math.pi * curve.r, 181)
    elif isinstance(curve, _Path):
        s = curve.s
    else:
        lo, hi = min((float(a) for a, _ in spans), default=0.0), max((float(e) for _, e in spans), default=0.0)
        s = np.linspace(lo - 0.1 * (hi - lo), hi + 0.1 * (hi - lo), 121)
    p = curve.frame(s)[0]
    return np.round(to_work(p), DECIMALS).tolist()


def _frame(spec: dict, to_work, lo, hi, centre, curve) -> dict:
    corners = np.array([[lo[0], hi[1]], [hi[0], hi[1]], [hi[0], lo[1]], [lo[0], lo[1]]])
    anchor = to_work(np.array([centre]))[0]
    return {"anchor": [round(float(anchor[0]), DECIMALS), round(float(anchor[1]), DECIMALS)],
            "corners": np.round(to_work(corners), DECIMALS).tolist(), "rotation": spec["rotation"]}


# -- a work's inscriptions together ---------------------------------------------------------------------------------------------------
def inscribed(data_dir: Path, texts: list[dict], size_mm: dict, measured: set | None) -> dict:
    """Every inscription of a work (``rows``, the lowest first) with its geometry in the work's mm (:func:`geometry`), what it engraves (its
    ``letters`` and ``backing`` without what the inscriptions above it cut away) and why it cannot be engraved (``problem``: its font is
    not on this computer, the font lacks letters of its text, its titanium colour is not chosen or not among the ``measured`` ones any
    more; ``measured`` None: the colours are not looked at); ``cut``: what all of them take out of the picture together (None without
    one)."""
    rows = []
    for spec in texts:
        row = {"text": spec, "geometry": None, "problem": None, "letters": None, "backing": None}
        try:
            row["geometry"] = geometry(data_dir, spec, size_mm)
        except fonts.FontError as exc:
            row["problem"] = str(exc)
        if row["problem"] is None:
            row["problem"] = _why_not_engraved(spec, row["geometry"], measured)
        rows.append(row)
    above = None
    for row in reversed(rows):
        found = row["geometry"]
        if found is None:
            continue
        row["letters"] = minus(found["letters"], above)
        row["backing"] = None if found["backing"] is None else minus(found["backing"], above)
        above = found["cut"] if above is None else shapely.union(above, found["cut"])
    return {"rows": rows, "cut": above if above is not None and not above.is_empty else None}


def _why_not_engraved(spec: dict, found: dict, measured: set | None) -> str | None:
    """Why an inscription laid out (``found``, :func:`geometry`) cannot be engraved: its font lacks letters of its text, or its colour is not
    chosen or not among the ``measured`` ones any more (None: the colours are not looked at)."""
    if found["missing"]:
        return f"its font has no letters «{''.join(found['missing'])}»: choose a font that has them"
    if spec["entry_id"] is None:
        return "choose the titanium colour of its letters"
    if measured is not None and any(spec[k] is not None and spec[k] not in measured for k in ENTRIES):
        return "its titanium colour is no longer measured on this laser, lens and titanium stock: choose another"
    return None


def text_blocker(rows: list[dict]) -> str | None:
    """Why a work's file cannot be written because of its inscriptions (:func:`inscribed`): the first one that cannot be engraved, by its
    number, and why; None when every one can."""
    for n, row in enumerate(rows, 1):
        if row["problem"]:
            return f"inscription {n} cannot be engraved: {row['problem']}"
    return None


def by_colour(rows: list[dict]) -> dict[str, list]:
    """What the inscriptions that can be engraved engrave, by titanium colour: their letters and backings."""
    out: dict[str, list] = {}
    for row in rows:
        if row["problem"]:
            continue
        for part, field in (("letters", "entry_id"), ("backing", "backing_entry_id")):
            shape, entry_id = row[part], row["text"][field]
            if shape is not None and not shape.is_empty and entry_id is not None:
                out.setdefault(entry_id, []).append((row["text"]["id"], shape))
    return out


def shown_row(row: dict, by_id: dict) -> dict:
    """An inscription as a screen draws it: its fields, the paths of its letters, backing and cut (:func:`shown`) as they are engraved (an
    inscription above takes its part away), the colours of its layers (``by_id``: the entries with their colours at their sizes) and why it
    cannot be engraved."""
    spec, found = row["text"], row["geometry"]
    colour = lambda key: by_id[spec[key]]["srgb"] if spec[key] in by_id else None      # noqa: E731
    drawn = shown({**found, "letters": row["letters"], "backing": row["backing"]}) if found is not None else None
    return {**copy.deepcopy(spec), "shown": drawn, "srgb": colour("entry_id"), "backing_srgb": colour("backing_entry_id"), "problem": row["problem"]}


# -- what the screen and the file take -------------------------------------------------------------------------------------------------
def _ring_d(coords) -> str:
    pts = np.round(np.asarray(coords)[:-1], DECIMALS)
    if len(pts) < 3:
        return ""
    return "M" + " L".join(f"{x:g} {y:g}" for x, y in pts) + " Z"


def svg_d(geom) -> str:
    """An SVG path (even-odd) of a MultiPolygon in mm."""
    if geom is None or geom.is_empty:
        return ""
    parts = []
    for poly in _polygons(geom).geoms:
        parts.append(_ring_d(poly.exterior.coords))
        parts += [_ring_d(r.coords) for r in poly.interiors]
    return " ".join(p for p in parts if p)


def shapes(geom) -> list[list[list[list[float]]]]:
    """A MultiPolygon as shapes of closed loops (outline, then holes; mm, the last point not repeated): what a LightBurn path and a row
    length take."""
    if geom is None or geom.is_empty:
        return []
    return [[np.asarray(poly.exterior.coords[:-1]).tolist()] + [np.asarray(r.coords[:-1]).tolist() for r in poly.interiors]
            for poly in _polygons(geom).geoms]


def shown(geom: dict) -> dict:
    """An inscription's geometry as the screen draws it: the paths of the letters, the backing and the cut, the guide and the frame, the
    areas and what to warn about."""
    return {"letters": svg_d(geom["letters"]), "backing": svg_d(geom["backing"]), "cut": svg_d(geom["cut"]), "guide": geom["guide"],
            "frame": geom["frame"], "missing": "".join(geom["missing"]), "clipped": geom["clipped"], "overflow": geom["overflow"],
            "crowded": geom["crowded"],
            "area_mm2": round(geom["letters"].area, 3), "backing_mm2": round(geom["backing"].area, 3) if geom["backing"] is not None else 0.0,
            "empty": geom["letters"].is_empty}


def mask(geom, box: dict, px_per_mm: float, size: tuple[int, int]) -> np.ndarray:
    """A geometry rasterised on a picture of ``size`` (columns, rows) covering ``box`` (mm, its x and y the corner) at ``px_per_mm``: 1 inside,
    0 outside. OpenCV fills the pixels its edges pass through as well, half a pixel more all round: the shape is drawn half a pixel
    smaller, so that the pixels count its area."""
    import cv2
    cols, rows = size
    out = np.zeros((rows, cols), np.uint8)
    if geom is None or geom.is_empty:
        return out
    k, x0, y0 = px_per_mm, box["x"], box["y"]
    polys = []
    for poly in _polygons(geom.buffer(-0.5 / k, join_style="mitre")).geoms:
        for ring in [poly.exterior, *poly.interiors]:
            pts = (np.asarray(ring.coords[:-1]) - [x0, y0]) * k - 0.5
            polys.append(np.round(pts * 16).astype(np.int32))
    if polys:
        cv2.fillPoly(out, polys, 1, shift=4)
    return out


def hole(geom, box: dict, px_per_mm: float, size: tuple[int, int]) -> np.ndarray:
    """The pixels of a picture (as :func:`mask`) that a geometry touches at all, however little: where a picture under an inscription's cut
    engraves nothing, so none of it falls into the gap or on the letters. A pixel touches the shape when its centre is within half a pixel
    of it across; the shape widened by half a diagonal holds every such centre, so the gap grows by at most about a pixel of the picture."""
    if geom is None or geom.is_empty:
        return np.zeros(size[::-1], np.uint8)
    return mask(geom.buffer(math.sqrt(0.5) / px_per_mm), box, px_per_mm, size)


def coverage(geom, box: dict, px_per_mm: float, size: tuple[int, int], supersample: int = 4) -> np.ndarray:
    """How much of every pixel a geometry covers (0..1), for drawing it smoothly on a picture."""
    import cv2
    cols, rows = size
    if geom is None or geom.is_empty:
        return np.zeros((rows, cols), np.float32)
    fine = mask(geom, box, px_per_mm * supersample, (cols * supersample, rows * supersample)).astype(np.float32)
    return cv2.resize(fine, (cols, rows), interpolation=cv2.INTER_AREA)


def preview_svg(data_dir: Path, face_id: str, text: str, height_mm: float = 10.0) -> str:
    """The text in a face as the font window shows it: the outline the file gets, drawn dark, a letter the font lacks drawn as the font's
    missing-letter glyph in red."""
    face = fonts.face(data_dir, face_id)
    text = (text or "").replace("\r\n", "\n")[:200] or SAMPLE
    spec = {**DEFAULTS, "text": text, "height_mm": height_mm, "font": fonts.described(face)}
    laid = _lines(face, spec, notdef=True)
    paths = {False: [], True: []}
    for g in laid["glyphs"]:
        d = " ".join("M" + " L".join(f"{x:.3f} {-y:.3f}" for x, y in c) + " Z" for c in g["contours"])
        paths[g["notdef"]].append(d)
    pts = [p for g in laid["glyphs"] for c in g["contours"] for p in c]
    if not pts:
        return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    arr = np.asarray(pts)
    (x0, y0), (x1, y1) = arr.min(axis=0), arr.max(axis=0)
    pad = height_mm * 0.15
    view = f"{x0 - pad:.3f} {-y1 - pad:.3f} {x1 - x0 + 2 * pad:.3f} {y1 - y0 + 2 * pad:.3f}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}"><path fill="#1f1f1f" fill-rule="nonzero" d="{" ".join(paths[False])}"/>'
            + (f'<path fill="#d32f2f" d="{" ".join(paths[True])}"/>' if paths[True] else "") + "</svg>")

