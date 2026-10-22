"""Asking the language model how each part of a photo engraving work should look (REQ-062, DEC-105).

The operator says in their own words what to change ("всё как есть, черно-белое, платье фиолетовым, кожу равномерно светлой"); the model
answers with one rule per part of the picture (:mod:`picture_rules`). What it may answer and what is done with it is decided here, not by
the model:

* it receives numbers only: the wish, the parts the people model found (:mod:`people`) with their share of the picture and mean colour,
  16 greys of the work's scale at its Min and Max with the colour each gives on the titanium, the lightness the near-grey greys reach, and
  the rules the work has now; a reduced copy of the picture goes with them only when the operator has allowed it for this work;
* its rules are checked (:func:`picture_rules.check`) before anything is applied, rules for parts the picture does not have are dropped,
  and an answer that breaks a rule is sent back once with the reason, a second bad one is refused and the work stays as it was
  (:func:`ai_colouring.choose`);
* the greys are always chosen by :func:`picture_rules.greys` on the scale, never by the model.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from . import ai_colouring as ai, picture_rules
from .conversion import ConversionError

TABLE_STEP = 17                     # the 16 greys of the brief: 255, 238, ... 0, the steps of the grey-scale plate

INSTRUCTIONS = """You decide how each part of a photograph looks when it is laser-engraved on titanium in grayscale mode. In this mode
every grey of the picture becomes a laser power, and on titanium each power gives a colour: "scale" lists greys (0 black .. 255 white) with
the L*a*b* colour each gives (L* 0 dark .. 100 light, a* green to red, b* blue to yellow). The picture was split into parts by a model:
"parts" gives each part found, its share of the picture and its mean colour in the photograph. "wish" is what the operator wants, in their
own words (often Russian). For each part choose one rule:
- "as_is": the picture's own greys there, as the engraver converts the picture (by luminance);
- "photo": each pixel the grey whose titanium colour is nearest the pixel's own colour;
- "neutral": black and white, only the greys whose titanium colour is nearly grey ("neutral" gives the lightness they reach); an optional
  "range": [L from, L to] inside it makes the part lighter or darker;
- "colour": one target colour "lab": [L, a, b], the part's own light and dark kept around it;
- "even": one even tone, the grey nearest the target colour "lab". It erases every detail inside the part: the eyes, brows and lips are
  part of "face_skin", so for skin that should look even and light use "colour" with a light target, which keeps them; "even" suits a
  background or plain clothes.
Choose target colours among the colours in "scale": others cannot be engraved, the nearest one is taken instead. A part the wish does not
mention keeps its rule in "current", or "as_is" when it has none. Use only the parts in "parts".
Reply with one JSON object and nothing else: {"rules": [{"part": "<part>", "kind": "<rule>", "lab": [L, a, b], "range": [L from, L to]}, ...],
"note": "<one sentence in Russian: what you did>"}; give "lab" only for colour and even, "range" only for neutral when it is needed."""


def request(wish) -> str:
    """The operator's wish as it is sent: some words, at most ``ai_colouring.MAX_TEXT`` characters."""
    text = wish.strip() if isinstance(wish, str) else ""
    if not text:
        raise ConversionError("describe what the AI should change in the picture")
    if len(text) > ai.MAX_TEXT:
        raise ConversionError(f"the description may have at most {ai.MAX_TEXT} characters")
    return text


def brief(wish: str, parts: Iterable[Mapping], table: Mapping, rules: Iterable[Mapping]) -> dict:
    """What the model is told, numbers only: the wish, the ``parts`` found (``part``, ``share``, ``lab``), 16 greys of the scale's
    ``table`` (``grayscale.scale_of_greys``) with their colours, the lightness the near-grey greys reach and the current ``rules``."""
    rows = table["levels"]
    scale = [{"grey": rows[level]["level"], "lab": [round(v, 1) for v in rows[level]["lab"]]}
             for level in range(len(rows) - 1, -1, -TABLE_STEP) if rows[level]["lab"] is not None]
    reach = [rows[level]["lab"][0] for level in picture_rules.neutral_levels(table)]
    return {"wish": wish, "parts": [{"part": p["part"], "share": p["share"], "lab": p["lab"]} for p in parts], "scale": scale,
            "neutral": [round(min(reach), 1), round(max(reach), 1)] if reach else None, "current": list(rules)}


def validate(answer, present: set[str]) -> list[dict]:
    """The model's rules, checked, without those for parts the picture does not have and without ``as_is`` (a part without a rule is as it
    is), or :class:`ai_colouring.Rejected` with the reason."""
    rules = answer.get("rules") if isinstance(answer, Mapping) else None
    if not isinstance(rules, list):
        raise ai.Rejected(ai.UNREADABLE)
    try:
        checked = picture_rules.check(rules)
    except picture_rules.RuleError as exc:
        raise ai.Rejected(str(exc)) from None
    return [r for r in checked if r["part"] in present and r["kind"] != "as_is"]


def ask(client, what: dict, photo: str | None, present: set[str]) -> tuple[list[dict], str]:
    """Ask the model for the rules of the parts and return them checked, with its one-sentence note."""
    return ai.choose(client, what, photo, lambda answer: validate(answer, present), INSTRUCTIONS)
