"""Domain guarantees the UX P0 pass must not break (feature ux-validation-p0, REQ-003; research n58, protocol section 4 of
docs/validation/ux-p0-protocol.md).

The guarantees already have tests in the files that own them (the table in docs/validation/ux-p0-guarantees.md names them). This file holds
what those tests did not prove or no longer prove after the nine features, each one written so that it FAILS when the guarantee breaks:

* the picture a photo work was made from is the same stored file, byte for byte, through a scale, a width and an undo;
* the card, the list and the prediction of a work read the one palette of the work's current width, before and after an undo;
* an older answer for a width the work no longer has cannot replace the palette of its current width (node, BUG-011);
* undoing a resize puts back the size of the exported file, not only the setting;
* every file a work handed out stays as it was after an edit, a repeat export and a restart;
* the findings of an earlier analysis run are stored as they were and the advice on them (the recommended step) is never stored with them;
* the file a photograph pair was made from is not discarded when the operator attaches another one, and the derived review of a pair is
  never stored with its measurements;
* the gate of ``accept_pair`` refuses in every state in which the gate of 0.38.1 refused, with the same words and in the same order;
* «Split again» changes nothing until it is confirmed, and cancelling it changes nothing (node).

Nothing here states a physical limit or a number of the laser: sizes are the ones the tests chose. What only a real browser can prove
(layout, focus, a screen reader) is not claimed: see section 5 of the results file."""
import itertools
import json
from pathlib import Path

from fastapi.testclient import TestClient

from test_findings import add as add_observation, w  # noqa: F401  (a laser with a stock; fixture)
from test_grey_scales import app_world, picture_png  # noqa: F401  (the measured grey-ramp plate; fixture)
from test_pair_review import checked, ready, world as pair_world  # noqa: F401  (a plate pair; fixture)
from test_ingest import edited_lbrn
from test_photo_engraving_ui import node, run as work_screen
from test_photo_knowledge import LINEAR, world as photo_world  # noqa: F401  (accepted photo engravings on a laser; fixture)
from test_photo_results import add_photo, mode as scale_mode
from test_photo_works import create as new_photo_work, scale_of, settings as change_work, step as undo_or_redo
from test_scale_palette_context import SNAPSHOT, response
from test_vector_work import colouring, job, routes_of, run_screen, work  # noqa: F401  (fixtures)
from titanium_platform import findings as fd, ingest as ig, lightburn, pair_review as pr, photo_knowledge as pk, photo_results as results, photo_work, setup as su
from titanium_platform.api.app import create_app


# -- the picture is kept (BUG-002) -------------------------------------------------------------------------------------------------------
def test_a_scale_a_width_and_an_undo_keep_the_stored_picture_unchanged(app_world):
    """BUG-002: choosing another scale lost the picture. The work keeps the very file it was made from: the bytes, the stored path, the name
    and the size, whatever scale or width is chosen and whatever is undone; only the prediction drawn from it changes."""
    client = app_world["client"]
    store = client.app.state.store
    work = new_photo_work(client, name="Kept")
    original = client.get(f"/api/photo-works/{work['id']}/picture").content
    stored_path = photo_work._work(store, work["id"])["image_path"]
    assert original == picture_png() and Path(stored_path).read_bytes() == original

    def unchanged(step):
        assert client.get(f"/api/photo-works/{work['id']}/picture").content == original, step
        now = photo_work._work(store, work["id"])
        assert (now["image_path"], now["image_name"], now["image_size"]) == (stored_path, "girl.png", [240, 120]), step
        assert Path(stored_path).read_bytes() == original, step

    other = scale_of(client, 250, 0.0254)
    moved = change_work(client, work, scale=other)
    assert moved["scale"] == other and moved["picture"]["preview"] != work["picture"]["preview"]        # the prediction follows the scale
    unchanged("another scale")
    shown = client.get(moved["picture"]["preview"])
    assert shown.status_code == 200 and shown.headers["content-type"] == "image/png" and len(shown.content) > 1000
    change_work(client, work, width_mm=100)
    unchanged("another width")
    change_work(client, work, scale=work["scale"])
    unchanged("back to the first scale")
    for n in range(3):
        assert undo_or_redo(client, work, "undo").status_code == 200
        unchanged(f"undo {n + 1}")
    assert client.get(f"/api/photo-works/{work['id']}").json()["scale"] == work["scale"]
    copy = client.post(f"/api/photo-works/{work['id']}/copy", json={}).json()
    assert client.get(f"/api/photo-works/{copy['id']}/picture").content == original          # a copy has the picture too, in a file of its own
    assert photo_work._work(store, copy["id"])["image_path"] != stored_path
    unchanged("after a copy")


# -- the card and the prediction read one palette (BUG-011) -----------------------------------------------------------------------------
def test_the_list_the_detail_and_the_prediction_of_a_work_read_the_palette_of_its_current_width_also_after_an_undo(app_world):
    """BUG-011: a card showed the palette of one engraving size and the picture the palette of another. Wherever the work's width is,
    the scale list asked for that width, the detail of the scale and the work's own prediction name the same size selection and the card
    and the detail draw the same colours; an undo of the resize returns all three to the earlier width together."""
    client, laser = app_world["client"], app_world["laser"]
    work = new_photo_work(client, name="Palette")

    def agree(row_mm):
        shown = client.get(f"/api/photo-works/{work['id']}").json()
        assert shown["width_mm"] == row_mm
        listed = client.get("/api/grey-scales", params={"device_id": laser["id"], "row_mm": row_mm}).json()["scales"]
        card = next(s for s in listed if s["mode"] == shown["scale"])
        detail = client.get("/api/grey-scales/scale", params={**shown["scale"], "row_mm": row_mm}).json()
        assert card["size"]["row_mm"] == detail["size"]["row_mm"] == shown["picture"]["scale_size"]["row_mm"] == row_mm
        assert card["size"] == detail["size"] == shown["picture"]["scale_size"]                  # the same selection of measured sizes, not only the same number
        assert card["bar"] == detail["bar"] and len(card["bar"]) > 4                             # the card draws what the detail has

    agree(60)
    change_work(client, work, width_mm=120)
    agree(120)
    change_work(client, work, width_mm=90)
    agree(90)
    assert undo_or_redo(client, work, "undo").status_code == 200
    agree(120)
    assert undo_or_redo(client, work, "undo").status_code == 200
    agree(60)


# -- cancelling puts the size back (BUG-011) ---------------------------------------------------------------------------------------------
def test_undoing_a_resize_puts_back_the_size_of_the_exported_file_and_its_picture(app_world):
    """The setting alone is not the guarantee: the LightBurn file written after the undo is the size and the picture of the file written
    before the resize."""
    client = app_world["client"]
    work = new_photo_work(client, name="Back")

    def exported():
        project = lightburn.parse_bytes(client.get(f"/api/photo-works/{work['id']}/export.lbrn2").content)
        region = project.layer(1).regions[0]
        return round(region.width, 3), round(region.height, 3), region.bitmap["png"]

    before = exported()
    assert before[:2] == (60.0, 30.0)
    change_work(client, work, width_mm=100)
    assert exported()[:2] == (100.0, 50.0)
    assert undo_or_redo(client, work, "undo").status_code == 200
    after = exported()
    assert after == before                                                                    # size and picture, byte for byte
    assert client.get(f"/api/photo-works/{work['id']}").json()["width_mm"] == 60
    assert undo_or_redo(client, work, "redo").status_code == 200 and exported()[:2] == (100.0, 50.0)


# -- the colour and the photo engraving are assessed apart ------------------------------------------------------------------------------------
def test_the_colour_verdict_and_the_photo_verdict_of_a_layer_are_two_marks_and_neither_overwrites_or_stands_in_for_the_other(photo_world):  # noqa: F811
    """``test_photo_results`` marks the photo first and the colour second. The other order, and re-marking one aspect, must leave the other
    alone as well: a bad colour does not make a good photo engraving bad (and does not take it off the recommended ones), a withdrawn colour
    verdict does not touch the photo's."""
    w, s = photo_world, photo_world["store"]
    pair = add_photo(w, "C23", LINEAR)
    row, = results.at_mode(s, scale_mode(w))
    results.mark(s, row["source"], "bad", "Gold is wrong", aspect="colour")
    results.mark(s, row["source"], "good", "Photograph is right", aspect="photo")
    found, = results.at_mode(s, scale_mode(w))
    assert found["verdict"] == "good"                                                          # what decides the photo engraving is the photo's mark
    assert found["assessments"] == {"colour": {"verdict": "bad", "note": "Gold is wrong"}, "photo": {"verdict": "good", "note": "Photograph is right"}}
    assert pk.best(s, w["laser"], w["lens"], w["titanium"], "grayscale")["source"]["pair_id"] == pair
    results.mark(s, row["source"], "unrated", aspect="colour")
    results.mark(s, row["source"], "bad", "Too pale", aspect="photo")
    found, = results.at_mode(s, scale_mode(w))
    assert found["assessments"]["colour"] == {"verdict": "unrated", "note": ""} and found["assessments"]["photo"] == {"verdict": "bad", "note": "Too pale"}
    assert s.one("SELECT COUNT(*) AS n FROM photo_result_mark WHERE source_key=?", (found["key"],))["n"] == 2          # one row for each aspect


# -- files are kept ------------------------------------------------------------------------------------------------------------------------
def test_every_file_a_work_handed_out_stays_as_it_was_after_an_edit_a_repeat_export_and_a_restart(work, job):  # noqa: F811
    """A repeat export is a new file (ux-engraving-lifecycle-p0); the files before it are not rewritten, not dropped from the list and still
    downloadable with the bytes that were handed out, also after the application is started again over the same data."""
    c, j = work, job
    client, first_url = c["client"], f"/api/vector/{j['id']}/export.lbrn2"
    handed = [client.get(first_url).content]
    colouring(c, j, op="assign", mode="random")                                              # an edit after the first file
    handed.append(client.get(first_url).content)
    colouring(c, j, op="assign", mode="contrast")
    handed.append(client.get(first_url).content)
    assert len({h for h in handed}) >= 2                                                      # the edits did change the file, so equality below is not vacuous

    def check(who, label):
        for number, body in enumerate(handed, 1):
            got = who.get(f"/api/vector/{j['id']}/exports/{number}")
            assert got.status_code == 200 and got.content == body, (label, number)
        files = who.get(f"/api/vector/{j['id']}").json()["lifecycle"]["files"]
        assert [(f["number"], f["downloadable"], f["recorded"]) for f in files] == [(1, True, True), (2, True, True), (3, True, True)], label

    check(client, "after the exports")
    client.close()
    reopened = TestClient(create_app(c["store"].data_dir))                                   # a new process over the same data directory
    check(reopened, "after a restart")


def test_attaching_another_lightburn_file_to_a_pair_keeps_the_file_it_replaced(pair_world):  # noqa: F811
    """The replaced file is the evidence of what was checked before. It stays on disk with its own bytes; the new one is written beside it."""
    store = pair_world["store"]
    pid = checked(pair_world)
    old = Path(ig.get_pair(store, pid)["lightburn_path"])
    assert old.read_bytes() == pair_world["lbrn"]
    other = edited_lbrn(pair_world, power_for_r1c2=33)
    ig.replace_lightburn_file(store, pid, "other.lbrn2", other)
    new = Path(ig.get_pair(store, pid)["lightburn_path"])
    assert new != old and new.read_bytes() == other
    assert old.is_file() and old.read_bytes() == pair_world["lbrn"]


def test_the_derived_review_of_a_pair_is_never_stored_with_its_measurements(pair_world):  # noqa: F811
    """``pair["review"]`` is worked out on every read (ux-photo-review-p0). Stored beside the measurements it could outlive them and disagree."""
    store = pair_world["store"]
    pid = ready(pair_world)
    ig.accept_pair(store, pid)
    assert "review" in ig.get_pair(store, pid)
    stored = json.loads(store.one("SELECT data_json FROM pair WHERE id=?", (pid,))["data_json"])
    assert "review" not in stored and "review" not in stored["check"]
    ig._save(store, pid, ig.get_pair(store, pid))                                              # a save of what was read does not store it either
    assert "review" not in json.loads(store.one("SELECT data_json FROM pair WHERE id=?", (pid,))["data_json"])
    assert store.one("SELECT COUNT(*) AS n FROM observation WHERE pair_id=?", (pid,))["n"] == 6


def test_the_advice_on_a_finding_is_worked_out_when_it_is_read_and_never_stored_with_its_run(store, w):  # noqa: F811
    """ux-evidence-summaries-p0 adds a recommended step to every finding. ``test_findings`` compares an earlier run with itself ignoring the
    keys that are worked out at read time; that is only sound while the stored rows hold neither. They do not, and a later run leaves the
    rows of the earlier one byte for byte as they were."""
    su.save_rules(store, *w["setup"], repeat_threshold=2, delta_tolerance=10, variance_threshold=2.0)
    for lab in ((50, 0, 0), (56, 0, 0)):
        add_observation(store, w, lab, power=40)
    first = fd.run_analysis(store, "manual")
    read = fd.findings_of(store, first["id"])["findings"]
    assert read and all("recommendation" in f and "remedies" in f for f in read)               # the page carries the advice
    rows = lambda: [r["data_json"] for r in store.query("SELECT data_json FROM finding WHERE run_id=? ORDER BY id", (first["id"],))]  # noqa: E731
    kept = rows()
    assert len(kept) == len(read) and all(not {"recommendation", "remedies"} & set(json.loads(text)) for text in kept)
    for lab in ((53, 0, 0), (53, 0, 0)):
        add_observation(store, w, lab, power=40)
    fd.run_analysis(store, "acceptance")
    assert rows() == kept


# -- the gate of the acceptance is not weaker than 0.38.1 ----------------------------------------------------------------------------------
def gate_of_0_38_1(pair: dict) -> str | None:
    """The conditions ``ingest.accept_pair`` raised on in 0.38.1, in its order, copied from that release (the seven ``raise`` lines the
    feature replaced by ``pair_review.refusal``)."""
    check = pair["check"]
    if not check or pair["status"] != "Ready to accept":
        return "run the check first; the pair is not ready to accept"
    if not check.get("color_measurement"):
        return "the photograph has no usable color measurement basis"
    if check["problems"]:
        return "resolve the problems found by the check: " + "; ".join(check["problems"])
    if check["discrepancies"] and not pair["file_confirmation"]:
        return "the LightBurn file differs from the plate definition: correct the pair or confirm the file"
    if not pair["masks_reviewed"]:
        return "review the layer masks overlaid on the photograph before accepting"
    if pair.get("matrix") and not pair["matrix"].get("confirmed"):
        return "confirm the settings read from the matrix before accepting"
    if not [rep for rep in check["layers"] if rep["measured_lab"] is not None]:
        return "no readable, comparable layer to accept"
    return None


def test_the_acceptance_gate_refuses_in_every_state_the_gate_of_0_38_1_refused_with_the_same_words():
    """All 3 x 2 x 2 x 2 x 2 x 2 x 3 x 2 = 576 combinations of what the gate reads. A legacy confirmation (kept with no copy of the differences)
    covers whatever differences there are, as it did, so the two gates must give the very same answer for each state."""
    layer = {"measured_lab": [50, 0, 0]}
    combos = itertools.product(
        (None, "empty", "checked"),                                 # no check at all / a check with nothing measured
        ("Ready to accept", "Awaiting check"),
        (None, {"mode": "reference_chart_corrected"}),
        ([], ["Alignment: x"]),
        ([], [{"cell_id": "r1c1", "field": "power", "defined": 1, "from_file": 2}]),
        (None, {"text": "used this file"}),                         # no confirmation / a legacy one
        (False, True),
        (None, {"confirmed": False}),
    )
    n = 0
    for shape, status, basis, problems, discrepancies, confirmation, masks, matrix in combos:
        check = None if shape is None else {"color_measurement": basis, "problems": problems, "discrepancies": discrepancies,
                                           "layers": [layer] if shape == "checked" else [{"measured_lab": None}]}
        pair = {"check": check, "status": status, "file_confirmation": confirmation, "masks_reviewed": masks, "matrix": matrix}
        assert pr.refusal(pair) == gate_of_0_38_1(pair), pair
        n += 1
    assert n == 3 * 2 * 2 * 2 * 2 * 2 * 2 * 2
    # a matrix whose settings were confirmed passes as before; a state that passed before still passes
    good = {"check": {"color_measurement": {"mode": "x"}, "problems": [], "discrepancies": [], "layers": [layer]}, "status": "Ready to accept",
            "file_confirmation": None, "masks_reviewed": True, "matrix": {"confirmed": True}}
    assert pr.refusal(good) is None and gate_of_0_38_1(good) is None
    # the one deliberate addition: a confirmation given for other differences than the current ones does not cover them
    differs = {**good, "check": {**good["check"], "discrepancies": [{"cell_id": "r1c1", "field": "power", "defined": 1, "from_file": 2}]},
               "file_confirmation": {"text": "used", "discrepancies": [{"cell_id": "r9c9", "field": "power", "defined": 1, "from_file": 3}]}}
    assert gate_of_0_38_1(differs) is None and pr.refusal(differs) == pr.FILE_DIFFERS


# -- a full re-split asks first (research n58) -----------------------------------------------------------------------------------------------
@node
def test_splitting_again_changes_nothing_until_it_is_confirmed_and_cancelling_changes_nothing(work, job, tmp_path):  # noqa: F811
    """«Split again» restarts the colouring: the colours chosen by hand, the variants and the undo steps of the split are lost. The button
    only opens a confirmation (its focus on «Cancel»); no request goes to the server until «Split again» in the dialog is pressed, and
    Cancel, the cross and Escape each leave the work and the server as they were."""
    routes = routes_of(work, job)
    out = run_screen(tmp_path, job, routes, """
  const posts = () => ctx.requests.filter((r) => r.path.endsWith('/split') && r.method === 'POST').length;
  const modal = () => ctx.document.body.querySelector('.modal');
  const open = async () => { await byText(tree, 'button', 'Split again').dispatch('click'); await tick(); return modal(); };
  let box = await open();
  out.opened = {title: box.getAttribute('aria-label'), text: box.textContent, posts: posts(), focus: ctx.document.activeElement && ctx.document.activeElement.textContent};
  await byText(box, 'button', 'Cancel').dispatch('click'); await tick();
  out.cancelled = {posts: posts(), open: !!modal()};
  box = await open();
  await box.querySelectorAll('button').find((b) => b.getAttribute('aria-label') === 'Close').dispatch('click'); await tick();
  out.crossed = {posts: posts(), open: !!modal()};
  box = await open();
  await ctx.document.dispatch('keydown', {key: 'Escape'}); await tick();
  out.escaped = {posts: posts(), open: !!modal()};
  box = await open();
  await byText(box, 'button', 'Split again').dispatch('click'); await tick(); await tick();
  out.confirmed = {posts: posts(), open: !!modal()};
""")
    assert out["opened"]["title"] == "Split the image again?" and out["opened"]["posts"] == 0
    for lost in ("coloring will restart", "manually selected colors", "coloring variants", "undo history"):
        assert lost in out["opened"]["text"], lost                                           # the dialog says what is lost
    assert "Previous LightBurn files and engraving results remain" in out["opened"]["text"]   # and what is kept
    assert out["opened"]["focus"] == "Cancel"                                                 # a quick Enter cannot confirm
    assert out["cancelled"] == {"posts": 0, "open": False}
    assert out["crossed"] == {"posts": 0, "open": False}
    assert out["escaped"] == {"posts": 0, "open": False}
    assert out["confirmed"] == {"posts": 1, "open": False}


# -- an older answer cannot replace the palette of the width the work has now (BUG-011) ---------------------------------------------------------
@node
def test_a_late_palette_answer_for_an_older_width_cannot_replace_the_palette_of_the_current_width(tmp_path):
    """The list of scales for 120 mm is on its way when the operator makes the work 90 mm. The answer for 120 mm arrives last: it is dropped,
    nothing for 120 mm is asked afterwards, and the card and the prediction strip stay the palette of 90 mm. (``test_scale_palette_context``
    holds the same for an undo; this is the second way a width is replaced.)"""
    at_120, at_90 = json.dumps(response(120)), json.dumps(response(90))
    result = work_screen(tmp_path, {"work": "7"}, SNAPSHOT + """
  const originalFetch = ctx.fetch;
  let release;
  const delayed = new Promise((resolve) => { release = resolve; });
  ctx.fetch = async (url, options) => {
    const result = await originalFetch(url, options);
    if (String(url).startsWith('/api/grey-scales?') && new URLSearchParams(String(url).split('?')[1]).get('row_mm') === '120') await delayed;
    return result;
  };
  const width = labelled(tree, 'Width on titanium, mm');
  data.scale = %s;
  width.value = '120'; await width.dispatch('change'); await settle();
  out.waiting = tree.textContent.includes('Loading scales for the work width');
  data.scale = %s;
  width.value = '90'; await width.dispatch('change'); await settle(); await wait(50); await settle();
  out.fresh = snapshot();
  out.widthNow = labelled(tree, 'Width on titanium, mm').value;
  release(); await settle(); await wait(50); await settle();
  out.late = snapshot();
  out.asked = requests.filter((r) => r.path === '/api/grey-scales/scale').map((r) => new URLSearchParams(r.url.split('?')[1]).get('row_mm'));
  out.listed = requests.filter((r) => r.path === '/api/grey-scales').map((r) => new URLSearchParams(r.url.split('?')[1]).get('row_mm'));
""" % (at_120, at_90), scale_data=response(60))
    assert result["waiting"] and result["widthNow"] == "90"
    assert result["listed"] == ["60", "120", "90"]
    assert "Colors at width 90 mm" in result["fresh"]["text"]
    assert result["late"] == result["fresh"]                                       # the late answer changed nothing on the screen
    assert result["late"]["card"] == result["late"]["preview"] and len(result["late"]["card"]) == 64
    assert "120" not in result["asked"] and result["asked"][-1] == "90"            # and the scale of 120 mm was never asked for


# -- the two halves of the guard of the palette are each held by a test of their own (BUG-002, BUG-011) -------------------------------------
# photo-engraving.js drops the answer of the list of scales when ``scalesRequest !== request || view.width_mm !== width``. The test above
# removes both halves at once. The two below each need one of them: (a) the identity of the request, (b) the width of the work. The list of
# scales is told apart by the time per cm² it names (the card of the work's scale prints it), which the test sets before each request.
PALETTE_PROBE = """
  const widthBox = labelled(tree, 'Width on titanium, mm');
  const mark = (seconds) => { data.scales = data.scales.map((s) => ({...s, time_s_per_cm2: seconds})); };           // what the next list will say
  const marker = () => (tree.querySelector('.ge-scale.is-chosen').textContent.match(/(\\d+) s\\/cm²/) || [])[1];
  const listed = () => requests.filter((r) => r.path === '/api/grey-scales').map((r) => new URLSearchParams(r.url.split('?')[1]).get('row_mm'));
  const quiet = async () => { await settle(); await wait(50); await settle(); };
  const originalFetch = ctx.fetch, gates = {};
  const arm = (width) => { let release; const held = new Promise((resolve) => { release = resolve; }); gates[width] = held; return release; };
  ctx.fetch = async (url, options) => {                                  // the answer to the next list for this width is held; the one after it is not
    const result = await originalFetch(url, options);
    if (String(url).startsWith('/api/grey-scales?')) {
      const asked = new URLSearchParams(String(url).split('?')[1]).get('row_mm');
      if (gates[asked]) { const held = gates[asked]; delete gates[asked]; await held; }
    }
    return result;
  };
"""


@node
def test_a_late_answer_of_an_older_request_for_the_same_width_cannot_replace_the_answer_of_the_newer_one(tmp_path):
    """(a) The list for 120 mm is asked and held. The work goes to 90 mm and back to 120 mm: the list for 120 mm is asked again and answered at
    once. The first answer arrives last. The width of the work is 120 mm again, so only the identity of the request tells it is the older
    answer: it must be dropped and the card keeps what the newer answer said. (Without the check of the request the old list wins.)"""
    result = work_screen(tmp_path, {"work": "7"}, PALETTE_PROBE + """
  mark(61); data.scale = %s;
  const release120 = arm('120');
  width = widthBox; width.value = '120'; await width.dispatch('change'); await quiet();
  out.pending = {loading: tree.textContent.includes('Loading scales'), marker: marker()};
  mark(62); data.scale = %s;
  width.value = '90'; await width.dispatch('change'); await quiet();
  out.at90 = marker();
  mark(63); data.scale = %s;
  width.value = '120'; await width.dispatch('change'); await quiet();
  out.at120 = {marker: marker(), text: tree.querySelector('.ge-scale.is-chosen').textContent.includes('Colors at width 120 mm')};
  release120(); await quiet();
  out.late = {marker: marker(), text: tree.querySelector('.ge-scale.is-chosen').textContent.includes('Colors at width 120 mm'), box: widthBox.value};
  out.listed = listed();
""" % (json.dumps(response(120)), json.dumps(response(90)), json.dumps(response(120))))
    assert result["pending"] == {"loading": True, "marker": "70"}                  # the old list stays while the new one is awaited
    assert result["at90"] == "62" and result["at120"] == {"marker": "63", "text": True}
    assert result["listed"] == ["60", "120", "90", "120"]                         # one list for each time the work took a width
    assert result["late"] == {"marker": "63", "text": True, "box": "120"}          # the late answer (61) changed nothing


@node
def test_an_answer_for_a_width_the_work_has_left_while_its_changes_were_still_on_their_way_is_dropped(tmp_path):
    """(b) The list for 120 mm is asked and held. Two more changes of the width are sent one after another (80 mm, then 90 mm). When the first
    of them is answered the work is 80 mm, but the screen is drawn again only after the last answer, so the request of the list for 120 mm is
    still the newest one: only the width of the work tells the answer is for a width it has left. It must be dropped, and no list may be asked
    for 80 mm, a width the work had only between two answers. (Without the check of the width the old list is taken and 80 mm is asked.)"""
    result = work_screen(tmp_path, {"work": "7"}, PALETTE_PROBE + """
  mark(61); data.scale = %s;
  const release120 = arm('120');
  const width = widthBox; width.value = '120'; await width.dispatch('change'); await quiet();
  out.pending = {loading: tree.textContent.includes('Loading scales'), marker: marker()};
  let release80, release90;
  hold.push(new Promise((resolve) => { release80 = resolve; }), new Promise((resolve) => { release90 = resolve; }));
  const saved = () => requests.filter((r) => r.path === '/api/photo-works/7/settings').map((r) => r.body.width_mm);
  width.value = '80'; width.dispatch('change'); await settle();                 // sent, its answer held
  width.value = '90'; width.dispatch('change'); await settle();                 // waits behind it
  release80(); await settle();                                                   // the work is 80 mm now; the change to 90 mm is on its way
  out.between = {saved: saved(), listed: listed(), loading: tree.textContent.includes('Loading scales')};
  mark(63); data.scale = %s;
  release120(); await quiet();                                                   // the answer for 120 mm arrives while the work is 80 mm
  out.stale = {listed: listed(), marker: marker(), loading: tree.textContent.includes('Loading scales')};
  release90(); await quiet();
  out.end = {listed: listed(), marker: marker(), text: tree.querySelector('.ge-scale.is-chosen').textContent.includes('Colors at width 90 mm'), box: width.value};
""" % (json.dumps(response(120)), json.dumps(response(90))))
    assert result["pending"] == {"loading": True, "marker": "70"}
    assert result["between"] == {"saved": [120, 80, 90], "listed": ["60", "120"], "loading": True}      # all three changes were sent in order
    assert result["stale"] == {"listed": ["60", "120"], "marker": "70", "loading": True}     # dropped: nothing taken from it, nothing asked for 80 mm
    assert result["end"] == {"listed": ["60", "120", "90"], "marker": "63", "text": True, "box": "90"}
