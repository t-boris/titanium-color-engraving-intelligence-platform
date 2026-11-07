"""QR codes of a business-card work (feature-2, REQ-005, DEC-031, DEC-038, DEC-040): the text each kind of code carries and what is said
when it is incomplete, the symbol as modules and as geometry (proved by reading the geometry back), and the physical check of module
size and quiet zone with the clearance that feeds it. Non-ASCII text is written as escapes in this source."""
import json
import re

import numpy as np
import pytest
import shapely
from shapely import affinity
from shapely.geometry import box

from titanium_platform import card_qr as Q, setup as su

CYRILLIC = "\u0418\u0432\u0430\u043d \u041f\u0435\u0442\u0440\u043e\u0432"          # a Russian first and last name
SAMPLES = {
    "link": {"url": "example.com/menu?table=5"},
    "vcard": {"first_name": "Ann", "last_name": "Lee", "organisation": "Lee & Co", "title": "Engraver", "phone": "+1 (415) 555-0100",
              "mobile": "+14155550101", "email": "ann@lee.example", "url": "lee.example", "address": "1 Main St\nSpringfield"},
    "text": {"text": "Titanium business card \u2013 " + CYRILLIC},
    "wifi": {"ssid": "Workshop", "password": "s3cret;pass", "security": "WPA", "hidden": True},
    "email": {"address": "ann@lee.example", "subject": "Hello", "body": "Please call me.\nThanks"},
    "phone": {"number": "+1 415 555 0100"},
}


def qr(kind, ecc="M", **fields):
    return {"kind": kind, "fields": fields, "ecc": ecc}


def sample(kind, ecc="M"):
    return qr(kind, ecc, **SAMPLES[kind])


def refused(kind, ecc="M", **fields) -> str:
    """The plain-English reason a code of this content is refused."""
    with pytest.raises(su.ValidationError) as caught:
        Q.payload(qr(kind, ecc, **fields))
    return str(caught.value)


def link(length):
    return "https://example.com/" + "a" * (length - 20)


# -- the API's constants and the entry forms -----------------------------------------------------------
def test_kinds_levels_and_thresholds_are_the_agreed_ones():
    assert Q.KINDS == ("link", "vcard", "text", "wifi", "email", "phone")
    assert Q.ECC_LEVELS == ("L", "M", "Q", "H") and Q.DEFAULT_ECC == "M"
    assert Q.THRESHOLDS == {"module_mm": 0.40, "quiet_modules": 4.0}


def test_the_entry_form_of_every_kind_lists_its_fields():
    assert set(Q.FIELDS) == set(Q.KINDS)
    names = {kind: [f["name"] for f in fields] for kind, fields in Q.FIELDS.items()}
    assert names == {"link": ["url"],
                     "vcard": ["first_name", "last_name", "organisation", "title", "phone", "mobile", "email", "url", "address"],
                     "text": ["text"], "wifi": ["ssid", "password", "security", "hidden"], "email": ["address", "subject", "body"],
                     "phone": ["number"]}
    for fields in Q.FIELDS.values():
        for f in fields:
            assert f["label"] and f["type"] in ("text", "multiline", "password", "select", "bool") and isinstance(f["required"], bool)
            if f["type"] == "select":
                assert f["default"] in f["options"]
            if f["type"] == "bool":
                assert f["default"] is False
    security = next(f for f in Q.FIELDS["wifi"] if f["name"] == "security")
    assert security["options"] == ["WPA", "WEP", "nopass"] and security["default"] == "WPA"
    assert next(f for f in Q.FIELDS["wifi"] if f["name"] == "password")["type"] == "password"
    assert [f["name"] for k in Q.FIELDS for f in Q.FIELDS[k] if f["required"]] == ["url", "text", "ssid", "address", "number"]
    json.dumps(Q.FIELDS)


# -- checked: what the operator typed, normalised --------------------------------------------------------
def test_checked_fills_defaults_strips_and_normalises_the_kind_and_level():
    c = Q.checked({"kind": " VCard ", "fields": {"first_name": "  Ann \n", "title": None}, "ecc": "q"})
    assert c["kind"] == "vcard" and c["ecc"] == "Q"
    assert c["fields"] == {"first_name": "Ann", "last_name": "", "organisation": "", "title": "", "phone": "", "mobile": "", "email": "",
                           "url": "", "address": ""}
    assert Q.checked({"kind": "wifi"}) == {"kind": "wifi", "ecc": "M", "fields": {"ssid": "", "password": "", "security": "WPA", "hidden": False}}
    assert Q.checked({"kind": "link", "fields": {"url": "x"}, "ecc": None})["ecc"] == "M"
    assert Q.checked({"kind": "phone", "fields": {"number": 5551234}})["fields"]["number"] == "5551234"


def test_checked_is_idempotent_serialisable_and_leaves_its_input_alone():
    raw = {"kind": "wifi", "fields": {"ssid": " Net ", "hidden": "yes", "security": "wep"}, "ecc": "h"}
    before = json.dumps(raw, sort_keys=True)
    c = Q.checked(raw)
    assert json.dumps(raw, sort_keys=True) == before
    assert c["fields"] == {"ssid": "Net", "password": "", "security": "WEP", "hidden": True}
    assert Q.checked(c) == c and json.loads(json.dumps(c)) == c
    assert Q.checked({"kind": "text", "fields": {"text": "x"}, "extra": 1}) == {"kind": "text", "fields": {"text": "x"}, "ecc": "M"}


def test_a_single_line_field_has_no_line_break_and_a_multiline_one_keeps_them():
    c = Q.checked({"kind": "vcard", "fields": {"first_name": "Ann\r\n  Lee", "address": "1 Main St\r\nTown\rX"}})
    assert c["fields"]["first_name"] == "Ann Lee" and c["fields"]["address"] == "1 Main St\nTown\nX"


@pytest.mark.parametrize("value, expected", [("true", True), ("1", True), ("On", True), (True, True), ("false", False), ("", False),
                                             ("no", False), (None, False), (0, False)])
def test_a_yes_no_field_accepts_the_usual_spellings(value, expected):
    assert Q.checked({"kind": "wifi", "fields": {"hidden": value}})["fields"]["hidden"] is expected


@pytest.mark.parametrize("raw, words", [
    ({"kind": "poster"}, ("poster", "link")),
    ({"kind": None}, ("type",)),
    ({"kind": "link", "fields": {"url": "x", "colour": "red"}}, ("colour", "url")),
    ({"kind": "link", "fields": {"url": "x"}, "ecc": "Z"}, ("'Z'", "L, M, Q or H")),
    ({"kind": "link", "fields": {"url": "x"}, "ecc": 7}, ("7",)),
    ({"kind": "wifi", "fields": {"security": "WPA3"}}, ("Security", "WPA3", "WPA, WEP, nopass")),
    ({"kind": "wifi", "fields": {"hidden": "maybe"}}, ("Hidden network",)),
    ({"kind": "link", "fields": {"url": ["a"]}}, ("Web address",)),
    ({"kind": "link", "fields": {"url": True}}, ("Web address",)),
    ({"kind": "link", "fields": {"url": "a\x00b"}}, ("Web address", "control")),
    ({"kind": "link", "fields": {"url": "a" * 2001}}, ("Web address", "2000")),
    ({"kind": "link", "fields": "url"}, ("fields",)),
    ("link", ("type",)),
])
def test_checked_refuses_what_cannot_be_a_code_in_plain_english(raw, words):
    with pytest.raises(su.ValidationError) as caught:
        Q.checked(raw)
    for word in words:
        assert word in str(caught.value)


# -- payload: link ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("given, expected", [
    ("https://example.com/a?b=c&d=e#f", "https://example.com/a?b=c&d=e#f"),
    ("HTTPS://Example.com/Path", "HTTPS://Example.com/Path"),
    ("http://example.com", "http://example.com"),
    ("mailto:ann@lee.example", "mailto:ann@lee.example"),
    ("tel:+14155550100", "tel:+14155550100"),
    ("ftp://files.example.com/x", "ftp://files.example.com/x"),
    ("example.com", "https://example.com"),
    ("  www.example.com/menu?x=1  ", "https://www.example.com/menu?x=1"),
    ("sub.example.co.uk/a/b", "https://sub.example.co.uk/a/b"),
    ("localhost:8080/x", "https://localhost:8080/x"),
    ("192.168.1.5:3000", "https://192.168.1.5:3000"),
    ("user@example.com/page", "https://user@example.com/page"),
    ("\u043f\u0440\u0438\u043c\u0435\u0440.\u0440\u0444/\u043c\u0435\u043d\u044e", "https://\u043f\u0440\u0438\u043c\u0435\u0440.\u0440\u0444/\u043c\u0435\u043d\u044e"),
    ("https://example.com/\u043f\u0443\u0442\u044c", "https://example.com/\u043f\u0443\u0442\u044c"),
])
def test_a_link_is_carried_as_given_with_https_added_to_a_bare_host(given, expected):
    assert Q.payload(qr("link", url=given)) == expected


def test_a_link_of_the_longest_allowed_size_is_accepted_and_one_more_is_not():
    assert len(Q.payload(qr("link", url=link(2000)))) == 2000
    assert "2000" in refused("link", url=link(2001))


@pytest.mark.parametrize("given, words", [
    ("", ("Web address", "enter")),
    ("   \n ", ("Web address", "enter")),
    ("example", ("Web address", "example.com/menu")),
    ("example .com", ("Web address", "spaces")),
    ("https://exa mple.com", ("Web address", "spaces")),
    ("javascript:alert(1)", ("Web address", "not a web address")),
    ("//example.com", ("Web address",)),
    ("1.2", ("Web address",)),
])
def test_an_empty_or_unusable_link_says_so(given, words):
    message = refused("link", url=given)
    for word in words:
        assert word in message


# -- payload: contact card -------------------------------------------------------------------------------
def test_a_contact_card_is_a_vcard_3_with_one_line_per_filled_field():
    assert Q.payload(sample("vcard")) == "\n".join([
        "BEGIN:VCARD", "VERSION:3.0", "N:Lee;Ann;;;", "FN:Ann Lee", "ORG:Lee & Co", "TITLE:Engraver", "TEL;TYPE=WORK,VOICE:+1(415)555-0100",
        "TEL;TYPE=CELL:+14155550101", "EMAIL:ann@lee.example", "URL:https://lee.example", "ADR;TYPE=WORK:;;1 Main St\\nSpringfield;;;;",
        "END:VCARD"])


def test_a_contact_card_needs_a_name_or_an_organisation_only():
    assert Q.payload(qr("vcard", first_name="Ann")) == "BEGIN:VCARD\nVERSION:3.0\nN:;Ann;;;\nFN:Ann\nEND:VCARD"
    assert Q.payload(qr("vcard", last_name="Lee")) == "BEGIN:VCARD\nVERSION:3.0\nN:Lee;;;;\nFN:Lee\nEND:VCARD"
    assert Q.payload(qr("vcard", organisation="Lee & Co")) == "BEGIN:VCARD\nVERSION:3.0\nN:;;;;\nFN:Lee & Co\nORG:Lee & Co\nEND:VCARD"
    message = refused("vcard", title="Engraver", email="ann@lee.example")
    assert "first name" in message and "organisation" in message
    assert refused("vcard") == message


def test_a_contact_card_escapes_comma_semicolon_backslash_and_line_break():
    text = Q.payload(qr("vcard", first_name="A,B", last_name="C;D", organisation="E\\F", title="G, H; I", address="J\nK,L"))
    lines = text.split("\n")
    assert "N:C\\;D;A\\,B;;;" in lines and "FN:A\\,B C\\;D" in lines and "ORG:E\\\\F" in lines
    assert "TITLE:G\\, H\\; I" in lines and "ADR;TYPE=WORK:;;J\\nK\\,L;;;;" in lines
    assert len(lines) == 8                                   # nothing was split into a line of its own


def test_a_contact_card_cannot_be_given_a_second_card_through_a_line_break():
    text = Q.payload(qr("vcard", first_name="Ann\nEND:VCARD\nBEGIN:VCARD", address="x\nEND:VCARD\nBEGIN:VCARD"))
    lines = text.split("\n")
    assert lines.count("BEGIN:VCARD") == 1 and lines.count("END:VCARD") == 1 and lines[0] == "BEGIN:VCARD" and lines[-1] == "END:VCARD"
    assert [line.split(":")[0].split(";")[0] for line in lines] == ["BEGIN", "VERSION", "N", "FN", "ADR", "END"]       # no line of its own


def test_a_contact_cards_website_is_a_link_and_is_not_text_escaped():
    assert "URL:https://lee.example/a,b;c" in Q.payload(qr("vcard", first_name="Ann", url="lee.example/a,b;c")).split("\n")
    assert "Website" in refused("vcard", first_name="Ann", url="nowhere")


def test_a_contact_card_carries_non_ascii_names_as_they_are():
    text = Q.payload(qr("vcard", first_name="\u0418\u0432\u0430\u043d", last_name="\u041f\u0435\u0442\u0440\u043e\u0432", organisation="Caf\u00e9"))
    assert "N:\u041f\u0435\u0442\u0440\u043e\u0432;\u0418\u0432\u0430\u043d;;;" in text and "ORG:Caf\u00e9" in text


@pytest.mark.parametrize("field, value, label", [("email", "ann.lee", "Email"), ("phone", "call me", "Phone"), ("mobile", "12", "Mobile"),
                                                 ("phone", "+1+415", "Phone")])
def test_a_contact_card_names_the_field_that_is_wrong(field, value, label):
    message = refused("vcard", first_name="Ann", **{field: value})
    assert message.startswith(label + ":")


# -- payload: text ---------------------------------------------------------------------------------------
def test_text_is_carried_as_typed_with_its_line_breaks_and_any_script():
    assert Q.payload(qr("text", text="  Line 1\r\nLine 2 ; , : \" \\ " + CYRILLIC + " \u00fc \U0001F600  ")) == \
        "Line 1\nLine 2 ; , : \" \\ " + CYRILLIC + " \u00fc \U0001F600"


def test_text_is_refused_when_empty_or_longer_than_a_thousand_characters():
    assert len(Q.payload(qr("text", text="a" * 1000))) == 1000
    assert "1000" in refused("text", text="a" * 1001) and refused("text", text="a" * 1001).startswith("Text:")
    assert refused("text", text="  \n ").startswith("Text:")


# -- payload: Wi-Fi --------------------------------------------------------------------------------------
def test_a_wifi_code_has_the_security_name_and_password_and_the_hidden_flag_when_set():
    assert Q.payload(qr("wifi", ssid="Cafe", password="secret123")) == "WIFI:T:WPA;S:Cafe;P:secret123;;"
    assert Q.payload(qr("wifi", ssid="Cafe", password="secret123", hidden=True)) == "WIFI:T:WPA;S:Cafe;P:secret123;H:true;;"
    assert Q.payload(qr("wifi", ssid="Cafe", password="0123456789", security="wep")) == "WIFI:T:WEP;S:Cafe;P:0123456789;;"
    assert Q.payload(sample("wifi")) == "WIFI:T:WPA;S:Workshop;P:s3cret\\;pass;H:true;;"


def test_an_open_wifi_network_has_no_password_even_when_one_was_typed():
    assert Q.payload(qr("wifi", ssid="Guest", security="nopass")) == "WIFI:T:nopass;S:Guest;;"
    assert Q.payload(qr("wifi", ssid="Guest", security="nopass", password="ignored", hidden=True)) == "WIFI:T:nopass;S:Guest;H:true;;"


def test_a_wifi_name_and_password_escape_backslash_semicolon_comma_colon_and_quote():
    text = Q.payload(qr("wifi", ssid='a\\b;c,d:e"f', password='p\\;,:"q'))
    assert text == 'WIFI:T:WPA;S:a\\\\b\\;c\\,d\\:e\\"f;P:p\\\\\\;\\,\\:\\"q;;'


def test_a_wifi_name_may_be_in_any_script_up_to_thirty_two_bytes():
    assert Q.payload(qr("wifi", ssid="a" * 32, security="nopass")).startswith("WIFI:T:nopass;S:" + "a" * 32)
    assert Q.payload(qr("wifi", ssid="\u0434" * 16, security="nopass")).count("\u0434") == 16
    message = refused("wifi", ssid="\u0434" * 17, security="nopass")
    assert message.startswith("Network name (SSID):") and "32" in message


@pytest.mark.parametrize("fields, label", [({}, "Network name (SSID)"), ({"ssid": "Cafe"}, "Password"),
                                           ({"ssid": "Cafe", "password": "x" * 65}, "Password")])
def test_a_wifi_code_names_what_is_missing(fields, label):
    assert refused("wifi", **fields).startswith(label + ":")


# -- payload: email --------------------------------------------------------------------------------------
def test_an_email_code_is_a_mailto_with_a_percent_encoded_subject_and_message():
    assert Q.payload(qr("email", address="ann@lee.example")) == "mailto:ann@lee.example"
    assert Q.payload(qr("email", address="ann@lee.example", subject="Hello & goodbye = 100%")) == \
        "mailto:ann@lee.example?subject=Hello%20%26%20goodbye%20%3D%20100%25"
    assert Q.payload(qr("email", address="ann@lee.example", subject="Hi", body="Line 1\nCaf\u00e9 " + "\u0434")) == \
        "mailto:ann@lee.example?subject=Hi&body=Line%201%0D%0ACaf%C3%A9%20%D0%B4"
    assert Q.payload(qr("email", address="ann@lee.example", body="only a message")) == "mailto:ann@lee.example?body=only%20a%20message"
    assert Q.payload(qr("email", address="a+tag@lee.example")) == "mailto:a+tag@lee.example"


@pytest.mark.parametrize("address", ["", "ann", "ann@", "@lee.example", "ann@lee", "ann lee@lee.example", "a@@b.example", "ann@lee.e",
                                     "a@" + "b" * 250 + ".example"])
def test_an_email_address_must_look_like_one(address):
    assert refused("email", address=address).startswith("Email address:")


def test_an_email_subject_and_message_have_a_limit():
    assert refused("email", address="a@b.example", subject="s" * 201).startswith("Subject:")
    assert refused("email", address="a@b.example", body="b" * 1001).startswith("Message:")


# -- payload: telephone ----------------------------------------------------------------------------------
@pytest.mark.parametrize("given, expected", [("+1 (415) 555-0100", "tel:+1(415)555-0100"), ("020 7946 0958", "tel:02079460958"),
                                             ("+14155550100", "tel:+14155550100"), ("112", "tel:112"), (" +49 30 123456 ", "tel:+4930123456")])
def test_a_phone_code_keeps_digits_plus_and_separators_without_spaces(given, expected):
    assert Q.payload(qr("phone", number=given)) == expected


@pytest.mark.parametrize("given", ["", "call me", "12", "+1+415", "1+415 555 0100", "415.555.0100", "1234567890123456", "+1 (415) x5"])
def test_a_phone_number_with_anything_else_is_refused_naming_the_field(given):
    assert refused("phone", number=given).startswith("Phone number:")


# -- matrix and modules ----------------------------------------------------------------------------------
FINDER = np.array([[1, 1, 1, 1, 1, 1, 1], [1, 0, 0, 0, 0, 0, 1], [1, 0, 1, 1, 1, 0, 1], [1, 0, 1, 1, 1, 0, 1], [1, 0, 1, 1, 1, 0, 1],
                   [1, 0, 0, 0, 0, 0, 1], [1, 1, 1, 1, 1, 1, 1]], bool)


@pytest.mark.parametrize("kind", Q.KINDS)
@pytest.mark.parametrize("ecc", Q.ECC_LEVELS)
def test_the_matrix_is_the_symbol_without_any_border(kind, ecc):
    m = Q.matrix(sample(kind, ecc))
    n = m.shape[0]
    assert m.dtype == bool and m.shape == (n, n) and 21 <= n <= 177 and (n - 17) % 4 == 0
    assert m[0].any() and m[-1].any() and m[:, 0].any() and m[:, -1].any()          # the symbol touches all four sides
    assert (m[:7, :7] == FINDER).all() and (m[:7, -7:] == FINDER).all() and (m[-7:, :7] == FINDER).all()
    assert Q.modules(sample(kind, ecc)) == n


def test_the_matrix_is_a_copy_the_caller_may_change():
    first = Q.matrix(sample("link"))
    first[:] = False
    assert Q.matrix(sample("link")).any()


def test_the_module_count_grows_with_the_content_and_with_the_error_correction():
    sizes = [Q.modules(qr("link", url=link(n))) for n in (25, 60, 120, 400, 1200)]
    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes)
    assert Q.modules(qr("link", url="https://example.com")) == 25
    for kind in Q.KINDS:
        counts = [Q.modules(sample(kind, ecc)) for ecc in Q.ECC_LEVELS]
        assert counts == sorted(counts), kind
    assert Q.modules(sample("vcard", "H")) > Q.modules(sample("vcard", "L"))


def test_the_error_correction_level_is_the_one_asked_for():
    """A 1500-character link fits at level Q and not at H: the level reaches the encoder, with a plain message when it does not fit."""
    long = qr("link", url=link(1500))
    assert Q.modules({**long, "ecc": "L"}) < Q.modules({**long, "ecc": "M"}) < Q.modules({**long, "ecc": "Q"}) <= 177
    with pytest.raises(su.ValidationError) as caught:
        Q.matrix({**long, "ecc": "H"})
    assert "error correction H" in str(caught.value) and "shorten" in str(caught.value)
    with pytest.raises(su.ValidationError):
        Q.geometry({**long, "ecc": "H"}, 20)


def test_the_matrix_of_incomplete_content_is_refused_like_the_payload():
    with pytest.raises(su.ValidationError, match="Web address"):
        Q.matrix(qr("link"))
    with pytest.raises(su.ValidationError, match="Web address"):
        Q.modules(qr("link"))


def _first_length_with(ecc, side):
    """The shortest link whose symbol has ``side`` modules (the encoder's choice is monotone in the length)."""
    lo, hi = 20, 2000
    while lo < hi:
        mid = (lo + hi) // 2
        try:
            big = Q._encode(link(mid), ecc, 0).shape[0] - 4 >= side
        except su.ValidationError:
            big = True
        lo, hi = (lo, mid) if big else (mid + 1, hi)
    return lo


@pytest.mark.parametrize("ecc", Q.ECC_LEVELS)
def test_a_code_the_encoder_would_make_unreadable_is_made_one_version_larger(ecc):
    """OpenCV 5.0's encoder makes version 21 (101 x 101 modules) a symbol no reader can open; a code is never made of it."""
    url = link(_first_length_with(ecc, 101))
    assert Q._encode(url, ecc, 0).shape[0] - 4 == 101                        # the premise: the encoder itself would pick version 21
    m = Q.matrix(qr("link", ecc, url=url))
    assert m.shape == (105, 105)
    assert Q.decode(m) == url


@pytest.mark.parametrize("length", [30, 150, 300, 700])
def test_codes_of_many_sizes_read_back(length):
    for ecc in ("L", "H"):
        url = link(length)
        try:
            m = Q.matrix(qr("link", ecc, url=url))
        except su.ValidationError:
            continue                                            # too long for H at this length
        assert Q.decode(m) == url, (ecc, m.shape)


# -- geometry --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", Q.KINDS)
@pytest.mark.parametrize("ecc", Q.ECC_LEVELS)
def test_the_geometry_carries_the_content(kind, ecc):
    g = Q.geometry(sample(kind, ecc), 20.0)
    assert Q.decode(g) == Q.payload(sample(kind, ecc))


def test_the_geometry_covers_the_square_centred_on_the_origin():
    for size in (17.5, 10.0, 31.25):
        g = Q.geometry(sample("vcard"), size)
        assert g.is_valid and not g.is_empty and g.geom_type in ("Polygon", "MultiPolygon")
        assert g.bounds == pytest.approx((-size / 2, -size / 2, size / 2, size / 2), abs=1e-9)
        assert g.centroid.x == pytest.approx(0, abs=size * 0.1) and g.centroid.y == pytest.approx(0, abs=size * 0.1)


def test_the_geometry_is_the_dark_modules_exactly_y_down_with_module_exact_edges():
    for kind in ("link", "wifi"):
        m = Q.matrix(sample(kind))
        n, size = m.shape[0], 25.0
        module = size / n
        g = Q.geometry(sample(kind), size)
        assert g.area == pytest.approx(m.sum() * module ** 2, rel=1e-9)
        rows, cols = np.indices(m.shape)
        x, y = -size / 2 + (cols + 0.5) * module, -size / 2 + (rows + 0.5) * module           # row 0 is the top, y grows downwards
        assert (shapely.contains_xy(g, x.ravel(), y.ravel()) == m.ravel()).all()
        for part in getattr(g, "geoms", [g]):
            for ring in [part.exterior, *part.interiors]:
                for px, py in ring.coords:
                    for v in (px, py):
                        cells = (v + size / 2) / module
                        assert cells == pytest.approx(round(cells), abs=1e-7)                  # every corner is on a module edge


def test_adjacent_modules_are_one_shape_not_slivers():
    g = Q.geometry(sample("link"), 20.0)
    n = Q.modules(sample("link"))
    top_left_finder = shapely.contains_xy(g, -10 + 0.5 * 20 / n, -10 + 0.5 * 20 / n)
    assert top_left_finder
    assert len(getattr(g, "geoms", [g])) < Q.matrix(sample("link")).sum() / 4
    assert shapely.get_num_coordinates(g) < 4 * Q.matrix(sample("link")).sum()


def test_the_geometry_scales_with_the_size_and_is_the_same_for_the_same_code():
    a, b = Q.geometry(sample("link"), 10.0), Q.geometry(sample("link"), 20.0)
    assert b.area == pytest.approx(4 * a.area, rel=1e-9)
    assert a.equals(Q.geometry(sample("link"), 10.0))
    assert not a.equals(Q.geometry(sample("text"), 10.0))


@pytest.mark.parametrize("size", [0, -5, float("nan"), float("inf"), "wide", None])
def test_the_geometry_needs_a_finite_positive_size(size):
    with pytest.raises(su.ValidationError):
        Q.geometry(sample("link"), size)


# -- reading a symbol back -------------------------------------------------------------------------------
def test_decode_reads_geometry_modules_and_images():
    c = sample("text")
    g, m, text = Q.geometry(c, 12.0), Q.matrix(c), Q.payload(c)
    assert Q.decode(g) == Q.decode(m) == text
    picture = np.kron(np.where(np.pad(m, 4), 0, 255).astype(np.uint8), np.ones((6, 6), np.uint8))
    assert Q.decode(picture) == text
    assert Q.decode(np.stack([picture] * 3, axis=-1)) == text                       # a colour image
    assert Q.decode(255 - picture) is None or Q.decode(255 - picture) == text       # an inverted one may or may not be read


def test_decode_reads_geometry_that_was_moved_or_turned():
    c = sample("link")
    g = Q.geometry(c, 14.0)
    assert Q.decode(affinity.translate(g, 40, 20)) == Q.payload(c)
    assert Q.decode(affinity.rotate(g, 90, origin=(0, 0))) == Q.payload(c)
    assert Q.decode(affinity.rotate(g, 30, origin=(0, 0))) == Q.payload(c)
    assert Q.decode(affinity.translate(affinity.rotate(g, -17, origin=(0, 0)), 30, 30)) == Q.payload(c)


def test_decode_answers_none_when_there_is_no_code():
    assert Q.decode(np.full((200, 200), 255, np.uint8)) is None
    assert Q.decode(np.random.default_rng(1).integers(0, 255, (200, 200), dtype=np.uint8)) is None
    assert Q.decode(box(0, 0, 10, 10)) is None
    assert Q.decode(shapely.Polygon()) is None
    assert Q.decode(np.zeros((3, 3, 3, 3), bool)) is None
    assert Q.decode(np.zeros((25, 25), bool)) is None


def test_a_code_that_is_engraved_small_is_still_the_same_code():
    c = sample("link")
    assert Q.decode(Q.geometry(c, 5.0)) == Q.payload(c)                               # 0.2 mm modules: a warning, not a different code


# -- check: module size and quiet zone (DEC-038, DEC-040) ---------------------------------------------------
def codes(result):
    return [w["code"] for w in result["warnings"]]


def test_the_result_names_the_values_the_thresholds_and_the_note():
    r = Q.check(10.0, 25, 2.0)
    assert r["module_mm"] == pytest.approx(0.4) and r["quiet_modules"] == pytest.approx(5.0)
    assert r["thresholds"] == Q.THRESHOLDS == {"module_mm": 0.40, "quiet_modules": 4.0}
    assert r["note"] == "Passing these checks does not guarantee that the engraved code will scan."
    assert r["warnings"] == []
    r["thresholds"]["module_mm"] = 9
    assert Q.THRESHOLDS["module_mm"] == 0.40                                      # the thresholds live in one place


def test_a_module_below_040_mm_warns_and_040_and_above_do_not():
    low = Q.check(7.75, 25, 5.0)                                                  # 0.31 mm
    assert codes(low) == ["module_size"]
    w = low["warnings"][0]
    assert w["message"] == "The module is 0.31 mm; below 0.40 mm a phone may not read the engraved code."
    assert w["value"] == pytest.approx(0.31) and w["threshold"] == 0.40
    assert codes(Q.check(10.0, 25, 5.0)) == []                                    # exactly 0.40 mm
    assert codes(Q.check(12.5, 25, 5.0)) == []                                    # 0.50 mm
    just_below = Q.check(9.99, 25, 5.0)                                           # 0.3996 mm must not read as "0.40 mm"
    assert codes(just_below) == ["module_size"]
    shown = float(re.search(r"module is ([0-9.]+) mm", just_below["warnings"][0]["message"]).group(1))
    assert shown < 0.40


def test_a_quiet_zone_below_4_modules_warns_and_4_and_above_do_not():
    assert codes(Q.check(10.0, 25, 1.6)) == []                                    # exactly 4 modules of 0.4 mm
    assert codes(Q.check(10.0, 25, 2.4)) == []                                    # 6
    w = Q.check(10.0, 25, 1.56)["warnings"]                                       # 3.9 modules
    assert [x["code"] for x in w] == ["quiet_zone"] and w[0]["value"] == pytest.approx(3.9) and w[0]["threshold"] == 4.0
    assert w[0]["message"] == "The quiet zone is 3.9 modules; keep at least 4 modules empty around the code."
    assert Q.check(10.0, 25, 1.0)["warnings"][0]["message"] == "The quiet zone is 2.5 modules; keep at least 4 modules empty around the code."
    assert codes(Q.check(10.0, 25, 0.0)) == ["quiet_zone"]
    assert Q.check(10.0, 25, 1.599)["warnings"][0]["message"].startswith("The quiet zone is 3.99")


def test_the_two_warnings_are_independent():
    assert codes(Q.check(7.5, 25, 5.0)) == ["module_size"]                        # small modules, plenty of room
    assert codes(Q.check(15.0, 25, 0.6)) == ["quiet_zone"]                        # 0.6 mm modules, a one-module zone
    both = Q.check(7.5, 25, 0.3)                                                  # 0.3 mm modules, a one-module zone
    assert codes(both) == ["module_size", "quiet_zone"]
    assert both["warnings"][1]["value"] == pytest.approx(1.0)
    assert both["module_mm"] == pytest.approx(0.3) and both["quiet_modules"] == pytest.approx(1.0)


def test_a_quiet_zone_is_counted_in_modules_of_this_code():
    assert Q.check(20.0, 50, 1.6)["quiet_modules"] == pytest.approx(4.0)          # 0.4 mm modules
    assert Q.check(40.0, 50, 1.6)["quiet_modules"] == pytest.approx(2.0)          # 0.8 mm modules: the same gap is fewer modules


@pytest.mark.parametrize("size, count, gap", [(0, 25, 1), (-1, 25, 1), (10, 0, 1), (10, 25, -0.1), (float("nan"), 25, 1), (10, 25, float("nan")),
                                              (10, 25, float("inf")), ("x", 25, 1)])
def test_a_check_of_nonsense_numbers_is_refused(size, count, gap):
    with pytest.raises(su.ValidationError):
        Q.check(size, count, gap)


# -- clearance --------------------------------------------------------------------------------------------
CARD = box(0, 0, 85, 54)


def test_the_clearance_is_the_nearest_element_or_the_card_edge():
    symbol = box(10, 10, 20, 20)
    assert Q.clearance(symbol, [], CARD) == pytest.approx(10.0)                                  # the left and top edges
    assert Q.clearance(symbol, [box(23, 10, 40, 20)], CARD) == pytest.approx(3.0)                # a neighbour closer than the edge
    assert Q.clearance(symbol, [box(60, 10, 70, 20), box(12, 25.5, 18, 30)], CARD) == pytest.approx(5.5)
    assert Q.clearance(box(1, 10, 11, 20), [box(30, 10, 40, 20)], CARD) == pytest.approx(1.0)    # the edge closer than a neighbour
    assert Q.clearance(box(75, 40, 83.5, 50), [], CARD) == pytest.approx(1.5)                    # the right edge
    assert Q.clearance(box(10, 44, 20, 53.2), [], CARD) == pytest.approx(0.8)                    # the bottom edge


def test_the_clearance_is_zero_when_the_symbol_touches_overlaps_or_leaves_the_card():
    symbol = box(10, 10, 20, 20)
    assert Q.clearance(symbol, [box(15, 15, 30, 30)], CARD) == 0.0
    assert Q.clearance(symbol, [box(20, 10, 30, 20)], CARD) == 0.0                                # touching
    assert Q.clearance(symbol, [box(0, 0, 85, 54)], CARD) == 0.0                                  # underneath
    assert Q.clearance(box(-5, 10, 5, 20), [], CARD) == 0.0                                       # across the edge
    assert Q.clearance(box(100, 10, 110, 20), [], CARD) == 0.0                                    # beside the card
    assert Q.clearance(box(0, 10, 10, 20), [], CARD) == 0.0                                       # on the edge


def test_the_clearance_ignores_empty_and_missing_geometries_and_an_empty_symbol_has_none():
    symbol = box(10, 10, 20, 20)
    assert Q.clearance(symbol, [None, shapely.Polygon(), box(24, 10, 30, 20)], CARD) == pytest.approx(4.0)
    assert Q.clearance(shapely.Polygon(), [], CARD) == 0.0 and Q.clearance(None, [], CARD) == 0.0


def test_the_clearance_with_nothing_near_is_large_but_not_beyond_the_card():
    assert Q.clearance(box(40, 20, 45, 25), [], CARD) == pytest.approx(20.0)                      # the nearest edge
    assert Q.clearance(box(40, 20, 45, 25), [box(0, 0, 1, 1)], None) == pytest.approx((39 ** 2 + 19 ** 2) ** 0.5)       # no card edge
    assert Q.clearance(box(40, 20, 45, 25), [], None) == Q.UNLIMITED_MM
    assert Q.clearance(box(40, 20, 45, 25), [], CARD) <= max(85, 54)


def test_the_clearance_of_a_symbol_is_measured_from_the_whole_square_of_the_code():
    g = affinity.translate(Q.geometry(sample("link"), 10.0), 40, 27)
    n = Q.modules(sample("link"))
    m = 10.0 / n
    # a small element in the white ring just inside the top-left finder pattern: on the code, whatever the dark modules around it
    inside = box(35 + 1.2 * m, 22 + 1.2 * m, 35 + 1.8 * m, 22 + 1.8 * m)
    assert g.distance(inside) > 0 and Q.clearance(g, [inside], CARD) == 0.0
    outside = box(46, 22, 50, 32)                                                                 # 1 mm from the square's right side
    assert Q.clearance(g, [outside], CARD) == pytest.approx(1.0)


def test_the_clearance_of_a_turned_symbol_is_measured_from_its_turned_square():
    g = affinity.translate(affinity.rotate(Q.geometry(sample("link"), 10.0), 45, origin=(0, 0)), 30, 27)
    corner = 30 + 5 * 2 ** 0.5                                                                    # the right corner of the turned square
    assert Q.clearance(g, [box(corner + 2, 0, 60, 54)], CARD) == pytest.approx(2.0, abs=1e-6)
    # axis-aligned bounds would say 0 for a neighbour inside the turned square's bounding box but outside the square itself
    assert Q.clearance(g, [box(35.2, 19.5, 36.0, 20.3)], CARD) == pytest.approx(
        g.minimum_rotated_rectangle.distance(box(35.2, 19.5, 36.0, 20.3)))
    assert Q.clearance(g, [box(35.2, 19.5, 36.0, 20.3)], CARD) > 0.5


# -- placed_check ---------------------------------------------------------------------------------------
def placed(size, dx=42.5, dy=27.0):
    """The code of a short link (25 modules, so 12.5 mm is 0.5 mm a module) centred at (dx, dy) on the card."""
    c = qr("link", url="https://example.com")
    return c, affinity.translate(Q.geometry(c, size), dx, dy)


def test_a_placed_code_reports_its_content_modules_and_checks():
    c, g = placed(12.5)
    r = Q.placed_check(c, 12.5, g, [], CARD)
    assert r["content"] == Q.payload(c) and r["modules"] == Q.modules(c)
    assert r["module_mm"] == pytest.approx(12.5 / r["modules"])
    assert r["clearance_mm"] == pytest.approx(27.0 - 6.25) and r["quiet_modules"] == pytest.approx(r["clearance_mm"] / r["module_mm"])
    assert r["warnings"] == [] and r["thresholds"] == Q.THRESHOLDS and r["note"] == Q.NOTE


def test_a_placed_code_warns_for_small_modules_and_for_a_crowded_neighbour_separately():
    c, g = placed(7.0)
    small = Q.placed_check(c, 7.0, g, [], CARD)
    assert codes(small) == ["module_size"] and small["module_mm"] == pytest.approx(7.0 / small["modules"])
    c, g = placed(12.5)
    crowded = Q.placed_check(c, 12.5, g, [box(50, 20, 60, 34)], CARD)                             # 1.25 mm from the symbol's right side
    assert codes(crowded) == ["quiet_zone"]
    assert crowded["clearance_mm"] == pytest.approx(1.25) and crowded["quiet_modules"] == pytest.approx(1.25 / 0.5)
    c, g = placed(7.0)
    both = Q.placed_check(c, 7.0, g, [box(46.5, 20, 60, 34)], CARD)                               # 0.5 mm = 1.8 modules of 0.28 mm
    assert codes(both) == ["module_size", "quiet_zone"]


def test_a_placed_code_that_is_not_yet_complete_is_refused_like_its_payload():
    with pytest.raises(su.ValidationError, match="Web address"):
        Q.placed_check(qr("link"), 12.5, box(0, 0, 1, 1), [], CARD)
