"""The colour of laser-oxidised titanium as a thin oxide film on metal (research step 1, 2026-10-18).

There is no pigment: a transparent titanium-oxide film of thickness d on the metal reflects light from its two faces, the
two waves interfere, and the spectrum that comes back depends on d. This module computes that spectrum (Fresnel
equations for air / film / titanium at the capture angle), turns it into Lab under D65 for the CIE 1931 2 degree
observer, and fits the model to the measured colours:

* a global set of parameters shared by every observation of a setup: the film's refractive-index scale, the film's
  absorption, a gloss factor (a rough, scattering surface returns a fraction of the specular reflectance) and the
  angle of incidence of the photograph's light;
* per observation: the film thickness d and the share f of *dark oxide* (the absorbing, rough oxide of the "black"
  regimes, which a transparent film cannot explain), found on a grid; and whether another interference order fits
  nearly as well (the thickness-to-colour curve is a spiral, and a colour can lie near it twice).

What is known and what is assumed:
* colour matching functions and D65 are the standard CIE tables, 400-700 nm in 10 nm steps (the ends of the visible
  range carry very little weight);
* the optical constants of titanium are smoothed published values (Johnson and Christy 1974, Palik) and the film's
  index is a Cauchy law typical of anatase / amorphous TiO2 (n about 2.3-2.5); neither has been measured on the
  operator's metal, which is why the index scale and the absorption are fitted;
* the reflectance of the dark oxide is taken flat and small (``DARK_REFLECTANCE``);
* the model says nothing about how d depends on the laser settings; that is the kinetics step.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from . import color
from .db import Store, now

WAVELENGTHS = np.arange(400, 701, 10)
# CIE 1931 2 degree colour matching functions, 400..700 nm step 10
XBAR = np.array([0.0143, 0.0435, 0.1344, 0.2839, 0.3483, 0.3362, 0.2908, 0.1954, 0.0956, 0.0320, 0.0049, 0.0093, 0.0633,
                 0.1655, 0.2904, 0.4334, 0.5945, 0.7621, 0.9163, 1.0263, 1.0622, 1.0026, 0.8544, 0.6424, 0.4479, 0.2835,
                 0.1649, 0.0874, 0.0468, 0.0227, 0.0114])
YBAR = np.array([0.0004, 0.0012, 0.0040, 0.0116, 0.0230, 0.0380, 0.0600, 0.0910, 0.1390, 0.2080, 0.3230, 0.5030, 0.7100,
                 0.8620, 0.9540, 0.9950, 0.9950, 0.9520, 0.8700, 0.7570, 0.6310, 0.5030, 0.3810, 0.2650, 0.1750, 0.1070,
                 0.0610, 0.0320, 0.0170, 0.0082, 0.0041])
ZBAR = np.array([0.0679, 0.2074, 0.6456, 1.3856, 1.7471, 1.7721, 1.6692, 1.2876, 0.8130, 0.4652, 0.2720, 0.1582, 0.0782,
                 0.0422, 0.0203, 0.0087, 0.0039, 0.0021, 0.0017, 0.0011, 0.0008, 0.0003, 0.0002, 0.0000, 0.0000, 0.0000,
                 0.0000, 0.0000, 0.0000, 0.0000, 0.0000])
# CIE standard illuminant D65, relative spectral power, 400..700 nm step 10
D65 = np.array([82.75, 91.49, 93.43, 86.68, 104.86, 117.01, 117.81, 114.86, 115.92, 108.81, 109.35, 107.80, 104.79, 107.69,
                104.41, 104.05, 100.00, 96.33, 95.79, 88.69, 90.01, 89.60, 87.70, 83.29, 83.70, 80.03, 80.21, 82.28, 78.28,
                69.72, 71.61])
# titanium, smoothed published values (n, k) at 400..700 nm
_TI_WL = np.array([400, 450, 500, 550, 600, 650, 700])
TI_N = np.interp(WAVELENGTHS, _TI_WL, [1.86, 1.98, 2.10, 2.24, 2.36, 2.47, 2.55])
TI_K = np.interp(WAVELENGTHS, _TI_WL, [2.56, 2.75, 2.90, 3.00, 3.10, 3.20, 3.30])
CAUCHY_A, CAUCHY_B = 2.25, 0.045          # n(lambda) = A + B / lambda^2, lambda in micrometres: about 2.5 at 400 nm, 2.34 at 700 nm
DARK_REFLECTANCE = 0.04                   # flat reflectance of the absorbing dark oxide
MAX_THICKNESS_NM = 400
THICKNESS_STEP_NM = 2
DARK_SHARES = np.round(np.arange(0.0, 0.91, 0.1), 2)
COLOURED_CHROMA = 8.0                     # observations with less chroma are "dark / neutral": the film alone cannot make them
ORDER_SEPARATION_NM = 40                  # two thickness candidates farther apart than this belong to different orders
AMBIGUITY_DE = 3.0                        # ... and are both reported when their residuals differ by less than this
UNDETERMINED_DARK_SHARE = 0.6             # from this share of dark oxide on, the film thickness is not determined by the colour

# the global parameter grid of the fit
SCALES = (0.92, 1.0, 1.08)
ABSORPTIONS = (0.0, 0.05, 0.1)
GLOSSES = (0.4, 0.55, 0.7, 0.85, 1.0)
ANGLES = (0.0, 20.0, 40.0)

SETTING_KEY = "oxide_model"


@dataclass
class Params:
    scale: float = 1.0
    absorption: float = 0.0
    gloss: float = 0.7
    angle: float = 0.0

    def as_dict(self) -> dict:
        return {"scale": self.scale, "absorption": self.absorption, "gloss": self.gloss, "angle": self.angle}


# -- optics ----------------------------------------------------------------------------------------------------
def film_index(scale: float = 1.0, absorption: float = 0.0) -> np.ndarray:
    lam = WAVELENGTHS / 1000.0
    return scale * (CAUCHY_A + CAUCHY_B / lam ** 2) + 1j * absorption


def reflectance(thickness_nm: float, n_film: np.ndarray, angle_deg: float = 0.0) -> np.ndarray:
    """Spectral reflectance of air / film / titanium, s and p polarisations averaged."""
    n0, n1, n2 = 1.0, n_film, TI_N + 1j * TI_K
    s0 = np.sin(np.deg2rad(angle_deg))
    c0 = np.cos(np.deg2rad(angle_deg))
    c1 = np.sqrt(1 - (n0 * s0 / n1) ** 2 + 0j)
    c2 = np.sqrt(1 - (n0 * s0 / n2) ** 2 + 0j)
    beta = 2 * np.pi * n1 * thickness_nm * c1 / WAVELENGTHS
    phase = np.exp(2j * beta)
    total = np.zeros(len(WAVELENGTHS))
    for pol in ("s", "p"):
        if pol == "s":
            r01 = (n0 * c0 - n1 * c1) / (n0 * c0 + n1 * c1)
            r12 = (n1 * c1 - n2 * c2) / (n1 * c1 + n2 * c2)
        else:
            r01 = (n1 * c0 - n0 * c1) / (n1 * c0 + n0 * c1)
            r12 = (n2 * c1 - n1 * c2) / (n2 * c1 + n1 * c2)
        r = (r01 + r12 * phase) / (1 + r01 * r12 * phase)
        total = total + np.abs(r) ** 2 / 2
    return total


_K_NORM = 100.0 / float(np.sum(D65 * YBAR))
_WHITE = np.array([float(np.sum(D65 * c)) * _K_NORM for c in (XBAR, YBAR, ZBAR)])


def spectrum_to_lab(reflectance_spectrum: np.ndarray) -> np.ndarray:
    xyz = np.array([float(np.sum(D65 * reflectance_spectrum * c)) * _K_NORM for c in (XBAR, YBAR, ZBAR)]) / _WHITE
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def film_curve(params: Params, step_nm: float = THICKNESS_STEP_NM, max_nm: float = MAX_THICKNESS_NM) -> tuple[np.ndarray, np.ndarray]:
    """Lab of the pure film (no dark oxide) at every thickness: the spiral the coloured regimes follow."""
    n1 = film_index(params.scale, params.absorption)
    thicknesses = np.arange(0, max_nm + 1e-9, step_nm)
    spectra = np.array([reflectance(d, n1, params.angle) for d in thicknesses])
    return thicknesses, spectra


def mixture_lab(spectra: np.ndarray, gloss: float, dark_share: float) -> np.ndarray:
    """Lab of every spectrum mixed with the dark oxide: R = gloss * ((1 - f) * R_film + f * R_dark)."""
    mixed = gloss * ((1 - dark_share) * spectra + dark_share * DARK_REFLECTANCE)
    return np.array([spectrum_to_lab(row) for row in mixed])


# -- the fit ------------------------------------------------------------------------------------------------------
def _table(params: Params) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    thicknesses, spectra = film_curve(params)
    labs = np.stack([mixture_lab(spectra, params.gloss, f) for f in DARK_SHARES])     # (shares, thicknesses, 3)
    return thicknesses, DARK_SHARES, labs


def fit_point(lab, table) -> dict:
    """Thickness and dark share nearest to ``lab`` on the table, plus the best candidate of any other order."""
    thicknesses, shares, labs = table
    distance = np.linalg.norm(labs - np.asarray(lab, float), axis=2)            # (shares, thicknesses)
    best_per_thickness = distance.min(axis=0)
    share_per_thickness = distance.argmin(axis=0)
    i = int(best_per_thickness.argmin())
    result = {"thickness_nm": float(thicknesses[i]), "dark_share": float(shares[share_per_thickness[i]]),
              "residual_de": float(best_per_thickness[i]), "alternative": None}
    far = np.abs(thicknesses - thicknesses[i]) > ORDER_SEPARATION_NM
    if far.any():
        j = int(np.argmin(np.where(far, best_per_thickness, np.inf)))
        if best_per_thickness[j] - best_per_thickness[i] < AMBIGUITY_DE:
            result["alternative"] = {"thickness_nm": float(thicknesses[j]), "dark_share": float(shares[share_per_thickness[j]]),
                                     "residual_de": float(best_per_thickness[j])}
    return result


def fit_global(labs: np.ndarray, coloured: np.ndarray) -> tuple[Params, list[dict], tuple]:
    """The global parameters that minimise the median residual of the coloured observations; the per-point fits."""
    best = None
    for scale in SCALES:
        for absorption in ABSORPTIONS:
            for gloss in GLOSSES:
                for angle in ANGLES:
                    params = Params(scale, absorption, gloss, angle)
                    table = _table(params)
                    fits = [fit_point(lab, table) for lab in labs]
                    residual = np.array([f["residual_de"] for f in fits])
                    score = float(np.median(residual[coloured])) if coloured.any() else float(np.median(residual))
                    if best is None or score < best[0]:
                        best = (score, params, fits, table)
    _, params, fits, table = best
    return params, fits, table


def calibrated_observations(store: Store) -> list[dict]:
    """Every accepted observation measured through a reference chart (not the clean witness, not service layers)."""
    rows = store.query(
        "SELECT o.id, o.pair_id, o.layer_index, o.profile_id, o.lab_json, o.parameters_json, o.evidence_json, p.lightburn_name, "
        "p.engraving_title FROM observation o JOIN pair p ON p.id = o.pair_id WHERE p.status = 'Accepted' AND o.layer_index >= 0 "
        "ORDER BY o.id")
    out = []
    for r in rows:
        evidence = json.loads(r["evidence_json"] or "{}")
        if (evidence.get("color_measurement") or {}).get("mode") != "reference_chart_corrected":
            continue
        if evidence.get("role") not in (None, "test feature"):
            continue
        out.append({"observation_id": r["id"], "pair_id": r["pair_id"], "layer_index": r["layer_index"], "profile_id": r["profile_id"],
                    "work": r["engraving_title"] or r["lightburn_name"].rsplit(".", 1)[0], "layer": evidence.get("layer_name"),
                    "lab": json.loads(r["lab_json"]), "parameters": json.loads(r["parameters_json"])})
    return out


def report(store: Store, refit: bool = False) -> dict:
    """The model fitted to the calibrated observations: parameters, the spiral, every observation's thickness, dark share
    and residual, and a summary. The global parameters are kept as a setting and refitted when the observations change."""
    observations = calibrated_observations(store)
    labs = np.array([o["lab"] for o in observations]) if observations else np.zeros((0, 3))
    chroma = np.hypot(labs[:, 1], labs[:, 2]) if len(labs) else np.zeros(0)
    coloured = chroma >= COLOURED_CHROMA
    stamp = {"count": len(observations), "ids": [o["observation_id"] for o in observations]}
    saved = store.get_setting(SETTING_KEY)
    if len(observations) < 6:
        params, fits, table = Params(), [], None
        note = "fewer than 6 calibrated observations: the default parameters are shown, nothing is fitted"
    elif saved and not refit and saved.get("stamp") == stamp:
        params = Params(**saved["params"])
        table = _table(params)
        fits = [fit_point(lab, table) for lab in labs]
        note = f"parameters fitted on {saved['stamp']['count']} observations on {saved['fitted_at'][:10]}"
    else:
        params, fits, table = fit_global(labs, coloured)
        store.set_setting(SETTING_KEY, {"params": params.as_dict(), "stamp": stamp, "fitted_at": now()})
        note = f"parameters fitted now on {len(observations)} observations"
    if table is None:
        table = _table(params)
    thicknesses, spectra = film_curve(params, step_nm=5.0)
    spiral = mixture_lab(spectra, params.gloss, 0.0)
    points = []
    for o, f in zip(observations, fits):
        c = float(np.hypot(o["lab"][1], o["lab"][2]))
        points.append({**o, "chroma": round(c, 1), "coloured": bool(c >= COLOURED_CHROMA), "thickness_nm": f["thickness_nm"],
                       "dark_share": f["dark_share"], "residual_de": round(f["residual_de"], 2),
                       # a colour that is mostly dark oxide says little about the film under it
                       "thickness_determined": bool(f["dark_share"] < UNDETERMINED_DARK_SHARE and f["alternative"] is None),
                       "alternative": None if f["alternative"] is None else {k: (round(v, 2) if isinstance(v, float) else v)
                                                                             for k, v in f["alternative"].items()}})
    _attach_doses(store, points)
    ordered = assign_ramps(points, table) if ORDER_BY_RAMPS else 0
    residual = np.array([p["residual_de"] for p in points]) if points else np.zeros(0)
    summary = {
        "observations": len(points), "coloured": int(coloured.sum()), "dark": int((~coloured).sum()),
        "median_de_coloured": round(float(np.median(residual[coloured])), 2) if coloured.any() else None,
        "p90_de_coloured": round(float(np.percentile(residual[coloured], 90)), 2) if coloured.any() else None,
        "median_de_dark": round(float(np.median(residual[~coloured])), 2) if (~coloured).any() else None,
        "within_5_de": round(float((residual < 5).mean()), 2) if len(residual) else None,
        "ambiguous": int(sum(p["alternative"] is not None for p in points)),
        "thickness_determined": int(sum(p["thickness_determined"] for p in points)),
        "ordered_by_ramps": ordered,
        "goal": "median residual of the coloured regimes below 5 dE",
    }
    return {"params": params.as_dict(), "note": note, "summary": summary, "points": points,
            "spiral": [{"thickness_nm": float(d), "lab": [round(float(v), 2) for v in lab]} for d, lab in zip(thicknesses, spiral)],
            "assumptions": ["titanium n, k: smoothed published values, not measured on this metal",
                            "film index: Cauchy law of anatase-like TiO2, scaled by the fitted factor",
                            "dark oxide: flat reflectance of 4 %, mixed by area with the film",
                            "angle: one angle of incidence for the whole photograph",
                            "colour matching functions and D65 at 10 nm, 400-700 nm"]}


# -- kinetics: thickness against the dose of the laser settings (research step 2) ----------------------------------
KINETICS_MIN_POINTS = 6
USABLE_R2 = 0.5                            # a law explaining less of the variance than this predicts nothing
THICKNESS_NEIGHBOURHOOD_NM = 15            # observations this close in fitted thickness made "the same film"


def dose_features(store: Store, profile_id: int, parameters: dict) -> dict | None:
    """What the settings put into the metal: areal energy (J/cm2, every pass), pulse energy, fluence, pulses per mm2,
    pulse overlap; None when the layer's settings are incomplete for this laser."""
    from . import devices, profiles as pf
    required = ("power", "frequency", "speed", "line_interval")
    if any(parameters.get(k) is None for k in required):
        return None
    profile = pf.get_profile(store, profile_id)
    device = profile.get("device")
    if not device or not device.get("passport"):
        return None
    passes = int(parameters.get("passes") or 1)
    pulse = parameters.get("pulse_width")
    try:
        if pulse is not None:
            op = devices.operating_point(device["passport"], parameters["power"], parameters["frequency"], parameters["speed"], pulse,
                                         parameters["line_interval"], passes, device.get("lens"))
            return {"areal_energy_j_cm2": op["areal_energy_j_cm2"], "pulse_energy_mj": op["pulse_energy_mj"],
                    "fluence_j_cm2": op["fluence_j_cm2"], "pulses_per_mm2": op["pulses_per_mm2"], "pulse_overlap": op["pulse_overlap"],
                    "output_power_w": op["output_power_w"], "complete": True}
        from .characterization import characterize
        ch = characterize(device["passport"], device.get("lens"))
        output = ch["effective_power_w"] * parameters["power"] / 100
        areal = output / (parameters["speed"] * parameters["line_interval"]) * 100 * passes
        return {"areal_energy_j_cm2": round(areal, 6), "pulse_energy_mj": None, "fluence_j_cm2": None, "pulses_per_mm2": None,
                "pulse_overlap": None, "output_power_w": round(output, 6), "complete": False}
    except (KeyError, ValueError, TypeError):
        return None


def _power_law(x: np.ndarray, y: np.ndarray) -> dict | None:
    """y = a * x^b fitted in log space; the residual in y's own units."""
    ok = (x > 0) & (y > 0)
    if ok.sum() < 3:
        return None
    lx, ly = np.log(x[ok]), np.log(y[ok])
    b, la = np.polyfit(lx, ly, 1)
    pred = np.exp(la + b * lx)
    ss_res = float(np.sum((ly - (la + b * lx)) ** 2)); ss_tot = float(np.sum((ly - ly.mean()) ** 2))
    return {"a": float(np.exp(la)), "b": float(b), "r2": round(1 - ss_res / ss_tot, 3) if ss_tot > 0 else None,
            "median_abs_residual": round(float(np.median(np.abs(pred - y[ok]))), 1), "n": int(ok.sum())}


def _spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 4 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    rank = lambda v: np.argsort(np.argsort(v)).astype(float)
    return round(float(np.corrcoef(rank(x), rank(y))[0, 1]), 3)


# -- dose ramps: one film order for a whole ramp (operator-approved plan, 2026-10-18) -----------------------------------
ORDER_BY_RAMPS = False                     # off (2026-10-18): on the operator's matrices the film model's first-order colours are
                                           # far darker and more saturated than the measured ones, so a ramp-wide order taken from
                                           # it skips the first order (gold, purple, blue) and the "laws" it yields are artefacts of
                                           # the monotone constraint; switch on once the model reproduces a measured ramp
RAMP_MIN_POINTS = 4                        # coloured observations of one pair at one pulse regime that make a ramp
RAMP_COST_CAP_DE = 15.0                    # a colour that fits nowhere on its ramp pulls the path no further than this
RAMP_LIGHTNESS_WEIGHT = 0.35               # on a ramp the order is read mostly from hue: lightness follows the surface's roughness
                                           # and the light it mirrors, which the model does not know
EXTRAPOLATION_FACTOR = 2.0                 # a computed dose farther than this from the measured doses is not proposed


def regime_of(parameters: dict) -> tuple[float, float] | None:
    """The pulse regime of a setting: frequency (kHz) and pulse width (ns)."""
    frequency, width = parameters.get("frequency"), parameters.get("pulse_width")
    return None if frequency is None or width is None else (float(frequency), float(width))


def _attach_doses(store: Store, points: list[dict]) -> None:
    for p in points:
        p["dose"] = dose_features(store, p["profile_id"], p["parameters"])


def _monotone_path(cost: np.ndarray) -> list[int]:
    """Column indices t_0 <= t_1 <= ... (one row per point, rows in dose order) with the least summed cost."""
    n, width = cost.shape
    acc = cost[0].copy()
    back = np.zeros((n, width), int)
    prefix_val, prefix_idx = np.empty(width), np.empty(width, int)
    for k in range(1, n):
        best_val, best_idx = np.inf, 0
        for j in range(width):
            if acc[j] < best_val:
                best_val, best_idx = acc[j], j
            prefix_val[j], prefix_idx[j] = best_val, best_idx
        acc = cost[k] + prefix_val
        back[k] = prefix_idx
    t = int(acc.argmin())
    path = [t]
    for k in range(n - 1, 0, -1):
        t = int(back[k, t])
        path.append(t)
    return path[::-1]


def assign_ramps(points: list[dict], table) -> int:
    """On a dose ramp (the coloured observations of one pair at one pulse regime with a known dose) the film can only
    grow with the areal energy, so one film order is chosen for the whole ramp: the thicknesses, never decreasing with
    the dose, whose colours fit best together. A single colour often fits two orders nearly equally (the spiral passes
    near it twice); the ramp decides. The fit along the ramp weighs lightness less than hue (``RAMP_LIGHTNESS_WEIGHT``):
    the measured surface is lighter than the model at thin films and darker at thick ones, while the sequence of hues
    is what the interference fixes. Mostly-dark colours take no part (their film is not seen). Each placed point keeps
    its own best fit as ``free_fit``; ``residual_de`` stays the plain colour difference. Returns the number placed."""
    thicknesses, shares, labs = table
    groups: dict[tuple, list[dict]] = {}
    for p in points:
        regime = regime_of(p["parameters"])
        if regime is None or p.get("dose") is None or not p["coloured"] or p["dark_share"] >= UNDETERMINED_DARK_SHARE:
            continue
        groups.setdefault((p["pair_id"], regime), []).append(p)
    placed = 0
    for (pair_id, regime), ramp in groups.items():
        doses = {round(p["dose"]["areal_energy_j_cm2"], 6) for p in ramp}
        if len(ramp) < RAMP_MIN_POINTS or len(doses) < 3:
            continue
        ramp.sort(key=lambda p: p["dose"]["areal_energy_j_cm2"])
        weight = np.array([RAMP_LIGHTNESS_WEIGHT, 1.0, 1.0])
        offsets = np.stack([labs - np.asarray(p["lab"], float) for p in ramp])                     # (n, shares, thicknesses, 3)
        weighted = np.linalg.norm(offsets * weight, axis=3)
        path = _monotone_path(np.minimum(weighted.min(axis=1), RAMP_COST_CAP_DE))
        for p, d, off, t in zip(ramp, weighted, offsets, path):
            s = int(d[:, t].argmin())
            share = float(shares[s])
            p.update(free_fit={"thickness_nm": p["thickness_nm"], "dark_share": p["dark_share"], "residual_de": p["residual_de"]},
                     thickness_nm=float(thicknesses[t]), dark_share=share, residual_de=round(float(np.linalg.norm(off[s, t])), 2),
                     hue_residual_de=round(float(d[s, t]), 2), alternative=None,
                     thickness_determined=bool(share < UNDETERMINED_DARK_SHARE),
                     ramp={"pair_id": pair_id, "frequency": regime[0], "pulse_width": regime[1], "points": len(ramp)})
            placed += 1
    return placed


def regime_laws(points: list[dict]) -> list[dict]:
    """For each pulse regime: the power law d = a * E^b on its coloured observations whose film thickness is determined."""
    groups: dict[tuple, list[dict]] = {}
    for p in points:
        regime = regime_of(p["parameters"])
        if regime is not None and p.get("dose") is not None:
            groups.setdefault(regime, []).append(p)
    out = []
    for (frequency, width), group in sorted(groups.items()):
        determined = [p for p in group if p["coloured"] and p["thickness_determined"]]
        x = np.array([p["dose"]["areal_energy_j_cm2"] for p in determined], float)
        y = np.array([p["thickness_nm"] for p in determined], float)
        law = _power_law(x, y) if len(determined) >= KINETICS_MIN_POINTS else None
        doses = [p["dose"]["areal_energy_j_cm2"] for p in group]
        out.append({"frequency": frequency, "pulse_width": width, "observations": len(group), "determined": len(determined),
                    "from_ramps": sum(1 for p in determined if p.get("ramp")), "pairs": len({p["pair_id"] for p in group}),
                    "dose_range": [round(min(doses), 1), round(max(doses), 1)],
                    "determined_dose_range": [round(float(x.min()), 1), round(float(x.max()), 1)] if len(x) else None,
                    "thickness_vs_dose_spearman": _spearman(x, y), "law": law,
                    "usable": bool(law is not None and (law.get("r2") or 0) >= USABLE_R2)})
    return out


def _kinetics_note(regimes: list[dict]) -> str:
    if not any(r["law"] for r in regimes):
        return "too few determined points for a law; photograph plates with a monotone dose ramp at one pulse regime"
    if not any(r["usable"] for r in regimes):
        return "no usable law on this set: within each pulse regime the film thicknesses do not follow the areal energy closely enough"
    return "a power law of thickness against areal energy for each pulse regime that has one, on this photograph set only"


def kinetics(store: Store) -> dict:
    """Film thickness and dark share of every calibrated observation against the dose of its settings, and for each pulse
    regime a power law d = a * E^b on the observations whose thickness is determined (on a dose ramp the film order is
    chosen for the whole ramp, ``assign_ramps``). A research result: the numbers say how far the data carry it."""
    fitted = report(store)
    points = fitted["points"]
    with_dose = [p for p in points if p.get("dose") is not None]
    regimes = regime_laws(points)
    summary = {"observations": len(points), "with_dose": len(with_dose),
               "thickness_determined": sum(1 for p in with_dose if p["thickness_determined"] and p["coloured"]),
               "ordered_by_ramps": sum(1 for p in points if p.get("ramp")), "regimes": regimes,
               "usable_regimes": sum(1 for r in regimes if r["usable"]),
               "dark_share_vs_dose_spearman": _spearman(np.array([p["dose"]["areal_energy_j_cm2"] for p in with_dose], float),
                                                       np.array([p["dark_share"] for p in with_dose], float)),
               "note": _kinetics_note(regimes)}
    ordered = sorted(with_dose, key=lambda p: p["dose"]["areal_energy_j_cm2"])
    return {"summary": summary, "params": fitted["params"],
            "points": [{"work": p["work"], "layer": p["layer"], "lab": p["lab"], "coloured": p["coloured"], "thickness_nm": p["thickness_nm"],
                        "dark_share": p["dark_share"], "residual_de": p["residual_de"], "thickness_determined": p["thickness_determined"],
                        "ramp": p.get("ramp"), "free_fit": p.get("free_fit"), "alternative": p["alternative"], "dose": p["dose"],
                        "parameters": p["parameters"]} for p in ordered]}


# -- settings for a wanted colour (research step 3) -------------------------------------------------------------
def _power_for_dose(dose_of, target: float, low: float = 1.0, high: float = 100.0) -> float | None:
    """The power (%) at which ``dose_of(power)``, increasing with the power, reaches ``target``; None when no power
    between ``low`` and ``high`` reaches it."""
    low_dose, high_dose = dose_of(low), dose_of(high)
    if low_dose is None or high_dose is None or not low_dose <= target <= high_dose:
        return None
    for _ in range(40):
        middle = (low + high) / 2
        if dose_of(middle) < target:
            low = middle
        else:
            high = middle
    return round((low + high) / 2, 1)


def _by_regime(store: Store, regimes: list[dict], points: list[dict], thickness: float) -> list[dict]:
    """For each pulse regime with a usable law: the areal energy that law gives for ``thickness``, and a setting that
    puts it in: the measured observation of the regime nearest in dose, with the power that reaches that dose."""
    out = []
    for regime in regimes:
        law = regime["law"]
        if not regime["usable"] or thickness <= 0 or law["b"] == 0:
            continue
        energy = float((thickness / law["a"]) ** (1 / law["b"]))
        low, high = regime["determined_dose_range"]
        if not low / EXTRAPOLATION_FACTOR <= energy <= high * EXTRAPOLATION_FACTOR:
            continue
        members = [p for p in points if p.get("dose") is not None and p["coloured"] and p["thickness_determined"]
                   and regime_of(p["parameters"]) == (regime["frequency"], regime["pulse_width"])]
        nearest = min(members, key=lambda p: abs(np.log(p["dose"]["areal_energy_j_cm2"] / energy)))
        base = nearest["parameters"]

        def dose_of(power, base=base, profile_id=nearest["profile_id"]):
            dose = dose_features(store, profile_id, {**base, "power": power})
            return None if dose is None else dose["areal_energy_j_cm2"]

        power = _power_for_dose(dose_of, energy)
        settings = None if power is None else {**{k: base.get(k) for k in ("frequency", "pulse_width", "speed", "line_interval", "passes")},
                                                "power": power}
        out.append({"frequency": regime["frequency"], "pulse_width": regime["pulse_width"], "areal_energy_j_cm2": round(energy, 1),
                    "within_measured": bool(low <= energy <= high), "settings": settings, "law": law,
                    "nearest_measured": {"work": nearest["work"], "layer": nearest["layer"], "lab": nearest["lab"], "pair_id": nearest["pair_id"],
                                         "thickness_nm": nearest["thickness_nm"], "parameters": base,
                                         "areal_energy_j_cm2": round(nearest["dose"]["areal_energy_j_cm2"], 1)}})
    return sorted(out, key=lambda r: (not r["within_measured"], abs(np.log(r["areal_energy_j_cm2"] / r["nearest_measured"]["areal_energy_j_cm2"]))))


def settings_for_colour(store: Store, lab: list[float]) -> dict:
    """What the film model says about a wanted colour: the film thickness (and dark share) that would give it, in every
    order that fits; which measured settings produced films of that thickness; and, for each pulse regime whose kinetics
    law is usable, the dose and a setting computed from the law. Measured settings are evidence; computed ones are
    marked so."""
    fitted = report(store)
    params = Params(**fitted["params"])
    fit = fit_point(lab, _table(params))
    candidates = [{"thickness_nm": fit["thickness_nm"], "dark_share": fit["dark_share"], "residual_de": round(fit["residual_de"], 2)}]
    if fit["alternative"] is not None:
        candidates.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in fit["alternative"].items()})
    regimes = regime_laws(fitted["points"])
    for c in candidates:
        near = [p for p in fitted["points"] if abs(p["thickness_nm"] - c["thickness_nm"]) <= THICKNESS_NEIGHBOURHOOD_NM
                and p["thickness_determined"]]
        c["same_film_measured"] = [{"work": p["work"], "layer": p["layer"], "lab": p["lab"], "thickness_nm": p["thickness_nm"],
                                    "residual_de": p["residual_de"], "parameters": p["parameters"], "pair_id": p["pair_id"],
                                    "ambiguous": p["alternative"] is not None, "from_ramp": p.get("ramp") is not None}
                                   for p in sorted(near, key=lambda q: q["residual_de"])[:8]]
        c["by_regime"] = _by_regime(store, regimes, fitted["points"], c["thickness_nm"]) if c["dark_share"] < UNDETERMINED_DARK_SHARE else []
    reachable = fit["residual_de"] <= 8.0
    usable = [r for r in regimes if r["usable"]]
    return {"target": [float(v) for v in lab], "params": fitted["params"], "candidates": candidates,
            "reachable_by_a_film": bool(reachable),
            "kinetics": {"usable": bool(usable), "regimes": len(usable), "note": _kinetics_note(regimes)},
            "note": ("the colour lies on the film spiral: a film of the thickness above gives it" if reachable else
                     "the colour lies off the film spiral by more than 8 dE: no oxide film of titanium gives it under this model")}
