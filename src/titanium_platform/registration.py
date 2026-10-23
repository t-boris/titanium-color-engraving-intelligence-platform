"""Match engraved LightBurn details to a photograph in *file millimetres*.

The photograph is the only thing transformed.  In particular, a marker match
never changes the dimensions recorded by LightBurn.  Several jobs may be
visible on one piece of metal, so individual high-scoring marks are only
proposals: a registration needs one geometrically consistent set.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, permutations

import cv2
import numpy as np


@dataclass
class Registration:
    image_to_mm: np.ndarray
    method: str
    matches: list[dict]
    residual_px: float
    reflected: bool
    qr_offset_px: tuple[float, float] | None = None
    qr_used_as_anchor: bool = False
    details: dict | None = None      # element anchoring: statuses, window, hidden margins (anchoring.py)


def match_closed_vectors(img_bgr: np.ndarray, layers: list, image_to_mm: np.ndarray,
                         excluded_layer_indices: set[int] | None = None,
                         layer_offsets_px: dict | None = None) -> list[dict]:
    """Check each photographically resolvable closed vector near its file position.

    The global registration supplies location and scale; this search tests the
    *shape border* of each vector independently. Its best local translation is
    evidence for the reviewer, not a change to LightBurn dimensions or to the
    masks used for color measurements. Layer membership is only provenance.
    """
    excluded = excluded_layer_indices or set()
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    contrast = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    edges = cv2.Canny(contrast, 35, 105)
    distance = cv2.distanceTransform(255 - edges, cv2.DIST_L2, 3)
    mm_to_image = np.linalg.inv(np.asarray(image_to_mm, np.float64))
    height, width = gray.shape
    result = []
    for layer in layers:
        if layer.index in excluded:
            continue
        offset = (layer_offsets_px or {}).get(layer.index)
        if offset is None:
            offset = (layer_offsets_px or {}).get(str(layer.index))
        layer_to_image = mm_to_image.copy()
        if offset:
            shift = offset["offset_px"] if isinstance(offset, dict) else offset
            translation = np.eye(3)
            translation[:2, 2] = np.asarray(shift, float)
            layer_to_image = translation @ mm_to_image
        for region_index, region in enumerate(layer.regions):
            if not (getattr(region, "closed", len(region.polygon) >= 3) or
                    getattr(region, "kind", "") in ("rect", "bitmap")) or len(region.polygon) < 3:
                continue
            source = np.asarray(region.polygon, np.float32)
            if abs(cv2.contourArea(source)) < .15:
                continue
            projected = cv2.perspectiveTransform(source[None], layer_to_image)[0]
            if not np.isfinite(projected).all():
                continue
            x, y, w, h = cv2.boundingRect(projected)
            if min(w, h) < 7 or x < 15 or y < 15 or x + w >= width - 15 or y + h >= height - 15:
                continue
            # Sample the complete polygon border at about two-pixel spacing.
            samples = []
            for a, b in zip(projected, np.roll(projected, -1, axis=0)):
                n = max(3, min(250, int(np.linalg.norm(b - a) / 2)))
                samples.append(a[None, :] + np.linspace(0, 1, n, endpoint=False)[:, None] * (b - a)[None, :])
            border = np.concatenate(samples)
            if len(border) > 1000:
                border = border[::int(np.ceil(len(border) / 1000))]
            radius = max(4, min(15, int(round(min(w, h) * .2))))
            shifts = range(-radius, radius + 1, max(2, radius // 4))
            best = (-1.0, 0, 0)
            for dy in shifts:
                for dx in shifts:
                    px = np.clip(np.rint(border[:, 0] + dx).astype(np.int32), 0, width - 1)
                    py = np.clip(np.rint(border[:, 1] + dy).astype(np.int32), 0, height - 1)
                    score = float(np.mean(np.exp(-distance[py, px] / 2.0)))
                    if score > best[0]:
                        best = (score, dx, dy)
            score, dx, dy = best
            # Uniform fills may have no sharp edge in a dark RAW exposure.
            # Compare the vector's interior with a narrow ring immediately
            # outside it, independently of any other vector in the layer.
            pad = 18
            x0, y0 = max(0, x-pad), max(0, y-pad)
            x1, y1 = min(width, x+w+pad), min(height, y+h+pad)
            local_mask = np.zeros((y1-y0, x1-x0), np.uint8)
            local_pts = np.rint(projected - (x0, y0)).astype(np.int32)
            cv2.fillPoly(local_mask, [local_pts], 1)
            interior = cv2.erode(local_mask, np.ones((5, 5), np.uint8)) > 0
            ring = (cv2.dilate(local_mask, np.ones((13, 13), np.uint8)) > 0) & (local_mask == 0)
            fill_contrast = 0.0
            relative_contrast = 0.0
            if interior.sum() >= 9 and ring.sum() >= 9:
                crop = gray[y0:y1, x0:x1]
                inside = float(np.median(crop[interior]))
                outside = float(np.median(crop[ring]))
                fill_contrast = abs(inside - outside)
                relative_contrast = fill_contrast / max(8.0, outside)
            found = (score >= .42 or
                     fill_contrast >= 3 and relative_contrast >= .15 or
                     score >= .3 and fill_contrast >= 2)
            if score < .42:
                # A nearby scratch can maximise a weak edge score. A fill
                # observation alone does not justify moving the vector.
                dx = dy = 0
            center = projected.mean(axis=0)
            result.append({"layer_index": layer.index, "region_index": region_index,
                           "element": f"{layer.name} #{region_index + 1}",
                           "size_mm": [round(region.width, 3), round(region.height, 3)],
                           "expected_center_px": center.round(1).tolist(),
                           "found_center_px": (center + (dx, dy)).round(1).tolist(),
                           "offset_px": [dx, dy], "edge_support": round(score, 3),
                           "fill_contrast": round(fill_contrast, 1),
                           "status": "found" if found else "uncertain"})
    return result


def snap_layer_translations(img_bgr: np.ndarray, layers: list, image_to_mm: np.ndarray,
                            excluded_layer_indices: set[int] | None = None) -> dict[int, dict]:
    """Match each layer's complete vector pattern to nearby RAW image detail.

    Only translation is fitted here. The LightBurn dimensions and relative
    positions of every polygon within a layer remain unchanged. A correlation
    peak must be strong and substantially better than the global alignment.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    detail = cv2.GaussianBlur(gray, (0, 0), 12) - gray
    mm_to_image = np.linalg.inv(np.asarray(image_to_mm, np.float64))
    height, width = gray.shape
    pad = min(60, max(18, int(round(min(height, width) * .018))))
    result: dict[int, dict] = {}
    for layer in layers:
        if layer.index in (excluded_layer_indices or set()) or len(layer.regions) < 3:
            continue
        projected = []
        for region in layer.regions:
            if len(region.polygon) < 3:
                continue
            polygon = np.asarray(region.polygon, np.float32)
            if abs(cv2.contourArea(polygon)) < .01:
                continue
            projected.append(cv2.perspectiveTransform(polygon[None], mm_to_image)[0])
        if len(projected) < 3:
            continue
        points = np.concatenate(projected)
        if not np.isfinite(points).all():
            continue
        x0, y0 = np.floor(points.min(axis=0)).astype(int)
        x1, y1 = np.ceil(points.max(axis=0)).astype(int) + 1
        tw, th = x1 - x0, y1 - y0
        if min(tw, th) < 12 or tw * th > 2_000_000:
            continue
        if x0 - pad < 0 or y0 - pad < 0 or x1 + pad > width or y1 + pad > height:
            continue
        template = np.zeros((th, tw), np.uint8)
        for polygon in projected:
            cv2.fillPoly(template, [np.rint(polygon - (x0, y0)).astype(np.int32)], 255)
        density = float(np.count_nonzero(template)) / template.size
        if not .005 <= density <= .75:
            continue
        search = detail[y0-pad:y1+pad, x0-pad:x1+pad]
        reference = template.astype(np.float32)
        winner = None
        for polarity in ("dark", "light"):
            crop = search if polarity == "dark" else -search
            response = cv2.matchTemplate(crop, reference, cv2.TM_CCOEFF_NORMED)
            _, peak, _, location = cv2.minMaxLoc(response)
            baseline = float(response[pad, pad])
            if winner is None or peak > winner[0]:
                winner = (peak, baseline, location, polarity)
        peak, baseline, location, polarity = winner
        dx, dy = location[0] - pad, location[1] - pad
        if (dx or dy) and peak >= .28 and peak - baseline >= .08:
            result[layer.index] = {"offset_px": [int(dx), int(dy)],
                                   "shape_match": round(float(peak), 3),
                                   "baseline_match": round(baseline, 3),
                                   "contrast": polarity}
    return result


def _runs(values: np.ndarray, minimum: int) -> list[tuple[int, int]]:
    """Half-open runs of evidence, including a run cut by the photograph edge."""
    starts = np.flatnonzero(np.diff(np.r_[False, values, False].astype(np.int8)) == 1)
    ends = np.flatnonzero(np.diff(np.r_[False, values, False].astype(np.int8)) == -1)
    return [(int(a), int(b)) for a, b in zip(starts, ends) if b - a >= minimum]


def _partial_marker_edge(gray: np.ndarray, marker: dict, mm_to_image: np.ndarray,
                         dx: float, dy: float, right_side: bool) -> dict | None:
    """Locate the surviving left border of an ArUco square.

    The opposite border may be outside the photograph or the metal. Requiring
    a complete template would systematically discard exactly these markers.
    The search is constrained by the already verified plate registration.
    """
    corners = _file_corners(marker, dx, dy)
    projected = cv2.perspectiveTransform(corners[None], mm_to_image)[0]
    x0, y0 = projected.min(axis=0)
    x1, y1 = projected.max(axis=0)
    side_x, side_y = x1 - x0, y1 - y0
    height, width = gray.shape
    if min(side_x, side_y) < 18:
        return None
    cy = (y0 + y1) / 2
    ys = slice(max(0, round(cy - .28 * side_y)), min(height, round(cy + .28 * side_y)))
    if right_side:
        bg_x0, bg_x1 = x0 - 2.3 * side_x, x0 - 1.7 * side_x
        near_x0, near_x1 = x0 - .9 * side_x, x0 - .55 * side_x
    else:
        bg_x0, bg_x1 = x1 + 1.2 * side_x, x1 + 1.8 * side_x
        near_x0, near_x1 = x1 + .15 * side_x, x1 + .45 * side_x
    backgrounds = []
    for lo, hi in ((bg_x0, bg_x1), (near_x0, near_x1)):
        xa, xb = max(0, round(lo)), min(width, round(hi))
        if xb - xa >= 8 and ys.stop - ys.start >= 8:
            backgrounds.append(float(np.median(gray[ys, xa:xb])))
    if not backgrounds:
        return None
    threshold = max(3., .55 * max(backgrounds))
    py0, py1 = max(0, round(y0 + .2 * side_y)), min(height, round(y1 - .2 * side_y))
    px0, px1 = max(0, round(x0 - .5 * side_x)), min(width, round(x0 + .5 * side_x))
    if py1 - py0 < 10 or px1 - px0 < 12:
        return None
    columns = (gray[py0:py1, px0:px1] < threshold).mean(axis=0)
    present = np.convolve(columns, np.ones(7) / 7, mode="same") > .7
    candidates = _runs(present, max(5, round(.035 * side_x)))
    if not candidates:
        return None
    # A nearby QR may contribute a short dark run. The marker's exterior has
    # a continuous border across the central scan band.
    left, end = max(candidates, key=lambda run: run[1] - run[0])
    left += px0
    if abs(left - x0) > .42 * side_x:
        return None
    xa, xb = max(0, round(left + .02 * side_x)), min(width, round(left + .08 * side_x))
    if xb - xa < 4:
        return None
    ry0, ry1 = max(0, round(y0 - .5 * side_y)), min(height, round(y1 + .5 * side_y))
    rows = (gray[ry0:ry1, xa:xb] < threshold).mean(axis=1)
    present = np.convolve(rows, np.ones(7) / 7, mode="same") > .7
    runs = _runs(present, max(10, round(.35 * side_y)))
    if not runs:
        return None
    top, bottom = max(runs, key=lambda run: run[1] - run[0])
    top += ry0
    bottom += ry0
    if not (.65 * side_y <= bottom - top <= 1.3 * side_y):
        return None
    if abs(top - y0) > .45 * side_y or abs(bottom - y1) > .45 * side_y:
        return None
    return {"left_px": int(left), "top_px": int(top), "bottom_px": int(bottom),
            "predicted_bounds_px": [round(float(v), 1) for v in (x0, y0, x1, y1)],
            "visible_fraction": round(float((bottom - top) / side_y), 3)}


def _label_groups(rects: list[dict]) -> list[list[dict]]:
    """Group the engraving's letter pixels spatially, independently of layer."""
    remaining = set(range(len(rects)))
    groups = []
    while remaining:
        pending = [remaining.pop()]
        component = []
        while pending:
            index = pending.pop()
            component.append(rects[index])
            a = rects[index]
            neighbors = []
            for other_index in remaining:
                b = rects[other_index]
                x_gap = max(a["x"] - b["x"] - b["width"], b["x"] - a["x"] - a["width"], 0)
                y_gap = max(a["y"] - b["y"] - b["height"], b["y"] - a["y"] - a["height"], 0)
                if x_gap <= 1.0 and y_gap <= 1.0:
                    neighbors.append(other_index)
            remaining.difference_update(neighbors)
            pending.extend(neighbors)
        groups.append(component)
    return sorted(groups, key=lambda g: (min(r["y"] for r in g), min(r["x"] for r in g)))


def snap_marker_features(img_bgr: np.ndarray, markers: dict, label_rects: list[dict],
                         image_to_mm: np.ndarray, dx: float, dy: float) -> dict[str, dict]:
    """Refine clipped fiducials and tiny label clusters without changing file geometry."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    detail = cv2.GaussianBlur(gray, (0, 0), 12) - gray
    mm_to_image = np.linalg.inv(np.asarray(image_to_mm, np.float64))
    height, width = gray.shape
    middle_x = (markers["extent"]["min_x"] + markers["extent"]["max_x"]) / 2
    results = {}
    for marker in markers.get("aruco", []):
        observed = _partial_marker_edge(gray, marker, mm_to_image, dx, dy, marker["x"] > middle_x)
        if not observed:
            continue
        x0, y0, x1, y1 = observed["predicted_bounds_px"]
        scale_y = (observed["bottom_px"] - observed["top_px"]) / (y1 - y0)
        transform = [[1., 0., observed["left_px"] - x0],
                     [0., scale_y, observed["top_px"] - scale_y * y0],
                     [0., 0., 1.]]
        bounds = [marker["x"] + dx, marker["y"] + dy,
                  marker["x"] + marker["size"] + dx, marker["y"] + marker.get("height", marker["size"]) + dy]
        results[f"aruco:{marker['id']}"] = {"bounds_mm": bounds,
                                             "pixel_transform": transform, **observed,
                                             "method": "visible marker border"}
    for index, rects in enumerate(_label_groups(label_rects)):
        if len(rects) < 10:
            continue
        polygons = []
        for rect in rects:
            x, y = rect["x"] + dx, rect["y"] + dy
            w, h = rect["width"], rect["height"]
            polygon = np.float32([[(x, y), (x+w, y), (x+w, y+h), (x, y+h)]])
            polygons.append(cv2.perspectiveTransform(polygon, mm_to_image)[0])
        points = np.concatenate(polygons)
        x0, y0 = np.floor(points.min(axis=0)).astype(int)
        x1, y1 = np.ceil(points.max(axis=0)).astype(int) + 1
        if min(x1 - x0, y1 - y0) < 12 or (x1 - x0) * (y1 - y0) > 250_000:
            continue
        template = np.zeros((y1-y0, x1-x0), np.uint8)
        for polygon in polygons:
            cv2.fillPoly(template, [np.rint(polygon - (x0, y0)).astype(np.int32)], 255)
        pad = max(35, min(65, int(.03 * min(width, height))))
        sx0, sy0 = max(0, x0-pad), max(0, y0-pad)
        sx1, sy1 = min(width, x1+pad), min(height, y1+pad)
        if sx1-sx0 < x1-x0 or sy1-sy0 < y1-y0:
            continue
        response = cv2.matchTemplate(detail[sy0:sy1, sx0:sx1],
                                     template.astype(np.float32), cv2.TM_CCOEFF_NORMED)
        _, peak, _, location = cv2.minMaxLoc(response)
        baseline = float(response[y0-sy0, x0-sx0])
        if peak < .5 or peak - baseline < .15:
            continue
        shift_x, shift_y = int(location[0] + sx0 - x0), int(location[1] + sy0 - y0)
        bounds = [min(r["x"] for r in rects) + dx, min(r["y"] for r in rects) + dy,
                  max(r["x"]+r["width"] for r in rects) + dx,
                  max(r["y"]+r["height"] for r in rects) + dy]
        results[f"label:{index}"] = {"bounds_mm": bounds,
                                      "pixel_transform": [[1., 0., shift_x], [0., 1., shift_y], [0., 0., 1.]],
                                      "offset_px": [shift_x, shift_y],
                                      "shape_match": round(float(peak), 3),
                                      "baseline_match": round(baseline, 3),
                                      "method": "engraved label vectors"}
    return results


def visible_right_surface_edge(img_bgr: np.ndarray, markers: dict,
                               image_to_mm: np.ndarray, dx: float, dy: float) -> list[list[int]]:
    """Estimate a photographed metal edge that cuts through right fiducials.

    This is only a visibility limit for overlays and measurements. It never
    supplies a LightBurn coordinate or changes the engraving's dimensions.
    A weak or inconsistent edge leaves the photograph unclipped.
    """
    right = sorted(markers.get("aruco", []), key=lambda item: item["x"])[-2:]
    if len(right) < 2 or right[0]["x"] != right[1]["x"]:
        return []
    mm_to_image = np.linalg.inv(np.asarray(image_to_mm, np.float64))
    rectangles = [cv2.perspectiveTransform(_file_corners(item, dx, dy)[None], mm_to_image)[0]
                  for item in right]
    left = float(min(points[:, 0].min() for points in rectangles))
    far = float(max(points[:, 0].max() for points in rectangles))
    side = far - left
    height, width = img_bgr.shape[:2]
    xa, xb = max(0, round(left + .45 * side)), min(width, round(far + .35 * side))
    top = max(0, round(min(points[:, 1].min() for points in rectangles)))
    bottom = min(height - 1, round(max(points[:, 1].max() for points in rectangles)))
    if xb - xa < 35 or bottom - top < 100:
        return []
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    observations = []
    for center in np.linspace(top + 60, bottom - 60, 10):
        cy = round(center)
        ya, yb = max(0, cy - 60), min(height, cy + 60)
        band = gray[ya:yb, xa:xb]
        if min(band.shape) < 25:
            continue
        smooth = cv2.GaussianBlur(band, (0, 0), 8)
        gradient = np.diff(smooth, axis=1).mean(axis=0)
        position = int(np.argmax(gradient))
        edge = xa + position
        strength = float(gradient[position])
        if (strength < .35 or position < 15 or position > len(gradient) - 16 or
                abs(edge - far) > .45 * side):
            continue
        inside = gray[ya:yb, max(0, edge-40):max(0, edge-15)]
        outside = gray[ya:yb, min(width, edge+15):min(width, edge+40)]
        if inside.size == 0 or outside.size == 0:
            continue
        if float(np.mean(outside) - np.mean(inside)) < 4 and float(np.std(outside)) < 1.5 * float(np.std(inside)):
            continue
        observations.append([cy, edge])
    if len(observations) < 5 or np.ptp([point[1] for point in observations]) > .5 * side:
        return []
    return observations


def _marker_variants(marker_id: int):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    original = cv2.aruco.generateImageMarker(dictionary, marker_id, 6, borderBits=1)
    for reflected in (False, True):
        for turns in range(4):
            bitmap = cv2.flip(original, 1) if reflected else original
            bitmap = np.rot90(bitmap, turns).copy()
            corners = np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.]])
            if reflected:
                corners[:, 0] = 1 - corners[:, 0]
            for _ in range(turns):
                corners = np.column_stack((corners[:, 1], 1 - corners[:, 0]))
            yield (reflected, turns), bitmap, corners


def _candidate_sizes(shape: tuple[int, int], markers: dict, scale: float) -> list[int]:
    height, width = shape
    extent = markers["extent"]
    work_w = extent["max_x"] - extent["min_x"]
    work_h = extent["max_y"] - extent["min_y"]
    side = float(np.median([m["size"] for m in markers["aruco"]]))
    # The engraving may occupy just part of the photograph; these are search
    # bounds, not a guessed physical scale.  The fitted transform uses mm.
    fit = min(width / max(work_w, 1), height / max(work_h, 1)) * side * scale
    low, high = max(9, int(fit * .14)), min(int(min(width, height) * scale / 3), int(fit * 1.25))
    if high <= low:
        return []
    sizes = np.geomspace(low, high, 12)
    return sorted(set(int(round(s)) for s in sizes))


def _template_candidates(img_bgr: np.ndarray, markers: dict) -> list[dict]:
    height, width = img_bgr.shape[:2]
    scale = min(1., 1200 / max(height, width))
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    sizes = _candidate_sizes((height, width), markers, scale)
    results = []
    for marker in markers["aruco"]:
        marker_id = marker["id"]
        for orientation, bitmap, corner_map in _marker_variants(marker_id):
            raw = []
            for size in sizes:
                if size >= min(gray.shape[:2]):
                    continue
                template = cv2.resize(bitmap, (size, size), interpolation=cv2.INTER_NEAREST)
                response = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                for _ in range(4):
                    _, score, _, (x, y) = cv2.minMaxLoc(response)
                    if score < .57:
                        break
                    raw.append((score, x / scale, y / scale, size / scale))
                    radius = max(4, size // 2)
                    cv2.rectangle(response, (max(0, x-radius), max(0, y-radius)),
                                  (min(response.shape[1]-1, x+radius), min(response.shape[0]-1, y+radius)), -1, -1)
            raw.sort(reverse=True)
            kept = []
            for score, x, y, size in raw:
                center = np.array([x + size / 2, y + size / 2])
                if any(np.linalg.norm(center - item["center"]) < .6 * max(size, item["size"]) for item in kept):
                    continue
                points = np.column_stack((x + corner_map[:, 0] * size, y + corner_map[:, 1] * size))
                kept.append({"id": marker_id, "score": float(score), "center": center, "size": size,
                             "points": points, "orientation": orientation})
                if len(kept) >= 6:
                    break
            results.extend(kept)
    return results


def _file_corners(marker: dict, dx: float, dy: float) -> np.ndarray:
    x, y, s, t = marker["x"] + dx, marker["y"] + dy, marker["size"], marker.get("height", marker["size"])   # a scaled file's marker (BUG-006)
    return np.array([(x, y), (x+s, y), (x+s, y+t), (x, y+t)], np.float32)


def _fit(matches: list[dict], by_id: dict, dx: float, dy: float) -> np.ndarray | None:
    image = np.concatenate([m["points"] for m in matches]).astype(np.float32)
    file = np.concatenate([_file_corners(by_id[m["id"]], dx, dy) for m in matches])
    h, _ = cv2.findHomography(image, file, 0)
    return h


def _residual(h: np.ndarray, matches: list[dict], by_id: dict, dx: float, dy: float) -> float:
    mm_to_image = np.linalg.inv(h)
    distances = []
    for m in matches:
        predicted = cv2.perspectiveTransform(_file_corners(by_id[m["id"]], dx, dy)[None], mm_to_image)[0]
        distances.extend(np.linalg.norm(predicted - m["points"], axis=1))
    return float(np.median(distances))


def _center_fit(matches: list[dict], by_id: dict, dx: float, dy: float) -> tuple[np.ndarray, float] | None:
    """Use marker centres for the final fit; template edges are biased by engraving bloom."""
    image = np.float32([m["center"] for m in matches])
    file = np.float32([_file_corners(by_id[m["id"]], dx, dy).mean(axis=0) for m in matches])
    if len(matches) == 4:
        h = cv2.getPerspectiveTransform(image, file)
    else:
        h = np.vstack([cv2.getAffineTransform(image[:3], file[:3]), [0, 0, 1]])
    # A projective fit through four points has zero residual by construction.
    # Test the simpler affine model to catch an unrelated old marker.
    affine_xy, *_ = np.linalg.lstsq(np.column_stack((image, np.ones(len(image)))), file, rcond=None)
    affine = np.vstack([affine_xy.T, [0, 0, 1]])
    projected = cv2.perspectiveTransform(image[None], affine)[0]
    mm_per_px = np.median([by_id[m["id"]]["size"] / m["size"] for m in matches])
    residual = float(np.max(np.linalg.norm(projected - file, axis=1)) / mm_per_px)
    # Compare all independent centre-to-centre scales in mm. A second job's
    # fiducial may have the right ID but will not complete this rectangle.
    ratios = [np.linalg.norm(image[i] - image[j]) / np.linalg.norm(file[i] - file[j])
              for i, j in combinations(range(len(matches)), 2)]
    if max(ratios) / min(ratios) > 1.18:
        return None
    return h, residual


def _two_marker_similarity(left: dict, right: dict, by_id: dict, dx: float, dy: float) -> tuple[np.ndarray, float, bool] | None:
    """Use centre spacing for scale when only two engraved marks survive.

    Template squares can be several percent too small because engraving bloom
    changes the edge. Their *centres* remain stable. Handedness comes from the
    matched marker pattern, and the QR identifier must verify the result later.
    """
    f0 = _file_corners(by_id[left["id"]], dx, dy).mean(axis=0).astype(float)
    f1 = _file_corners(by_id[right["id"]], dx, dy).mean(axis=0).astype(float)
    p0, p1 = left["center"].astype(float), right["center"].astype(float)
    file_delta, image_delta = f1 - f0, p1 - p0
    file_span, image_span = np.linalg.norm(file_delta), np.linalg.norm(image_delta)
    if file_span < 1 or image_span < 3 * max(left["size"], right["size"]):
        return None
    rough = _fit([left, right], by_id, dx, dy)
    if rough is None:
        return None
    try:
        rough_to_image = np.linalg.inv(rough)
    except np.linalg.LinAlgError:
        return None
    reflected = bool(np.linalg.det(rough_to_image[:2, :2]) < 0)
    unit_f = file_delta / file_span
    unit_f_perp = np.array([-unit_f[1], unit_f[0]])
    unit_p = image_delta / image_span
    unit_p_perp = np.array([-unit_p[1], unit_p[0]])
    file_basis = np.column_stack((unit_f, unit_f_perp))
    image_basis = np.column_stack((unit_p, -unit_p_perp if reflected else unit_p_perp))
    linear = image_span / file_span * image_basis @ file_basis.T
    mm_to_image = np.vstack((np.column_stack((linear, p0 - linear @ f0)), [0., 0., 1.]))
    try:
        image_to_mm = np.linalg.inv(mm_to_image)
    except np.linalg.LinAlgError:
        return None
    residual = _residual(image_to_mm, [left, right], by_id, dx, dy)
    return image_to_mm, residual, reflected


def _refine_pair_with_qr(img_bgr: np.ndarray, markers: dict, left: dict, right: dict,
                         by_id: dict, dx: float, dy: float, image_to_mm: np.ndarray,
                         expected_identifier: str) -> np.ndarray | None:
    """Use the real QR centre to correct shear and unequal horizontal/vertical scale.

    Two marker centres fix one axis exactly, but a photograph need not be a
    similarity transform. The independently decoded QR supplies the third,
    well-spaced point needed for an affine fit in the original file millimetres.
    """
    qr = markers.get("qr") or {}
    rects = qr.get("rects") or []
    if not rects:
        return None
    x0 = min(rect["x"] for rect in rects) + dx
    x1 = max(rect["x"] + rect["width"] for rect in rects) + dx
    y0 = min(rect["y"] for rect in rects) + dy
    y1 = max(rect["y"] + rect["height"] for rect in rects) + dy
    file_qr_center = np.float32([(x0 + x1) / 2, (y0 + y1) / 2])
    predicted = cv2.perspectiveTransform(
        np.float32([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]),
        np.linalg.inv(image_to_mm))[0]
    side = float(max(np.ptp(predicted[:, 0]), np.ptp(predicted[:, 1])))
    pad = max(30, int(side * .65))
    height, width = img_bgr.shape[:2]
    cx0 = max(0, int(np.floor(predicted[:, 0].min())) - pad)
    cy0 = max(0, int(np.floor(predicted[:, 1].min())) - pad)
    cx1 = min(width, int(np.ceil(predicted[:, 0].max())) + pad)
    cy1 = min(height, int(np.ceil(predicted[:, 1].max())) + pad)
    if cx1 - cx0 < 30 or cy1 - cy0 < 30:
        return None
    from . import photo

    decoded, points = photo.decode_identifier(img_bgr[cy0:cy1, cx0:cx1])
    if decoded != expected_identifier or points is None:
        return None
    qr_points = points + np.float32([cx0, cy0])
    qr_center = qr_points.mean(axis=0)
    if np.linalg.norm(qr_center - predicted.mean(axis=0)) > side * .65:
        return None
    file_points = np.float32([
        _file_corners(by_id[item["id"]], dx, dy).mean(axis=0)
        for item in (left, right)
    ] + [file_qr_center])
    image_points = np.float32([left["center"], right["center"], qr_center])
    if abs(cv2.contourArea(file_points)) < 1 or abs(cv2.contourArea(image_points)) < 10:
        return None
    mm_to_image = np.vstack([cv2.getAffineTransform(file_points, image_points), [0., 0., 1.]])
    old_linear = np.linalg.inv(image_to_mm)[:2, :2]
    relative = mm_to_image[:2, :2] @ np.linalg.inv(old_linear)
    if np.linalg.det(relative) <= 0 or np.linalg.norm(relative - np.eye(2), ord=2) > .18:
        return None
    # A decoded QR can belong to an earlier job on the same sheet. Its four
    # physical corners must also fit the file's QR square after refinement.
    projected = cv2.perspectiveTransform(
        np.float32([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]), mm_to_image)[0]
    corner_error = min(max(np.linalg.norm(projected - qr_points[list(order)], axis=1))
                       for order in permutations(range(4)))
    if corner_error > max(6., side * .12):
        return None
    return np.linalg.inv(mm_to_image)


def _qr_verified_pair(img_bgr: np.ndarray, markers: dict, by_id: dict, candidates: list[dict],
                      dx: float, dy: float, expected_identifier: str,
                      layers: list | None = None) -> Registration | None:
    """Recover a plate from two strong marks only when its engraved QR agrees."""
    from . import photo

    ext = markers["extent"]
    area = (ext["min_x"] + dx, ext["min_y"] + dy,
            ext["max_x"] - ext["min_x"], ext["max_y"] - ext["min_y"])
    strong = [item for item in candidates if item["score"] >= .7]
    proposals = []
    for left, right in combinations(strong, 2):
        if left["id"] == right["id"] or left["orientation"] != right["orientation"]:
            continue
        if max(left["size"], right["size"]) / min(left["size"], right["size"]) > 1.25:
            continue
        fitted = _two_marker_similarity(left, right, by_id, dx, dy)
        if fitted is None:
            continue
        h, residual, reflected = fitted
        if residual > .2 * np.median([left["size"], right["size"]]):
            continue
        proposals.append((left["score"] + right["score"] - residual / 100, h, residual, reflected, left, right))
    for _, h, residual, reflected, left, right in sorted(proposals, key=lambda item: -item[0])[:12]:
        seen = photo.read_identifier_rectified(img_bgr, h, area)
        refined = _refine_pair_with_qr(img_bgr, markers, left, right, by_id, dx, dy, h,
                                       expected_identifier)
        if seen != expected_identifier and refined is None:
            continue
        qr_offset = None
        if refined is not None:
            qr = markers["qr"]
            qr_center = np.float32([[[qr["x"] + dx + qr["size"] / 2,
                                      qr["y"] + dy + qr["size"] / 2]]])
            old_px = cv2.perspectiveTransform(qr_center, np.linalg.inv(h))[0, 0]
            new_px = cv2.perspectiveTransform(qr_center, np.linalg.inv(refined))[0, 0]
            qr_offset = tuple(round(float(value), 1) for value in new_px - old_px)
        use_refined = refined is not None
        if refined is not None and layers:
            excluded = {layer.index for layer in layers if layer.name.startswith("CLEAN-") or
                        layer.name == "Markers and labels"}
            base_vectors = match_closed_vectors(img_bgr, layers, h, excluded)
            qr_vectors = match_closed_vectors(img_bgr, layers, refined, excluded)
            if len(base_vectors) >= 12 and len(qr_vectors) >= 12:
                base_found = sum(item["status"] == "found" for item in base_vectors)
                qr_found = sum(item["status"] == "found" for item in qr_vectors)
                base_fill = sum(item["fill_contrast"] for item in base_vectors)
                qr_fill = sum(item["fill_contrast"] for item in qr_vectors)
                if max(base_found, qr_found) >= 5:
                    use_refined = (qr_found >= base_found + 2 or
                                   qr_found >= base_found and qr_fill > base_fill * 1.08)
        if use_refined:
            h = refined
            residual = _residual(h, [left, right], by_id, dx, dy)
        matches = [{"id": item["id"], "score": round(item["score"], 3),
                    "center_px": item["center"].round(1).tolist()} for item in (left, right)]
        return Registration(h, "two marker + QR", sorted(matches, key=lambda item: item["id"]),
                            round(residual, 2), reflected, qr_offset, use_refined)
    return None


def register_markers(img_bgr: np.ndarray, markers: dict, dx: float = 0., dy: float = 0.,
                     expected_identifier: str | None = None,
                     layers: list | None = None) -> Registration | None:
    """Find a consistent set of engraved markers, including faint/mirrored ones.

    Template recognition is only a proposal generator.  A candidate must
    agree with other *different IDs* at LightBurn's known positions and scale.
    This rejects old registration marks from earlier work on the same sheet.
    """
    by_id = {m["id"]: m for m in markers.get("aruco", [])}
    if len(by_id) < 3:
        return None
    candidates = _template_candidates(img_bgr, markers)
    best = None
    for orientation in {(c["orientation"]) for c in candidates}:
        group = [c for c in candidates if c["orientation"] == orientation]
        for left, right in combinations(group, 2):
            if left["id"] == right["id"] or max(left["size"], right["size"]) / min(left["size"], right["size"]) > 1.35:
                continue
            if np.linalg.norm(left["center"] - right["center"]) < 3 * max(left["size"], right["size"]):
                continue
            h = _fit([left, right], by_id, dx, dy)
            if h is None:
                continue
            try:
                mm_to_image = np.linalg.inv(h)
            except np.linalg.LinAlgError:
                continue
            selected = [left, right]
            for marker_id, marker in by_id.items():
                if marker_id in (left["id"], right["id"]):
                    continue
                p = _file_corners(marker, dx, dy).mean(axis=0).reshape(1, 1, 2)
                predicted = cv2.perspectiveTransform(p, mm_to_image)[0, 0]
                choices = [c for c in group if c["id"] == marker_id and
                           .7 < c["size"] / left["size"] < 1.4 and
                           np.linalg.norm(c["center"] - predicted) < 1.3 * c["size"]]
                if choices:
                    selected.append(max(choices, key=lambda c: c["score"] -
                                        .15 * np.linalg.norm(c["center"] - predicted) / c["size"]))
            if len(selected) < 3:
                continue
            fitted = _center_fit(selected, by_id, dx, dy)
            if fitted is None:
                continue
            refined, residual = fitted
            if residual > .35 * np.median([m["size"] for m in selected]):
                continue
            quality = (len(selected), -residual, sum(m["score"] for m in selected))
            if best is None or quality > best[0]:
                best = (quality, refined, selected, residual, orientation)
    if best is None:
        if expected_identifier:
            return _qr_verified_pair(img_bgr, markers, by_id, candidates, dx, dy,
                                     expected_identifier, layers)
        return None
    _, h, matches, residual, orientation = best
    return Registration(h, "marker templates", [
        {"id": m["id"], "score": round(m["score"], 3), "center_px": m["center"].round(1).tolist()}
        for m in sorted(matches, key=lambda m: m["id"])], round(residual, 2), orientation[0])


def _closed_file_features(layers: list) -> list[dict]:
    features = []
    for layer in layers:
        for region_no, region in enumerate(layer.regions):
            if not (getattr(region, "closed", len(region.polygon) >= 3) or
                    getattr(region, "kind", "") in ("rect", "bitmap")):
                continue
            polygon = np.asarray(region.polygon, np.float32)
            if len(polygon) < 3 or cv2.contourArea(polygon) < .15:
                continue
            area = float(cv2.contourArea(polygon))
            if region.width < .35 or region.height < .35:
                continue
            moments = cv2.moments(polygon)
            center = np.array([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]], np.float32)
            features.append({"name": f"{layer.name} #{region_no + 1}", "layer_index": getattr(layer, "index", 0),
                             "region_index": region_no, "center": center,
                             "contour": polygon.reshape(-1, 1, 2), "area": area})
    # Large, isolated details carry more reliable geometry than tiny text
    # glyphs. Limit the combinatorial search without changing their mm values.
    return sorted(features, key=lambda f: -f["area"])[:16]


def _photo_contours(img_bgr: np.ndarray) -> list[dict]:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    scale = min(1., 1600 / max(gray.shape))
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    lifted = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    edges = cv2.Canny(lifted, 45, 110)
    threshold = cv2.threshold(lifted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    found = []
    for mask in (edges, threshold):
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 40 or area > .4 * gray.size:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if min(w, h) < 7 or x < 2 or y < 2 or x + w >= gray.shape[1] - 2 or y + h >= gray.shape[0] - 2:
                continue
            moments = cv2.moments(contour)
            if moments["m00"] == 0:
                continue
            center = np.array([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]]) / scale
            if any(np.linalg.norm(center - c["center"]) < max(w, h) / scale * .12 and
                   abs(np.log(area / c["area"] / scale**2)) < .3 for c in found):
                continue
            found.append({"center": center, "area": area / scale**2,
                          "contour": contour.astype(np.float32) / scale,
                          "bbox": (x / scale, y / scale, w / scale, h / scale)})
    return sorted(found, key=lambda c: -c["area"])[:220]


def _similarity(a: np.ndarray, b: np.ndarray, u: np.ndarray, v: np.ndarray, reflected: bool) -> np.ndarray | None:
    """File mm -> image pixels from two independently identified details."""
    source = np.stack((a, b)).astype(float)
    if reflected:
        source[:, 0] *= -1
    delta = source[1] - source[0]
    target = v - u
    if np.linalg.norm(delta) < 1 or np.linalg.norm(target) < 10:
        return None
    angle = np.arctan2(target[1], target[0]) - np.arctan2(delta[1], delta[0])
    scale = np.linalg.norm(target) / np.linalg.norm(delta)
    c, s = np.cos(angle) * scale, np.sin(angle) * scale
    rot = np.array([[c, -s], [s, c]]) @ (np.diag([-1, 1]) if reflected else np.eye(2))
    offset = u - rot @ a
    return np.vstack((np.column_stack((rot, offset)), [0, 0, 1]))


def _single_detail_hypotheses(feature: dict, contour: dict):
    """One oriented contour can define scale, rotation and translation.

    All cyclic corner orders and both handednesses are proposals. Nearby
    *other* details have to verify the chosen order before it is accepted.
    """
    src = cv2.approxPolyDP(feature["contour"], .015 * cv2.arcLength(feature["contour"], True), True)
    dst = cv2.approxPolyDP(contour["contour"], .025 * cv2.arcLength(contour["contour"], True), True)
    if len(src) != len(dst) or not 3 <= len(src) <= 8:
        return
    src = src.reshape(-1, 2).astype(np.float32)
    dst = dst.reshape(-1, 2).astype(np.float32)
    for reverse in (False, True):
        ordered = dst[::-1] if reverse else dst
        for shift in range(len(src)):
            target = np.roll(ordered, shift, axis=0)
            if len(src) == 3:
                h = np.vstack((cv2.getAffineTransform(src, target), [0, 0, 1]))
            else:
                h, _ = cv2.findHomography(src, target, 0)
            if h is not None and np.isfinite(h).all():
                yield h, reverse


def _unique_shape_alignment(features: list[dict], visible: list[dict]) -> Registration | None:
    """One asymmetric polygon with 5+ corners can orient itself without fiducials."""
    proposals = []
    for feature in features:
        if len(feature["contour"]) < 5:
            continue
        ranked = sorted((cv2.matchShapes(feature["contour"], c["contour"], cv2.CONTOURS_MATCH_I1, 0), j)
                        for j, c in enumerate(visible))
        if not ranked or ranked[0][0] > .055:
            continue
        if len(ranked) > 1 and ranked[1][0] <= 2 * ranked[0][0] + .015:
            continue
        contour = visible[ranked[0][1]]
        src = cv2.approxPolyDP(feature["contour"], .015 * cv2.arcLength(feature["contour"], True), True)
        dst = cv2.approxPolyDP(contour["contour"], .025 * cv2.arcLength(contour["contour"], True), True)
        if len(src) != len(dst) or len(src) < 5:
            continue
        for h, reflected in _single_detail_hypotheses(feature, contour):
            projected = cv2.perspectiveTransform(src, h).reshape(-1, 2)
            target = dst.reshape(-1, 2)
            # Vertex order can start anywhere on either contour.
            error = min(float(np.median(np.linalg.norm(projected - np.roll(
                target[::-1] if flip else target, shift, axis=0), axis=1)))
                for flip in (False, True) for shift in range(len(target)))
            if error < 3 and np.isfinite(h).all():
                proposals.append((ranked[0][0], error, h, reflected, feature, contour))
    if not proposals:
        return None
    proposals.sort(key=lambda item: (item[0], item[1]))
    _, error, mm_to_image, _, feature, contour = proposals[0]
    reflected = bool(np.linalg.det(mm_to_image[:2, :2]) < 0)
    return Registration(np.linalg.inv(mm_to_image), "single distinctive detail", [
        {"element": feature["name"], "center_mm": feature["center"].round(3).tolist(),
         "center_px": contour["center"].round(1).tolist()}], round(error, 2), reflected)


def register_geometry(img_bgr: np.ndarray, layers: list) -> Registration | None:
    """Align unmarked work from independently recognisable closed details.

    This conservative path requires at least three non-collinear details whose
    shapes, relative sizes and positions all agree. Repeated grids or a single
    plain rectangle are ambiguous and intentionally need manual landmarks.
    """
    features = _closed_file_features(layers)
    if not features:
        return None
    visible = _photo_contours(img_bgr)
    if not visible:
        return None
    if len(features) < 3 or len(visible) < 3:
        return _unique_shape_alignment(features, visible)
    options = []
    for i, feature in enumerate(features):
        ranked = []
        for j, contour in enumerate(visible):
            score = cv2.matchShapes(feature["contour"], contour["contour"], cv2.CONTOURS_MATCH_I1, 0)
            if np.isfinite(score) and score < .28:
                ranked.append((float(score), j))
        ranked.sort()
        for score, j in ranked[:4]:
            options.append((i, j, score))
    if len(options) < 3:
        return _unique_shape_alignment(features, visible)
    file_xy = np.array([f["center"] for f in features])
    span = np.ptp(file_xy, axis=0)
    if min(span) < 1:
        return None
    best = None
    def hypotheses():
        # A distinctive triangle/polygon can start the search alone. Its
        # corners define the initial transform; nearby elements grow the map.
        for i, j, score in options:
            if score > .12:
                continue
            for h, reflected in _single_detail_hypotheses(features[i], visible[j]):
                yield h, reflected, (i,)
        # Two less distinctive contours can still initialise a similarity.
        for (i, j, _), (k, l, _) in combinations(options, 2):
            if i == k or j == l or np.linalg.norm(file_xy[i] - file_xy[k]) < .2 * max(span):
                continue
            for reflected in (False, True):
                h = _similarity(file_xy[i], file_xy[k], visible[j]["center"], visible[l]["center"], reflected)
                if h is not None:
                    yield h, reflected, (i, k)

    # Every hypothesis must grow to at least three independently matched,
    # non-collinear details. This is the verification step after one anchor.
    for transform, reflected, seeds in hypotheses():
        scale = np.sqrt(abs(np.linalg.det(transform[:2, :2])))
        if not np.isfinite(scale) or scale < .2 or scale > max(img_bgr.shape):
            continue
        try:
            tolerance = max(8., .035 * max(span) * scale)
            matches = []
            used = set()
            predicted = cv2.perspectiveTransform(file_xy[None].astype(np.float32), transform)[0]
            order = sorted(range(len(features)), key=lambda fi: min(np.linalg.norm(file_xy[fi] - file_xy[seed]) for seed in seeds))
            for fi in order:
                point = predicted[fi]
                choices = []
                for oi, oj, shape_score in options:
                    if oi != fi or oj in used:
                        continue
                    distance = np.linalg.norm(point - visible[oj]["center"])
                    area_ratio = visible[oj]["area"] / (features[fi]["area"] * scale**2)
                    if distance <= tolerance and .3 < area_ratio < 3:
                        choices.append((shape_score + distance / tolerance + abs(np.log(area_ratio)), oj, distance))
                if choices:
                    _, oj, distance = min(choices)
                    matches.append((fi, oj, distance))
                    used.add(oj)
            if len(matches) < 3:
                continue
            src = np.float32([features[fi]["center"] for fi, _, _ in matches])
            dst = np.float32([visible[oj]["center"] for _, oj, _ in matches])
            if cv2.contourArea(cv2.convexHull(src)) < .04 * span[0] * span[1]:
                continue
            affine, inliers = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=tolerance / 2)
            if affine is None or int(inliers.sum()) < 3:
                continue
            affine = np.vstack((affine, [0, 0, 1]))
            residual = float(np.median(np.linalg.norm(cv2.perspectiveTransform(src[None], affine)[0] - dst, axis=1)))
            quality = (int(inliers.sum()), -residual, -sum(d for _, _, d in matches))
            if best is None or quality > best[0]:
                best = (quality, affine, matches, residual, reflected)
        except (cv2.error, np.linalg.LinAlgError, ValueError):
            continue
    if best is None:
        return _unique_shape_alignment(features, visible)
    _, mm_to_image, matches, residual, _ = best
    reflected = bool(np.linalg.det(mm_to_image[:2, :2]) < 0)
    return Registration(np.linalg.inv(mm_to_image), "geometry", [
        {"element": features[fi]["name"], "center_mm": features[fi]["center"].round(3).tolist(),
         "center_px": visible[oj]["center"].round(1).tolist()}
        for fi, oj, _ in matches], round(residual, 2), reflected)


def suggest_element_anchors(img_bgr: np.ndarray, layers: list, limit: int = 6) -> list[dict]:
    """Best quadrilateral candidates for a human to move directly on the photo."""
    features = [feature for feature in _closed_file_features(layers)
                if len(feature["contour"]) == 4 and feature["area"] >= .5]
    visible = _photo_contours(img_bgr)
    height, width = img_bgr.shape[:2]
    ranked = []
    for feature in features:
        for contour in visible:
            # A few pixels of text or a scratch can have a mathematically
            # perfect rectangular shape but four unusably overlapping handles.
            _, _, box_w, box_h = contour["bbox"]
            if min(box_w, box_h) < .035 * min(width, height):
                continue
            approx = cv2.approxPolyDP(contour["contour"], .025 * cv2.arcLength(contour["contour"], True), True)
            if len(approx) != 4:
                continue
            score = cv2.matchShapes(feature["contour"], contour["contour"], cv2.CONTOURS_MATCH_I1, 0)
            if not np.isfinite(score) or score > .35:
                continue
            # Start the handles at the detected photo detail. The operator
            # resolves any 90-degree or mirror ambiguity while moving them.
            points = approx.reshape(4, 2).astype(float)
            center = points.mean(axis=0)
            angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
            points = points[np.argsort(angles)]
            start = int(np.argmin(points[:, 0] + points[:, 1]))
            points = np.roll(points, -start, axis=0)
            photo_points = np.column_stack((points[:, 0] / width, points[:, 1] / height))
            ranked.append({"layer_index": feature["layer_index"], "region_index": feature["region_index"],
                           "element": feature["name"], "shape_score": round(float(score), 3),
                           "corners_fraction": np.clip(photo_points, 0, 1).round(6).tolist(),
                           "center_px": contour["center"].round(1).tolist()})
    ranked.sort(key=lambda item: item["shape_score"])
    unique = []
    for suggestion in ranked:
        if any(item["layer_index"] == suggestion["layer_index"] and
               item["region_index"] == suggestion["region_index"] for item in unique):
            continue
        if any(np.linalg.norm(np.asarray(item["center_px"]) - suggestion["center_px"]) < .035 * min(width, height)
               for item in unique):
            continue
        unique.append(suggestion)
        if len(unique) == limit:
            break
    return unique


def snap_translations(img_bgr: np.ndarray, layers: list, image_to_mm: np.ndarray,
                      excluded_layer_indices: set[int] | None = None, limit: int = 24) -> list[dict]:
    """Propose photo detail centers that corroborate one rigid shift of the whole drawing.

    A generic rectangle is not a unique landmark: its shift needs agreement from
    another independent vector. This is only a UI magnet, never an automatic
    measurement or a change to LightBurn's millimetre geometry.
    """
    features = _closed_file_features([l for l in layers if l.index not in (excluded_layer_indices or set())])
    visible = _photo_contours(img_bgr)
    if not features or not visible:
        return []
    mm_to_image = np.linalg.inv(np.asarray(image_to_mm, float))
    proposals = []
    for fi, feature in enumerate(features):
        points = cv2.perspectiveTransform(feature["contour"].astype(np.float32).reshape(1, -1, 2), mm_to_image)[0]
        if not np.isfinite(points).all():
            continue
        area = abs(cv2.contourArea(points))
        if area < 100:
            continue
        center = points.mean(axis=0)
        for contour in visible:
            ratio = contour["area"] / area
            if not .55 <= ratio <= 1.8:
                continue
            shape = cv2.matchShapes(points, contour["contour"], cv2.CONTOURS_MATCH_I1, 0)
            if not np.isfinite(shape) or shape > .18:
                continue
            shift = contour["center"] - center
            if np.any(np.abs(shift) > .55 * np.asarray(img_bgr.shape[1::-1])):
                continue
            proposals.append((fi, shift, float(shape + .08 * abs(np.log(ratio))), feature))
    ranked = []
    for fi, shift, score, feature in proposals:
        support = {other_fi for other_fi, other_shift, _, _ in proposals
                   if np.linalg.norm(other_shift - shift) <= max(12, .007 * min(img_bgr.shape[:2]))}
        corners = len(cv2.approxPolyDP(feature["contour"], .02 * cv2.arcLength(feature["contour"], True), True))
        if len(support) < 2 and not (corners >= 5 and score < .05):
            continue
        ranked.append((-len(support), score, float(np.linalg.norm(shift)), feature["name"], shift))
    ranked.sort(key=lambda item: item[:3])
    unique = []
    for neg_support, score, _, name, shift in ranked:
        if any(np.linalg.norm(np.asarray(item["shift_px"]) - shift) < 10 for item in unique):
            continue
        unique.append({"element": name, "shift_px": np.round(shift, 1).tolist(),
                       "support_count": -neg_support, "shape_score": round(score, 3)})
        if len(unique) >= limit:
            break
    return unique
