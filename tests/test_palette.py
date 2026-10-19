"""The palette of a vector work and the recolouring modes (REQ-034, DEC-073, DEC-074, DEC-075)."""
import itertools

import pytest

import obs
from titanium_platform import color, engraving_time, palette, setup as su
from titanium_platform.api.app import create_app


# -- the palette of one laser, lens and titanium stock -----------------------------------------------------------------------
@pytest.fixture
def world(store):
    w = obs.setup(store)
    w["ti"] = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")["id"]
    w["other_ti"] = su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0, surface="brushed")["id"]
    return w


def partition(store, w, **extra):
    return palette.vector_palette(store, w["setup"][0], w["setup"][1], w["ti"], **extra)


def test_the_palette_holds_every_measured_fill_colour_of_its_laser_lens_and_titanium_one_entry_per_recipe(store, world):
    obs.add(store, world, [60.0, 5.0, 20.0], speed=1000, line_interval=0.01, material_id=world["ti"], engraving="e1", layer_type="Scan")
    obs.add(store, world, [62.0, 5.0, 20.0], speed=1000, line_interval=0.01, material_id=world["ti"], engraving="e2", layer_type="Scan")
    obs.add(store, world, [40.0, 10.0, -20.0], speed=2000, line_interval=0.02, material_id=world["ti"], layer_type="Scan")
    obs.add(store, world, [50.0, 0.0, 0.0], speed=1000, line_interval=0.01, material_id=world["other_ti"], layer_type="Scan")   # other stock
    obs.add(store, world, [55.0, 0.0, 0.0], speed=1000, line_interval=0.01, material_id=world["ti"], lens_id=None, layer_type="Scan")  # lens unknown
    other = obs.setup(store)                                                                                   # another laser and lens
    other["n"] = 100
    obs.add(store, other, [45.0, 0.0, 0.0], speed=1000, line_interval=0.01, material_id=world["ti"], layer_type="Scan")
    p = partition(store, world)
    assert len(p["entries"]) == 2 and p["max_colours"] == 29
    first, second = p["entries"]                                                                               # lightest first
    assert first["lab"] == pytest.approx([61.0, 5.0, 20.0]) and first["engravings"] == 2 and first["photographs"] == 2
    assert first["basis"] == "chart" and first["mode"] == "Scan" and first["task"]["kind"] == "fill"
    assert first["time_s_per_cm2"] == pytest.approx(engraving_time.per_area({"speed": 1000, "line_interval": 0.01})["s_per_cm2"])
    assert first["time"]["estimate"] is True and first["parameters"]["speed"] == 1000
    assert second["engravings"] == 1 and second["time_s_per_cm2"] < first["time_s_per_cm2"]
    assert len({e["id"] for e in p["entries"]}) == 2 and partition(store, world)["entries"][0]["id"] == first["id"]   # stable ids


def test_a_colour_repeated_on_independent_engravings_has_its_stability_confidence_and_expected_error(store, world):
    for engraving, lab in (("e1", [60.0, 5.0, 20.0]), ("e2", [62.0, 5.0, 20.0]), ("e3", [61.0, 5.0, 23.0])):
        obs.add(store, world, lab, material_id=world["ti"], engraving=engraving, layer_type="Scan")
    obs.add(store, world, [40.0, 0.0, 0.0], speed=2000, material_id=world["ti"], layer_type="Scan")
    repeated, once = partition(store, world)["entries"]
    variance = 1.0 + 0.0 + 3.0        # per-axis sample variances of the three engravings (L 1, a 0, b 3)
    assert repeated["stability"] == {"assessed": True, "variance": pytest.approx(variance), "engravings": 3,
                                     "max_deviation": pytest.approx(color.delta_e([61.0, 5.0, 23.0], [61.0, 5.0, 21.0]))}
    assert repeated["confidence"] == pytest.approx(3 / 5) and repeated["expected_delta_e"] == pytest.approx(variance ** 0.5)
    assert once["stability"]["assessed"] is False and once["confidence"] is None and once["expected_delta_e"] is None


def test_colours_measured_as_photographed_are_left_to_the_operator_unless_included():
    pal = [entry("chart", [60, 0, 0], 9.0), {**entry("as-shot", [50, 0, 0], 1.0), "basis": "as-shot"}]
    assert chosen(palette.assign(sources([50, 0, 0]), pal, "closest", tolerance_de=3)) == {0: "chart"}
    assert chosen(palette.assign(sources([50, 0, 0]), pal, "closest", tolerance_de=3, include_as_shot=True)) == {0: "as-shot"}
    assert chosen(palette.assign(sources([50, 0, 0]), pal, "fewer_layers", tolerance_de=3, keep={0: "as-shot"})) == {0: "as-shot"}
    with pytest.raises(su.ValidationError, match="measured as photographed: include such colours"):
        palette.assign(sources([50, 0, 0]), pal[1:], "random", tolerance_de=3)


def test_only_recipes_that_fill_an_area_are_colours_and_the_others_are_counted(store, world):
    ti = world["ti"]
    obs.add(store, world, [60.0, 5.0, 20.0], material_id=ti, layer_type="Scan")
    obs.add(store, world, [30.0, 5.0, 20.0], material_id=ti, layer_type="Cut", speed=500)                    # Line mode
    obs.add(store, world, [35.0, 5.0, 20.0], material_id=ti, layer_type="Image", speed=600)                  # an image layer
    obs.add(store, world, [45.0, 5.0, 20.0], material_id=ti, layer_type="Scan", speed=700, task_kind="text")  # measured as text
    p = partition(store, world)
    assert [e["mode"] for e in p["entries"]] == ["Scan"] and p["entries"][0]["task"]["kind"] == "fill"
    assert p["left_out"] == {"line": 1, "image": 1, "other_mode": 0, "task": 1, "provisional": 0, "slower": 0}


def test_the_palette_can_be_limited_to_recipes_no_slower_than_a_time_per_square_centimetre(store, world):
    obs.add(store, world, [60.0, 5.0, 20.0], speed=1000, line_interval=0.01, material_id=world["ti"], layer_type="Scan")   # ~10.3 s
    obs.add(store, world, [40.0, 5.0, 20.0], speed=4000, line_interval=0.01, material_id=world["ti"], layer_type="Scan")   # ~2.8 s
    p = partition(store, world, max_time_s_per_cm2=5)
    assert [e["parameters"]["speed"] for e in p["entries"]] == [4000] and p["left_out"]["slower"] == 1 and p["max_time_s_per_cm2"] == 5


def test_a_titanium_stock_that_does_not_exist_is_refused(store, world):
    with pytest.raises(su.ValidationError, match="titanium stock was not found"):
        palette.vector_palette(store, world["setup"][0], world["setup"][1], 999)


# -- assignment on constructed palettes ----------------------------------------------------------------------------------------
def entry(entry_id, lab, seconds):
    return {"id": entry_id, "lab": list(lab), "time_s_per_cm2": seconds}


def sources(*labs, pixels=None):
    return [{"index": i, "lab": list(lab), "pixels": (pixels or [100] * len(labs))[i]} for i, lab in enumerate(labs)]


def chosen(result):
    return {c["index"]: c["entry_id"] for c in result["colours"]}


def test_closest_takes_the_fastest_entry_within_the_tolerance_else_the_nearest():
    pal = [entry("near-slow", [50, 0, 0], 40.0), entry("close-fast", [52, 0, 0], 5.0), entry("far-fastest", [70, 0, 0], 1.0),
           entry("blue", [40, 0, -40], 9.0)]
    r = palette.assign(sources([50, 0, 0], [40, 0, -30]), pal, "closest", tolerance_de=3)
    assert chosen(r) == {0: "close-fast", 1: "blue"}
    first, second = r["colours"]
    assert first["how"] == "fastest_within_tolerance" and first["within_tolerance"] and first["delta_e"] == 2.0 and first["time_s_per_cm2"] == 5.0
    assert second["how"] == "nearest" and not second["within_tolerance"] and second["delta_e"] == 10.0
    assert r["totals"] == {"recipes": 2, "colours": 2, "within_tolerance": 1, "mean_delta_e": 6.0, "mean_time_s_per_cm2": 7.0}
    # without the fast entry the nearer one is taken; slower entries can be left out of the choice
    assert chosen(palette.assign(sources([50, 0, 0]), pal[:1] + pal[2:], "closest", tolerance_de=3)) == {0: "near-slow"}
    assert chosen(palette.assign(sources([50, 0, 0]), pal, "closest", tolerance_de=3, max_time=4)) == {0: "far-fastest"}


def test_the_mean_delta_e_is_weighted_by_pixels():
    pal = [entry("a", [50, 0, 0], 1.0), entry("b", [60, 0, 0], 1.0)]
    r = palette.assign(sources([52, 0, 0], [60, 0, 0], pixels=[300, 100]), pal, "closest", tolerance_de=1)
    assert r["totals"]["mean_delta_e"] == pytest.approx((2 * 300 + 0 * 100) / 400)


def lightness_kept(result, srcs, pal):
    labs = {e["id"]: e["lab"] for e in pal}
    by_index = {s["index"]: s for s in srcs}
    pairs = sorted((by_index[c["index"]]["lab"][0], labs[c["entry_id"]][0]) for c in result["colours"])
    return all(a[1] <= b[1] for a, b in zip(pairs, pairs[1:]))


def test_tonality_keeps_the_lightness_order_with_the_least_weighted_delta_e():
    # the nearest colours invert the order: the darker red source would take the lighter entry
    pal = [entry("light-red", [75, 40, 0], 9.0), entry("mid-green", [55, -30, 0], 9.0), entry("dark", [30, 0, 0], 9.0),
           entry("mid-red", [52, 35, 0], 9.0), entry("light-green", [72, -25, 0], 9.0)]
    srcs = sources([30, 0, 0], [50, 40, 0], [70, -30, 0], pixels=[100, 400, 200])
    closest = palette.assign(srcs, pal[:3], "closest", tolerance_de=2)
    assert not lightness_kept(closest, srcs, pal)
    for candidates in (pal[:3], pal):
        r = palette.assign(srcs, candidates, "tonality", tolerance_de=2)
        assert lightness_kept(r, srcs, pal) and r["lightness_order"] == "kept"
        cost = lambda pick: sum(s["pixels"] * color.delta_e(s["lab"], e["lab"]) for s, e in zip(srcs, pick))   # noqa: E731
        monotone = [pick for pick in itertools.product(candidates, repeat=3)
                    if all(a["lab"][0] <= b["lab"][0] for a, b in zip(pick, pick[1:]))]   # sources are given darkest first
        best = min(cost(pick) for pick in monotone)
        mine = sum(c["pixels"] * color.delta_e(c["lab"], c["entry_lab"]) for c in r["colours"])
        assert mine == pytest.approx(best)
    assert chosen(palette.assign(srcs, pal, "tonality", tolerance_de=2)) == {0: "dark", 1: "mid-red", 2: "light-green"}


def test_tonality_takes_the_faster_of_equally_good_entries():
    pal = [entry("slow", [50, 0, 0], 30.0), entry("fast", [50, 0, 0], 3.0)]
    assert chosen(palette.assign(sources([50, 0, 0]), pal, "tonality", tolerance_de=1)) == {0: "fast"}


def test_random_is_deterministic_per_seed_and_another_seed_gives_another_variant():
    pal = [entry(f"e{i}", [20 + 6 * i, (-1) ** i * 10, i], 5.0 + i) for i in range(10)]
    srcs = sources([30, 0, 0], [40, 5, 5], [50, 10, 10], [60, 0, 20], [70, -5, 5])
    one = palette.assign(srcs, pal, "random", tolerance_de=3, seed=1)
    assert chosen(one) == chosen(palette.assign(srcs, pal, "random", tolerance_de=3, seed=1)) and one["seed"] == 1
    assert len(set(chosen(one).values())) == 5                                           # each colour its own entry while there are enough
    assert chosen(palette.assign(srcs, pal, "random", tolerance_de=3, seed=2)) != chosen(one)
    assert all(c["how"] == "random" for c in one["colours"])


def clusters():
    """Two clusters of source colours; each source has an entry of its own (fast) and each cluster a slower entry in its middle."""
    srcs = sources([40, 10, 10], [42, 12, 8], [38, 8, 12], [70, -10, 30], [72, -8, 28], [68, -12, 32])
    own = [entry(f"own{s['index']}", [v + 0.5 for v in s["lab"]], 2.0) for s in srcs]
    middle = [entry("mid-a", [40, 10, 10], 20.0), entry("mid-b", [70, -10, 30], 20.0)]
    return srcs, own + middle


def test_fewer_layers_uses_fewer_recipes_than_closest_and_keeps_every_colour_within_the_tolerance():
    srcs, pal = clusters()
    closest = palette.assign(srcs, pal, "closest", tolerance_de=4)
    fewer = palette.assign(srcs, pal, "fewer_layers", tolerance_de=4)
    assert closest["totals"]["recipes"] == 6 and closest["totals"]["within_tolerance"] == 6
    assert fewer["totals"]["recipes"] == 2 and fewer["totals"]["within_tolerance"] == 6
    # one entry per cluster: of those covering a whole cluster, the faster (own0 and own3 reach their neighbours within 4 too)
    assert set(chosen(fewer).values()) == {"own0", "own3"} and all(c["how"] == "cover" for c in fewer["colours"])
    slow_only = [e for e in pal if e["id"] not in ("own0", "own3")]
    assert set(chosen(palette.assign(srcs, slow_only, "fewer_layers", tolerance_de=4)).values()) == {"mid-a", "mid-b"}


def test_fewer_layers_gives_a_colour_out_of_reach_its_nearest_entry_and_flags_it():
    srcs, pal = clusters()
    srcs.append({"index": 6, "lab": [20, 40, -40], "pixels": 50})
    r = palette.assign(srcs, pal, "fewer_layers", tolerance_de=4)
    out = next(c for c in r["colours"] if c["index"] == 6)
    assert out["how"] == "nearest_outside_tolerance" and not out["within_tolerance"]
    nearest = min(pal, key=lambda e: color.delta_e(e["lab"], [20, 40, -40]))
    assert out["entry_id"] == nearest["id"] and r["totals"]["within_tolerance"] == 6 and r["totals"]["recipes"] == 3


@pytest.mark.parametrize("mode", palette.MODES)
def test_every_mode_keeps_the_operators_own_choices(mode):
    srcs, pal = clusters()
    r = palette.assign(srcs, pal, mode, tolerance_de=4, seed=5, keep={"1": "own4", 3: "mid-a"})
    picks = {c["index"]: c for c in r["colours"]}
    assert picks[1]["entry_id"] == "own4" and picks[1]["how"] == "kept" and picks[3]["entry_id"] == "mid-a"
    assert r["keep"] == {"1": "own4", "3": "mid-a"}


def test_tonality_says_when_kept_choices_break_the_lightness_order():
    srcs, pal = clusters()
    r = palette.assign(srcs, pal, "tonality", tolerance_de=4, keep={0: "mid-b", 3: "mid-a"})     # dark gets light, light gets dark
    assert r["lightness_order"] == "broken_by_kept_choices"
    free = [s for s in srcs if s["index"] not in (0, 3)]
    assert lightness_kept({"colours": [c for c in r["colours"] if c["index"] not in (0, 3)]}, free, pal)


def test_a_work_holds_at_most_29_colours_and_never_more_recipes():
    pal = [entry(f"e{i}", [10 + 2.5 * i, 0, 0], 5.0) for i in range(35)]
    srcs = sources(*[[10 + 2.5 * i, 1, 1] for i in range(29)])
    for mode in palette.MODES:
        assert palette.assign(srcs, pal, mode, tolerance_de=3)["totals"]["recipes"] <= 29
    with pytest.raises(su.ValidationError, match="at most 29 colours"):
        palette.assign(sources(*[[10 + 2.5 * i, 1, 1] for i in range(30)]), pal, "closest", tolerance_de=3)


@pytest.mark.parametrize("args, message", [
    ({"mode": "nearest"}, "the recolouring mode must be closest, tonality, random or fewer_layers"),
    ({"source_colours": []}, "give the source colours to recolour"),
    ({"source_colours": [{"index": 0, "lab": [50, 0]}]}, "each source colour needs its index, a Lab colour and a pixel count"),
    ({"source_colours": [[0, [50, 0, 0], 10], [0, [60, 0, 0], 10]]}, "two source colours have the same index"),
    ({"keep": {"7": "a"}}, "a kept choice names a source colour that is not given"),
    ({"keep": {"0": "zz"}}, "a kept choice names a colour that is not in the palette of this laser, lens and titanium stock"),
    ({"palette": []}, "no measured colour of this laser, lens and titanium stock fills an area"),
    ({"max_time": 0.5}, "no colour of the palette engraves within 0.5 s per square centimetre"),
    ({"tolerance_de": -1}, "the delta E tolerance must be a non-negative number"),
])
def test_an_assignment_that_cannot_be_made_is_refused_with_the_reason(args, message):
    call = {"source_colours": [[0, [50, 0, 0], 10]], "palette": [entry("a", [50, 0, 0], 2.0)], "mode": "closest", "tolerance_de": 2, **args}
    with pytest.raises(su.ValidationError) as exc:
        palette.assign(call.pop("source_colours"), call.pop("palette"), call.pop("mode"), **call)
    assert str(exc.value) == message


# -- API ---------------------------------------------------------------------------------------------------------------------
def test_the_api_serves_the_palette_and_assigns_from_it(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app(tmp_path / "data")
    store = app.state.store
    w = obs.setup(store)
    ti = su.save_material(store, "Grade 2 sheet", grade="Grade 2", thickness_mm=1.0, surface="brushed")["id"]
    obs.add(store, w, [60.0, 5.0, 20.0], speed=1000, line_interval=0.01, material_id=ti, layer_type="Scan")
    obs.add(store, w, [40.0, 10.0, -20.0], speed=3000, line_interval=0.01, material_id=ti, layer_type="Scan")
    device_id, lens_id = w["setup"]
    client = TestClient(app)
    got = client.get("/api/vector-palette", params={"device_id": device_id, "lens_id": lens_id, "material_id": ti}).json()
    assert [e["lab"][0] for e in got["entries"]] == [60.0, 40.0] and got["left_out"]["line"] == 0
    assert len(client.get("/api/vector-palette", params={"device_id": device_id, "lens_id": lens_id, "material_id": ti,
                                                         "max_time_s_per_cm2": 5}).json()["entries"]) == 1
    body = {"device_id": device_id, "lens_id": lens_id, "material_id": ti, "mode": "closest",
            "source_colours": [{"index": 0, "lab": [58, 5, 18], "pixels": 900}, {"index": 1, "lab": [41, 9, -19], "pixels": 100}]}
    refused = client.post("/api/vector-palette/assign", json=body)
    assert refused.status_code == 422 and refused.json()["error"] == "set the delta E tolerance: none is saved for this laser and lens"
    r = client.post("/api/vector-palette/assign", json={**body, "tolerance_de": 5}).json()
    assert [c["entry_id"] for c in r["colours"]] == [got["entries"][0]["id"], got["entries"][1]["id"]]
    assert r["totals"]["recipes"] == 2 and all(c["within_tolerance"] for c in r["colours"]) and r["tolerance_de"] == 5
    su.save_rules(store, device_id, lens_id, delta_tolerance=1.0)                          # the saved rule when none is given
    ruled = client.post("/api/vector-palette/assign", json={**body, "mode": "fewer_layers", "keep": {"1": got["entries"][0]["id"]}}).json()
    assert ruled["tolerance_de"] == 1.0 and ruled["colours"][1]["how"] == "kept" and ruled["totals"]["recipes"] == 1
    assert client.post("/api/vector-palette/assign", json={**body, "lens_id": None}).status_code == 422   # the unknown lens has no colours
