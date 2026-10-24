"""What the application may reach outside this computer (feature electron, REQ-080): three switches the operator keeps in the workshop.

* ``ai``: the AI researcher and the designer's explanation (``research.py``); off, the key is not even read and the features say so;
* ``google_fonts``: fetching Google's family list and font files when the operator asks (``fonts.py``); off, the request is refused;
* ``update_checks``: whether the desktop shell may ask GitHub Releases for a newer version (DEC-048); the shell reads it here.

Nothing else leaves this computer: there is no telemetry. The switches are a setting of the workshop; they are applied to the modules
when the application starts and whenever they are changed, so that every workflow sees them without passing the store around.
"""
from __future__ import annotations

from . import fonts, research
from . import setup as su
from .db import Store

SETTING = "network"
DEFAULTS = {"ai": True, "google_fonts": True, "update_checks": False}


def get(store: Store) -> dict:
    kept = store.get_setting(SETTING) or {}
    return {key: bool(kept.get(key, default)) for key, default in DEFAULTS.items()}


def save(store: Store, body) -> dict:
    """Keep the switches given in ``body`` (the others stay) and apply them."""
    if not isinstance(body, dict) or any(key in body and not isinstance(body[key], bool) for key in DEFAULTS):
        raise su.ValidationError("the network settings are switches: each value is true or false")
    chosen = {**get(store), **{key: body[key] for key in DEFAULTS if key in body}}
    store.set_setting(SETTING, chosen)
    apply(store)
    return chosen


def apply(store: Store) -> dict:
    chosen = get(store)
    research.switched_on = chosen["ai"]
    fonts.network_allowed = chosen["google_fonts"]
    return chosen
