"""The reader of SVG files for a card (feature-3: import an SVG as editable vector artwork).

:func:`parse` turns the bytes of an SVG file into :class:`~titanium_platform.card_vector_geometry.Parsed`: one :class:`Shape` per painted
area, in painting order (the first is at the bottom), as shapely geometry in MILLIMETRES with y pointing down and the origin at the top-left
of the SVG's viewport, with a design colour (``#rrggbb``, opacity laid on white) and the element's ``id`` as the name. What could not be
carried over is told once, with a count, in ``notes`` (whole English sentences for the operator). A file that cannot be read at all raises
:class:`~titanium_platform.setup.ValidationError`; nothing else is raised for a bad file.

What is read:

* the size and the units of the root (``width``/``height`` in px, mm, cm, in, pt, pc, ``viewBox``, ``preserveAspectRatio``) become ONE
  transform to millimetres that is composed into the current transform matrix, so curves are flattened (within ``FLATNESS_MM``) in mm;
* ``svg`` (nested too), ``g``, ``a``, ``switch`` (its first child that can be shown), ``use`` (also of ``symbol`` and ``svg``, with
  ``viewBox``), ``path`` (the whole path syntax, including arcs and compact numbers), ``rect``, ``circle``, ``ellipse``, ``line``,
  ``polyline``, ``polygon``; every transform function; unknown elements and everything in ``defs`` are not drawn;
* the style: presentation attributes < the rules of ``<style>`` blocks (type, ``.class``, ``#id``, ``*``, comma lists and their
  combinations; anything else is ignored) < the ``style`` attribute; fill, stroke and their parts, fill-rule, opacity (laid on white),
  ``display``, ``visibility``, ``currentColor``; every CSS colour syntax and name;
* a gradient fill becomes the average colour of its stops (the integral over the gradient, stops of ``href`` chains included);
* a stroked element becomes its own shape after its fill shape (width scaled by the transform, cap, join and mitre limit honoured);
* ``clip-path`` (``userSpaceOnUse`` and ``objectBoundingBox``) cuts the shapes; the viewport of a nested ``svg``/``symbol`` cuts them too.

Counted in the notes and not carried over: text, pictures, pattern paints, dashes (drawn solid), masks and filters, markers, references to
objects that are not in the file. The file is untrusted: a DOCTYPE that declares entities is refused before it is parsed, nothing is ever
fetched, and the number of elements, of nodes visited (a ``use`` multiplies them), of flattened vertices, the nesting depth and the time
are all limited (:data:`MAX_ELEMENTS`, :data:`MAX_NODES`, :data:`MAX_VERTICES`, :data:`MAX_DEPTH`, :data:`MAX_SECONDS`); so are long outlines that
cross themselves, which are the one input that makes the geometry library slow beyond reason (:data:`MAX_TANGLED_RING`).
"""
from __future__ import annotations

import colorsys
import functools
import logging
import math
import re
import time
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from typing import NamedTuple

import shapely
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry

from . import card_vector_geometry as vg, setup as su

log = logging.getLogger(__name__)

MAX_BYTES = 32 * 1024 * 1024   # of a file (unpacked, when it is gzipped)
MAX_ELEMENTS = 300_000         # elements in the file
MAX_NODES = 1_000_000          # elements visited when drawing (a use of a group visits it again every time)
MAX_VERTICES = 1_500_000       # of all the flattened outlines
MAX_DEPTH = 100                # of nested groups, symbols and uses
MAX_SECONDS = 60.0             # of drawing
TANGLE_CHECK_MIN = 1000        # an outline of fewer points is never examined for crossing itself ...
MAX_TANGLED_RING = 12_000      # ... one that does cross itself is left out beyond this many points (making it valid takes minutes) ...
MAX_TANGLED_TOTAL = 60_000     # ... and so are all those that come after this many in the file (a stroke weighs a quarter of a fill)
MM_PER_PX = 25.4 / 96.0
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
Affine = tuple[float, float, float, float, float, float]   # (a, b, c, d, e, f): x' = a x + c y + e, y' = b x + d y + f
IDENTITY: Affine = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
TOO_COMPLEX = "This SVG file is too complex to import (%s). Simplify the drawing or export fewer objects, then try again."

# -- tables -----------------------------------------------------------------------------------------------------------------------------
_NAMED_TEXT = """aliceblue f0f8ff antiquewhite faebd7 aqua 00ffff aquamarine 7fffd4 azure f0ffff beige f5f5dc bisque ffe4c4 black 000000
blanchedalmond ffebcd blue 0000ff blueviolet 8a2be2 brown a52a2a burlywood deb887 cadetblue 5f9ea0 chartreuse 7fff00 chocolate d2691e
coral ff7f50 cornflowerblue 6495ed cornsilk fff8dc crimson dc143c cyan 00ffff darkblue 00008b darkcyan 008b8b darkgoldenrod b8860b
darkgray a9a9a9 darkgreen 006400 darkgrey a9a9a9 darkkhaki bdb76b darkmagenta 8b008b darkolivegreen 556b2f darkorange ff8c00
darkorchid 9932cc darkred 8b0000 darksalmon e9967a darkseagreen 8fbc8f darkslateblue 483d8b darkslategray 2f4f4f darkslategrey 2f4f4f
darkturquoise 00ced1 darkviolet 9400d3 deeppink ff1493 deepskyblue 00bfff dimgray 696969 dimgrey 696969 dodgerblue 1e90ff
firebrick b22222 floralwhite fffaf0 forestgreen 228b22 fuchsia ff00ff gainsboro dcdcdc ghostwhite f8f8ff gold ffd700 goldenrod daa520
gray 808080 green 008000 greenyellow adff2f grey 808080 honeydew f0fff0 hotpink ff69b4 indianred cd5c5c indigo 4b0082 ivory fffff0
khaki f0e68c lavender e6e6fa lavenderblush fff0f5 lawngreen 7cfc00 lemonchiffon fffacd lightblue add8e6 lightcoral f08080
lightcyan e0ffff lightgoldenrodyellow fafad2 lightgray d3d3d3 lightgreen 90ee90 lightgrey d3d3d3 lightpink ffb6c1 lightsalmon ffa07a
lightseagreen 20b2aa lightskyblue 87cefa lightslategray 778899 lightslategrey 778899 lightsteelblue b0c4de lightyellow ffffe0
lime 00ff00 limegreen 32cd32 linen faf0e6 magenta ff00ff maroon 800000 mediumaquamarine 66cdaa mediumblue 0000cd mediumorchid ba55d3
mediumpurple 9370db mediumseagreen 3cb371 mediumslateblue 7b68ee mediumspringgreen 00fa9a mediumturquoise 48d1cc
mediumvioletred c71585 midnightblue 191970 mintcream f5fffa mistyrose ffe4e1 moccasin ffe4b5 navajowhite ffdead navy 000080
oldlace fdf5e6 olive 808000 olivedrab 6b8e23 orange ffa500 orangered ff4500 orchid da70d6 palegoldenrod eee8aa palegreen 98fb98
paleturquoise afeeee palevioletred db7093 papayawhip ffefd5 peachpuff ffdab9 peru cd853f pink ffc0cb plum dda0dd powderblue b0e0e6
purple 800080 rebeccapurple 663399 red ff0000 rosybrown bc8f8f royalblue 4169e1 saddlebrown 8b4513 salmon fa8072 sandybrown f4a460
seagreen 2e8b57 seashell fff5ee sienna a0522d silver c0c0c0 skyblue 87ceeb slateblue 6a5acd slategray 708090 slategrey 708090
snow fffafa springgreen 00ff7f steelblue 4682b4 tan d2b48c teal 008080 thistle d8bfd8 tomato ff6347 turquoise 40e0d0 violet ee82ee
wheat f5deb3 white ffffff whitesmoke f5f5f5 yellow ffff00 yellowgreen 9acd32""".split()
NAMED_COLOURS = {name: "#" + value for name, value in zip(_NAMED_TEXT[0::2], _NAMED_TEXT[1::2])}

_PX_PER = {"": 1.0, "px": 1.0, "mm": 96.0 / 25.4, "cm": 96.0 / 2.54, "in": 96.0, "pt": 96.0 / 72.0, "pc": 16.0, "q": 96.0 / 101.6}
_RELATIVE_PX = {"em": 16.0, "rem": 16.0, "ex": 8.0}      # a font is not known: the browsers' default size stands in for it
_INHERITED = frozenset({"fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linecap", "stroke-linejoin",
                        "stroke-miterlimit", "stroke-dasharray", "color", "visibility", "clip-rule", "marker-start", "marker-mid", "marker-end"})
_PROPS = _INHERITED | {"opacity", "display", "clip-path", "mask", "filter", "stop-color", "stop-opacity", "overflow"}
_SHAPES = frozenset({"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"})
_DRAWN = _SHAPES | {"svg", "g", "a", "switch", "use", "text", "image", "foreignObject"}
_GRADIENTS = frozenset({"linearGradient", "radialGradient"})
_EMPTY: dict = {}               # shared and never changed
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_NUM_RE = re.compile(_NUM)
_LENGTH_RE = re.compile(rf"^\s*({_NUM})\s*([A-Za-z%]*)\s*$")
_SEP = re.compile(r"[\s,]*")
_FLAG = re.compile(r"[01]")
_URL = re.compile(r"""^url\(\s*['"]?#([^'")\s]+)['"]?\s*\)\s*(.*)$""", re.I | re.S)
_TRANSFORM_FN = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
_COLOUR_FN = re.compile(r"^(rgba?|hsla?)\(\s*(.*?)\s*\)$")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
_BLACK = ("#000000", 1.0)
_LIMIT = 1e9                    # a number beyond this is a broken file, not a drawing
_LIMIT_MM = 1e7                 # an outline reaching beyond this many mm (10 km) from the origin is nothing a card can hold


class _Ctx(NamedTuple):
    """Where the drawing has got to: the transform to mm, the inherited properties, the opacity of the ancestors, the clip they set, the size
    of the viewport (for percentages), the id of the ``use`` that instantiates the element, the ids being instantiated, the depth."""
    ctm: Affine
    inh: dict
    opacity: float
    clip: BaseGeometry | None
    vp: tuple[float, float]
    name: str | None
    stack: tuple
    depth: int


# -- numbers, lengths, transforms -------------------------------------------------------------------------------------------------------
def _length(text, base: float = 0.0, default: float | None = 0.0) -> float | None:
    """A length in user units (px); ``%`` is a share of ``base``; an unreadable or missing length is ``default``."""
    if text is None:
        return default
    m = _LENGTH_RE.match(text)
    if m is None:
        return default
    value, unit = float(m.group(1)), m.group(2).lower()
    factor = base / 100.0 if unit == "%" else _PX_PER.get(unit) or _RELATIVE_PX.get(unit)
    result = None if factor is None else value * factor
    return result if result is not None and -_LIMIT < result < _LIMIT else default


def _absolute_px(text) -> float | None:
    """A positive length in an absolute unit, in px; percentages, font-relative units and nonsense are None."""
    if text is None:
        return None
    m = _LENGTH_RE.match(text)
    factor = _PX_PER.get(m.group(2).lower()) if m else None
    if factor is None:
        return None
    value = float(m.group(1)) * factor
    return value if value > 0 and math.isfinite(value) else None


def _alpha(text) -> float:
    """An opacity (a number or a percentage) clamped to 0..1; unreadable is 1."""
    if text is None:
        return 1.0
    try:
        t = text.strip()
        value = float(t[:-1]) / 100.0 if t.endswith("%") else float(t)
    except ValueError:
        return 1.0
    return 0.0 if value != value else max(0.0, min(1.0, value))


def _mul(m: Affine, n: Affine) -> Affine:
    """The transform that applies ``n`` first and then ``m``."""
    return (m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1], m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
            m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5])


def _invert(m: Affine) -> Affine | None:
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-18:
        return None
    return (d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det)


@functools.lru_cache(maxsize=4096)
def _transform(text: str) -> Affine:
    """The matrix of a ``transform`` attribute (a list of functions, the last applied first); a function that cannot be read is skipped."""
    result = IDENTITY
    for name, args in _TRANSFORM_FN.findall(text):
        v = [float(x) for x in _NUM_RE.findall(args)]
        n = len(v)
        if not all(-_LIMIT < x < _LIMIT for x in v):
            continue
        if name == "matrix" and n == 6:
            m = (v[0], v[1], v[2], v[3], v[4], v[5])
        elif name == "translate" and n in (1, 2):
            m = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if n == 2 else 0.0)
        elif name == "scale" and n in (1, 2):
            m = (v[0], 0.0, 0.0, v[1] if n == 2 else v[0], 0.0, 0.0)
        elif name == "rotate" and n in (1, 3):
            r = math.radians(v[0])
            cos, sin = math.cos(r), math.sin(r)
            m = (cos, sin, -sin, cos, 0.0, 0.0)
            if n == 3:
                m = _mul(_mul((1.0, 0.0, 0.0, 1.0, v[1], v[2]), m), (1.0, 0.0, 0.0, 1.0, -v[1], -v[2]))
        elif name == "skewX" and n == 1:
            m = (1.0, 0.0, math.tan(math.radians(v[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and n == 1:
            m = (1.0, math.tan(math.radians(v[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        result = _mul(result, m)
    return result


def _viewbox(text) -> tuple[float, float, float, float] | None:
    if not text:
        return None
    v = [float(x) for x in _NUM_RE.findall(text)]
    return (v[0], v[1], v[2], v[3]) if len(v) == 4 and v[2] > 0 and v[3] > 0 and all(-_LIMIT < x < _LIMIT for x in v) else None


def _fit(box: tuple[float, float, float, float], width: float, height: float, aspect: str | None) -> Affine:
    """The transform that maps a ``viewBox`` onto a viewport of ``width`` x ``height`` at the origin (``preserveAspectRatio``)."""
    x, y, bw, bh = box
    words = (aspect or "").replace(",", " ").split()
    if words and words[0] == "defer":
        words = words[1:]
    align = words[0] if words else "xMidYMid"
    if align == "none":
        sx, sy = width / bw, height / bh
        return (sx, 0.0, 0.0, sy, -x * sx, -y * sy)
    scale = (max if len(words) > 1 and words[1] == "slice" else min)(width / bw, height / bh)
    share = {"Min": 0.0, "Mid": 0.5, "Max": 1.0}
    fx, fy = share.get(align[1:4], 0.5), share.get(align[5:8], 0.5)
    return (scale, 0.0, 0.0, scale, (width - bw * scale) * fx - x * scale, (height - bh * scale) * fy - y * scale)


def _scales(m: Affine) -> tuple[float, float]:
    """The largest stretch of a transform and the square root of its area factor (what a stroke width is multiplied by)."""
    a, b, c, d = m[:4]
    det = a * d - b * c
    s = a * a + b * b + c * c + d * d
    largest = math.sqrt((s + math.sqrt(max(0.0, s * s - 4.0 * det * det))) / 2.0)
    return largest, math.sqrt(abs(det))


# -- colours ----------------------------------------------------------------------------------------------------------------------------
def _channel(token: str, scale: float) -> float:
    return float(token[:-1]) * scale / 100.0 if token.endswith("%") else float(token)


def _colour(text: str, current: str = "#000000") -> tuple[str, float] | None:
    """``(#rrggbb, alpha)`` of a CSS colour (hex, rgb(a), hsl(a), a name, transparent, currentColor = ``current``); None if it is not one."""
    t = text.strip().lower()
    if not t:
        return None
    try:
        if t[0] == "#":
            h = t[1:]
            if not all(ch in "0123456789abcdef" for ch in h):
                return None
            if len(h) in (3, 4):
                h = "".join(ch * 2 for ch in h)
            if len(h) == 6:
                return "#" + h, 1.0
            return ("#" + h[:6], int(h[6:], 16) / 255.0) if len(h) == 8 else None
        if t in NAMED_COLOURS:
            return NAMED_COLOURS[t], 1.0
        if t == "transparent":
            return "#000000", 0.0
        if t == "currentcolor":
            return _colour(current, "#000000") if current.strip().lower() != "currentcolor" else _BLACK
        m = _COLOUR_FN.match(t)
        if m is None:
            return None
        parts = [p for p in re.split(r"[\s,/]+", m.group(2)) if p]
        if len(parts) not in (3, 4):
            return None
        alpha = max(0.0, min(1.0, _channel(parts[3], 1.0))) if len(parts) == 4 else 1.0
        if m.group(1).startswith("rgb"):
            return vg.hex_colour(*(_channel(p, 255.0) for p in parts[:3])), alpha
        hue = parts[0]
        turns = {"turn": 360.0, "rad": 180.0 / math.pi, "grad": 0.9, "deg": 1.0}
        unit = next((u for u in turns if hue.endswith(u)), "")
        degrees = float(hue[:len(hue) - len(unit)]) * turns.get(unit, 1.0)
        saturation = max(0.0, min(1.0, _channel(parts[1], 100.0) / 100.0))
        lightness = max(0.0, min(1.0, _channel(parts[2], 100.0) / 100.0))
        r, g, b = colorsys.hls_to_rgb((degrees / 360.0) % 1.0, lightness, saturation)
        return vg.hex_colour(r, g, b, scale=1.0), alpha
    except (ValueError, OverflowError):
        return None


# -- style sheets -----------------------------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=8192)
def _declarations(text: str) -> dict:
    """The properties of a declaration block (``a: b; c: d``) that matter here; ``!important`` is not told apart. Never changed by callers."""
    out = {}
    for item in re.split(r";(?![^()]*\))", text):
        name, colon, value = item.partition(":")
        name = name.strip().lower()
        if colon and name in _PROPS:
            out[name] = re.sub(r"\s*!\s*important\s*$", "", value.strip(), flags=re.I)
    return out


_SIMPLE_SELECTOR = re.compile(r"^(\*|[A-Za-z_][\w-]*)?((?:[.#][A-Za-z_][\w-]*)*)$")
_SELECTOR_PART = re.compile(r"([.#])([A-Za-z_][\w-]*)")


def _style_rules(css: str, order: int) -> list[tuple]:
    """``(specificity, order, tag, ids, classes, declarations)`` for every simple selector of a style sheet; at-rules, selectors with
    combinators, pseudo-classes or attributes, and anything unreadable are skipped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules, pos, n = [], 0, len(css)
    while pos < n:
        while pos < n and css[pos].isspace():
            pos += 1
        if pos >= n:
            break
        brace, semi = css.find("{", pos), css.find(";", pos)
        if css[pos] == "@":
            if brace < 0 or (0 <= semi < brace):
                pos = n if semi < 0 else semi + 1
                continue
            depth, i = 0, brace
            while i < n:
                depth += css[i] == "{"
                depth -= css[i] == "}"
                i += 1
                if depth == 0:
                    break
            pos = i
            continue
        if brace < 0:
            break
        close = css.find("}", brace)
        close = n if close < 0 else close
        decls = _declarations(css[brace + 1:close])
        for selector in css[pos:brace].split(","):
            m = _SIMPLE_SELECTOR.match(selector.strip())
            if m is None or not decls:
                continue
            tag = m.group(1)
            parts = _SELECTOR_PART.findall(m.group(2))
            ids = tuple(name for kind, name in parts if kind == "#")
            classes = tuple(name for kind, name in parts if kind == ".")
            if tag is None and not ids and not classes:
                continue
            specificity = (len(ids), len(classes), 1 if tag and tag != "*" else 0)
            rules.append((specificity, order + len(rules), tag, ids, classes, decls))
        pos = close + 1
    return rules


_TAG_CACHE: dict = {}
_MISSING = object()


def _local(tag) -> str | None:
    """The name of an element of the SVG namespace (or of no namespace); None for another vocabulary."""
    name = _TAG_CACHE.get(tag, _MISSING)
    if name is _MISSING:
        if isinstance(tag, str):
            if tag[:1] == "{":
                ns, _, rest = tag[1:].partition("}")
                name = rest if ns == SVG_NS else None
            else:
                name = tag
        else:
            name = None
        if len(_TAG_CACHE) < 4096:
            _TAG_CACHE[tag] = name
    return name


def _href(el) -> str | None:
    value = el.get("href") or el.get(XLINK_HREF)
    return value.strip() if value else None


def _inherit(decl: dict, inh: dict) -> dict:
    """The inherited properties of an element: the parent's, overridden by what the element declares."""
    update = None
    for key, value in decl.items():
        if key in _INHERITED and value != "inherit":
            if update is None:
                update = {}
            update[key] = value
    return inh if update is None else {**inh, **update}


# -- path data --------------------------------------------------------------------------------------------------------------------------
def _path_segments(d: str) -> list[tuple]:
    """The segments of path data, all absolute: ``("M", x, y)``, ``("L", x, y)``, ``("C", x1, y1, x2, y2, x, y)``, ``("Q", cx, cy, x, y)``,
    ``("A", rx, ry, rotation, large, sweep, x, y)`` and ``("Z",)``. H, V, S and T are expressed by those. Data that breaks off, or cannot be
    read, ends the path there (as the browsers draw it)."""
    segs: list[tuple] = []
    n, pos = len(d), 0
    cmd = ""
    x = y = sx = sy = lx = ly = 0.0           # the current point, where the sub-path began, the last control point
    last = ""
    skip, number, flag = _SEP.match, _NUM_RE.match, _FLAG.match
    while True:
        pos = skip(d, pos).end()
        if pos >= n:
            break
        ch = d[pos]
        if ch.isalpha():
            up = ch.upper()
            if up not in _ARITY or (not segs and up != "M"):
                break
            cmd = ch
            pos += 1
            if up == "Z":
                segs.append(("Z",))
                x, y = sx, sy
                last = "Z"
                continue
        elif not cmd or cmd in "Zz":
            break
        up = cmd.upper()
        relative = cmd != up
        args = []
        for i in range(_ARITY[up]):
            pos = skip(d, pos).end()
            m = flag(d, pos) if up == "A" and i in (3, 4) else number(d, pos)
            if m is None:
                break
            value = float(m.group())
            if not -_LIMIT < value < _LIMIT:
                break
            args.append(value)
            pos = m.end()
        else:
            if relative and up != "A":
                ox, oy = x, y
            else:
                ox = oy = 0.0
            if up == "M" or up == "L" or up == "T":
                nx, ny = args[0] + ox, args[1] + oy
                if up == "M":
                    segs.append(("M", nx, ny))
                    sx, sy = nx, ny
                    cmd = "l" if relative else "L"
                elif up == "L":
                    segs.append(("L", nx, ny))
                else:
                    qx, qy = (2.0 * x - lx, 2.0 * y - ly) if last in ("Q", "T") else (x, y)
                    segs.append(("Q", qx, qy, nx, ny))
                    lx, ly = qx, qy
            elif up == "H":
                nx, ny = args[0] + ox, y
                segs.append(("L", nx, ny))
            elif up == "V":
                nx, ny = x, args[0] + oy
                segs.append(("L", nx, ny))
            elif up == "C":
                nx, ny = args[4] + ox, args[5] + oy
                lx, ly = args[2] + ox, args[3] + oy
                segs.append(("C", args[0] + ox, args[1] + oy, lx, ly, nx, ny))
            elif up == "S":
                nx, ny = args[2] + ox, args[3] + oy
                x1, y1 = (2.0 * x - lx, 2.0 * y - ly) if last in ("C", "S") else (x, y)
                lx, ly = args[0] + ox, args[1] + oy
                segs.append(("C", x1, y1, lx, ly, nx, ny))
            elif up == "Q":
                nx, ny = args[2] + ox, args[3] + oy
                lx, ly = args[0] + ox, args[1] + oy
                segs.append(("Q", lx, ly, nx, ny))
            else:                                                  # A
                nx, ny = (args[5] + x, args[6] + y) if relative else (args[5], args[6])
                segs.append(("A", args[0], args[1], args[2], args[3] != 0.0, args[4] != 0.0, nx, ny))
            x, y = nx, ny
            last = up
            continue
        break                                                      # an argument is missing or unreadable: the path ends here
    return segs


def _flatten(segs: list[tuple], flatness: float) -> list[tuple[list, bool]]:
    """The sub-paths of segments as ``(points, closed)``, curves flattened to within ``flatness`` (in the units of the segments)."""
    out: list[tuple[list, bool]] = []
    pts = None
    sx = sy = cx = cy = 0.0
    for s in segs:
        kind = s[0]
        if kind == "M":
            if pts:
                out.append((pts, False))
            cx, cy = sx, sy = s[1], s[2]
            pts = [(cx, cy)]
            continue
        if kind == "Z":
            if pts:
                out.append((pts, True))
            pts = None
            cx, cy = sx, sy
            continue
        if pts is None:                                            # drawing after a close starts a new sub-path where the last began
            pts = [(sx, sy)]
            cx, cy = sx, sy
        if kind == "L":
            cx, cy = s[1], s[2]
            pts.append((cx, cy))
        elif kind == "C":
            pts.extend(vg.cubic((cx, cy), (s[1], s[2]), (s[3], s[4]), (s[5], s[6]), flatness))
            cx, cy = s[5], s[6]
        elif kind == "Q":
            pts.extend(vg.quadratic((cx, cy), (s[1], s[2]), (s[3], s[4]), flatness))
            cx, cy = s[3], s[4]
        else:
            pts.extend(vg.arc((cx, cy), s[1], s[2], s[3], s[4], s[5], (s[6], s[7]), flatness))
            cx, cy = s[6], s[7]
    if pts:
        out.append((pts, False))
    return out


def _numbers(text) -> list[float]:
    """The numbers in a text; none at all when one of them is beyond reason (the element is then not drawn)."""
    found = [float(v) for v in _NUM_RE.findall(text or "")]
    return found if all(-_LIMIT < v < _LIMIT for v in found) else []


# -- the reader -------------------------------------------------------------------------------------------------------------------------
class _Reader:
    """The state of reading one file: the elements by id, the style rules, the shapes found so far, what was lost, and the budgets."""

    def __init__(self, root: ET.Element):
        self.root = root
        self.ids: dict[str, ET.Element] = {}
        self.shapes: list[vg.Shape] = []
        self.counts: Counter = Counter()
        self.verts = 0
        self.nodes = 0
        self.tangled = 0.0                                         # points of the long self-crossing outlines made into geometry so far
        self.dry = False                                           # measuring an element for objectBoundingBox: no strokes
        self.deadline = time.monotonic() + MAX_SECONDS
        self._clips: dict = {}
        self._gradients: dict = {}
        self._css_cache: dict = {}
        self.universal: list = []
        self.by_tag: dict[str, list] = {}
        self.by_id: dict[str, list] = {}
        self.by_class: dict[str, list] = {}
        self.has_rules = False
        self._index()

    # -- set-up
    def _index(self) -> None:
        sheets = []
        for count, el in enumerate(self.root.iter(), 1):
            if count > MAX_ELEMENTS:
                raise su.ValidationError(TOO_COMPLEX % f"more than {MAX_ELEMENTS:,} elements".replace(",", " "))
            name = _local(el.tag)
            ident = el.get("id")
            if ident:
                self.ids.setdefault(ident, el)
            if name == "style" and "css" in (el.get("type") or "text/css").lower():
                sheets.append("".join(el.itertext()))
        order = 0
        for css in sheets:
            for rule in _style_rules(css, order):
                order = rule[1] + 1
                tag, ids, classes = rule[2], rule[3], rule[4]
                if ids:
                    self.by_id.setdefault(ids[0], []).append(rule)
                elif classes:
                    self.by_class.setdefault(classes[0], []).append(rule)
                elif tag and tag != "*":
                    self.by_tag.setdefault(tag, []).append(rule)
                else:
                    self.universal.append(rule)
        self.has_rules = bool(self.universal or self.by_tag or self.by_id or self.by_class)

    def _tick(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise su.ValidationError(TOO_COMPLEX % "the same parts are used too many times")
        if not self.nodes & 63 and time.monotonic() > self.deadline:
            raise su.ValidationError(TOO_COMPLEX % "it takes too long to read")

    # -- style
    def _css_for(self, el, tag: str) -> dict:
        ident, classes = el.get("id"), el.get("class")
        key = (tag, ident, classes)
        hit = None if ident else self._css_cache.get(key)
        if hit is None:
            names = classes.split() if classes else []
            found = list(self.universal) + self.by_tag.get(tag, [])
            if ident:
                found += self.by_id.get(ident, [])
            for name in names:
                found += self.by_class.get(name, [])
            found = [r for r in found if (r[2] is None or r[2] == "*" or r[2] == tag) and all(i == ident for i in r[3])
                     and all(c in names for c in r[4])]
            found.sort(key=lambda r: (r[0], r[1]))
            hit = {}
            for rule in found:
                hit.update(rule[5])
            if not ident:
                self._css_cache[key] = hit
        return hit

    def _declared(self, el, tag: str) -> dict:
        """The properties an element declares: presentation attributes, then style sheet rules, then its ``style`` attribute. Never changed."""
        attrib = el.attrib
        out = None
        for key, value in attrib.items():
            if key in _PROPS:
                if out is None:
                    out = {}
                out[key] = value.strip()
        if self.has_rules:
            css = self._css_for(el, tag)
            if css:
                if out is None:
                    out = dict(css)
                else:
                    out.update(css)
        style = attrib.get("style")
        if style:
            decls = _declarations(style)
            if decls:
                if out is None:
                    out = dict(decls)
                else:
                    out.update(decls)
        return _EMPTY if out is None else out

    def _paint(self, raw: str, st: dict, default) -> tuple[str, float] | None:
        """``(#rrggbb, alpha)`` of a paint value or None for no paint; a gradient is its average colour, a pattern is nothing (both counted)."""
        text = raw.strip()
        low = text.lower()
        if low == "none":
            return None
        if low.startswith("url("):
            m = _URL.match(text)
            if m is None:
                return default
            target = self.ids.get(m.group(1))
            tag = _local(target.tag) if target is not None else None
            if tag in _GRADIENTS:
                colour = self._gradient(m.group(1))
                if colour is None:
                    return None
                self.counts["gradient"] += 1
                return colour, 1.0
            if tag == "pattern":
                self.counts["pattern"] += 1
                return None
            fallback = m.group(2).strip()
            return None if not fallback or fallback.lower().startswith("url(") else self._paint(fallback, st, default)
        found = _colour(text, st.get("color", "#000000"))
        return default if found is None else found

    def _gradient(self, ident: str) -> str | None:
        """The average colour (on white) of a gradient's stops, those of the gradients it points to included; None when it has no stops."""
        if ident in self._gradients:
            return self._gradients[ident]
        stops, seen, el = [], set(), self.ids.get(ident)
        while el is not None and id(el) not in seen and _local(el.tag) in _GRADIENTS:
            seen.add(id(el))
            stops = [c for c in el if _local(c.tag) == "stop"]
            if stops:
                break
            href = _href(el)
            el = self.ids.get(href[1:]) if href and href.startswith("#") else None
        points = []
        for stop in stops:
            decl = self._declared(stop, "stop")
            try:
                text = (stop.get("offset") or "0").strip()
                offset = float(text[:-1]) / 100.0 if text.endswith("%") else float(text)
            except ValueError:
                offset = 0.0
            colour = _colour(decl.get("stop-color", "#000000"), decl.get("color", "#000000")) or _BLACK
            hex_on_white = vg.on_white(colour[0], colour[1] * _alpha(decl.get("stop-opacity")))
            points.append((max(0.0, min(1.0, offset)), vg.rgb_of(hex_on_white)))
        result = None
        if points:
            for i in range(1, len(points)):
                points[i] = (max(points[i][0], points[i - 1][0]), points[i][1])
            parts = [(points[0][0], points[0][1], points[0][1])]
            parts += [(b[0] - a[0], a[1], b[1]) for a, b in zip(points, points[1:])]
            parts.append((1.0 - points[-1][0], points[-1][1], points[-1][1]))
            total = sum(w for w, _, _ in parts)
            if total > 0:
                channels = [sum(w * (c0[k] + c1[k]) / 2.0 for w, c0, c1 in parts) / total for k in range(3)]
            else:
                channels = [sum(p[1][k] for p in points) / len(points) for k in range(3)]
            result = vg.hex_colour(*channels)
        self._gradients[ident] = result
        return result

    # -- the tree
    def _node(self, el, ctx: _Ctx) -> None:
        tag = _local(el.tag)
        if tag not in _DRAWN:
            return
        self._tick()
        decl = self._declared(el, tag)
        if decl.get("display") == "none":
            return
        opacity = ctx.opacity * _alpha(decl.get("opacity")) if "opacity" in decl else ctx.opacity
        if opacity <= 0.0:
            return
        transform = el.get("transform")
        sub = ctx._replace(ctm=_mul(ctx.ctm, _transform(transform)) if transform else ctx.ctm, inh=_inherit(decl, ctx.inh), opacity=opacity)
        if decl:
            if any(decl.get(k, "none").strip() != "none" for k in ("mask", "filter")):
                self.counts["effect"] += 1
            ref = _URL.match(decl["clip-path"]) if "clip-path" in decl else None
            if ref is not None:
                region = self._clip_region(ref.group(1), el, tag, sub)
                if region is not None:
                    sub = sub._replace(clip=self._intersect(sub.clip, region))
        self._content(el, tag, sub)

    def _children(self, el, ctx: _Ctx) -> None:
        if ctx.depth >= MAX_DEPTH:
            raise su.ValidationError(TOO_COMPLEX % "the parts are nested too deeply")
        sub = ctx._replace(depth=ctx.depth + 1)
        for child in el:
            self._node(child, sub)

    def _content(self, el, tag: str, ctx: _Ctx) -> None:
        if tag in _SHAPES:
            self._shape(el, tag, ctx)
        elif tag == "g" or tag == "a":
            self._children(el, ctx)
        elif tag == "svg":
            if el is self.root:
                self._children(el, ctx)
            else:
                self._viewport(el, "svg", ctx, x=_length(el.get("x"), ctx.vp[0]), y=_length(el.get("y"), ctx.vp[1]))
        elif tag == "use":
            self._use(el, ctx)
        elif tag == "switch":
            for child in el:
                if self._conditions(child):
                    self._node(child, ctx._replace(depth=ctx.depth + 1))
                    break
        elif tag == "text" or tag == "foreignObject":
            if "".join(el.itertext()).strip():
                self.counts["text"] += 1
        elif tag == "image":
            self.counts["image"] += 1

    @staticmethod
    def _conditions(child) -> bool:
        """Whether a child of ``switch`` can be the one shown: an SVG element that asks for no extension and for no other language."""
        if _local(child.tag) is None:
            return False
        if (child.get("requiredExtensions") or "").strip():
            return False
        languages = (child.get("systemLanguage") or "").replace(",", " ").split()
        return not languages or any(lang.lower().startswith("en") for lang in languages)

    def _use(self, el, ctx: _Ctx) -> None:
        href = _href(el)
        if not href:
            return
        target = self.ids.get(href[1:]) if href.startswith("#") else None
        if target is None:
            self.counts["missing"] += 1
            return
        ident = href[1:]
        if ident in ctx.stack or ctx.depth >= MAX_DEPTH:
            return
        dx, dy = _length(el.get("x"), ctx.vp[0]), _length(el.get("y"), ctx.vp[1])
        ctm = _mul(ctx.ctm, (1.0, 0.0, 0.0, 1.0, dx, dy)) if dx or dy else ctx.ctm
        sub = ctx._replace(ctm=ctm, name=el.get("id") or ctx.name, stack=ctx.stack + (ident,), depth=ctx.depth + 1)
        if _local(target.tag) == "symbol":
            sub = sub._replace(inh=_inherit(self._declared(target, "symbol"), sub.inh))
            self._viewport(target, "symbol", sub, w=_length(el.get("width"), ctx.vp[0], None), h=_length(el.get("height"), ctx.vp[1], None))
        else:
            self._node(target, sub)

    def _viewport(self, el, tag: str, ctx: _Ctx, *, x: float = 0.0, y: float = 0.0, w: float | None = None, h: float | None = None) -> None:
        """The content of a nested ``svg`` or a ``symbol``: placed at (x, y), sized, fitted to its ``viewBox``, cut at its edge."""
        if w is None:
            w = _length(el.get("width"), ctx.vp[0], None)
        if h is None:
            h = _length(el.get("height"), ctx.vp[1], None)
        sized = w is not None and h is not None and w > 0 and h > 0
        w = ctx.vp[0] if w is None else w
        h = ctx.vp[1] if h is None else h
        sub = ctx._replace(ctm=_mul(ctx.ctm, (1.0, 0.0, 0.0, 1.0, x, y)))
        box = _viewbox(el.get("viewBox"))
        if box is not None and w > 0 and h > 0:
            sub = sub._replace(ctm=_mul(sub.ctm, _fit(box, w, h, el.get("preserveAspectRatio"))), vp=(box[2], box[3]))
        elif w > 0 and h > 0:
            sub = sub._replace(vp=(w, h))
        if sized and self._declared(el, tag).get("overflow", "hidden") not in ("visible", "auto"):
            a, b, c, d, e, f = ctx.ctm
            corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            frame = Polygon([(a * px + c * py + e, b * px + d * py + f) for px, py in corners])
            if frame.is_valid and not frame.is_empty:
                sub = sub._replace(clip=self._intersect(ctx.clip, frame))
        self._children(el, sub)

    # -- clipping
    @staticmethod
    def _intersect(a: BaseGeometry | None, b: BaseGeometry) -> BaseGeometry:
        if a is None:
            shapely.prepare(b)
            return b
        try:
            both = vg.polygonal(a.intersection(b))
        except shapely.errors.ShapelyError:
            both = b
        shapely.prepare(both)
        return both

    def _clip_region(self, ref: str, el, tag: str, ctx: _Ctx) -> BaseGeometry | None:
        """The area a ``clip-path`` leaves visible, in mm; None when the reference is not a clipPath (the element is then not clipped)."""
        path = self.ids.get(ref)
        if path is None or _local(path.tag) != "clipPath":
            return None
        m = ctx.ctm
        transform = path.get("transform")
        if transform:
            m = _mul(m, _transform(transform))
        if (path.get("clipPathUnits") or "").strip() == "objectBoundingBox":
            box = self._user_bounds(el, tag, ctx)
            if box is None or box[2] <= box[0] or box[3] <= box[1]:
                region = Polygon()
                shapely.prepare(region)
                return region
            m = _mul(m, (box[2] - box[0], 0.0, 0.0, box[3] - box[1], box[0], box[1]))
        key = (ref, tuple(round(v, 7) for v in m))
        region = self._clips.get(key)
        if region is None:
            rule = self._declared(path, "clipPath").get("clip-rule", "nonzero")
            parts = [g for g in (self._clip_child(child, _local(child.tag), m, ctx.vp, rule, 0) for child in path) if g is not None]
            try:
                region = vg.polygonal(shapely.union_all(parts)) if parts else Polygon()
            except shapely.errors.ShapelyError:
                region = Polygon()
            shapely.prepare(region)
            self._clips[key] = region
        return region

    def _clip_child(self, el, tag: str | None, m: Affine, vp, rule: str, depth: int) -> BaseGeometry | None:
        if tag not in _SHAPES and tag != "use" or depth > 8:
            return None
        decl = self._declared(el, tag)
        if decl.get("display") == "none":
            return None
        transform = el.get("transform")
        if transform:
            m = _mul(m, _transform(transform))
        if tag == "use":
            href = _href(el)
            target = self.ids.get(href[1:]) if href and href.startswith("#") else None
            if target is None:
                return None
            dx, dy = _length(el.get("x"), vp[0]), _length(el.get("y"), vp[1])
            return self._clip_child(target, _local(target.tag), _mul(m, (1.0, 0.0, 0.0, 1.0, dx, dy)), vp, rule, depth + 1)
        largest, _ = _scales(m)
        if not 0 < largest < math.inf:
            return None
        rings = [pts for pts, _closed in self._outline(el, tag, vp, m, vg.FLATNESS_MM / largest) if len(pts) >= 3 and not self._tangled(pts, True, 1.0)]
        try:
            return vg.region(rings, decl.get("clip-rule", rule)) if rings else None
        except shapely.errors.ShapelyError:
            return None

    def _user_bounds(self, el, tag: str, ctx: _Ctx) -> tuple[float, float, float, float] | None:
        """The bounding box of an element in its own user space (what ``objectBoundingBox`` is measured on): it is drawn once, aside, and its
        shapes are taken back through the inverse of its transform."""
        inverse = _invert(ctx.ctm)
        if inverse is None:
            return None
        saved = (self.shapes, self.counts, self.dry)
        self.shapes, self.counts, self.dry = [], Counter(), True
        try:
            self._content(el, tag, ctx._replace(clip=None))
            found = self.shapes
        finally:
            self.shapes, self.counts, self.dry = saved
        a, b, c, d, e, f = inverse
        boxes = [affine_transform(s.geometry, [a, c, b, d, e, f]).bounds for s in found if not s.geometry.is_empty]
        if not boxes:
            return None
        return min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)

    # -- outlines
    def _segments(self, el, tag: str, vp) -> list[tuple]:
        if tag == "path":
            return _path_segments(el.get("d") or "")
        if tag == "rect":
            x, y = _length(el.get("x"), vp[0]), _length(el.get("y"), vp[1])
            w, h = _length(el.get("width"), vp[0]), _length(el.get("height"), vp[1])
            if not (w > 0 and h > 0):
                return []
            rx, ry = _length(el.get("rx"), vp[0], None), _length(el.get("ry"), vp[1], None)
            rx, ry = (ry if rx is None or rx < 0 else rx), (rx if ry is None or ry < 0 else ry)
            rx, ry = min(rx or 0.0, w / 2.0), min(ry or 0.0, h / 2.0)
            if rx <= 0 or ry <= 0:
                return [("M", x, y), ("L", x + w, y), ("L", x + w, y + h), ("L", x, y + h), ("Z",)]
            return [("M", x + rx, y), ("L", x + w - rx, y), ("A", rx, ry, 0.0, False, True, x + w, y + ry), ("L", x + w, y + h - ry),
                    ("A", rx, ry, 0.0, False, True, x + w - rx, y + h), ("L", x + rx, y + h), ("A", rx, ry, 0.0, False, True, x, y + h - ry),
                    ("L", x, y + ry), ("A", rx, ry, 0.0, False, True, x + rx, y), ("Z",)]
        if tag == "circle" or tag == "ellipse":
            cx, cy = _length(el.get("cx"), vp[0]), _length(el.get("cy"), vp[1])
            if tag == "circle":
                rx = ry = _length(el.get("r"), math.hypot(*vp) / math.sqrt(2.0))
            else:
                rx, ry = _length(el.get("rx"), vp[0], None), _length(el.get("ry"), vp[1], None)
                rx, ry = (ry if rx is None else rx), (rx if ry is None else ry)
            if rx is None or ry is None or not (rx > 0 and ry > 0):
                return []
            return [("M", cx + rx, cy), ("A", rx, ry, 0.0, False, True, cx, cy + ry), ("A", rx, ry, 0.0, False, True, cx - rx, cy),
                    ("A", rx, ry, 0.0, False, True, cx, cy - ry), ("A", rx, ry, 0.0, False, True, cx + rx, cy), ("Z",)]
        if tag == "line":
            x1, y1, x2, y2 = (_length(el.get(k), vp[i % 2]) for i, k in enumerate(("x1", "y1", "x2", "y2")))
            return [("M", x1, y1), ("L", x2, y2)]
        v = _numbers(el.get("points"))
        pairs = list(zip(v[0::2], v[1::2]))
        if len(pairs) < 2:
            return []
        segs = [("M", *pairs[0])] + [("L", px, py) for px, py in pairs[1:]]
        return segs + [("Z",)] if tag == "polygon" else segs

    def _outline(self, el, tag: str, vp, ctm: Affine, flatness: float) -> list[tuple[list, bool]]:
        """The sub-paths of an element in mm, as ``(points, closed)``; curves are flattened to within ``flatness`` of user space."""
        segs = self._segments(el, tag, vp)
        if not segs:
            return []
        a, b, c, d, e, f = ctm
        out = []
        for pts, closed in _flatten(segs, flatness):
            if len(pts) < 2:
                continue
            self.verts += len(pts)
            if self.verts > MAX_VERTICES:
                raise su.ValidationError(TOO_COMPLEX % f"more than {MAX_VERTICES:,} outline points".replace(",", " "))
            moved = [(a * px + c * py + e, b * px + d * py + f) for px, py in pts]
            xs, ys = zip(*moved)
            if -_LIMIT_MM < min(xs) and max(xs) < _LIMIT_MM and -_LIMIT_MM < min(ys) and max(ys) < _LIMIT_MM and math.isfinite(sum(xs) + sum(ys)):
                out.append((moved, closed))
        return out

    # -- shapes
    def _tangled(self, pts: list, closed: bool, weight: float) -> bool:
        """Whether a long outline that crosses itself must be left out, the budget for such outlines (:data:`MAX_TANGLED_RING`,
        :data:`MAX_TANGLED_TOTAL`) being spent. ``weight`` is what its points cost against the budget (a fill 1, a stroke a quarter)."""
        n = len(pts)
        if n < TANGLE_CHECK_MIN:
            return False
        try:
            clean = Polygon(pts).is_valid if closed else LineString(pts).is_simple
        except (ValueError, shapely.errors.ShapelyError):
            clean = False
        if clean:
            return False
        cost = n * weight
        if cost > MAX_TANGLED_RING or self.tangled + cost > MAX_TANGLED_TOTAL:
            self.counts["tangled"] += 1
            return True
        self.tangled += cost
        return False

    def _emit(self, geometry: BaseGeometry, colour: str, alpha: float, clip: BaseGeometry | None, name: str | None) -> None:
        """Add a shape: cut by the clip, dropped when nothing is left of it, in the design colour ``colour`` laid on white with ``alpha``."""
        if geometry.is_empty:
            return
        if clip is not None:
            try:
                if clip.is_empty or not clip.intersects(geometry):
                    return
                if not clip.contains(geometry):
                    geometry = vg.polygonal(geometry.intersection(clip))
            except shapely.errors.ShapelyError:
                pass
        if not geometry.is_empty and geometry.area >= vg.MIN_AREA_MM2:
            self.shapes.append(vg.Shape(geometry, vg.on_white(colour, alpha), name[:200] if name else None))

    def _shape(self, el, tag: str, ctx: _Ctx) -> None:
        st = ctx.inh
        if st.get("visibility", "visible") in ("hidden", "collapse"):
            return
        largest, root_area = _scales(ctx.ctm)
        if not 0 < largest < math.inf or root_area <= 0:
            return
        paths = self._outline(el, tag, ctx.vp, ctx.ctm, vg.FLATNESS_MM / largest)
        if not paths:
            return
        name = el.get("id") or ctx.name
        if tag != "line":
            fill = self._paint(st.get("fill", "black"), st, _BLACK)
            alpha = ctx.opacity * _alpha(st.get("fill-opacity")) * (fill[1] if fill else 0.0)
            if fill is not None and alpha > 0:
                rings = [pts for pts, _closed in paths if len(pts) >= 3 and not self._tangled(pts, True, 1.0)]
                try:
                    area = vg.region(rings, "evenodd" if st.get("fill-rule") == "evenodd" else "nonzero") if rings else Polygon()
                except shapely.errors.ShapelyError:
                    area = Polygon()
                self._emit(area, fill[0], alpha, ctx.clip, name)
        if tag in ("path", "line", "polyline", "polygon") and any(st.get(k, "none").strip() != "none" for k in ("marker-start", "marker-mid", "marker-end")):
            self.counts["marker"] += 1
        if self.dry or st.get("stroke", "none").strip() == "none":
            return
        pen = self._paint(st["stroke"], st, None)
        alpha = ctx.opacity * _alpha(st.get("stroke-opacity")) * (pen[1] if pen else 0.0)
        width = _length(st.get("stroke-width"), math.hypot(*ctx.vp) / math.sqrt(2.0), 1.0) * root_area
        if pen is None or alpha <= 0 or not 0 < width < _LIMIT_MM:
            return
        try:
            limit = float(st.get("stroke-miterlimit", "4"))
        except ValueError:
            limit = 4.0
        if not 1.0 <= limit <= 1000.0:
            limit = 4.0
        cap, join = st.get("stroke-linecap", "butt").strip(), st.get("stroke-linejoin", "miter").strip()
        pieces = [vg.stroke(pts, width, closed=closed, cap=cap, join=join, miter_limit=limit) for pts, closed in paths
                  if not self._tangled(pts, closed, 0.25)]
        pieces = [p for p in pieces if not p.is_empty]
        if not pieces:
            return
        try:
            line = vg.polygonal(shapely.union_all(pieces))
        except shapely.errors.ShapelyError:
            return
        dashes = [v for v in _numbers(st.get("stroke-dasharray")) if v > 0]
        if dashes and st.get("stroke-dasharray", "none").strip() != "none":
            self.counts["dash"] += 1
        self._emit(line, pen[0], alpha, ctx.clip, name + " outline" if name else None)

    # -- the result
    def notes(self) -> list[str]:
        c = self.counts
        out = []

        def count(key: str, one: str, many: str) -> None:
            if c[key]:
                out.append((one if c[key] == 1 else many).format(n=c[key]))
        count("text", "{n} text object was not imported: convert the text to outlines in the program that made the file.",
              "{n} text objects were not imported: convert the text to outlines in the program that made the file.")
        count("image", "{n} picture was not imported: only vector drawings can be carried over, not embedded or linked images.",
              "{n} pictures were not imported: only vector drawings can be carried over, not embedded or linked images.")
        count("pattern", "{n} pattern fill was not imported: patterns cannot be carried over.",
              "{n} pattern fills were not imported: patterns cannot be carried over.")
        count("gradient", "{n} gradient fill was replaced by its average colour.", "{n} gradient fills were replaced by their average colour.")
        count("dash", "{n} dashed line was drawn solid.", "{n} dashed lines were drawn solid.")
        count("effect", "Masks and filters are not applied: {n} object was drawn without its mask or filter.",
              "Masks and filters are not applied: {n} objects were drawn without their mask or filter.")
        count("marker", "{n} line end marker (an arrowhead or similar) was not drawn.", "{n} line end markers (arrowheads or similar) were not drawn.")
        count("tangled", "{n} outline was left out: it crosses itself too many times to be imported.",
              "{n} outlines were left out: they cross themselves too many times to be imported.")
        count("missing", "{n} reference to an object that is not in the file was skipped.", "{n} references to objects that are not in the file were skipped.")
        return out


# -- entry point ------------------------------------------------------------------------------------------------------------------------
def _decode(data) -> bytes:
    """The bytes of the XML text: a byte order mark stripped, UTF-16 turned into UTF-8, a gzipped file (.svgz) unpacked; entity
    declarations (billion laughs, external entities) refused before anything is parsed."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise su.ValidationError("The file could not be read: it is not an SVG file.")
    data = bytes(data)
    if data[:2] == b"\x1f\x8b":
        unpacker = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            data = unpacker.decompress(data, MAX_BYTES + 1)
        except zlib.error:
            raise su.ValidationError("The file could not be read: it is not an SVG file.") from None
        if unpacker.unconsumed_tail:
            raise su.ValidationError(TOO_COMPLEX % "the unpacked file is huge")
    if len(data) > MAX_BYTES:
        raise su.ValidationError(TOO_COMPLEX % f"the file is larger than {MAX_BYTES // 2**20} MB")
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            text = data.decode("utf-16")
        except UnicodeError:
            raise su.ValidationError("The file could not be read: it is not an SVG file.") from None
        data = re.sub(r"^\s*<\?xml[^>]*\?>", "", text).encode("utf-8")
    if re.search(rb"<!ENTITY", data, re.I):
        raise su.ValidationError("The file declares entities in its header, which is refused for safety. Export the drawing again as plain SVG.")
    return data


class _Builder(ET.TreeBuilder):
    """Builds the element tree and refuses a file as soon as it has more than :data:`MAX_ELEMENTS` elements, before they are all in memory."""

    def __init__(self):
        super().__init__()
        self.count = 0

    def start(self, tag, attrs):
        self.count += 1
        if self.count > MAX_ELEMENTS:
            raise su.ValidationError(TOO_COMPLEX % f"more than {MAX_ELEMENTS:,} elements".replace(",", " "))
        return super().start(tag, attrs)


def _read_xml(data: bytes) -> ET.Element:
    parser = ET.XMLParser(target=_Builder())
    try:
        parser.feed(data)
        return parser.close()
    except (ET.ParseError, ValueError, LookupError, UnicodeError) as exc:
        raise su.ValidationError(f"The file could not be read as SVG: it is not valid XML ({str(exc)[:100]}).") from None


def _root_transform(root: ET.Element) -> tuple[Affine, tuple[float, float]]:
    """The transform from the root's user units to mm, and the size of its viewport in user units (what percentages refer to)."""
    box = _viewbox(root.get("viewBox"))
    width, height = _absolute_px(root.get("width")), _absolute_px(root.get("height"))
    if box is None:
        return (MM_PER_PX, 0.0, 0.0, MM_PER_PX, 0.0, 0.0), (width or 0.0, height or 0.0)
    if width is None and height is None:
        width, height = box[2], box[3]
    elif width is None:
        width = height * box[2] / box[3]
    elif height is None:
        height = width * box[3] / box[2]
    fit = _fit(box, width, height, root.get("preserveAspectRatio"))
    return _mul((MM_PER_PX, 0.0, 0.0, MM_PER_PX, 0.0, 0.0), fit), (box[2], box[3])


def parse(data: bytes) -> vg.Parsed:
    """Read the bytes of an SVG file into shapes in painting order (mm, y down, origin at the top-left of the viewport) and notes about
    what could not be carried over. Raises :class:`~titanium_platform.setup.ValidationError` for a file that cannot be read."""
    try:
        data = _decode(data)
        root = _read_xml(data)
        if _local(root.tag) != "svg":
            raise su.ValidationError("The file is not an SVG drawing: it has no <svg> element at its top.")
        reader = _Reader(root)
        ctm, viewport = _root_transform(root)
        reader._node(root, _Ctx(ctm, {}, 1.0, None, viewport, None, (), 0))
        notes = reader.notes()
        if not reader.shapes:
            notes.append("The file contains no vector drawing that can be imported.")
        return vg.Parsed(reader.shapes, notes, "svg")
    except su.ValidationError:
        raise
    except RecursionError:
        raise su.ValidationError(TOO_COMPLEX % "the parts are nested too deeply") from None
    except Exception as exc:                      # a broken file must never surface as anything but a message to the operator
        log.warning("SVG import failed unexpectedly", exc_info=True)
        raise su.ValidationError(f"The SVG file could not be read ({type(exc).__name__}).") from exc
