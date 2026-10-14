"""The passport sections read from the photographs, and the repeatable import of a physical unit (REQ-017, DEC-037 to DEC-039)."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from titanium_platform import devices as dv
from titanium_platform import profiles as pf
from titanium_platform.db import Store

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "tools" / "units" / "jpt-ydflp-e-60-m7-m-r-mc2bdjd71684.json"
JPEG = b"\xff\xd8\xff\xe0" + b"1" * 64


def load_tool():
    spec = importlib.util.spec_from_file_location("import_unit", ROOT / "tools" / "import_unit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def unit():
    return json.loads(UNIT.read_text(encoding="utf-8"))


@pytest.fixture
def photos(tmp_path, unit):
    folder = tmp_path / "photos"
    folder.mkdir()
    for d in unit["documents"]:
        (folder / d["file"]).write_bytes(JPEG)
    return folder


def passport_of(unit):
    return dict(dv.TEMPLATES[unit["template"]]["passport"]) | unit["passport"]


# -- controller, report, waveforms --------------------------------------------------------------------------
def test_the_unit_file_is_a_valid_passport(unit):
    p = dv.validate_passport(passport_of(unit))
    assert len(p["waveforms"]) == 2 and len(p["test_report"]["rows"]) == 9 and p["controller"]["software"] == "EZCAD 2.14.10"
    assert sum(len(t["fields"]) for t in p["controller"]["tabs"]) >= 50 and p["test_report"]["serial"] == "MC2BDJD71684"


def test_handwritten_controller_values_are_flagged_and_never_certain(unit):
    fields = [f for t in unit["passport"]["controller"]["tabs"] for f in t["fields"]]
    by_key = {f["key"]: f for f in fields}
    assert by_key["Galvo 1 Scale"]["status"] == "handwritten" and by_key["Galvo 1 Scale"]["value"] == "см. фото"
    assert by_key["Max PWM"]["value"] == 200.0 and by_key["Max PWM"]["status"] == "printed"
    assert not [f for f in fields if f["status"] == "confirmed"]                       # only the operator may confirm
    assert any("Масштабы гальво" in t for t in unit["passport"]["open_items"])        # every unread value is an open item


@pytest.mark.parametrize("bad", [
    {"tabs": "x"}, {"tabs": [{"key": "", "fields": []}]}, {"tabs": [{"key": "a", "fields": "x"}]},
    {"tabs": [{"key": "a", "fields": [{"key": "k", "value": 1, "status": "guess"}]}]},
    {"tabs": [{"key": "a", "fields": [{"key": "k", "value": [1], "status": "printed"}]}]},
    {"tabs": [{"key": "a", "fields": [{"key": "k", "value": float("nan"), "status": "printed"}]}]}, [1]])
def test_a_malformed_controller_section_is_refused(store, unit, bad):
    with pytest.raises(pf.ValidationError, match="controller"):
        dv.create_device(store, "X", passport_of(unit) | {"controller": bad})


@pytest.mark.parametrize("bad", [[1], {"rows": "x"}, {"rows": [{"key": ""}]}, {"rows": [{"key": "a", "min": [1]}]}])
def test_a_malformed_test_report_is_refused(store, unit, bad):
    with pytest.raises(pf.ValidationError, match="test report"):
        dv.create_device(store, "X", passport_of(unit) | {"test_report": bad})


@pytest.mark.parametrize("bad", [
    [{"t_ns": [0, 1], "p_kw": [1]}], [{"t_ns": [0], "p_kw": [1]}], [{"t_ns": [1, 0], "p_kw": [1, 2]}], [{"t_ns": [0, 0], "p_kw": [1, 2]}],
    [{"t_ns": [0, 1], "p_kw": [1, float("inf")]}], [{"t_ns": [0, 1], "p_kw": [1, "x"]}], ["x"], [{"t_ns": list(range(3001)), "p_kw": list(range(3001))}]])
def test_a_malformed_waveform_is_refused(store, unit, bad):
    with pytest.raises(pf.ValidationError):
        dv.create_device(store, "X", passport_of(unit) | {"waveforms": bad})


def test_waveform_energy_is_the_integral_and_is_compared_with_the_passport(store, unit):
    w = {"title": "t", "frequency_khz": 100, "t_ns": [0, 10, 20, 30], "p_kw": [0, 2, 2, 0]}
    s = dv.waveform_stats(dv._waveforms([w])[0], 60)
    assert s["peak_kw"] == 2 and s["energy_mj"] == pytest.approx((10 * 1 + 10 * 2 + 10 * 1) / 1000)        # trapezoids: 40 kW*ns = 0.04 mJ
    assert s["passport_energy_mj"] == pytest.approx(0.6) and s["ratio"] == pytest.approx(0.04 / 0.6, rel=1e-2)


def test_a_negative_ringing_does_not_reduce_the_energy():
    w = dv._waveforms([{"t_ns": [0, 1, 2, 3], "p_kw": [0, 4, -4, 0]}])[0]
    assert dv.waveform_stats(w, 60)["energy_mj"] == pytest.approx((0 + 4) / 2 * 1 / 1000 + (4 + 0) / 2 * 1 / 1000)


def test_the_digitised_waveforms_agree_with_the_passport_within_a_few_percent(store, unit):
    """The check that the digitisation is trustworthy: the integral of each printed pulse is the pulse energy 60 W / frequency."""
    charts = dv.charts(dv.validate_passport(passport_of(unit)))
    first, second = charts["waveforms"]
    assert 0.9 < first["stats"]["ratio"] < 1.2 and first["stats"]["peak_kw"] == pytest.approx(8.7, abs=0.4)
    assert 0.6 < second["stats"]["ratio"] < 1.0 and second["stats"]["peak_kw"] == pytest.approx(10.0, abs=0.5)
    assert first["approximate"] and second["approximate"] and "детектор" in second["note"]




# -- the import tool ------------------------------------------------------------------------------------------
def run(tool, data_dir, photos, *extra):
    return tool.main(["--data-dir", str(data_dir), "--photos", str(photos), "--unit", str(UNIT), *extra])


def test_the_import_creates_the_device_with_its_photographs_byte_for_byte(tmp_path, photos, unit):
    tool, data = load_tool(), tmp_path / "data"
    assert run(tool, data, photos) == 0
    store = Store(data)
    try:
        [d] = dv.list_devices(store)
        assert d["serial"] == "MC2BDJD71684" and len(d["documents"]) == 5 and d["passport"]["controller"] and len(d["passport"]["waveforms"]) == 2
        assert {x["kind"] for x in d["documents"]} == {"test_report", "cutoff_table", "controller_config", "waveform", "packing_list"}
        stored = dv.get_document(store, d["id"], d["documents"][0]["id"])
        assert Path(stored["path"]).read_bytes() == JPEG
    finally:
        store.close()


def test_running_the_import_again_changes_nothing_but_makes_a_backup(tmp_path, photos):
    tool, data = load_tool(), tmp_path / "data"
    run(tool, data, photos)
    run(tool, data, photos)
    store = Store(data)
    try:
        [d] = dv.list_devices(store)
        assert len(d["documents"]) == 5 and len(list((data / "files").iterdir())) == 5
    finally:
        store.close()
    backups = list(data.glob("backup-*"))
    assert len(backups) == 1 and sqlite3.connect(backups[0] / "titanium.sqlite").execute("SELECT COUNT(*) FROM laser_device").fetchone()[0] == 1


def test_a_missing_photograph_stops_the_import_before_anything_is_written(tmp_path, photos, capsys):
    tool, data = load_tool(), tmp_path / "data"
    (photos / "IMG_3263.JPG").unlink()
    assert run(tool, data, photos) == 2 and "IMG_3263.JPG" in capsys.readouterr().err
    assert not (data / "titanium.sqlite").exists()


def test_the_import_can_link_an_existing_profile_without_a_new_version(tmp_path, photos):
    tool, data = load_tool(), tmp_path / "data"
    store = Store(data)
    p = pf.create_profile(store, "JPT MOPA M7 60W", 200, 0.025, 1)
    store.close()
    assert run(tool, data, photos, "--link-profile", "JPT MOPA M7 60W") == 0
    store = Store(data)
    try:
        profiles = pf.list_profiles(store)
        assert [x["version"] for x in profiles] == [1] and profiles[0]["id"] == p["id"] and profiles[0]["device"]["serial"] == "MC2BDJD71684"
        assert profiles[0]["constants"] == p["constants"]
    finally:
        store.close()


def test_a_missing_profile_is_reported_and_the_device_still_exists(tmp_path, photos, capsys):
    tool, data = load_tool(), tmp_path / "data"
    assert run(tool, data, photos, "--link-profile", "Nope") == 3 and "Nope" in capsys.readouterr().err
    store = Store(data)
    try:
        assert len(dv.list_devices(store)) == 1
    finally:
        store.close()

def test_the_unit_file_has_no_value_the_report_does_not_give(unit):
    rows = {r["key"]: r for r in unit["passport"]["test_report"]["rows"]}
    assert rows["Nominal average output power"]["result"] == 62.6 and rows["Central emission wavelength"]["result"] == 1067.0
    assert rows["Long-term average power instability"]["result"] is None and rows["Output beam diameter"]["result"] == 7.0
