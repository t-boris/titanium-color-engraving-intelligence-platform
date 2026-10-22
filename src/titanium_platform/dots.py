"""Which dots of the engraving grid the laser fires in each dot kind of a LightBurn image layer.

In every dot kind the laser fires each dot of the engraving grid (one pixel at the layer's line interval, 0.0254 mm = 1000 dpi for
example) at the layer's one power or not at all; the kind decides which dots. ``photo_modes.coverage`` takes the struck share of a
pixel to be its darkness. This module runs the algorithms themselves, so a preview can show the pattern each kind leaves and the
tone it really gives: Atkinson loses the lightest and the darkest tones, threshold keeps none in between, sketch strikes edges only.

* ``threshold``: a dot is fired where the picture is darker than ``photo_modes.THRESHOLD_CUT``.
* ``ordered``: a dot is fired where its darkness is above the threshold of its place in an 8 x 8 Bayer pattern repeated over the
  grid.
* ``dither`` (Floyd-Steinberg), ``atkinson``, ``stucki``, ``jarvis`` (Jarvis-Judice-Ninke): error diffusion with the published
  kernels (``KERNELS``). The dots are taken row by row from the top, each row from left to right; a dot is fired when its darkness
  plus the error it was given reaches one half, and what it missed by is shared among the dots after it. Atkinson passes on 6/8 of
  the error and drops the rest, so light greys stay blank and dark greys turn solid.
* ``halftone``: a grid of square cells, ``cells_per_inch`` to the inch and turned ``angle_deg`` counter-clockwise, each with one
  round spot at its centre whose area is the share of the cell its mean darkness asks for; past a quarter circle the spots meet
  and the white shrinks to the corners.
* ``newsprint``: the same spots on a fixed grid of ``NEWSPRINT_PITCH`` dots turned 45 degrees.
* ``sketch``: a high-pass of the picture: a dot is fired where it is darker than its blurred surroundings by ``SKETCH_CUT``, so
  only the dark side of a hard edge is struck and flat areas and soft shading stay blank.

White (``photo_modes.WHITE``) and empty pixels (alpha below ``photo_modes.ALPHA_MIN``) are never fired; in error diffusion they
also take no error and pass none on, so a white area stops it.

Sources: LightBurn's documentation of the Image Mode (https://docs.lightburnsoftware.com/latest/Reference/CutSettingsEditor/ImageMode/)
names the kinds, says Atkinson "resembles Jarvis but preserves detail better, though very light or dark areas may be blown out",
Ordered uses "an ordered/regular grid pattern", Newsprint generates "a grid of spots that are larger in darker areas", Halftone "is
similar to newsprint but can have variable cell size and pattern angle" (Cells per Inch: "Number of Halftone shading dots to compute
per inch"; Halftone Angle: "Angle of the Halftone shading pattern") and Sketch "engraves only at the areas where light and dark
values meet at hard edges (highpass filtering)". The defaults of a new layer, cellsPerInch 50 and halftoneAngle 22.5, are what
LightBurn writes into the files of layers nobody set them on (seven public .lbrn/.lbrn2 files agree), and a forum user remembers
22.5 (https://forum.lightburnsoftware.com/t/halftone-questions-angle/16438). The kernels are the published ones (Floyd and Steinberg
1976; Jarvis, Judice and Ninke 1976; Stucki 1981; Atkinson's for the Macintosh). Inferred, as nothing published says it: the left to
right order on every row (LightBurn does not say whether it runs serpentine), the 8 x 8 size of the Bayer pattern, the round spot,
the per-cell mean and the direction of the angle of halftone, newsprint's pitch and angle, sketch's blur and cut, and how white and empty dots treat the error.

Pure functions on arrays: the same picture and settings always give the same dots (nothing is random).
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import photo_modes

KINDS = ("threshold", "ordered", "atkinson", "dither", "stucki", "jarvis", "newsprint", "halftone", "sketch")

FIRE = 0.5                       # an error-diffusion dot fires when its darkness plus the error it was given reaches this
BAYER_SIZE = 8                   # side of the ordered pattern in dots (inferred)
HALFTONE_CELLS_PER_INCH = 50.0   # LightBurn's cellsPerInch on a new layer
HALFTONE_ANGLE_DEG = 22.5        # LightBurn's halftoneAngle on a new layer, degrees
NEWSPRINT_PITCH = 6.0            # dots between the centres of neighbouring newsprint spots (inferred: LightBurn has no setting)
NEWSPRINT_ANGLE_DEG = 45.0       # angle of the newsprint grid, the screen angle of newspaper black (inferred)
SKETCH_SIGMA = 2.0               # dots: the blur whose difference from the picture is sketch's high-pass (inferred)
SKETCH_CUT = 0.1                 # sketch fires a dot this much darker (0 white .. 1 black) than its blurred surroundings (inferred)

# Error diffusion kernels: (divisor, taps); a tap (dx, dy, n) gives n / divisor of a dot's error to the dot dx to its right and
# dy below it.
KERNELS: dict[str, tuple[int, tuple[tuple[int, int, int], ...]]] = {
    "dither": (16, ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1))),
    "atkinson": (8, ((1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1))),
    "jarvis": (48, ((1, 0, 7), (2, 0, 5), (-2, 1, 3), (-1, 1, 5), (0, 1, 7), (1, 1, 5), (2, 1, 3),
                    (-2, 2, 1), (-1, 2, 3), (0, 2, 5), (1, 2, 3), (2, 2, 1))),
    "stucki": (42, ((1, 0, 8), (2, 0, 4), (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2),
                    (-2, 2, 1), (-1, 2, 2), (0, 2, 4), (1, 2, 2), (2, 2, 1))),
}
_REACH = 2                       # the farthest any kernel reaches, in dots, sideways and down


def struck(grey, kind, *, dpi: float, alpha=None, cells_per_inch: float | None = None,
           angle_deg: float | None = None) -> np.ndarray:
    """True where a dot is fired. ``grey`` is 0 (black) .. 1 (white), one value per dot of the engraving grid, whose dpi is ``dpi``.

    ``kind`` is a ``ditherMode`` string of a dot kind (``KINDS``, or an alias ``photo_modes.mode`` reads). ``alpha`` (same shape,
    None for opaque) empties the dots less opaque than ``photo_modes.ALPHA_MIN``. ``cells_per_inch`` and ``angle_deg`` are the
    layer's halftone settings; None takes LightBurn's defaults.
    """
    key = _kind(kind)
    g = np.clip(np.asarray(grey, np.float64), 0.0, 1.0)
    if g.ndim != 2:
        raise ValueError("grey must be a 2-D array")
    empty = g >= 1.0 - photo_modes.WHITE
    if alpha is not None:
        empty |= np.asarray(alpha, np.float64) < photo_modes.ALPHA_MIN
    dark = np.where(empty, 0.0, 1.0 - g)
    if key == "threshold":
        fired = g < photo_modes.THRESHOLD_CUT
    elif key == "ordered":
        fired = _ordered(dark)
    elif key in KERNELS:
        fired = _diffuse(dark, empty, KERNELS[key])
    elif key == "halftone":
        cells = HALFTONE_CELLS_PER_INCH if cells_per_inch is None else float(cells_per_inch)
        if not dpi > 0 or not cells > 0:
            raise ValueError("halftone needs a dpi and cells per inch above zero")
        fired = _spots(dark, float(dpi) / cells, HALFTONE_ANGLE_DEG if angle_deg is None else float(angle_deg))
    elif key == "newsprint":
        fired = _spots(dark, NEWSPRINT_PITCH, NEWSPRINT_ANGLE_DEG)
    else:
        fired = _sketch(dark)
    return fired & ~empty


def coverage(grey, kind, *, dots_per_px: int, dpi: float, alpha=None, cells_per_inch: float | None = None,
             angle_deg: float | None = None) -> np.ndarray:
    """The share (0..1) of each pixel of ``grey`` that the dots strike: what the eye sees from a distance.

    ``grey`` is a picture at preview size; each of its pixels becomes ``dots_per_px`` x ``dots_per_px`` dots of a grid at ``dpi``
    (nearest neighbour: a pixel is one cell of the grid), ``struck`` runs on that grid, and each cell is averaged.
    """
    n = int(dots_per_px)
    if n < 1:
        raise ValueError("dots_per_px must be at least 1")
    g = np.asarray(grey, np.float64)
    if g.ndim != 2:
        raise ValueError("grey must be a 2-D array")

    def up(a):
        return np.repeat(np.repeat(a, n, axis=0), n, axis=1)

    fired = struck(up(g), kind, dpi=dpi, alpha=None if alpha is None else up(np.asarray(alpha, np.float64)),
                   cells_per_inch=cells_per_inch, angle_deg=angle_deg)
    h, w = g.shape
    return fired.reshape(h, n, w, n).mean(axis=(1, 3))


def _kind(name) -> str:
    found = photo_modes.mode(name)
    if found is None or found.key not in KINDS:
        raise ValueError(f"not a dot kind: {name!r} (one of {', '.join(KINDS)})")
    return found.key


def _bayer(size: int) -> np.ndarray:
    """The Bayer index matrix of a side that is a power of two: each dot's rank in the order the dots of a tile are fired."""
    m = np.zeros((1, 1), np.int64)
    while m.shape[0] < size:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return m


_BAYER = (_bayer(BAYER_SIZE) + 0.5) / BAYER_SIZE ** 2          # thresholds strictly between 0 and 1: white never fires, black always


def _ordered(dark: np.ndarray) -> np.ndarray:
    h, w = dark.shape
    return dark > _BAYER[np.arange(h)[:, None] % BAYER_SIZE, np.arange(w)[None, :] % BAYER_SIZE]


def _skew(taps) -> int:
    """The smallest k for which every source of a dot lies on an earlier wavefront ``x + k * y``: ``dx + k * dy > 0`` for each tap."""
    if any(dy < 0 or (dy == 0 and dx <= 0) for dx, dy, _ in taps):
        raise ValueError("a tap must point to a dot after the one it comes from")
    return max([1] + [(-dx) // dy + 1 for dx, dy, _ in taps if dy > 0])


def _diffuse(dark: np.ndarray, empty: np.ndarray, kernel) -> np.ndarray:
    """Error diffusion, row by row from the top and left to right, computed along wavefronts.

    The dot (y, x) only needs the error of dots its kernel reaches back to, all of which lie on a wavefront ``x + k * y`` before its
    own once k is ``_skew`` of the kernel (2 for Floyd-Steinberg and Atkinson, 3 for Jarvis and Stucki). The dots of one wavefront
    are therefore independent and are computed at once: each gathers the error of its sources tap by tap and is quantised. In a
    padded flat buffer the dots of one wavefront are equally spaced (one row down is ``k`` dots left), so every gather is a strided
    slice. The result is the same as the plain loop over the dots in raster order.
    """
    divisor, taps = kernel
    h, w = dark.shape
    if dark.size == 0:
        return np.zeros((h, w), bool)
    k = _skew(taps)
    r = _REACH
    wp = w + 2 * r                                              # a padded row: r blank dots either side, r blank rows on top
    d = np.zeros((h + r, wp))
    d[r:, r:r + w] = dark
    open_ = np.zeros((h + r, wp))
    open_[r:, r:r + w] = ~empty
    d, open_ = d.ravel(), open_.ravel()
    err = np.zeros(d.size)
    fired = np.zeros(d.size, bool)
    sources = [(dy * wp + dx, n / divisor) for dx, dy, n in taps]
    step, base = wp - k, r * wp + r                             # flat index of (y, x) is base + x + y * wp = base + t + y * step
    for t in range(w + k * (h - 1)):
        y0, y1 = max(0, -((w - 1 - t) // k)), min(h - 1, t // k)
        if y1 < y0:                                             # a picture narrower than k has wavefronts with no dot
            continue
        start = base + t + y0 * step
        stop = start + (y1 - y0) * step + 1
        v = d[start:stop:step].copy()
        for back, share in sources:
            v += share * err[start - back:stop - back:step]
        hit = (v >= FIRE) & (open_[start:stop:step] > 0)
        err[start:stop:step] = (v - hit) * open_[start:stop:step]
        fired[start:stop:step] = hit
    return fired.reshape(h + r, wp)[r:, r:r + w]


def _disc_share(radius: np.ndarray) -> np.ndarray:
    """The share of a unit square inside the disc of ``radius`` about its centre: the order in which a cell's dots join its spot."""
    rr = np.minimum(radius, math.sqrt(0.5))
    disc = np.pi * rr * rr
    a = np.maximum(rr, 0.5)
    cut = disc - 4.0 * (a * a * np.arccos(0.5 / a) - 0.5 * np.sqrt(a * a - 0.25))   # less the four segments past the sides
    return np.minimum(np.where(rr <= 0.5, disc, cut), np.nextafter(1.0, 0.0))


def _spots(dark: np.ndarray, pitch: float, angle_deg: float) -> np.ndarray:
    """Round spots on a grid of square cells ``pitch`` dots wide, turned by ``angle_deg`` counter-clockwise as the picture is seen
    (rows run down, so the turn is clockwise in row and column numbers): a cell fires the dots nearest its centre, as many as its
    mean darkness asks for."""
    h, w = dark.shape
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    ys, xs = (np.arange(h) + 0.5)[:, None], (np.arange(w) + 0.5)[None, :]
    u, v = (xs * c - ys * s) / pitch, (xs * s + ys * c) / pitch
    iu, iv = np.floor(u), np.floor(v)
    level = _disc_share(np.hypot(u - iu - 0.5, v - iv - 0.5))
    iu, iv = (iu - iu.min()).astype(np.int64), (iv - iv.min()).astype(np.int64)
    cell = (iu * (int(iv.max()) + 1) + iv).ravel()
    mean = np.bincount(cell, dark.ravel()) / np.maximum(np.bincount(cell), 1)
    return level < mean[cell].reshape(h, w)


def _sketch(dark: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(dark.astype(np.float32), (0, 0), SKETCH_SIGMA, borderType=cv2.BORDER_REPLICATE)
    return dark - blurred >= SKETCH_CUT
