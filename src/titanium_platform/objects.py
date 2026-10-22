"""The objects of a picture of people, to colour it like a colouring book: the operator picks the lips, the glasses, the hair, the pole
behind the person ... and gives each its own colours (the colouring is done elsewhere; this module only finds the objects).

Objects are found at preview size (the item of ``prediction_store.decode_upload``) from what the people model and the face detector
give, with no model of their own:

* the parts of the people model (:mod:`people`): background, hair, face skin, body skin, clothes and other things worn (glasses,
  jewellery), each one object as the model gives it;
* the lips and the eyes of every face the face detector finds (:mod:`faces`), carved out of the face skin:

  - the lips are the pixels of the detector's lips ellipse, in the face skin, that are redder and less yellow than the skin around them:
    a* - b* (lightly blurred) above Otsu's threshold over the ellipse. a* alone loses the lit side of the lips, which turns lilac rather
    than red. Only the pieces at the mouth count (those reaching the inner half of the ellipse), so reddish specks on the chin or the
    cheek are not lips; the gap between the lips is closed and small holes (a highlight) are filled. When the two sides of the threshold
    differ by less than ``LIPS_CONTRAST`` (a grey picture) the lips cannot be told from the skin and there are none;
  - an eye is the face skin of the detector's eye ellipse where the eye is visible: an eye whose ellipse is at least ``EYE_HIDDEN``
    covered by the people model's "other" part (sunglasses, a mask) is no object, the glasses stay "other"; frames crossing a visible eye
    stay "other" too, and clear glasses the model leaves out of "other" do not hide the eye;

  the lips of all faces are one object, and so are all visible eyes;
* the background split into pieces by colour: graph segmentation (``cv2.ximgproc``) of a copy at most ``SEGMENT_SIDE`` px long, whose
  segments' background pixels are the candidate pieces. The largest ``BACKGROUND_PIECES`` with at least ``BACKGROUND_SHARE`` of the
  background (and ``MIN_SHARE`` of the picture) are kept; the background pixels of every other segment join the kept piece of the nearest
  mean colour. Piece 0 is the largest, the main one.

An object under ``MIN_SHARE`` of the opaque picture is not kept: lips and eyes go back to the face skin, the pixels of any other object
join the nearest object kept. Objects are numbered in the order of ``KINDS`` and then of their pieces, so the same picture always gives
the same ids. Transparent pixels (``photo_modes.ALPHA_MIN``) belong to no object (-1). Every step is deterministic.
"""
from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

from . import color, faces, people, photo_modes

KINDS = ("background", "hair", "face_skin", "body_skin", "clothes", "other", "lips", "eyes")
MIN_SHARE = 0.005               # an object smaller than this share of the opaque picture is not kept
SEGMENT_SIDE = 400              # px: the long side of the copy the background is segmented on
SEGMENT_SIGMA = 1.0             # graph segmentation: the blur before it,
SEGMENT_K = 1500                # its scale (larger: larger segments)
SEGMENT_LEAST = 0.0125          # and its least segment, as a share of the copy
BACKGROUND_SHARE = 0.03         # a background piece has at least this share of the background
BACKGROUND_PIECES = 4           # and there are at most this many
LIPS_INNER = 0.5                # a piece of the lips reaches the lips ellipse scaled by this
LIPS_BLUR = 0.02                # sigma of the blur of a* - b*, as a share of the lips ellipse's long semi-axis
LIPS_CLOSE = 0.05               # the gap between the lips is closed by a disc this share of the long semi-axis across
LIPS_HOLE = 0.1                 # holes in the lips up to this share of their area are filled
LIPS_CONTRAST = 4.0             # a* - b*: lips differ from the skin around them by at least this on average
EYE_HIDDEN = 0.5                # an eye ellipse covered this much by the "other" part is hidden

# the colours of the objects on the overlay: by kind, and for background pieces 1.. their own
TINTS = {"background": (90, 90, 90), "hair": (160, 90, 40), "face_skin": (255, 140, 100), "body_skin": (255, 190, 140),
         "clothes": (70, 120, 255), "other": (60, 200, 90), "lips": (220, 40, 60), "eyes": (40, 200, 220)}
PIECE_TINTS = ((150, 60, 200), (230, 200, 40), (20, 130, 130), (200, 100, 170))

_KIND_OF_PART = np.array([KINDS.index(p) for p in people.PARTS], np.int32)
_BACKGROUND, _FACE, _OTHER = KINDS.index("background"), KINDS.index("face_skin"), KINDS.index("other")
_LIPS, _EYES = KINDS.index("lips"), KINDS.index("eyes")
_PIECES = 256                   # key of a pixel: kind * _PIECES + piece


def part_scores(item: dict) -> np.ndarray:
    """The people model's scores of the item's picture, computed once and kept with the item under ``part_scores`` (the same key
    ``prediction_store.part_scores`` keeps them under, so either computes them for both)."""
    if "part_scores" not in item:
        item["part_scores"] = people.scores(item["bgr_full"])
    return item["part_scores"]


def find(item: dict, *, detect: Callable[[np.ndarray], np.ndarray] | None = None) -> dict:
    """The objects of the item's picture (``picture``, ``alpha``, ``lab`` at preview size; ``part_scores``, or ``bgr_full`` to compute
    them); ``detect`` replaces the face detector (see ``faces.important_areas``).

    Returns ``{"labels": int32 (rows, cols), the id of every pixel's object, -1 where transparent, "objects": [{"id", "kind", "piece"
    (0 but for background pieces 1..), "share" (of the opaque picture), "lab" (mean [L, a, b]), "hex" ("#rrggbb"), "box" ([x0, y0, x1, y1]
    in preview pixels, x1 and y1 one past the last)}], "faces": number found, "notes": why lips or eyes are missing (a list of sentences),
    "face_error": why the face search could not run, or None}``."""
    rows, cols = item["picture"].shape
    opaque = np.asarray(item["alpha"]) >= photo_modes.ALPHA_MIN
    lab = np.asarray(item["lab"], np.float64)
    parts = people.parts_at(part_scores(item), (cols, rows))
    kind = _KIND_OF_PART[parts]
    rgb8 = np.clip(color.lab_to_srgb8(lab.reshape(-1, 3)), 0, 255).astype(np.uint8).reshape(rows, cols, 3)
    search = faces.important_areas(rgb8, detect=detect)
    notes = []
    if not search.face_found:
        notes.append("The face search could not run, so there are no lips or eyes." if search.error else "No face was found, so there are no lips or eyes.")
    else:
        skin = (kind == _FACE) & opaque
        lips, unclear = _lips([a for a in search.areas if a["kind"] == "lips"], lab, skin)
        eyes, hidden = _eyes([a for a in search.areas if a["kind"] == "eye"], kind, opaque)
        kind[lips] = _LIPS
        kind[eyes & skin & ~lips] = _EYES
        if unclear:
            notes.append("The lips could not be told from the skin by their colour.")
        if hidden:
            notes.append(f"{hidden} eye{'s are' if hidden > 1 else ' is'} behind glasses or something else worn: "
                         "they stay in the part 'other'.")
    total = int(opaque.sum())
    piece = np.zeros((rows, cols), np.int32)
    background = (kind == _BACKGROUND) & opaque
    if background.any():
        piece[background] = _background_pieces(rgb8, lab, background, total)
    key = np.where(opaque, kind * _PIECES + piece, -1)
    key, dropped = _keep(key, opaque, total)
    if _LIPS in dropped:
        notes.append("The lips are too small to be an object.")
    if _EYES in dropped:
        notes.append("The eyes are too small to be an object.")
    labels, objects = _numbered(key, opaque, lab, total)
    return {"labels": labels, "objects": objects, "faces": search.faces, "notes": notes, "face_error": search.error}


def overlay(item: dict, found: dict) -> np.ndarray:
    """The preview of the picture with every object of ``found`` (``find``) tinted in its colour (``TINTS``, background pieces 1.. in
    ``PIECE_TINTS``), RGB uint8, to check what was found; transparent pixels are left grey."""
    grey = np.repeat((np.clip(item["picture"], 0, 1) * 255)[..., None], 3, axis=-1).astype(np.float32)
    labels = found["labels"]
    tints = np.zeros((max(len(found["objects"]), 1), 3), np.float32)
    for o in found["objects"]:
        tints[o["id"]] = PIECE_TINTS[(o["piece"] - 1) % len(PIECE_TINTS)] if o["piece"] else TINTS[o["kind"]]
    shown = labels >= 0
    out = grey.copy()
    out[shown] = grey[shown] * 0.45 + tints[labels[shown]] * 0.55
    return out.round().astype(np.uint8)


# -- lips and eyes --------------------------------------------------------------------------------------------------------------------
def _scaled(area: dict, factor: float) -> dict:
    e = area["ellipse"]
    return {"ellipse": {**e, "axes": [e["axes"][0] * factor, e["axes"][1] * factor]}}


def _otsu(values: np.ndarray) -> float:
    """Otsu's threshold of ``values`` (on 256 levels between their least and largest)."""
    lo, hi = float(values.min()), float(values.max())
    if hi - lo < 1e-9:
        return hi
    levels = np.round((values - lo) / (hi - lo) * 255).astype(np.uint8).reshape(-1, 1)
    t, _ = cv2.threshold(levels, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return lo + (t + 0.5) / 255 * (hi - lo)


def _holes_filled(mask: np.ndarray, largest: float) -> np.ndarray:
    """``mask`` with its holes (areas it encloses) of at most ``largest`` pixels filled."""
    holes = np.pad(~mask, 1, constant_values=True).astype(np.uint8)
    n, cc, stats, _ = cv2.connectedComponentsWithStats(holes, connectivity=4)
    small = np.zeros(n, bool)
    small[1:] = stats[1:, cv2.CC_STAT_AREA] <= largest
    small[cc[0, 0]] = False                                   # the outside, around the padding
    return mask | small[cc[1:-1, 1:-1]]


def _one_mouth(area: dict, lab: np.ndarray, skin: np.ndarray) -> np.ndarray | None:
    """The lips in one face's lips ellipse (see the module docstring): a mask, or None when they cannot be told from the skin."""
    shape = skin.shape
    ellipse = faces.area_mask(area, shape) & skin
    if ellipse.sum() < 16:
        return np.zeros(shape, bool)
    ys, xs = np.nonzero(ellipse)
    axis = max(area["ellipse"]["axes"])
    sigma = max(0.5, LIPS_BLUR * axis)
    m = int(np.ceil(3 * sigma)) + 2
    y0, y1, x0, x1 = max(0, ys.min() - m), min(shape[0], ys.max() + m + 1), max(0, xs.min() - m), min(shape[1], xs.max() + m + 1)
    box = (slice(y0, y1), slice(x0, x1))
    feature = cv2.GaussianBlur((lab[box][..., 1] - lab[box][..., 2]).astype(np.float32), (0, 0), sigma)
    inside = ellipse[box]
    values = feature[inside]
    threshold = _otsu(values)
    above = values > threshold
    if above.all() or not above.any() or values[above].mean() - values[~above].mean() < LIPS_CONTRAST:
        return None
    candidate = cv2.morphologyEx((inside & (feature > threshold)).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, pieces = cv2.connectedComponents(candidate, connectivity=8)
    inner = faces.area_mask(_scaled(area, LIPS_INNER), shape)[box]
    at_mouth = np.zeros(n, bool)
    at_mouth[np.unique(pieces[inner & (candidate > 0)])] = True
    at_mouth[0] = False
    lips = at_mouth[pieces]
    size = max(3, int(round(LIPS_CLOSE * axis)) | 1)
    lips = cv2.morphologyEx(lips.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))) > 0
    lips &= inside
    lips = _holes_filled(lips, LIPS_HOLE * lips.sum()) & np.asarray(skin[box])
    out = np.zeros(shape, bool)
    out[box] = lips
    return out


def _lips(areas: list[dict], lab: np.ndarray, skin: np.ndarray) -> tuple[np.ndarray, bool]:
    """The lips of every face, and whether some could not be told from the skin."""
    lips, unclear = np.zeros(skin.shape, bool), False
    for area in areas:
        found = _one_mouth(area, lab, skin)
        if found is None:
            unclear = True
        else:
            lips |= found
    return lips, unclear


def _eyes(areas: list[dict], kind: np.ndarray, opaque: np.ndarray) -> tuple[np.ndarray, int]:
    """The eye ellipses of the visible eyes, and how many eyes are hidden by the "other" part."""
    eyes, hidden = np.zeros(kind.shape, bool), 0
    for area in areas:
        ellipse = faces.area_mask(area, kind.shape) & opaque
        if not ellipse.any():
            continue
        if (ellipse & (kind == _OTHER)).sum() >= EYE_HIDDEN * ellipse.sum():
            hidden += 1
        else:
            eyes |= ellipse
    return eyes, hidden


# -- the background -------------------------------------------------------------------------------------------------------------------
def _nearest(keep: np.ndarray) -> np.ndarray:
    """For every pixel the flat index of the nearest pixel where ``keep`` is True (Euclidean, OpenCV's 5 x 5 mask)."""
    source = (~keep).astype(np.uint8)                                     # zero: the pixels to take from
    _, nearest = cv2.distanceTransformWithLabels(source, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    lut = np.zeros(int(nearest.max()) + 1, np.int64)
    lut[nearest[keep]] = np.flatnonzero(keep)
    return lut[nearest]


def _people_filled(rgb8: np.ndarray, background: np.ndarray) -> np.ndarray:
    """The picture with every pixel off the background in the colour of the nearest background pixel, so that no segment of the
    background reaches into a person (and takes their colours) and a person never joins two pieces of the background."""
    return rgb8.reshape(-1, 3)[_nearest(background)].reshape(rgb8.shape)


def _background_pieces(rgb8: np.ndarray, lab: np.ndarray, background: np.ndarray, total: int) -> np.ndarray:
    """The piece of every background pixel (in the order of ``lab[background]``), 0 the largest (see the module docstring)."""
    rows, cols = background.shape
    scale = min(1.0, SEGMENT_SIDE / max(rows, cols))
    size = (max(1, round(cols * scale)), max(1, round(rows * scale)))
    small = rgb8 if scale >= 1 else cv2.resize(rgb8, size, interpolation=cv2.INTER_AREA)
    seen = background if scale >= 1 else cv2.resize(background.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    if seen.any() and not seen.all():
        small = _people_filled(small, seen)
    least = max(1, round(SEGMENT_LEAST * size[0] * size[1]))
    graph = cv2.ximgproc.segmentation.createGraphSegmentation(SEGMENT_SIGMA, SEGMENT_K, least)
    segments = graph.processImage(cv2.cvtColor(small, cv2.COLOR_RGB2BGR)).astype(np.int32)
    if scale < 1:
        segments = cv2.resize(segments, (cols, rows), interpolation=cv2.INTER_NEAREST)
    ids, where, counts = np.unique(segments[background], return_inverse=True, return_counts=True)
    order = np.lexsort((ids, -counts))                                    # the largest first, then by segment number
    enough = max(BACKGROUND_SHARE * int(background.sum()), MIN_SHARE * total)
    kept = [i for i in order[:BACKGROUND_PIECES] if counts[i] >= enough] or [order[0]]
    colours = lab[background]
    means = np.stack([np.bincount(where, weights=colours[:, c], minlength=len(ids)) for c in range(3)], axis=1) / counts[:, None]
    nearest = np.argmin(((means[:, None, :] - means[kept][None]) ** 2).sum(-1), axis=1)   # the kept piece of the nearest colour
    nearest[kept] = np.arange(len(kept))
    sizes = np.bincount(nearest, weights=counts, minlength=len(kept))
    rank = np.empty(len(kept), np.int32)
    rank[np.lexsort((np.arange(len(kept)), -sizes))] = np.arange(len(kept))
    return rank[nearest[where]]


# -- keeping and numbering ------------------------------------------------------------------------------------------------------------
def _keep(key: np.ndarray, opaque: np.ndarray, total: int) -> tuple[np.ndarray, set[int]]:
    """The keys with every object under ``MIN_SHARE`` of the picture taken out: lips and eyes back to the face skin, any other object's
    pixels to the nearest object kept; and the kinds of the lips and eyes dropped."""
    least = MIN_SHARE * total
    keys, counts = np.unique(key[opaque], return_counts=True)
    dropped = {int(k) // _PIECES for k, c in zip(keys, counts) if c < least and int(k) // _PIECES in (_LIPS, _EYES)}
    if dropped:
        key = key.copy()
        key[np.isin(key // _PIECES, list(dropped)) & opaque] = _FACE * _PIECES
        keys, counts = np.unique(key[opaque], return_counts=True)
    small = keys[counts < least]
    if len(small) and len(small) < len(keys):
        fill = np.isin(key, small) & opaque
        key = key.copy()
        key[fill] = key.reshape(-1)[_nearest(opaque & ~fill)[fill]]
    return key, dropped


def _numbered(key: np.ndarray, opaque: np.ndarray, lab: np.ndarray, total: int) -> tuple[np.ndarray, list[dict]]:
    """The labels (ids in the order of the keys: kind, then piece) and each object's description."""
    keys, ids, counts = np.unique(key[opaque], return_inverse=True, return_counts=True)
    labels = np.full(key.shape, -1, np.int32)
    labels[opaque] = ids.reshape(-1)
    colours = lab[opaque]
    means = np.stack([np.bincount(ids.reshape(-1), weights=colours[:, c], minlength=len(keys)) for c in range(3)], axis=1) / counts[:, None]
    rgb = np.clip(color.lab_to_srgb8(means), 0, 255).astype(int) if len(keys) else np.zeros((0, 3), int)
    objects, piece_of = [], {}
    for i, k in enumerate(keys):
        kind = KINDS[int(k) // _PIECES]
        piece_of[kind] = piece_of.get(kind, -1) + 1                       # pieces numbered again from 0, in their order
        x0, y0, w, h = cv2.boundingRect((labels == i).astype(np.uint8))
        objects.append({"id": i, "kind": kind, "piece": piece_of[kind], "share": round(float(counts[i]) / total, 4),
                        "lab": [round(float(v), 1) for v in means[i]], "hex": "#%02x%02x%02x" % tuple(rgb[i]), "box": [x0, y0, x0 + w, y0 + h]})
    return labels, objects
