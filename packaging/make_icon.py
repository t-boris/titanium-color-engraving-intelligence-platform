"""The application icon of the desktop workshop (feature electron, REQ-080): a titanium plate on which the colours of the oxide film
spread in rings from the point the laser heats, in the order the metal shows them as it cools outward: white heat, straw, bronze,
purple, deep blue, sky blue, cyan, green, bare metal. Drawn with NumPy and OpenCV (both in the core's environment), rendered at four
times the size and downscaled for smooth edges; written as ``desktop/assets/icon-1024.png``, ``icon.icns`` (macOS, through
``iconutil``) and ``icon.ico`` (Windows, PNG-compressed entries). Run: ``.venv/bin/python packaging/make_icon.py``."""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "desktop" / "assets"
SIZE, SCALE = 1024, 4
S = SIZE * SCALE
# the oxide colours of titanium by temperature, hottest first (sRGB)
STOPS = [(0.00, (255, 253, 244)), (0.05, (252, 228, 150)), (0.12, (236, 170, 70)), (0.20, (200, 100, 60)), (0.29, (160, 60, 165)),
         (0.39, (60, 80, 215)), (0.50, (70, 150, 235)), (0.61, (90, 215, 220)), (0.72, (125, 210, 135)), (0.84, (170, 175, 160)),
         (1.00, (128, 132, 138))]


def ramp(t: np.ndarray) -> np.ndarray:
    """Colours (RGB float 0..1) for heat positions ``t`` in 0..1 along the stops."""
    out = np.zeros(t.shape + (3,), dtype=np.float32)
    for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
        mask = (t >= a) & (t <= b)
        k = ((t[mask] - a) / (b - a))[:, None]
        out[mask] = (np.array(ca) * (1 - k) + np.array(cb) * k) / 255.0
    return out


def rounded_mask(size: int, inset: int, radius: int) -> np.ndarray:
    mask = np.zeros((size, size), dtype=np.uint8)
    cv2.rectangle(mask, (inset + radius, inset), (size - inset - radius, size - inset), 255, -1)
    cv2.rectangle(mask, (inset, inset + radius), (size - inset, size - inset - radius), 255, -1)
    for cx in (inset + radius, size - inset - radius):
        for cy in (inset + radius, size - inset - radius):
            cv2.circle(mask, (cx, cy), radius, 255, -1)
    return mask


def draw() -> np.ndarray:
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    rng = np.random.default_rng(7)
    # the plate: brushed dark titanium with a soft diagonal sheen
    sheen = 0.12 * np.clip(1 - np.abs((xx + yy) / S - 0.95) * 2.2, 0, 1)
    brush = cv2.GaussianBlur(rng.normal(0, 1, (S, 1)).astype(np.float32), (1, 0), 0) if False else rng.normal(0, 1, (S, 1)).astype(np.float32)
    brush = cv2.resize(brush, (S, S), interpolation=cv2.INTER_NEAREST) * 0.018
    base = np.array([0.24, 0.255, 0.275], dtype=np.float32)
    plate = base[None, None, :] * (1 + sheen[..., None] + brush[..., None])
    # the heat rings around the point the beam touches (a little above and left of the centre)
    cx, cy = S * 0.44, S * 0.47
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (S * 0.46)
    t = np.clip(r, 0, 1)
    rings = ramp(t)
    rings = cv2.GaussianBlur(rings, (0, 0), S * 0.004)
    alpha = np.clip(1.22 - r, 0, 1) ** 1.1                         # the colours fade into bare metal at the edge of the plate
    alpha = alpha * (0.93 + 0.07 * np.cos(r * 90.0))                # faint fine rings of the scan lines
    img = plate * (1 - alpha[..., None]) + rings * alpha[..., None]
    # the beam from the top right to the point, with its glow
    beam = np.zeros((S, S), dtype=np.float32)
    cv2.line(beam, (int(S * 0.88), int(S * 0.10)), (int(cx), int(cy)), 1.0, int(S * 0.006), cv2.LINE_AA)
    glow = cv2.GaussianBlur(beam, (0, 0), S * 0.012)
    core = cv2.GaussianBlur(beam, (0, 0), S * 0.0015)
    spark = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * (S * 0.012) ** 2)))
    img += glow[..., None] * np.array([0.55, 0.15, 0.10], dtype=np.float32) + core[..., None] * np.array([1.0, 0.75, 0.65], dtype=np.float32)
    img += spark[..., None] * np.array([1.0, 0.98, 0.9], dtype=np.float32)
    img = np.clip(img, 0, 1)
    # the macOS plate: a rounded square, with a thin lighter rim
    inset, radius = int(S * 0.098), int(S * 0.182)
    mask = rounded_mask(S, inset, radius)
    rim = cv2.dilate(mask, np.ones((3, 3), np.uint8)) - cv2.erode(mask, np.ones((int(S * 0.006),) * 2, np.uint8))
    img = np.where(rim[..., None] > 0, img * 0.55 + 0.35, img)
    img = img * (mask[..., None] / 255.0)                                      # transparent pixels are black too, whatever the viewer does
    rgba = np.dstack([(img[..., ::-1] * 255).astype(np.uint8), mask])        # OpenCV writes BGRA
    return cv2.resize(rgba, (SIZE, SIZE), interpolation=cv2.INTER_AREA)


def write_ico(png_by_size: dict[int, bytes], path: Path) -> None:
    sizes = sorted(png_by_size)
    offset = 6 + 16 * len(sizes)
    head = struct.pack("<HHH", 0, 1, len(sizes))
    entries, blobs = b"", b""
    for size in sizes:
        blob = png_by_size[size]
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(blobs))
        blobs += blob
    path.write_bytes(head + entries + blobs)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = draw()
    cv2.imwrite(str(OUT / "icon-1024.png"), icon)
    pngs = {}
    for size in (16, 32, 64, 128, 256, 512, 1024):
        small = icon if size == SIZE else cv2.resize(icon, (size, size), interpolation=cv2.INTER_AREA)
        pngs[size] = cv2.imencode(".png", small)[1].tobytes()
    write_ico({s: pngs[s] for s in (16, 32, 64, 128, 256)}, OUT / "icon.ico")
    if sys.platform == "darwin" and shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as tmp:
            iconset = Path(tmp) / "icon.iconset"
            iconset.mkdir()
            for size in (16, 32, 128, 256, 512):
                (iconset / f"icon_{size}x{size}.png").write_bytes(pngs[size])
                (iconset / f"icon_{size}x{size}@2x.png").write_bytes(pngs[size * 2])
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "icon.icns")], check=True)
    print(sorted(p.name for p in OUT.iterdir()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
