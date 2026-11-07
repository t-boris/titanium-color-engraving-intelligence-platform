"""QR codes of a business-card work (feature-2, REQ-005, DEC-031, DEC-038, DEC-040).

A QR code is an element of a card side: ``{"kind", "fields", "ecc"}``. Six kinds are offered (``KINDS``), each with its own entry form
(``FIELDS``): a link, a contact card (vCard 3.0), plain text, a Wi-Fi network, an email and a telephone number. :func:`checked`
normalises what the operator typed, :func:`payload` turns it into the text the code carries (and says in plain English what is missing
or wrong), :func:`matrix` is the symbol as modules and :func:`geometry` is the symbol as shapely geometry in millimetres, the dark modules
being what is engraved.

The symbol is made by OpenCV's ``QRCodeEncoder``; no new library. Two facts about that encoder are handled here:

* its image carries a two-module white border, which is cropped (the quiet zone is the card's business, see :func:`clearance`);
* its version 21 (101 x 101 modules) is not a valid symbol: three independent readers fail on it. The symbol is made one version
  larger (105 x 105) instead, so a code is never engraved that no reader can open.

The physical check (DEC-038, DEC-040) is :func:`check`: a module smaller than 0.40 mm or a quiet zone smaller than 4 modules is a
warning, never an error; the two are independent and a value exactly at the threshold is fine. :func:`clearance` measures the quiet zone as
the distance from the symbol to the nearest other engraved element of the same side or to the card edge. Passing the check does not
guarantee that the engraved code scans (``NOTE``).

:func:`decode` reads a symbol back (as geometry, modules or an image) so a test can prove that the geometry carries its content.
"""
from __future__ import annotations

import functools
import math
import re
from urllib.parse import quote

import cv2
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry.base import BaseGeometry

from . import setup as su

KINDS = ("link", "vcard", "text", "wifi", "email", "phone")
KIND_LABELS = {"link": "Link", "vcard": "Contact card (vCard)", "text": "Text", "wifi": "Wi-Fi network", "email": "Email",
               "phone": "Phone number"}
ECC_LEVELS = ("L", "M", "Q", "H")
DEFAULT_ECC = "M"
# DEC-040: both limits live here and are checked independently; a warning never blocks work or engraving.
THRESHOLDS = {"module_mm": 0.40, "quiet_modules": 4.0}
NOTE = "Passing these checks does not guarantee that the engraved code will scan."

LINK_MAX = 2000
TEXT_MAX = 1000
SUBJECT_MAX = 200
BODY_MAX = 1000
FIELD_MAX = 2000                 # no entry of any field is longer than this, whatever the kind
SSID_MAX_BYTES = 32              # IEEE 802.11
WIFI_PASSWORD_MAX = 64           # a WPA passphrase has up to 63 characters, a raw key 64 hex digits
PHONE_DIGITS = (3, 15)           # E.164 allows up to 15 digits
UNLIMITED_MM = 1e6               # the clearance of a symbol with nothing around it
_EPS = 1e-9                      # a value this close to a threshold is at it (float noise), not below it
WIFI_SECURITY = ("WPA", "WEP", "nopass")


def _field(name: str, label: str, type: str = "text", required: bool = False, **extra) -> dict:
    return {"name": name, "label": label, "type": type, "required": required, **extra}


# The entry form of every kind: what the operator is asked for. ``required`` is what the code cannot be made without (a contact card
# needs a name *or* an organisation, so none of its fields is required alone).
FIELDS = {
    "link": [_field("url", "Web address", required=True)],
    "vcard": [_field("first_name", "First name"), _field("last_name", "Last name"), _field("organisation", "Organisation"),
              _field("title", "Job title"), _field("phone", "Phone"), _field("mobile", "Mobile"), _field("email", "Email"),
              _field("url", "Website"), _field("address", "Address", "multiline")],
    "text": [_field("text", "Text", "multiline", True)],
    "wifi": [_field("ssid", "Network name (SSID)", required=True), _field("password", "Password", "password"),
             _field("security", "Security", "select", options=list(WIFI_SECURITY), default="WPA"),
             _field("hidden", "Hidden network", "bool", default=False)],
    "email": [_field("address", "Email address", required=True), _field("subject", "Subject"),
              _field("body", "Message", "multiline")],
    "phone": [_field("number", "Phone number", required=True)],
}
_SPECS = {kind: {f["name"]: f for f in fields} for kind, fields in FIELDS.items()}


# -- entry: normalise what the operator typed ----------------------------------------------------------
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TRUE, _FALSE = {"true", "1", "yes", "on"}, {"false", "0", "no", "off", ""}


def _kind(value) -> str:
    kind = str(value).strip().lower() if isinstance(value, str) else value
    if kind not in KINDS:
        raise su.ValidationError(f"QR code type {value!r} is not offered; choose link, vcard, text, wifi, email or phone")
    return kind


def _ecc(value) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_ECC
    level = value.strip().upper() if isinstance(value, str) else value
    if level not in ECC_LEVELS:
        raise su.ValidationError(f"Error correction {value!r} is not offered; choose L, M, Q or H")
    return level


def _entry(spec: dict, value):
    """One field's value, normalised: a string stripped (a single-line field has no line breaks, a multi-line one has \\n), a bool, or
    one of a select's options."""
    label, kind = spec["label"], spec["type"]
    if kind == "bool":
        if isinstance(value, str):
            value = value.strip().lower()
            if value in _TRUE | _FALSE:
                return value in _TRUE
        elif value is None or isinstance(value, (bool, int)) and value in (0, 1):
            return bool(value)
        raise su.ValidationError(f"{label}: choose yes or no")
    if kind == "select":
        text = "" if value is None else str(value).strip()
        if not text:
            return spec["default"]
        for option in spec["options"]:
            if option.lower() == text.lower():
                return option
        raise su.ValidationError(f"{label}: {text!r} is not offered; choose {', '.join(spec['options'])}")
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise su.ValidationError(f"{label}: enter text")
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if _CONTROL.search(text):
        raise su.ValidationError(f"{label}: remove the control characters")
    if kind != "multiline":
        text = re.sub(r"\s*\n\s*", " ", text)
    text = text.strip()
    if len(text) > FIELD_MAX:
        raise su.ValidationError(f"{label}: at most {FIELD_MAX} characters are allowed")
    return text


def checked(qr) -> dict:
    """``{"kind", "fields", "ecc"}`` normalised: the kind and the error-correction level validated (L, M, Q or H; M when not given),
    every field of the kind present (strings stripped, a missing one empty or its default), a field the kind does not have refused.
    Whether the content is *complete* is :func:`payload`'s business, so a code just added may be stored empty."""
    if not isinstance(qr, dict):
        raise su.ValidationError("A QR code needs a type, its fields and an error-correction level")
    kind = _kind(qr.get("kind"))
    raw = qr.get("fields")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise su.ValidationError(f"{KIND_LABELS[kind]}: the fields must be a set of named entries")
    specs = _SPECS[kind]
    unknown = sorted(str(k) for k in raw if k not in specs)
    if unknown:
        raise su.ValidationError(f"{KIND_LABELS[kind]}: no field {', '.join(repr(k) for k in unknown)}; the fields are {', '.join(specs)}")
    return {"kind": kind, "fields": {name: _entry(spec, raw.get(name)) for name, spec in specs.items()}, "ecc": _ecc(qr.get("ecc"))}


# -- payload: the text a code carries ------------------------------------------------------------------
_BARE_SCHEMES = ("mailto", "tel", "sms", "smsto", "geo", "sip", "facetime", "skype", "callto", "whatsapp")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://")
_HOST = re.compile(r"(?:(?:[\w\-]+\.)+[^\W\d_][\w\-]+|localhost|[0-9]{1,3}(?:\.[0-9]{1,3}){3})(?::[0-9]{1,5})?")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s.]{2,}")
_PHONE = re.compile(r"\+?[0-9\s()\-]+")


def _need(value: str, label: str, what: str) -> str:
    if not value:
        raise su.ValidationError(f"{label}: enter {what}")
    return value


def _longest(value: str, label: str, limit: int) -> None:
    if len(value) > limit:
        raise su.ValidationError(f"{label}: at most {limit} characters are allowed, this has {len(value)}")


def _link(value: str, label: str = "Web address") -> str:
    """The address as given; ``https://`` is added when it has no scheme but looks like a host (``example.com/menu``)."""
    _need(value, label, "the address the code should open")
    _longest(value, label, LINK_MAX)
    if re.search(r"\s", value):
        raise su.ValidationError(f"{label}: an address has no spaces")
    if _SCHEME.match(value) or value.lower().startswith(tuple(f"{s}:" for s in _BARE_SCHEMES)):
        return value
    authority = re.split(r"[/?#]", value, maxsplit=1)[0].rsplit("@", 1)[-1]
    if _HOST.fullmatch(authority):
        return "https://" + value
    raise su.ValidationError(f"{label}: {value!r} is not a web address; enter one such as example.com/menu")


def _email(value: str, label: str) -> str:
    if len(value) > 254 or not _EMAIL.fullmatch(value):
        raise su.ValidationError(f"{label}: {value!r} is not an email address")
    return value


def _phone(value: str, label: str) -> str:
    """A number as digits with the usual separators, without spaces: ``+1 (415) 555-0100`` becomes ``+1(415)555-0100``."""
    if not _PHONE.fullmatch(value):
        raise su.ValidationError(f"{label}: use only digits, spaces and + - ( ); a plus sign may only start the number")
    digits = len(re.findall(r"[0-9]", value))
    if not PHONE_DIGITS[0] <= digits <= PHONE_DIGITS[1]:
        raise su.ValidationError(f"{label}: enter {PHONE_DIGITS[0]} to {PHONE_DIGITS[1]} digits, this has {digits}")
    return re.sub(r"\s+", "", value)


def _vcard_text(value: str) -> str:
    """A vCard text value: backslash, comma, semicolon and line break escaped (RFC 6350, 3.4)."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _vcard(f: dict) -> str:
    first, last, organisation = f["first_name"], f["last_name"], f["organisation"]
    if not (first or last or organisation):
        raise su.ValidationError("Contact: enter a first name, a last name or an organisation")
    esc = _vcard_text
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"N:{esc(last)};{esc(first)};;;", f"FN:{esc(' '.join(p for p in (first, last) if p) or organisation)}"]
    if organisation:
        lines.append(f"ORG:{esc(organisation)}")
    if f["title"]:
        lines.append(f"TITLE:{esc(f['title'])}")
    if f["phone"]:
        lines.append(f"TEL;TYPE=WORK,VOICE:{esc(_phone(f['phone'], 'Phone'))}")
    if f["mobile"]:
        lines.append(f"TEL;TYPE=CELL:{esc(_phone(f['mobile'], 'Mobile'))}")
    if f["email"]:
        lines.append(f"EMAIL:{esc(_email(f['email'], 'Email'))}")
    if f["url"]:
        lines.append(f"URL:{_link(f['url'], 'Website')}")      # a URI value is not text: it is not escaped (RFC 6350, 6.7.8)
    if f["address"]:
        lines.append(f"ADR;TYPE=WORK:;;{esc(f['address'])};;;;")
    lines.append("END:VCARD")
    return "\n".join(lines)


def _wifi(f: dict) -> str:
    ssid, security = _need(f["ssid"], "Network name (SSID)", "the name of the Wi-Fi network"), f["security"]
    if len(ssid.encode("utf-8")) > SSID_MAX_BYTES:
        raise su.ValidationError(f"Network name (SSID): at most {SSID_MAX_BYTES} bytes are allowed (a letter outside A-Z takes more than one)")
    esc = lambda s: re.sub(r'([\\;,:"])', r"\\\1", s)
    parts = [f"T:{security}", f"S:{esc(ssid)}"]
    if security != "nopass":
        password = _need(f["password"], "Password", "the network password, or choose nopass for an open network")
        _longest(password, "Password", WIFI_PASSWORD_MAX)
        parts.append(f"P:{esc(password)}")
    if f["hidden"]:
        parts.append("H:true")
    return "WIFI:" + ";".join(parts) + ";;"


def _mailto(f: dict) -> str:
    address = _email(_need(f["address"], "Email address", "the address the message goes to"), "Email address")
    _longest(f["subject"], "Subject", SUBJECT_MAX)
    _longest(f["body"], "Message", BODY_MAX)
    query = []
    if f["subject"]:
        query.append("subject=" + quote(f["subject"], safe=""))
    if f["body"]:
        query.append("body=" + quote(f["body"].replace("\n", "\r\n"), safe=""))      # a line break in a mailto body is CRLF (RFC 6068)
    return "mailto:" + quote(address, safe="@+-._!$'*~") + ("?" + "&".join(query) if query else "")


def _text(f: dict) -> str:
    text = _need(f["text"], "Text", "the text the code should show")
    _longest(text, "Text", TEXT_MAX)
    return text


_BUILDERS = {
    "link": lambda f: _link(f["url"]),
    "vcard": _vcard,
    "text": _text,
    "wifi": _wifi,
    "email": _mailto,
    "phone": lambda f: "tel:" + _phone(_need(f["number"], "Phone number", "the number to call"), "Phone number"),
}


def payload(qr) -> str:
    """The text the code carries; refused, in plain English naming the field, when the content is missing or invalid."""
    qr = checked(qr)
    return _BUILDERS[qr["kind"]](qr["fields"])


# -- symbol: modules and geometry ----------------------------------------------------------------------
_CV_LEVEL = {"L": cv2.QRCODE_ENCODER_CORRECT_LEVEL_L, "M": cv2.QRCODE_ENCODER_CORRECT_LEVEL_M,
             "Q": cv2.QRCODE_ENCODER_CORRECT_LEVEL_Q, "H": cv2.QRCODE_ENCODER_CORRECT_LEVEL_H}
_BROKEN_VERSIONS = {21}          # OpenCV 5.0's encoder makes an unreadable symbol of these versions (101 x 101 modules)


def _encode(text: str, ecc: str, version: int) -> np.ndarray:
    params = cv2.QRCodeEncoder.Params()
    params.correction_level = _CV_LEVEL[ecc]
    params.version = version
    try:
        return cv2.QRCodeEncoder.create(params).encode(text)
    except cv2.error:
        raise su.ValidationError(f"The content does not fit in a QR code with error correction {ecc}; "
                                 "shorten it or choose a lower level") from None


@functools.lru_cache(maxsize=128)
def _symbol(text: str, ecc: str) -> np.ndarray:
    """The dark modules (True) of the symbol of ``text``, without the encoder's white border; read-only."""
    image = _encode(text, ecc, 0)
    if (image.shape[0] - 4 - 17) // 4 in _BROKEN_VERSIONS:
        image = _encode(text, ecc, (image.shape[0] - 4 - 17) // 4 + 1)
    dark = image == 0
    rows, cols = np.flatnonzero(dark.any(axis=1)), np.flatnonzero(dark.any(axis=0))
    symbol = dark[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].copy()
    side = symbol.shape[0]
    if symbol.shape[0] != symbol.shape[1] or side < 21 or (side - 17) % 4:
        raise RuntimeError(f"the QR encoder returned a {symbol.shape[1]} x {symbol.shape[0]} symbol")
    symbol.flags.writeable = False
    return symbol


def matrix(qr) -> np.ndarray:
    """The symbol as a square boolean array, True = dark module, without any quiet border (the first and last row and column each
    hold a dark module). Raises when the content does not fit in a QR code at the code's error-correction level."""
    qr = checked(qr)
    return _symbol(_BUILDERS[qr["kind"]](qr["fields"]), qr["ecc"]).copy()


def modules(qr) -> int:
    """Modules along one side of the symbol (21 for version 1, 4 more per version)."""
    return int(matrix(qr).shape[0])


@functools.lru_cache(maxsize=64)
def _geometry(text: str, ecc: str, size: float):
    dark = _symbol(text, ecc)
    n = dark.shape[0]
    edges = np.linspace(-size / 2, size / 2, n + 1)           # one set of edges for every module: neighbours share them exactly
    x0, y0, x1, y1 = [], [], [], []
    for r in range(n):
        d = np.diff(np.concatenate(([0], dark[r].astype(np.int8), [0])))
        starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        x0.extend(edges[starts]); x1.extend(edges[ends]); y0.extend([edges[r]] * len(starts)); y1.extend([edges[r + 1]] * len(starts))
    union = shapely.union_all(shapely.box(x0, y0, x1, y1))
    return shapely.simplify(union, 0, preserve_topology=True)         # exactly collinear vertices only: edges stay module-exact


def geometry(qr, size_mm: float):
    """The symbol as shapely geometry in mm, centred on (0, 0), y down, covering the square ``size_mm`` x ``size_mm`` (a module is
    ``size_mm / modules``). The geometry is the union of the dark modules, which is what is engraved."""
    size = su._finite(size_mm, "QR code size", True)
    qr = checked(qr)
    return _geometry(_BUILDERS[qr["kind"]](qr["fields"]), qr["ecc"], size)


# -- physical suitability (DEC-038, DEC-040) -----------------------------------------------------------
def _shown(value: float, limit: float, digits: tuple[int, ...]) -> str:
    """``value`` with as few decimals as keep it visibly below ``limit`` (0.399 must not read 0.40)."""
    for d in digits:
        text = f"{value:.{d}f}"
        if float(text) < limit:
            return text
    return repr(value)


def check(size_mm: float, modules: int, clearance_mm: float) -> dict:
    """Module size and quiet zone of a QR code placed at ``size_mm`` with ``clearance_mm`` of empty space around it. A value below its
    threshold is a warning; the two are independent, a value at the threshold does not warn, and nothing here blocks work."""
    size = su._finite(size_mm, "QR code size", True)
    count = su._finite(modules, "QR code modules", True)
    clear = su._finite(clearance_mm, "QR code clearance")
    if clear < 0:
        raise su.ValidationError("QR code clearance must not be negative")
    module_mm = size / count
    quiet = clear / module_mm
    warnings = []
    limit = THRESHOLDS["module_mm"]
    if module_mm < limit - _EPS:
        warnings.append({"code": "module_size", "value": module_mm, "threshold": limit,
                         "message": f"The module is {_shown(module_mm, limit, (2, 3, 4, 5))} mm; below {limit:.2f} mm a phone may not "
                                    "read the engraved code."})
    limit = THRESHOLDS["quiet_modules"]
    if quiet < limit - _EPS:
        warnings.append({"code": "quiet_zone", "value": quiet, "threshold": limit,
                         "message": f"The quiet zone is {_shown(quiet, limit, (1, 2, 3, 4))} modules; keep at least {limit:g} modules "
                                    "empty around the code."})
    return {"module_mm": module_mm, "quiet_modules": quiet, "warnings": warnings, "thresholds": dict(THRESHOLDS), "note": NOTE}


def clearance(symbol, others, card) -> float:
    """The empty space around a placed QR code in mm: the least distance from the symbol to any of ``others`` (the other engraved
    geometries of the same side) and to the card edge, all in card coordinates. 0 when the symbol touches or overlaps another element or is
    not inside the card. The symbol counts as the whole square of the code (a lettering inside its white modules is on the code), so a
    rotated symbol is measured by its rotated square. With nothing around it the answer is the card's size (``UNLIMITED_MM`` without a card)."""
    if symbol is None or symbol.is_empty:
        return 0.0
    footprint = symbol.minimum_rotated_rectangle
    if card is not None and not card.is_empty and not card.covers(footprint):
        return 0.0
    distances = [footprint.distance(g) for g in others or () if g is not None and not g.is_empty]
    cap = UNLIMITED_MM
    if card is not None and not card.is_empty:
        distances.append(card.boundary.distance(footprint))
        x0, y0, x1, y1 = card.bounds
        cap = max(x1 - x0, y1 - y0)
    return float(min(distances + [cap]))


def placed_check(qr, size_mm: float, symbol, others, card) -> dict:
    """:func:`check` of a code placed at ``size_mm``, its clearance measured from ``symbol`` (its final geometry on the card), plus the
    ``content`` the code carries, its ``modules`` and the ``clearance_mm`` used. Raises like :func:`payload` for incomplete content."""
    content, count = payload(qr), modules(qr)
    gap = clearance(symbol, others, card)
    return {**check(size_mm, count, gap), "content": content, "modules": count, "clearance_mm": gap}


# -- reading a symbol back -----------------------------------------------------------------------------
def _grid(geom: BaseGeometry) -> np.ndarray | None:
    """The dark modules of a QR geometry (any rotation, any size) sampled at the module centres, else None. The module is the smallest
    step between the edges of the geometry once it is turned square to the axes."""
    if geom.is_empty:
        return None
    ring = geom.minimum_rotated_rectangle
    if ring.geom_type == "Polygon":
        (ax, ay), (bx, by) = list(ring.exterior.coords)[:2]
        angle = math.degrees(math.atan2(by - ay, bx - ax))
        if abs(angle - 90 * round(angle / 90)) > 1e-6:
            geom = affinity.rotate(geom, -angle, origin=ring.centroid)
    x0, y0, x1, y1 = geom.bounds
    side = max(x1 - x0, y1 - y0)
    if side <= 0:
        return None
    steps = []
    for axis in (0, 1):
        edge = np.unique(shapely.get_coordinates(geom)[:, axis])
        step = np.diff(edge)
        steps.extend(step[step > 1e-4 * side])
    if not steps:
        return None
    n = round(side / min(steps))
    centres = (np.arange(n) + 0.5) * side / n
    xs, ys = np.meshgrid(x0 + centres, y0 + centres)
    return shapely.contains_xy(geom, xs, ys)


def _readers():
    yield lambda img: cv2.QRCodeDetector().detectAndDecode(img)[0]
    if hasattr(cv2, "QRCodeDetectorAruco"):
        yield lambda img: cv2.QRCodeDetectorAruco().detectAndDecode(img)[0]
    if hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
        def wechat(img):
            texts = cv2.wechat_qrcode_WeChatQRCode().detectAndDecode(img)[0]
            return texts[0] if texts else ""
        yield wechat


def decode(source) -> str | None:
    """The text a QR code carries, else None. ``source`` is shapely geometry (the dark modules, like :func:`geometry`), a boolean array
    (True = dark module) or a grey or colour image. Modules are drawn square at 8 pixels (then 12) inside a white border of 4 modules and
    read by OpenCV's classic detector, then its ArUco-based one, then the WeChat one."""
    if isinstance(source, BaseGeometry):
        source = _grid(source)
    if source is None:
        return None
    source = np.asarray(source)
    for image in _views(source):
        for read in _readers():
            try:
                text = read(image)
            except cv2.error:              # a degenerate view is not a reading
                continue
            if text:
                return text
    return None


def _views(source: np.ndarray):
    """The images a symbol is read from: modules drawn square at 8 then 12 pixels in a white border of 4 modules, or the image itself."""
    if source.dtype != bool:
        yield source if source.dtype == np.uint8 else cv2.normalize(source, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    elif source.ndim == 2:
        for scale in (8, 12):
            image = np.full(tuple((s + 8) * scale for s in source.shape), 255, np.uint8)
            image[4 * scale:-4 * scale, 4 * scale:-4 * scale] = np.where(source.repeat(scale, 0).repeat(scale, 1), 0, 255)
            yield image
