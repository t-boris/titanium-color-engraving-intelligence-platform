"""Colouring a photograph work by the language model (feature vector-detail-and-colour-control, REQ-050, DEC-084).

The operator picks a style (or describes a look of their own) and the model chooses a measured titanium colour for every source
colour of the work, by its own principles of that style. What it may choose from and what it must keep is decided here, not by the model:

* it receives numbers only: the source colours in Lab with their share of the area, which of them touch (the length of their shared
  border), the measured palette of the work's laser, lens and titanium, the colours the operator already chose by hand (they stay) and
  the number of LightBurn layers it may use; a copy of the photograph at ``PHOTO_PX`` goes with them only when the operator has allowed
  that for this work;
* its answer is checked before anything is applied (:func:`validate`): every colour must be a measured one the automatic modes may use,
  every free source colour needs one, the recipes must fit the layers, and the order of light and dark of the source is kept unless the
  operator allowed free lightness. A rejected answer is sent back once with the reason; a second bad answer is refused and the
  colouring stays as it was;
* the choice is stored in the colouring (and so in its variant) and is never asked for again when it is restored.

Nothing here talks to the network except :func:`choose`, through the client handed to it (``research.openai_client()``; tests hand a fake).
"""
from __future__ import annotations

import base64
import json

import cv2
import numpy as np

from . import conversion as cv, research

STYLES = ("realistic", "artistic", "impressionism", "cubism")
CUSTOM = "custom"
PHOTO_PX = 512                      # the longer side of the reduced photograph that may be sent, once the operator has allowed it
MAX_TEXT = 400                      # characters of the operator's own description
MAX_NOTE = 300                      # characters kept of the model's one-line note
MAX_PAIRS = 60                      # touching pairs of source colours in the brief, the longest borders first
ATTEMPTS = 2                        # the first answer and one more after a rejection
EPS = 1e-9

INSTRUCTIONS = """You choose titanium colours for a laser-engraved picture. The picture was split into flat source colours. For every
source colour in "free" choose exactly one colour of "palette"; these are the only colours that can be engraved. You see numbers, not
the picture: L*a*b* values (L* is lightness, 0 dark to 100 light), the share of the picture each source colour covers, and "touching": pairs
of source colours that share a border, with the share of all borders. Colours in "fixed" were chosen by the operator and stay; they count
towards "max_recipes", the number of different palette colours the whole picture may use. Never use an id that is not in "palette".
Follow "wish" as an artist would, by your own principles of that look, while obeying "lightness". Choose for the whole picture at once:
neighbouring regions should stay distinguishable and the result should look like one coherent piece.
Reply with one JSON object and nothing else: {"colours": {"<source index>": "<palette id>", ...}, "note": "<one sentence in Russian: the idea you followed>"}."""

WISH = {
    "realistic": "Realistic: reproduce the photograph as faithfully as this palette allows. Match each source colour by perceived "
                 "difference; where two palette colours are almost as close, prefer the one that keeps touching regions distinguishable.",
    "artistic": "Artistic: keep the subject recognisable and its light and dark structure, but interpret the colours as a painter would: "
                "a harmonious, limited scheme, warmer lights against cooler shadows, tasteful contrast between neighbours.",
    "impressionism": "Impressionist: light and colour over line. Lights warm and bright, shadows cool and coloured rather than grey or black, "
                     "vivid neighbouring hues that mix in the eye; avoid flat black and dull neutrals unless the palette has nothing else.",
    "cubism": "Cubist: read regions as flat facets. Touching facets get clearly different colours from a restrained earthy range "
              "(ochre, brown, grey, blue-green), with strong contrast across every shared border, even where that departs from natural colour.",
}
KEEP_ORDER = ("lightness: keep the order of light and dark of the source. If source colour A is lighter than source colour B, the palette "
              "colour you give A must not be darker than the one you give B. Hue and saturation are yours to choose.")
FREE_ORDER = "lightness: free. You may change the order of light and dark of the source where the style calls for it."

UNREADABLE = "the AI answer could not be read"
NOT_MEASURED = "the AI chose a colour that is not among the measured colours of this titanium"
INCOMPLETE = "the AI left a colour of the picture without a titanium colour"
ORDER_BROKEN = "the AI changed the order of light and dark; allow free lightness to let it"


class Rejected(cv.ConversionError):
    """The model's answer breaks a rule; the message is what the operator is told and what the model is told to correct."""


def request(op: dict) -> tuple[str, str | None, bool]:
    """The style, the operator's own text (only for a style of their own) and whether lightness is free, from an operation."""
    style = op.get("style")
    if style not in STYLES + (CUSTOM,):
        raise cv.ConversionError("choose a style for the AI colouring: realistic, artistic, impressionism, cubism or your own description")
    text = None
    if style == CUSTOM:
        text = op.get("text")
        text = text.strip() if isinstance(text, str) else ""
        if not text:
            raise cv.ConversionError("describe the look you want for the AI colouring")
        if len(text) > MAX_TEXT:
            raise cv.ConversionError(f"the description may have at most {MAX_TEXT} characters")
    free = op.get("free_lightness", False)
    if not isinstance(free, bool):
        raise cv.ConversionError("free lightness must be on or off")
    return style, text, free


def touching(document: dict) -> list[list]:
    """Pairs of source colours that border one another, ``[a, b, share]`` with the share of all such borders by length, longest first."""
    colour_of = {r["id"]: r["color"] for r in document["regions"]}
    length: dict[tuple[int, int], float] = {}
    for arc in document["arcs"]:
        a, b = colour_of.get(arc["left"]), colour_of.get(arc["right"])
        if a is None or b is None or a == b or len(arc["points"]) < 2:
            continue
        pts = np.asarray(arc["points"], float)
        key = (min(a, b), max(a, b))
        length[key] = length.get(key, 0.0) + float(np.hypot(*np.diff(pts, axis=0).T).sum())
    total = sum(length.values()) or 1.0
    return [[a, b, round(v / total, 4)] for (a, b), v in sorted(length.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_PAIRS]]


def brief(style: str, text: str | None, free_lightness: bool, *, free: list[dict], fixed: dict[str, object], touches: list[list],
          palette: list[dict], max_recipes: int) -> dict:
    """What the model is told, numbers only: ``free`` source colours (``index``, ``lab``, ``share``), the operator's ``fixed`` choices
    (source index to palette id), the touching pairs, the usable ``palette`` entries and the layers left."""
    wish = WISH[style] if style in WISH else f"The operator's own description of the look they want, to follow as far as the palette allows: {text}"
    return {"wish": wish, "lightness": FREE_ORDER if free_lightness else KEEP_ORDER, "max_recipes": max_recipes,
            "free": [{"index": s["index"], "lab": s["lab"], "share": s["share"]} for s in free], "fixed": fixed, "touching": touches,
            "palette": [{"id": e["id"], "lab": [round(v, 1) for v in e["lab"]]} for e in palette]}


def photo_data_url(image_bytes: bytes) -> str:
    """The photograph reduced to ``PHOTO_PX`` on its longer side, as a JPEG data URL."""
    img = cv.decode_image_bytes(image_bytes)
    scale = PHOTO_PX / max(img.shape[:2])
    if scale < 1:
        img = cv2.resize(img, (max(1, round(img.shape[1] * scale)), max(1, round(img.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    done, data = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not done:
        raise cv.ConversionError("the image could not be read")
    return "data:image/jpeg;base64," + base64.b64encode(data.tobytes()).decode("ascii")


def validate(answer, *, free: set[int], palette: dict, lightness: dict[int, float], keep_order: bool, max_recipes: int, recipes) -> dict[int, object]:
    """The model's answer as ``{source index: palette id}`` for the ``free`` source colours, or :class:`Rejected`.

    ``palette`` is what the model may use (id to entry), ``lightness`` the L* of every free source colour, ``recipes`` the number of
    different colours the picture would use with a choice (the operator's own included)."""
    colours = answer.get("colours") if isinstance(answer, dict) else None
    if not isinstance(colours, dict):
        raise Rejected(UNREADABLE)
    by_text = {str(i): i for i in palette}
    chosen: dict[int, object] = {}
    for key, value in colours.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            raise Rejected(UNREADABLE) from None
        if index not in free:                      # a colour the operator chose or left out: theirs stays
            continue
        if isinstance(value, bool) or str(value) not in by_text:
            raise Rejected(NOT_MEASURED)
        chosen[index] = by_text[str(value)]
    if set(chosen) != free:
        raise Rejected(INCOMPLETE)
    used = recipes(chosen)
    if used > max_recipes:
        raise Rejected(f"the AI chose {used} different colours but the file has {max_recipes} layers for them")
    if keep_order:
        order = sorted(free, key=lambda i: (lightness[i], i))
        for n, a in enumerate(order):
            for b in order[n + 1:]:
                if lightness[a] < lightness[b] - EPS and palette[chosen[a]]["lab"][0] > palette[chosen[b]]["lab"][0] + EPS:
                    raise Rejected(ORDER_BROKEN)
    return chosen


def _parse(text: str):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise Rejected(UNREADABLE)
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        raise Rejected(UNREADABLE) from None


def _ask(client, messages: list[dict]) -> str:
    """One call of the model. Whatever goes wrong with the service (no network, a refused key, a quota, a cut answer) is one message for
    the operator and the answer is not used; the service's own text is never shown, it may carry part of the key."""
    try:
        result = client.responses.create(model=research.DEFAULT_MODEL, reasoning={"effort": "medium"}, store=False, max_output_tokens=4000,
                                         instructions=INSTRUCTIONS, input=messages)
    except Exception:
        raise cv.ConversionError("the AI service did not answer: check the connection and the key, then try again") from None
    if getattr(result, "status", None) == "incomplete":
        raise cv.ConversionError("the AI answer was cut off: try again")
    return getattr(result, "output_text", "") or ""


def choose(client, what: dict, photo: str | None, check) -> tuple[dict[int, object], str]:
    """Ask the model for a colouring and return its checked choice and note. ``check`` turns a parsed answer into the choice or raises
    :class:`Rejected`; a rejected answer is sent back with its reason once, and the second one is refused."""
    text = json.dumps(what, ensure_ascii=False, separators=(",", ":"))
    content = [{"type": "input_text", "text": text}, {"type": "input_image", "image_url": photo}] if photo else text
    messages = [{"role": "user", "content": content}]
    for attempt in range(ATTEMPTS):
        reply = _ask(client, messages)
        try:
            answer = _parse(reply)
            chosen = check(answer)
        except Rejected as exc:
            if attempt == ATTEMPTS - 1:
                raise                              # the second bad answer is refused as it is
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": f"Rejected: {exc}. Reply again with the corrected JSON object only."}]
            continue
        note = answer.get("note")
        return chosen, (note.strip()[:MAX_NOTE] if isinstance(note, str) else "")
    raise AssertionError("unreachable")
