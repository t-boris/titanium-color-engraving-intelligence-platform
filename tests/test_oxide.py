"""The thin-film model of the oxide colour (research step 1)."""
import numpy as np

from titanium_platform import oxide


def test_bare_titanium_is_light_and_neutral_and_a_thin_film_turns_gold_then_blue():
    n1 = oxide.film_index()
    bare = oxide.spectrum_to_lab(oxide.reflectance(0, n1))
    gold = oxide.spectrum_to_lab(oxide.reflectance(25, n1))
    blue = oxide.spectrum_to_lab(oxide.reflectance(65, n1))
    assert 70 < bare[0] < 90 and abs(bare[1]) < 4 and abs(bare[2]) < 6
    assert gold[2] > 20 and gold[1] > -5                       # yellow: positive b*
    assert blue[2] < -15                                       # blue: negative b*


def test_the_spiral_is_continuous_and_returns_near_its_start_colours_at_higher_orders():
    thicknesses, spectra = oxide.film_curve(oxide.Params(), step_nm=2)
    labs = oxide.mixture_lab(spectra, 1.0, 0.0)
    steps = np.linalg.norm(np.diff(labs, axis=0), axis=1)
    assert steps.max() < 25                                    # the steepest stretch (gold -> purple near 32 nm) moves 20 dE per 2 nm
    hue = np.degrees(np.arctan2(labs[:, 2], labs[:, 1]))
    assert np.ptp(hue[(thicknesses > 10) & (thicknesses < 120)]) > 180    # the first order runs through most hues


def test_a_colour_made_by_the_model_is_fitted_back_to_its_thickness_and_dark_share():
    params = oxide.Params(scale=1.0, absorption=0.05, gloss=0.7, angle=20.0)
    table = oxide._table(params)
    thicknesses, spectra = oxide.film_curve(params)
    for d, f in ((30.0, 0.0), (70.0, 0.2), (110.0, 0.0)):
        lab = oxide.mixture_lab(spectra[[int(d / oxide.THICKNESS_STEP_NM)]], params.gloss, f)[0]
        fit = oxide.fit_point(lab + np.array([0.5, -0.3, 0.4]), table)
        assert abs(fit["thickness_nm"] - d) <= 4, (d, fit)
        assert abs(fit["dark_share"] - f) <= 0.1
        assert fit["residual_de"] < 1.5


def test_a_dark_neutral_colour_needs_the_dark_oxide_not_the_film():
    table = oxide._table(oxide.Params(gloss=0.7))
    fit = oxide.fit_point([36.0, -1.5, 2.5], table)
    assert fit["dark_share"] >= 0.5 and fit["residual_de"] < 6


def test_the_global_fit_recovers_the_parameters_from_synthetic_observations():
    truth = oxide.Params(scale=1.0, absorption=0.0, gloss=0.7, angle=20.0)
    thicknesses, spectra = oxide.film_curve(truth)
    rng = np.random.default_rng(1)
    picks = rng.choice(np.arange(10, 150, 5), 20, replace=False)
    labs = np.array([oxide.mixture_lab(spectra[[int(d / oxide.THICKNESS_STEP_NM)]], truth.gloss, 0.0)[0] for d in picks])
    labs += rng.normal(0, 0.6, labs.shape)
    coloured = np.hypot(labs[:, 1], labs[:, 2]) >= oxide.COLOURED_CHROMA
    params, fits, _ = oxide.fit_global(labs, coloured)
    assert params.gloss == truth.gloss and params.angle == truth.angle and params.scale == truth.scale
    assert np.median([f["residual_de"] for f in fits]) < 2.0
    assert np.median(np.abs(np.array([f["thickness_nm"] for f in fits]) - picks)) <= 4


def test_a_power_law_is_recovered_and_a_short_series_gives_none():
    x = np.array([50.0, 100.0, 200.0, 400.0, 800.0])
    law = oxide._power_law(x, 3.0 * x ** 0.5)
    assert abs(law["a"] - 3.0) < 0.05 and abs(law["b"] - 0.5) < 0.01 and law["r2"] > 0.999 and law["n"] == 5
    assert oxide._power_law(np.array([1.0, 2.0]), np.array([1.0, 2.0])) is None


def test_kinetics_without_calibrated_observations_says_what_is_missing(tmp_path):
    from titanium_platform.db import Store
    store = Store(tmp_path)
    result = oxide.kinetics(store, (1, None))
    assert result["summary"]["observations"] == 0 and result["summary"]["regimes"] == [] and result["summary"]["usable_regimes"] == 0
    assert "monotone dose ramp" in result["summary"]["note"]
    store.close()


def test_settings_for_a_colour_name_the_film_and_say_when_no_film_gives_it(tmp_path):
    from titanium_platform.db import Store
    store = Store(tmp_path)
    params = oxide.Params()                                                # an empty store keeps the default parameters
    _, spectra = oxide.film_curve(params)
    target = oxide.mixture_lab(spectra[[int(20 / oxide.THICKNESS_STEP_NM)]], params.gloss, 0.0)[0]     # the model's own 20 nm film
    gold = oxide.settings_for_colour(store, [float(v) for v in target])
    assert gold["reachable_by_a_film"] and any(c["thickness_nm"] <= 40 for c in gold["candidates"])
    assert gold["kinetics"]["usable"] is False and gold["candidates"][0]["same_film_measured"] == []
    assert gold["candidates"][0]["by_regime"] == [] and gold["partition"] is None
    assert gold["kinetics"]["note"].startswith("choose a laser and lens")         # no setting is computed across lasers and lenses
    green = oxide.settings_for_colour(store, [50.0, -70.0, 60.0])        # a saturated green no titanium oxide gives
    assert not green["reachable_by_a_film"]
    store.close()


# -- dose ramps and the kinetics of each pulse regime ------------------------------------------------------------------
def test_the_monotone_path_takes_the_order_the_whole_ramp_supports_not_each_points_best():
    cost = np.array([[5, 0, 5, 5, 5, 5],
                     [5, 5, 0.5, 5, 0.0, 5],          # alone, this point would take the higher order (4)
                     [5, 5, 0.0, 5, 5, 5]], float)
    assert oxide._monotone_path(cost) == [1, 2, 2]


def ramp_points(truth, pair_id=1, regime=(330.0, 4.0), seed=3):
    params = oxide.Params()
    table = oxide._table(params)
    _, spectra = oxide.film_curve(params)
    rng = np.random.default_rng(seed)
    points = []
    for k, d in enumerate(truth):
        lab = oxide.mixture_lab(spectra[[int(d / oxide.THICKNESS_STEP_NM)]], params.gloss, 0.0)[0] + rng.normal(0, 1.0, 3)
        fit = oxide.fit_point(lab, table)
        points.append({"pair_id": pair_id, "device_id": 1, "lens_id": None, "parameters": {"frequency": regime[0], "pulse_width": regime[1]},
                       "dose": {"areal_energy_j_cm2": 40.0 * 1.3 ** k}, "lab": lab.tolist(),
                       "coloured": bool(np.hypot(lab[1], lab[2]) >= oxide.COLOURED_CHROMA), "thickness_nm": fit["thickness_nm"],
                       "dark_share": fit["dark_share"], "residual_de": fit["residual_de"], "alternative": fit["alternative"],
                       "thickness_determined": bool(fit["dark_share"] < oxide.UNDETERMINED_DARK_SHARE and fit["alternative"] is None)})
    return points, table


def test_a_ramp_of_model_colours_is_placed_in_dose_order_and_a_short_series_is_left_alone():
    truth = [12, 18, 24, 30, 36, 44, 52, 60, 70, 96, 110, 126, 140]
    points, table = ramp_points(truth)
    short, _ = ramp_points([20, 40], pair_id=2)
    placed = oxide.assign_ramps(points + short, table)
    ramp = [p for p in points if p.get("ramp")]
    assert placed == len(ramp) >= 11 and not any(p.get("ramp") for p in short)
    thicknesses = [p["thickness_nm"] for p in sorted(ramp, key=lambda p: p["dose"]["areal_energy_j_cm2"])]
    assert thicknesses == sorted(thicknesses)
    assert all(abs(p["thickness_nm"] - d) <= 4 for p, d in zip(points, truth) if p.get("ramp"))
    assert all(p["alternative"] is None and p["thickness_determined"] and "free_fit" in p for p in ramp)


def test_each_pulse_regime_gets_its_own_law_and_a_scattered_regime_none():
    rng = np.random.default_rng(5)
    points = []
    for regime, a, b in (((330.0, 4.0), 3.0, 0.5), ((1950.0, 2.0), 0.8, 0.8)):
        for e in np.geomspace(50, 800, 10):
            points.append({"pair_id": 1, "parameters": {"frequency": regime[0], "pulse_width": regime[1]}, "dose": {"areal_energy_j_cm2": float(e)},
                           "coloured": True, "thickness_determined": True, "thickness_nm": float(a * e ** b * rng.uniform(0.97, 1.03))})
    for e in np.geomspace(50, 800, 10):
        points.append({"pair_id": 2, "parameters": {"frequency": 60.0, "pulse_width": 250.0}, "dose": {"areal_energy_j_cm2": float(e)},
                       "coloured": True, "thickness_determined": True, "thickness_nm": float(rng.uniform(10, 300))})
    laws = {(r["frequency"], r["pulse_width"]): r for r in oxide.regime_laws(points)}
    assert laws[(330.0, 4.0)]["usable"] and abs(laws[(330.0, 4.0)]["law"]["b"] - 0.5) < 0.03
    assert laws[(1950.0, 2.0)]["usable"] and abs(laws[(1950.0, 2.0)]["law"]["b"] - 0.8) < 0.03
    assert not laws[(60.0, 250.0)]["usable"]
    assert "for each pulse regime" in oxide._kinetics_note(list(laws.values()))


def test_settings_computed_from_a_law_name_the_laser_and_lens_whose_measurements_gave_it(store):
    """DEC-042/063: a law and the power that reaches its dose belong to one laser and lens; the dose is computed on them."""
    import obs
    w = obs.setup(store)
    points = []
    for e in np.geomspace(50, 800, 10):
        points.append({"pair_id": 1, "work": "ramp", "layer": "C01", "lab": [50, 0, 0], "device_id": 999, "lens_id": None,
                       "parameters": {"frequency": 40.0, "pulse_width": 200.0, "speed": 900.0, "line_interval": 0.025, "passes": 1,
                                      "power": 20.0},
                       "dose": {"areal_energy_j_cm2": float(e)}, "coloured": True, "thickness_determined": True,
                       "thickness_nm": float(3.0 * e ** 0.5)})
    regimes = oxide.regime_laws(points)
    (entry,) = oxide._by_regime(store, regimes, points, 30.0, w["setup"], oxide._table(oxide.Params()))   # 100 J/cm2: reachable on this laser
    assert (entry["device_id"], entry["lens_id"]) == w["setup"] and entry["settings"]["power"] is not None   # computed on this laser


# -- REQ-002: a setting computed from a law carries its three estimates and never leaves the measured doses ----------------------
def ramp(table, a=3.0, b=0.5, doses=np.geomspace(50, 800, 10), noise=0.0, pair_id=1, seed=0):
    """Cells of one pulse regime whose film follows d = a E^b and whose colour is the model's colour of that film."""
    thicknesses, shares, labs = table
    rng = np.random.default_rng(seed)
    out = []
    for e in doses:
        d = a * e ** b
        lab = labs[0, int(np.argmin(np.abs(thicknesses - d)))] + rng.normal(0, noise, 3)
        out.append({"pair_id": pair_id, "engraving_id": f"e{pair_id}", "work": "ramp", "layer": "C01", "lab": [float(v) for v in lab],
                    "parameters": {"frequency": 40.0, "pulse_width": 200.0, "speed": 900.0, "line_interval": 0.025, "passes": 1, "power": 20.0},
                    "dose": {"areal_energy_j_cm2": float(e)}, "coloured": True, "thickness_determined": True, "dark_share": 0.0,
                    "thickness_nm": float(d * rng.uniform(0.98, 1.02))})
    return out


def test_a_setting_computed_from_a_law_carries_confidence_expected_colour_error_and_stability(store):
    import obs
    w = obs.setup(store)
    table = oxide._table(oxide.Params())
    points = ramp(table, noise=1.0)
    regimes = oxide.regime_laws(points)
    (entry,) = oxide._by_regime(store, regimes, points, 30.0, w["setup"], table)
    e = entry["estimates"]
    assert entry["settings"] is not None and entry["note"] is None
    law = regimes[0]["law"]
    assert e["confidence"] == round(law["r2"] * 1 / 3, 3) and e["engravings"] == 1         # one plate: never above a third (DEC-029)
    assert 0 < e["expected_delta_e"] < 6 and e["stability"]["assessed"] and e["stability"]["cells"] == oxide.NEAREST_CELLS
    assert e["stability"]["variance"] > 0
    two = oxide.regime_laws(points + ramp(table, noise=1.0, pair_id=2, seed=1))
    (again,) = oxide._by_regime(store, two, points + ramp(table, noise=1.0, pair_id=2, seed=1), 30.0, w["setup"], table)
    assert again["estimates"]["engravings"] == 2 and again["estimates"]["confidence"] > e["confidence"] * 1.4   # 2/4 against 1/3


def test_no_dose_beyond_the_measured_doses_of_a_regime_is_computed(store):
    """The law reaches 30 nm at 100 J/cm2; the measured cells span 50-800. A film that needs 1100 J/cm2 is not extrapolated."""
    import obs
    w = obs.setup(store)
    table = oxide._table(oxide.Params())
    points = ramp(table)
    regimes = oxide.regime_laws(points)
    high = regimes[0]["determined_dose_range"][1]
    beyond = 3.0 * (1.37 * high) ** 0.5                         # within the old allowance of twice the span, now refused
    assert oxide._by_regime(store, regimes, points, beyond, w["setup"], table) == []
    assert oxide._by_regime(store, regimes, points, 3.0 * 40 ** 0.5, w["setup"], table) == []          # below the lowest dose


def test_without_all_three_estimates_no_setting_is_offered_and_the_entry_says_why(store):
    import obs
    w = obs.setup(store)
    table = oxide._table(oxide.Params())
    points = ramp(table)
    regimes = oxide.regime_laws(points)
    regimes[0]["law"] = dict(regimes[0]["law"], r2=None)
    (entry,) = oxide._by_regime(store, regimes, points, 30.0, w["setup"], table)
    assert entry["settings"] is None and entry["estimates"] is None
    assert entry["note"] == "the law of this pulse regime has no r2: the confidence of a computed setting is not known"
    assert entry["nearest_measured"]["parameters"]["power"] == 20.0                  # the measured setting is still shown
    estimates, note = oxide._estimates(regimes[0]["law"] | {"r2": 0.9}, points[:1], 100.0, table)
    assert estimates is None and note.startswith("fewer than two measured cells near this dose")


def test_the_power_for_a_dose_is_found_and_none_when_no_power_reaches_it():
    assert oxide._power_for_dose(lambda power: 4.0 * power, 150.0) == 37.5
    assert oxide._power_for_dose(lambda power: 4.0 * power, 500.0) is None
    assert oxide._power_for_dose(lambda power: None, 10.0) is None


def test_only_model_eligible_observations_are_fitted_and_a_laser_and_lens_keep_their_own_fit(store):
    """The film fit takes chart-corrected, model-eligible observations; asked for one laser and lens it uses theirs alone."""
    import obs
    w = obs.setup(store)
    device_id, lens_id = w["setup"]
    evidence = {"role": "test feature", "color_measurement": {"mode": "reference_chart_corrected"}}
    for k in range(8):
        for lens, eligible in ((lens_id, 1), (None, 1), (lens_id, 0)):
            obs.add(store, w, (40 + k, 5, 10 + k), power=10 + k, lens_id=lens, model_eligible=eligible, evidence=evidence)
    everything = oxide.calibrated_observations(store)
    assert len(everything) == 16 and {store.one("SELECT model_eligible FROM observation WHERE id=?", (o["observation_id"],))[0] for o in everything} == {1}
    known = oxide.calibrated_observations(store, (device_id, lens_id))
    assert len(known) == 8 and {(o["device_id"], o["lens_id"]) for o in known} == {(device_id, lens_id)}
    oxide.report(store, partition=(device_id, None))
    assert store.get_setting(f"oxide_model:laser:{device_id}/lens:unknown")["stamp"]["count"] == 8
    assert store.get_setting("oxide_model") is None                  # the partition's fit is kept apart from the general one
