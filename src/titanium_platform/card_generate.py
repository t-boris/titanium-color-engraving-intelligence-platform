"""Icons and drawings for a card, generated from a description (feature-2, REQ-002, DEC-039).

The picture comes from the OpenAI image service through the application's own client (:func:`research.started_client`), so it uses the
workshop's key and obeys the workshop's «AI» switch (:mod:`outbound`): with the switch off, without a key or without a connection the
operator is told which of them is missing, and the rest of the card workspace keeps working. The description is sent to the service;
nothing else leaves the computer. The picture returned is stored as an ordinary image element and traced into engravable shapes on the
device (:mod:`card_image`), exactly as an imported graphic is.

The model is a setting of the workshop (``card_generation``, key ``model``); :data:`DEFAULT_MODEL` is used until one is set.
"""
from __future__ import annotations

from . import research, setup as su
from .db import Store

SETTING = "card_generation"
DEFAULT_MODEL = "gpt-image-2"
KINDS = ("icon", "drawing")
MIN_DESCRIPTION, MAX_DESCRIPTION = 3, 300
SIZE = "1024x1024"
PROMPTS = {
    "icon": ("A simple, bold, single-colour icon of {description}. Solid black shapes with thick clean outlines on a plain white background, "
             "centred, no text, no shading, no gradients, no colours, high contrast, suited to laser engraving on a small metal business card."),
    "drawing": ("A pencil-style line drawing of {description}. Black lines and fine hatching on a plain white background, centred, no text, "
                "no colour, suited to laser engraving on a small metal business card."),
}


def model(store: Store) -> str:
    """The image model in use: the workshop's setting, or the default."""
    kept = store.get_setting(SETTING) or {}
    value = kept.get("model") if isinstance(kept, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else DEFAULT_MODEL


def available(store: Store) -> dict:
    """``{"available", "reason"}``: whether a picture can be asked for now and, when it cannot, what the operator must do first."""
    if not research.switched_on:
        return {"available": False, "reason": "The AI switch is off: turn it on in the network settings to generate pictures."}
    if not research.ai_library():
        return {"available": False, "reason": "The OpenAI library is missing from this installation: install the application's dependencies."}
    if not research.ai_available():
        return {"available": False, "reason": "No OpenAI key is set: add it in the workshop's AI settings to generate pictures."}
    return {"available": True, "reason": None}


def _description(value) -> str:
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if not MIN_DESCRIPTION <= len(text) <= MAX_DESCRIPTION:
        raise su.ValidationError(f"describe the picture in {MIN_DESCRIPTION} to {MAX_DESCRIPTION} characters")
    return text


def generate(store: Store, description, kind: str) -> tuple[bytes, str]:
    """Ask the image service for ``kind`` ("icon" or "drawing") of ``description``; returns the PNG bytes and the description used."""
    if kind not in KINDS:
        raise su.ValidationError("generate an icon or a drawing")
    text = _description(description)
    state = available(store)
    if not state["available"]:
        raise su.ValidationError(state["reason"])
    chosen = model(store)
    options = {"response_format": "b64_json"} if chosen.startswith("dall-e") else {"quality": "medium", "output_format": "png", "background": "opaque"}
    try:
        data = research.generated_image(chosen, PROMPTS[kind].format(description=text), size=SIZE, **options)
    except research.ResearchError as error:
        raise su.ValidationError(str(error)) from None
    return data, text
