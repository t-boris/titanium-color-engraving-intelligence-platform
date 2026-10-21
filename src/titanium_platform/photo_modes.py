"""The kinds of photo engraving LightBurn offers, and which part of a picture each of them strikes (REQ-053, REQ-054, DEC-095).

A LightBurn "image" layer turns the grey levels of a picture into laser work in one of eleven ways. They fall into four families:

* ``power``  (grayscale): every opaque pixel is scanned and the grey level sets the power between Min (lightest) and Max (darkest);
  white is scanned at Min power, so only Min 0 leaves white blank.
* ``dots``   (threshold, ordered, atkinson, dither, stucki, jarvis, newsprint, halftone): every dot is fired at the layer's own power or
  not at all, so a tone is the share of the area struck by dots. White is never struck. Threshold cuts at one grey (no tones in
  between: nothing to measure); the others spread the dots so that their density follows the darkness (an assumption: the exact
  algorithms are not modelled). Their tone is predicted from what was photographed in the same mode (``PROFILE``).
* ``edges``  (sketch): a high-pass of the picture decides where the dots go; for a line drawing the dots lie where the lines are.
* ``depth``  (3dslice): the picture is a depth map; each pass strikes the pixels darker than its level, so white gets no pass.

Sources: LightBurn's documentation of the Image Mode and of the cut settings, its forum for what the documentation leaves out
(binary output, transparent pixels are empty), and the files of the operator, which use grayscale, jarvis, sketch, 3dslice,
stucki and threshold. What is documented and what is only inferred is marked in ``basis``.

Pure functions on plain data: nothing is read from the store, so the same rules serve the check of a photograph, the composition of a
file and the prediction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

STRIKE_MIN = 0.05      # a pixel is "engraved over" when dots cover at least this share of its area (an assumption: a pale shading
                       # of a few dots does not hide the fill below it)
ALPHA_MIN = 0.5        # a pixel less opaque than this is empty (forum reports: fully transparent pixels are not engraved)
THRESHOLD_CUT = 0.5    # grey at which threshold mode and pass-through turn from white to black (LightBurn has no level setting)
WHITE = 0.5 / 255      # a grey this close to white is white: one level of an 8-bit picture

POWER, DOTS, EDGES, DEPTH = "power", "dots", "edges", "depth"
CURVE, PROFILE, NONE = "curve", "profile", "none"      # what a prediction of the mode rests on: power -> colour, grey -> colour, nothing

# Settings of the layer that change the result, by family; the mode adds its own (cells per inch, passes, ...).
_COMMON = ("speed", "frequency", "pulse width", "line interval (dpi)", "passes")


@dataclass(frozen=True)
class Mode:
    key: str                      # the ``ditherMode`` string of the file, lower case
    label: str                    # English; the screens translate it
    family: str
    controls: str                 # what the grey level of a pixel controls
    settings: tuple[str, ...]     # the layer settings that matter for this mode
    uses: str                     # what it is for, as LightBurn and its users say
    predicted_from: str           # CURVE: power -> colour at the mode; PROFILE: grey -> colour at the mode; NONE
    basis: str                    # "documented" or "inferred"

    @property
    def binary(self) -> bool:
        return self.family != POWER

    def as_dict(self) -> dict:
        return {**asdict(self), "binary": self.binary, "settings": list(self.settings)}


def _mode(key, label, family, controls, uses, extra=(), predicted_from=PROFILE, basis="documented") -> Mode:
    power = ("min power", "max power") if family == POWER else ("power", "dot width correction")
    return Mode(key, label, family, controls, power + _COMMON + tuple(extra), uses, predicted_from, basis)


_DOTS = "dot density: the darker the pixel, the more dots are fired, each at the layer's power"
MODES: dict[str, Mode] = {m.key: m for m in (
    _mode("grayscale", "Grayscale", POWER, "power: Min power for the lightest pixel, Max power for the darkest, linear in between "
          "(no formula is published; linear is the operator's rule, Q-024)", "tone on materials that react smoothly to power; on titanium the "
          "power moves the oxide through its colours, so the grey level moves hue as well as lightness", predicted_from=CURVE),
    _mode("threshold", "Threshold", DOTS, "on or off at mid grey: darker pixels are struck at full power, lighter ones never", "pictures that are "
          "already black and white", extra=("brightness (moves the cut)",), predicted_from=NONE),
    _mode("ordered", "Ordered", DOTS, _DOTS + " (a fixed Bayer pattern)", "large solid areas, logos", basis="inferred"),
    _mode("atkinson", "Atkinson", DOTS, _DOTS + " (error diffusion that drops a quarter of the error)", "in between; weak in very light and very dark areas"),
    _mode("dither", "Dither (Floyd-Steinberg)", DOTS, _DOTS + " (error diffusion)", "photographs; can streak in large flat areas"),
    _mode("stucki", "Stucki", DOTS, _DOTS + " (error diffusion over a wide neighbourhood)", "photographs; weak in mid-tones"),
    _mode("jarvis", "Jarvis", DOTS, _DOTS + " (error diffusion over a wide neighbourhood)", "photographs; LightBurn's usual advice for tone"),
    _mode("newsprint", "Newsprint", DOTS, _DOTS + " (a grid of spots, larger where it is darker)", "a visible pattern, smoothest at high dpi",
          basis="inferred"),
    _mode("halftone", "Halftone", DOTS, _DOTS + " (a grid of round dots set by cells per inch and angle)", "high dpi; cells per inch about a quarter of the dpi",
          extra=("cells per inch", "halftone angle")),
    _mode("sketch", "Sketch", EDGES, "edges: a high-pass of the picture decides where dots go; flat areas stay blank", "line drawings and handwriting",
          predicted_from=NONE, basis="inferred"),
    _mode("3dslice", "3D slice", DEPTH, "depth: each pass fires the pixels darker than its level, so the darkest pixel gets every pass and white none",
          "depth maps on a galvo laser; engraves relief, not a tone", extra=("number of passes", "cleanup pass"), predicted_from=NONE),
)}
ALIASES = {"dithered": "dither", "floydsteinberg": "dither", "passthrough": "threshold", "pass-through": "threshold", "3d slice": "3dslice",
           "3dsliced": "3dslice", "3d": "3dslice"}


def mode(name) -> Mode | None:
    """The mode a ``ditherMode`` string of a file names, or None for a string this version does not know."""
    key = str(name or "").strip().lower()
    return MODES.get(ALIASES.get(key, key))


def describe(name) -> dict:
    """The catalogue entry of a mode for the screens; a mode the version does not know is said to be unknown, never guessed at."""
    found = mode(name)
    if found is None:
        return {"key": str(name or ""), "known": False, "family": None}
    return {**found.as_dict(), "known": True}


def catalogue() -> list[dict]:
    return [describe(key) for key in MODES]


def coverage(name, grey, alpha=None, *, negative: bool = False, min_power=None, max_power=None, adjustments=None) -> np.ndarray:
    """The share (0..1) of each pixel's area that the layer strikes, from the picture's grey (0 black .. 1 white) and its alpha.

    ``grey`` and ``alpha`` are arrays of one shape; ``alpha`` None means opaque. ``adjustments`` are the layer's picture adjustments
    (gamma, contrast, brightness as ``prediction.adjustments_of`` returns them) and apply first; ``negative`` swaps light and dark
    after them. A pixel less opaque than ``ALPHA_MIN`` is empty in every mode. Grayscale strikes every opaque pixel whose power is above
    zero: all of them when Min power is above zero (white is scanned at Min), the pixels that are not white when it is zero (or when
    Max is zero too); the other modes strike in proportion to the darkness, threshold by a cut at mid grey. A mode this
    version does not know is treated as the dots family, the most common one, and the caller says so.
    """
    from . import prediction                                    # the standard formulas for gamma, contrast, brightness (assumed, DEC-057)
    g = np.asarray(grey, np.float64)
    if adjustments:
        values = prediction.adjustments_of(adjustments)["values"]
        g = prediction.adjust_grey(g, values["Gamma"], values["Contrast"], values["Brightness"])
    g = np.clip(g, 0.0, 1.0)
    if negative:
        g = 1.0 - g
    found = mode(name)
    family = found.family if found is not None else DOTS
    if family == POWER:
        low = 0.0 if min_power is None else float(min_power)
        high = 100.0 if max_power is None else float(max_power)
        out = np.where((low > 0) | ((high > 0) & (g < 1.0 - WHITE)), 1.0, 0.0)
    elif found is not None and found.key == "threshold":
        out = (g < THRESHOLD_CUT).astype(np.float64)
    else:
        out = 1.0 - g
    if alpha is not None:
        out = np.where(np.asarray(alpha, np.float64) >= ALPHA_MIN, out, 0.0)
    return out


def struck(name, grey, alpha=None, **kwargs) -> np.ndarray:
    """Boolean: the pixels on which the layer's engraving shows over what lies below (coverage at least ``STRIKE_MIN``)."""
    return coverage(name, grey, alpha, **kwargs) >= STRIKE_MIN


def decode_picture(png: bytes) -> tuple[np.ndarray, np.ndarray] | None:
    """The embedded picture as grey levels 0..1 (black engraves) and its opacity 0..1 (1 where the picture has no alpha channel)."""
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.dtype != np.uint8:
        img = (img.astype(np.float32) / (65535.0 if img.dtype == np.uint16 else 1.0) * 255).clip(0, 255).astype(np.uint8)
    if img.ndim == 2:
        grey, alpha = img.astype(np.float32) / 255.0, np.ones(img.shape, np.float32)
    else:
        grey = cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        alpha = img[..., 3].astype(np.float32) / 255.0 if img.shape[2] == 4 else np.ones(grey.shape, np.float32)
    return grey, alpha


def struck_mask(layer, image_to_mm: np.ndarray, shape: tuple[int, int], flip: bool = False, *, with_coverage: bool = False):
    """Pixels of a raster (a photograph, or a grid of millimetres) on which an image layer strikes the metal: what the pictures of the
    layer strike by its mode (``coverage``), laid over the raster through ``image_to_mm`` (raster pixel -> project mm), not the
    rectangle of the bitmap. ``flip`` is the edge of the picture that is up, as the tonal profile found it. With ``with_coverage`` the
    share of each pixel struck (0..1) is returned as well."""
    summary = layer.image_summary() or {}
    mm_to_image = np.linalg.inv(np.asarray(image_to_mm, float))
    out = np.zeros(shape, np.float32)
    for region in layer.regions:
        bm = region.bitmap
        found = decode_picture(bm["png"]) if bm and bm.get("png") else None
        if found is None:
            continue
        grey, alpha = found
        cover = coverage(summary.get("dither"), grey, alpha, negative=bool(summary.get("negative")), min_power=summary.get("min_power"),
                         max_power=summary.get("max_power"), adjustments=summary.get("adjusted")).astype(np.float32)
        rows, cols = cover.shape
        a, b, c, d, e, f = bm["matrix"]
        local_to_mm = np.array([[a, c, e], [b, d, f], [0, 0, 1.0]])
        to_local = np.array([[bm["w"] / cols, 0, -bm["w"] / 2],
                             [0, (-1 if flip else 1) * bm["h"] / rows, (bm["h"] / 2 if flip else -bm["h"] / 2)], [0, 0, 1.0]])
        warp = mm_to_image @ local_to_mm @ to_local
        scale = float(np.sqrt(abs(np.linalg.det(warp[:2, :2]))))          # raster pixels per picture pixel
        if scale < 0.7:                                                   # a picture finer than the raster: average it down first
            cover = cv2.resize(cover, (max(1, round(cols * scale)), max(1, round(rows * scale))), interpolation=cv2.INTER_AREA)
            warp = warp @ np.diag([cols / cover.shape[1], rows / cover.shape[0], 1.0])
        out = np.maximum(out, cv2.warpPerspective(cover, warp, (shape[1], shape[0]), flags=cv2.INTER_LINEAR))
    mask = out >= STRIKE_MIN
    return (mask, out) if with_coverage else mask
