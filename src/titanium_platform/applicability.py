"""How far a forecast rests on what was measured (feature ux-evidence-summaries-p0, REQ-001; research n31).

A forecast of a colour on titanium is drawn from colours measured at a row length (DEC-107, ``row_length``) on test strips and on engraved
works. The screen says, above the forecast, which of these it can claim, and the claim is derived only from the evidence the curve was
actually made of (``prediction.Curve.size`` and its sources), never assumed:

  measured_here    the colours were measured at this row length (``prediction.MEASURED``) and rest on more than a test strip
  other_width      the row length was not measured: the colours lie between two measured lengths or are those of the nearest measured length,
                   never extrapolated (``prediction.BETWEEN``, ``OUTSIDE``)
  test_scale_only  every point of the curve comes from a test grey ramp: no engraved photograph confirms the forecast for a picture
                   (``prediction_store.prediction_evidence``); this holds at whatever width the ramp was measured
  unknown          no point of the curve says the length it was measured at

``level`` is the weakest claim that applies, in the order test_scale_only, other_width, unknown, measured_here; ``limits`` lists every
limit that applies (a ramp measured at another width has both), so a screen can name the second one beside the first. The numbers
(``size``) are the curve's own; the words belong to the screen.

Pure functions on plain data: nothing is read from or written to the store.
"""
from __future__ import annotations

from typing import Mapping

from . import prediction

MEASURED_HERE, OTHER_WIDTH, TEST_SCALE_ONLY, UNKNOWN = "measured_here", "other_width", "test_scale_only", "unknown"
LEVELS = (MEASURED_HERE, OTHER_WIDTH, TEST_SCALE_ONLY, UNKNOWN)
_WEAKEST_FIRST = (TEST_SCALE_ONLY, OTHER_WIDTH, UNKNOWN)       # which limit names the claim when several apply


def _width_limit(size: Mapping | None) -> str | None:
    """The limit the row length alone puts on a forecast: None when it was measured, else ``other_width`` or ``unknown``."""
    how = (size or {}).get("how")
    if how == prediction.MEASURED:
        return None
    return OTHER_WIDTH if how in (prediction.BETWEEN, prediction.OUTSIDE) else UNKNOWN


def of_size(size: Mapping | None, ramp_only: bool = False) -> dict:
    """The claim a curve made for ``size`` (``Curve.size``) can make; ``ramp_only``: every point of it is from a test grey ramp."""
    limits = [limit for limit in (TEST_SCALE_ONLY if ramp_only else None, _width_limit(size)) if limit]
    level = next((limit for limit in _WEAKEST_FIRST if limit in limits), MEASURED_HERE)
    size = dict(size or {})
    return {"level": level, "limits": limits,
            "size": {"how": size.get("how", prediction.UNKNOWN), "row_mm": size.get("row_mm"), "measured_mm": list(size.get("measured_mm") or []),
                     "from_mm": list(size.get("from_mm") or [])}}


def of_counts(layers: int, estimated_layers: int, estimated_zones: int, ramp_only_zones: int, zones: int | None = None) -> dict:
    """The claim a preview of a work makes as a whole, from how many of its colour layers and photo zones are not backed by colours
    measured at their size (``estimated_*``: other width or width unknown) and how many zones rest on a test ramp only. A work with
    nothing to forecast claims nothing it cannot back: ``measured_here``, with zero counts."""
    limits = [limit for limit, n in ((TEST_SCALE_ONLY, ramp_only_zones), (OTHER_WIDTH, estimated_layers + estimated_zones)) if n]
    level = next((limit for limit in _WEAKEST_FIRST if limit in limits), MEASURED_HERE)
    return {"level": level, "limits": limits,
            "counts": {"layers": layers, "estimated_layers": estimated_layers, "zones": zones, "estimated_zones": estimated_zones,
                       "ramp_only_zones": ramp_only_zones}}


def of_preview(evidence: Mapping) -> dict:
    """The claim of a preview of a work from the counts the vector work already keeps (``preview_evidence``: ``layers``,
    ``estimated_layers``, ``estimated_zones``, ``ramp_only_zones``)."""
    return of_counts(evidence["layers"], evidence["estimated_layers"], evidence["estimated_zones"], evidence["ramp_only_zones"])
