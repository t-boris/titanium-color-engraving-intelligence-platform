"""The ``.tcelab`` v1 file (electron REQ-083, DEC-024): canonical JSON any implementation can hash the same, one record per line, read in
constant memory, and every malformed, unsafe or oversized release refused with a reason."""
from __future__ import annotations

import hashlib
import io
import json
import uuid

import pytest

from titanium_platform import lab_format as lf

LAB = str(uuid.UUID(int=1, version=4))
RELEASE = str(uuid.UUID(int=2, version=4))


def uid(n: int) -> str:
    return str(uuid.UUID(int=1000 + n, version=4))


def manifest(**changes) -> dict:
    base = {"format": "tcelab", "schema_version": "1.0", "origin_lab_id": LAB, "release_id": RELEASE, "release_number": None,
            "created_at": "2026-10-24T12:00:00Z", "producer": {"name": "titanium-platform", "version": "0.29.0"},
            "algorithm_versions": {"evidence": "1", "palette": "1", "prediction": "2", "row_length": "1", "tonal_profile": "1",
                                   "against_clean": "1"},
            "capabilities": {"required": ["measurements"], "optional": []}, "usage_terms": {"id": "CC-BY-4.0", "version": "4.0"},
            "attribution": {"name": "Test Lab", "organization": None, "url": "https://example.org/lab"}}
    base.update(changes)
    return base


def sections(n: int = 3) -> dict:
    equipment = [{"id": uid(1), "seq": 0, "laser": {"id": uid(2), "public_name": "Fiber 60 W", "manufacturer": "JPT", "model": "M7",
                                                    "rated_power_w": 60, "wavelength_nm": 1064}, "lens": {"id": uid(3), "focal_length_mm": 174.0}}]
    materials = [{"id": uid(4), "seq": 0, "family": "titanium", "grade": "Grade 2", "thickness_mm": 0.5}]
    captures = [{"id": uid(5), "seq": 0, "engraving_id": uid(6), "equipment_id": uid(1), "material_id": uid(4),
                 "measured_at": "2026-09-01T10:00:00Z", "basis": "chart", "experiment": None, "over_fills": False, "batch_known": True}]
    measurements = [{"id": uid(10 + i), "seq": i, "capture_id": uid(5), "layer": {"index": i + 1, "label": f"C{i + 1:02d}", "role": "test_feature"},
                     "lab": [60.0 - 5 * i, 4.25, -0.1 * i], "kind": "calibrated", "model_eligible": True, "repeat_eligible": True,
                     "matrix": False, "task": {"kind": "fill", "basis": "derived"},
                     "parameters": {"power": 10.0 * (i + 1), "frequency": 60.0, "speed": 900.0, "pulse_width": 200.0, "line_interval": 0.025,
                                    "passes": 1, "layer_type": "Scan", "source_settings": {"scanOpt": {"Value": "individual"}}},
                     "row_mm": 20.0} for i in range(n)]
    return {"equipment": equipment, "materials": materials, "captures": captures, "measurements": measurements}


def written(tmp_path, m=None, lab=None, s=None) -> bytes:
    path = tmp_path / "lab.tcelab"
    lf.write(path, m or manifest(), lab or {"id": LAB, "name": "Test Lab", "description": "Numbers\nonly"}, s or sections())
    return path.read_bytes()


def read_all(data: bytes, **kw) -> list:
    return list(lf.read(io.BytesIO(data), **kw))


# -- canonical JSON ------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value, text", [
    (0.0, "0"), (-0.0, "0"), (1.0, "1"), (1.5, "1.5"), (-1.5, "-1.5"), (0.1 + 0.2, "0.30000000000000004"), (1e20, "100000000000000000000"),
    (1e21, "1e+21"), (1e-6, "0.000001"), (1e-7, "1e-7"), (123.456, "123.456"), (5e-324, "5e-324"), (1.7976931348623157e308, "1.7976931348623157e+308"),
    (333333333.33333329, "333333333.3333333"), (4.50, "4.5"), (2e-3, "0.002"), (0.000001234, "0.000001234"), (1.234e-7, "1.234e-7")])
def test_numbers_are_written_as_ecmascript_prints_them(value, text):
    assert lf._es_number(value) == text


def test_members_are_sorted_strings_escaped_minimally_and_nothing_else_is_accepted():
    assert lf.canonical({"b": [1, True, None], "a": "é\"\n\x01"}) == '{"a":"é\\"\\n\\u0001","b":[1,true,null]}'
    for bad in (float("nan"), float("inf"), 2 ** 60, {"a b": 1}, {1: 2}, b"x", {"x": [[[[[[[[[[1]]]]]]]]]]}):
        with pytest.raises(lf.FormatError):
            lf.canonical(bad)


def test_a_line_with_a_repeated_key_or_a_non_number_is_refused():
    with pytest.raises(lf.FormatError, match="twice"):
        lf.decode('{"a":1,"a":2}')
    for constant in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(lf.FormatError):
            lf.decode('{"a":%s}' % constant)


# -- writing and reading -------------------------------------------------------------------------------------------------------------
def test_a_release_is_one_json_document_whose_hash_leaves_out_only_itself(tmp_path):
    data = written(tmp_path)
    document = json.loads(data)                                              # any JSON reader reads it whole
    assert list(document) == ["manifest", "lab", *lf.SECTIONS]
    m = document["manifest"]
    assert m["counts"] == {"equipment": 1, "materials": 1, "captures": 1, "measurements": 3, "tone_profiles": 0, "provenance": 0}
    lines = data.split(b"\n")
    without = b'{"manifest":' + lf.canonical({k: v for k, v in m.items() if k != "content_sha256"}).encode()
    assert hashlib.sha256(b"\n".join([without, *lines[1:]])).hexdigest() == m["content_sha256"]
    assert data.endswith(b"}\n") and b"\r" not in data and not data.startswith(b"\xef\xbb\xbf")


def test_reading_gives_every_piece_in_order_and_ends_only_when_counts_and_hash_hold(tmp_path):
    pieces = read_all(written(tmp_path))
    assert [kind for kind, _ in pieces] == ["manifest", "compatibility", "lab", "equipment", "materials", "captures",
                                             "measurements", "measurements", "measurements", "end"]
    assert pieces[-1][1]["release_id"] == RELEASE and pieces[1][1]["strict"]


def test_the_same_content_written_twice_has_the_same_bytes_and_hash(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert written(tmp_path / "a") == written(tmp_path / "b")


def test_a_failed_write_leaves_no_file_behind(tmp_path):
    bad = sections()
    bad["measurements"][1]["lab"] = [float("nan"), 0.0, 0.0]
    with pytest.raises(lf.FormatError):
        lf.write(tmp_path / "x.tcelab", manifest(), {"id": LAB, "name": "L"}, bad)
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(lf.Cancelled):
        lf.write(tmp_path / "x.tcelab", manifest(), {"id": LAB, "name": "L"}, sections(), cancelled=lambda: True)
    assert list(tmp_path.iterdir()) == []


def _mutated(data: bytes, old: bytes, new: bytes) -> bytes:
    assert old in data
    return data.replace(old, new, 1)


def _record(data: bytes, line: int, change) -> bytes:
    """``data`` with the record on ``line`` changed by ``change`` and written canonically again (the hash then no longer holds)."""
    lines = data.split(b"\n")
    comma = lines[line].startswith(b",")
    record = json.loads(lines[line][1:] if comma else lines[line])
    change(record)
    lines[line] = (b"," if comma else b"") + lf.canonical(record).encode()
    return b"\n".join(lines)


EQUIPMENT, SECOND_MEASUREMENT = 3, 13


@pytest.mark.parametrize("change, code", [
    (lambda d: _mutated(d, b'"lab":[60,', b'"lab":[61,'), "hash"),
    (lambda d: _mutated(d, b'"lab":[60,', b'"lab":[ 60,'), "canonical"),
    (lambda d: d.replace(b"\n", b"\r\n"), "framing"),
    (lambda d: b"\xef\xbb\xbf" + d, "framing"),
    (lambda d: d[: len(d) // 2], "truncated"),
    (lambda d: d[:-1], "truncated"),
    (lambda d: d + b"x", "framing"),
    (lambda d: d.replace(b'"kind":"calibrated"', b'"kind":"calibrated","kind":"relative"', 1), "duplicate_key"),
    (lambda d: _mutated(d, b'"lab":[60,', b'"lab":[NaN,'), "number"),
    (lambda d: _mutated(d, b'"schema_version":"1.0"', b'"schema_version":"2.0"'), "version_major"),
    (lambda d: _mutated(d, b'"required":["measurements"]', b'"required":["measurements","spectra"]'), "capability"),
    (lambda d: _mutated(d, b'"id":"CC-BY-4.0"', b'"id":"anything-goes"'), "terms"),
    (lambda d: _mutated(d, b'"measurements":3', b'"measurements":4'), "counts"),
    (lambda d: _mutated(d, b'"seq":1,', b'"seq":0,'), "order"),
    (lambda d: _mutated(d, b'"public_name":"Fiber 60 W"', b'"public_name":"javascript:alert(1)"'), "text"),
    (lambda d: _mutated(d, b'"public_name":"Fiber 60 W"', b'"public_name":"/Users/me/secret"'), "text"),
    (lambda d: _record(d, EQUIPMENT, lambda r: r["laser"].update(public_name="Fiber\u202e60")), "text"),
    (lambda d: _mutated(d, b'"url":"https://example.org/lab"', b'"url":"http://example.org/lab"'), "url"),
    (lambda d: _mutated(d, b'"url":"https://example.org/lab"', b'"url":"https://me:pw@example.org/lab"'), "url"),
    (lambda d: _record(d, SECOND_MEASUREMENT, lambda r: r.update(photo="x")), "schema"),
    (lambda d: b"PK\x03\x04" + d, "not_a_release"),
])
def test_a_damaged_or_unsafe_release_is_refused_with_its_reason(tmp_path, change, code):
    data = change(written(tmp_path))
    with pytest.raises(lf.FormatError) as found:
        read_all(data)
    assert found.value.code == code, str(found.value)


def test_a_newer_minor_version_is_read_keeping_members_this_version_does_not_know(tmp_path):
    m = manifest(schema_version="1.1")
    s = sections()
    data = written(tmp_path, m=m, s=s)
    # a 1.1 writer added a member; rewrite the line and the hash as it would have
    lines = data.split(b"\n")
    record = json.loads(lines[SECOND_MEASUREMENT][1:])
    record["colour_temperature_k"] = 5000
    lines[SECOND_MEASUREMENT] = b"," + lf.canonical(record).encode()
    head = json.loads(lines[0][len(b'{"manifest":'):])
    del head["content_sha256"]
    body = b"\n".join(lines[1:])
    head["content_sha256"] = hashlib.sha256(b'{"manifest":' + lf.canonical(head).encode() + b"\n" + body).hexdigest()
    data = b'{"manifest":' + lf.canonical(head).encode() + b"\n" + body
    pieces = read_all(data)
    assert pieces[1][1] == {"schema_version": "1.1", "strict": False, "newer_minor": True, "unknown_optional": []}
    assert any(kind == "measurements" and rec.get("colour_temperature_k") == 5000 for kind, rec in pieces)
    with pytest.raises(lf.FormatError, match="not allowed"):           # the same member in a 1.0 release is refused
        lf.check_record("measurements", record, strict=True)


def test_limits_refuse_a_release_and_never_shorten_it(tmp_path):
    small = lf.ResourcePolicy(max_records={**lf.DEFAULT_POLICY.max_records, "measurements": 2})
    data = written(tmp_path)
    with pytest.raises(lf.FormatError, match="exceed the limit"):
        read_all(data, policy=small)
    with pytest.raises(lf.FormatError, match="larger than"):
        read_all(data, policy=lf.ResourcePolicy(max_bytes=500))
    with pytest.raises(lf.FormatError, match="exceed the limit|more than"):
        lf.write(tmp_path / "big.tcelab", manifest(), {"id": LAB, "name": "L"}, sections(), policy=small)


def test_the_manifest_is_read_alone_before_anything_else(tmp_path):
    path = tmp_path / "lab.tcelab"
    path.write_bytes(written(tmp_path))
    assert lf.peek_manifest(path)["release_id"] == RELEASE
    path.write_bytes(b"not a release\n")
    with pytest.raises(lf.FormatError, match="not a laboratory release"):
        lf.peek_manifest(path)


def test_the_approved_terms_are_the_three_of_dec_042():
    assert set(lf.USAGE_TERMS) == {"CC-BY-4.0", "CC-BY-NC-4.0", "tce-own-engravings-1"}
    assert not lf.USAGE_TERMS["tce-own-engravings-1"]["redistribute"] and not lf.USAGE_TERMS["CC-BY-NC-4.0"]["commercial"]
