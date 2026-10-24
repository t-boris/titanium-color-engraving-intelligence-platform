"""Color-space helpers: sRGB <-> linear <-> CIE Lab (D65) and the CIE76 color difference.

Assumption (DEC-026, proposed): the requirements fix neither the color space nor the ΔE formula, so
this module uses CIE Lab under D65 and ΔE*ab (CIE76).
"""
from __future__ import annotations

import numpy as np

_M_RGB_TO_XYZ = np.array(
    [[0.4124564, 0.3575761, 0.1804375],
     [0.2126729, 0.7151522, 0.0721750],
     [0.0193339, 0.1191920, 0.9503041]]
)
_M_XYZ_TO_RGB = np.linalg.inv(_M_RGB_TO_XYZ)
_WHITE_D65 = np.array([0.95047, 1.0, 1.08883])
WHITE_POINTS = {"D65": _WHITE_D65, "D50": np.array([0.96422, 1.0, 0.82521])}      # CIE 1931 2° observer
_BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def linear_rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Linear sRGB (0..1, shape (...,3)) -> Lab."""
    xyz = np.asarray(rgb, dtype=np.float64) @ _M_RGB_TO_XYZ.T / _WHITE_D65
    eps, kappa = 216 / 24389, 24389 / 27
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def _lab_to_xyz(lab: np.ndarray, white: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200
    eps, kappa = 216 / 24389, 24389 / 27
    f = np.stack([fx, fy, fz], axis=-1)
    return np.where(f ** 3 > eps, f ** 3, (116 * f - 16) / kappa) * white


def lab_to_linear_rgb(lab: np.ndarray) -> np.ndarray:
    return _lab_to_xyz(lab, _WHITE_D65) @ _M_XYZ_TO_RGB.T


def lab_under_to_linear_rgb(lab: np.ndarray, white_point: str) -> np.ndarray:
    """Lab given relative to ``white_point`` (D65 or D50, 2° observer) as linear sRGB, adapted to D65 with the Bradford
    transform (published chart values are often given for D50)."""
    xyz = _lab_to_xyz(lab, WHITE_POINTS[white_point])
    if white_point != "D65":
        gain = (_BRADFORD @ _WHITE_D65) / (_BRADFORD @ WHITE_POINTS[white_point])
        xyz = xyz @ (np.linalg.inv(_BRADFORD) @ np.diag(gain) @ _BRADFORD).T
    return xyz @ _M_XYZ_TO_RGB.T


def srgb8_to_lab(rgb8: np.ndarray) -> np.ndarray:
    return linear_rgb_to_lab(srgb_to_linear(np.asarray(rgb8, dtype=np.float64) / 255.0))


def lab_to_srgb8(lab: np.ndarray) -> np.ndarray:
    return np.round(linear_to_srgb(lab_to_linear_rgb(lab)) * 255).astype(int)


def delta_e(a, b) -> float:
    """CIE76 ΔE*ab between two Lab triples."""
    return float(np.linalg.norm(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)))


def valid_lab(lab) -> bool:
    try:
        L, a, b = (float(x) for x in lab)
    except (TypeError, ValueError):
        return False
    return all(np.isfinite([L, a, b])) and 0 <= L <= 100 and -128 <= a <= 127 and -128 <= b <= 127


AGAINST_CLEAN_ALGORITHM = "1"      # how a camera-relative colour is expressed against clean titanium; a release names it


def against_clean(lab, clean, nominal) -> list[float]:
    """The colour as it would look next to nominal clean titanium: its ratio to the clean surface of the *same* photograph, per
    channel in linear light (exposure and illuminant cancel), applied to the nominal clean titanium (DEC-056)."""
    ratio = np.clip(lab_to_linear_rgb(np.asarray(lab, float)), 0, 1) / np.maximum(lab_to_linear_rgb(np.asarray(clean, float)), 1e-4)
    shown = np.clip(lab_to_linear_rgb(np.asarray(nominal, float)) * ratio, 0, 1)
    return [float(v) for v in linear_rgb_to_lab(shown)]
