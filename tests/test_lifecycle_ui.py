"""The path of a work's file and its readiness on the screens (feature ux-engraving-lifecycle-p0, REQ-001..003): the four steps with the
current one marked in words, what can be done next, why a file cannot be made yet with a button to the place that fixes it, the one
«Download LightBurn» action (one request at a time, a failure kept beside the button with a retry), the files made before, the basis a
comparison stands on, and the way back to a work after an accepted result. Run in node over the small DOM of ui_dom.js with answers
shaped as the server's lifecycle answer (the server side has its own tests: test_lifecycle.py, test_lifecycle_traced.py)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from lifecycle_stub import file_record, lifecycle
from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
GLUE = ("const __went = [], __renders = []; App.go = (route) => { __went.push(route); }; App.render = () => { __renders.push(1); };"
        "globalThis.__went = __went; globalThis.__renders = __renders;")
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes || {});
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', 'list.js', 'hardware.js', {code: %(glue)s}, 'screens/lifecycle.js', 'screens/vector-review.js',
  'screens/prediction-review.js', {code: 'globalThis.LC = Lifecycle; globalThis.VR = VectorReview; globalThis.PR = PredictionReview;'}]);
const tick = () => new Promise((r) => setTimeout(r, 0));
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const toasts = () => ctx.document.body.querySelectorAll('div').filter((d) => (d.className || '').split(' ')[0] === 'toast').map((d) => d.textContent.replace(/\s*×$/, ''));
const LC = ctx.LC, VR = ctx.VR, PR = ctx.PR;
const saved = [];                                                  // a link clicked to save a file: [its address, the name it is saved as]
ctx.document.createElement('a').constructor.prototype.click = function () { saved.push([this.getAttribute('href'), this.getAttribute('download')]); };
const status = (root) => root.querySelectorAll('div').find((d) => d.getAttribute('role') === 'status');
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, data, body):
    (tmp_path / "data.json").write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "screen.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout)


def accepted(pair_id=3, **over):
    return {"pair_id": pair_id, "status": "Accepted", "photo_name": "IMG_1.DNG", "created_at": "2026-10-21T10:00:00", "accepted_at": "2026-10-21T10:05:00",
            "engraving_id": "abc", "linked_by": "review", **over}


def waiting(pair_id=4, **over):
    return accepted(pair_id, status="Awaiting check", accepted_at=None, **over)


# -- the chain ------------------------------------------------------------------------------------------------------------------------
@node
@pytest.mark.parametrize("stage", ["prepared", "file", "result", "verified"])
def test_the_chain_names_four_steps_marks_the_current_one_with_words_and_shape_and_says_what_comes_next(tmp_path, stage):
    """The four steps are always in the same order; the state of each is said in a word (not by colour alone) and the current one is marked for
    a screen reader with aria-current."""
    files = [] if stage == "prepared" else [file_record(1, stage=stage)]
    out = run(tmp_path, {"lc": lifecycle(stage, files=files)}, """
  const chain = LC.chain(data.lc);
  out.steps = chain.querySelectorAll('li').map((li) => [li.querySelector('.lc-name').textContent, li.querySelector('.lc-word').textContent.trim(), li.getAttribute('aria-current')]);
  out.label = chain.querySelector('ol').getAttribute('aria-label');
  out.next = chain.querySelector('.lc-next').textContent;
  out.action = chain.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  const seen = [];
  const wired = LC.chain(data.lc, {onAction: (a) => seen.push(a.code)});
  out.buttons = wired.querySelectorAll('button').map((b) => b.textContent);
  for (const b of wired.querySelectorAll('button')) await b.dispatch('click');
  out.seen = seen;
""")
    names = ["Prepared", "File downloaded", "Result added", "Verified"]
    states = ["(done)" if i < ["prepared", "file", "result", "verified"].index(stage) else "(current)" if i == ["prepared", "file", "result", "verified"].index(stage)
              else "(upcoming)" for i in range(4)]
    assert [s[0] for s in out["steps"]] == names and [s[1] for s in out["steps"]] == states
    assert [s[2] for s in out["steps"]].count("step") == 1 and out["steps"][["prepared", "file", "result", "verified"].index(stage)][2] == "step"
    assert out["label"] == "Work file lifecycle"
    # the action of the stage: results are added and checked on the photograph screens (links); the rest belongs to the screen that draws the chain
    assert out["action"] == {"prepared": [], "file": [["Add result", "#/ingest?plan=7"]], "result": [["Review and accept result", "#/ingest?pair=4"]],
                             "verified": [["Open analysis", "#/analysis/3"]]}[stage]
    assert out["buttons"] == {"prepared": ["Go to file"], "file": [], "result": [], "verified": ["Compare with expected"]}[stage]
    assert out["seen"] == {"prepared": ["download"], "file": [], "result": [], "verified": ["compare"]}[stage]
    assert out["next"].startswith({"prepared": "Download the file and open it in LightBurn.",
                           "file": "File #1 downloaded. After engraving, add the result: the file and a photograph.",
                           "result": "The result was added but not accepted. Review and accept the measurements.",
                           "verified": "The result has been reviewed. Compare it with the expected result."}[stage])


@node
def test_a_work_that_cannot_be_exported_yet_says_to_fix_it_and_an_edited_work_says_the_old_file_stays_in_history(tmp_path):
    prepared = lifecycle("prepared", files=[file_record(2, current=False)], edited_after=2)
    blocked = lifecycle("prepared", ready=False, blockers=[{"code": "weak_regions", "count": 2}])
    loose = lifecycle("file", files=[file_record(1)], unlinked=[accepted()])
    loose["chain"]["unlinked"] = 1
    out = run(tmp_path, {"edited": prepared, "blocked": blocked, "loose": loose}, """
  out.fix = LC.chain(data.blocked, {onAction: () => {}}).querySelectorAll('button').map((b) => b.textContent);
  out.edited = LC.chain(data.edited).querySelector('.lc-next').textContent;
  out.blocked = LC.chain(data.blocked).querySelector('.lc-next').textContent;
  out.loose = LC.chain(data.loose).querySelector('.lc-next').textContent;
  out.none = LC.chain(null);
""")
    assert out["edited"].startswith("The work changed after file #2. The earlier file remains in history; this version needs a new file.")
    assert out["blocked"] == "The file cannot be created yet. See what to fix below." and out["fix"] == ["What to fix"]
    assert "Results without a file: 1" in out["loose"] and out["none"] is None            # a view not loaded yet draws nothing


@node
def test_a_file_exported_before_exports_were_recorded_is_named_as_such_not_as_number_zero(tmp_path):
    old = lifecycle("file", files=[file_record(0, recorded=False, at=None, name=None, download_url=None, downloadable=False, promise="none")])
    out = run(tmp_path, {"lc": old}, """
  out.next = LC.chain(data.lc).querySelector('.lc-next').textContent;
  out.files = LC.files(data.lc).textContent;
""")
    assert "(before MarkView recorded exports)" in out["next"] and "№ 0" not in out["next"] + out["files"]
    assert "date unknown" in out["files"] and "file not retained" in out["files"] and "prediction not saved with file" in out["files"]


# -- the readiness --------------------------------------------------------------------------------------------------------------------
@node
def test_the_readiness_states_size_time_layers_and_checks_and_each_blocker_in_words_with_a_button_to_where_it_is_fixed(tmp_path):
    blocked = lifecycle("prepared", ready=False, seconds=125.0, time_complete=False, layers=31, layer_cap=29,
                        checks={"colours": False, "layers": {"used": 31, "cap": 29, "ok": False}, "cleanup": True, "markers": True},
                        blockers=[{"code": "weak_regions", "count": 2, "target": {"kind": "region", "id": "r4"}},
                                  {"code": "too_many_layers", "count": 31, "cap": 29, "target": {"kind": "tab", "id": "colours"}},
                                  {"code": "text", "number": 2, "problem": "the font 'Gone Sans' is not on this computer any more: choose another font"},
                                  {"code": "zone", "number": 1, "problem": "the width of the picture must be 1..1000 mm"}, {"code": "nothing_to_engrave"}],
                        reason="every region is excluded: there is nothing to engrave")
    out = run(tmp_path, {"lc": blocked}, """
  const seen = [];
  const card = LC.readiness(data.lc, {onTarget: (b) => seen.push(b.target), designer: '/designer?device=1&lens=2'});
  out.text = card.textContent;
  out.rows = card.querySelectorAll('li').map((li) => li.querySelector('span').textContent);
  out.buttons = card.querySelectorAll('button').map((b) => b.textContent);
  out.links = card.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  for (const b of card.querySelectorAll('button')) await b.dispatch('click');
  out.targets = seen;
  out.details = card.querySelectorAll('details').map((d) => d.textContent);
""")
    assert out["text"].startswith("LightBurn file: not ready")
    assert "150,0 × 143,0 mm" in out["text"].replace(".", ",") and "≈ 2 min 05 s (incomplete estimate)" in out["text"] and "31 of 29 layers" in out["text"]
    assert "colors some unreachable" in out["text"] and "C00 cleaning present" in out["text"] and "markers on" in out["text"]
    assert out["rows"][0].startswith("Regions without sufficient data: 2.") and "LightBurn layers required: 31; available: 29" in out["rows"][1]
    assert out["rows"][2] == "Inscription 2 cannot be engraved: the font 'Gone Sans' is not on this computer any more: choose another font. Open it and fix the issue."
    assert out["rows"][3] == "Photo zone 1 cannot be engraved: the width of the picture must be 1..1000 mm."          # the reason is the inscription's and the zone's own
    assert out["rows"][4] == "Nothing to engrave: all regions are excluded."
    assert out["buttons"] == ["Show region", "Open Colors tab"] and out["targets"] == [{"kind": "region", "id": "r4"}, {"kind": "tab", "id": "colours"}]
    assert out["links"] == [["Experiment goals", "#/designer?device=1&lens=2"]]               # only for a blocker that is missing measurements
    assert any("every region is excluded: there is nothing to engrave" in d for d in out["details"])        # the exact words of the check, on demand


@node
def test_a_ready_work_says_so_and_a_blocker_without_a_target_has_no_button_and_an_unknown_code_is_not_shown_raw(tmp_path):
    ready = lifecycle("prepared")
    odd = lifecycle("prepared", ready=False, blockers=[{"code": "something_new"}, {"code": "draft"}])
    out = run(tmp_path, {"ready": ready, "odd": odd}, """
  out.ready = LC.readiness(data.ready).textContent;
  const card = LC.readiness(data.odd, {onTarget: () => {}});
  out.odd = card.querySelectorAll('li').map((li) => li.textContent);
  out.buttons = card.querySelectorAll('button').length;
""")
    assert out["ready"].startswith("LightBurn file: ready to export") and "Checks:" in out["ready"]
    assert out["odd"] == ["The file cannot be created yet. ", "The plan is a draft. Complete conversion to enable export. "] and out["buttons"] == 0
    assert not any("something_new" in text for text in out["odd"])


# -- the download ---------------------------------------------------------------------------------------------------------------------
DOWNLOAD = {"/api/vector/7/export.lbrn2": {"status": 200, "text": "<xml/>", "type": "application/xml",
                                           "headers": {"content-disposition": "attachment; filename*=UTF-8''work.lbrn2"}}}


@node
def test_the_download_button_asks_the_server_once_for_a_double_click_then_runs_the_after_step_and_can_be_pressed_again(tmp_path):
    out = run(tmp_path, {"routes": DOWNLOAD}, """
  let done = 0;
  const got = LC.downloadButton('/vector/7/export.lbrn2', 'vector.lbrn2', 'Download LightBurn', {onDone: () => { done += 1; }});
  ctx.document.body.append(got.el);
  const first = got.button.dispatch('click'), second = got.button.dispatch('click');    // the second press comes while the first is still running
  out.busy = got.button.getAttribute('aria-busy');
  await Promise.all([first, second]); await tick();
  out.requests = ctx.requests.map((r) => r.method + ' ' + r.path);
  out.done = done; out.after = [got.button.disabled, got.button.getAttribute('aria-busy'), got.failure.hidden];
  await got.button.dispatch('click'); await tick();
  out.again = ctx.requests.length; out.saved = saved.slice();
""")
    assert out["busy"] == "true" and out["requests"] == ["GET /api/vector/7/export.lbrn2"] and out["done"] == 1
    assert out["after"] == [False, None, True] and out["again"] == 2
    assert out["saved"] == [["blob:x", "work.lbrn2"], ["blob:x", "work.lbrn2"]]                 # saved under the name the server gave, once per request


@node
def test_a_refused_download_keeps_its_reason_in_russian_beside_the_button_with_a_retry_that_works_once_the_server_agrees(tmp_path):
    routes = {"/api/vector/7/export.lbrn2": {"status": 422, "json": {"error": "every region is excluded: there is nothing to engrave", "kind": "invalid"}}}
    out = run(tmp_path, {"routes": routes}, """
  let done = 0;
  const got = LC.downloadButton('/vector/7/export.lbrn2', 'vector.lbrn2', 'Download LightBurn', {onDone: () => { done += 1; }});
  ctx.document.body.append(got.el);
  await got.button.dispatch('click'); await tick();
  out.failure = [got.failure.hidden, got.failure.textContent, got.failure.getAttribute('role'), got.failure.querySelectorAll('button').map((b) => b.textContent)];
  out.enabled = !got.button.disabled; out.doneAfterFailure = done; out.toast = toasts();
  ctx.fetch = async () => ({ok: true, status: 200, headers: {get: () => null}, blob: async () => ({size: 1})});         // the server now agrees
  await got.failure.querySelector('button').dispatch('click'); await tick();
  out.after = [got.failure.hidden, done];
""")
    assert out["failure"][0] is False and out["failure"][1].startswith("File not received: every region is excluded: there is nothing to engrave")
    assert out["failure"][2] == "alert" and out["failure"][3] == ["Retry"]
    assert out["enabled"] and out["doneAfterFailure"] == 0 and any("every region is excluded" in t for t in out["toast"])
    assert out["after"] == [True, 1]


@node
def test_a_download_that_cannot_reach_the_server_or_gets_an_unreadable_answer_says_so_in_russian(tmp_path):
    routes = {"/api/vector/7/export.lbrn2": {"status": 500, "text": "<html>boom</html>", "type": "text/html"}}
    out = run(tmp_path, {"routes": routes}, """
  const got = LC.downloadButton('/vector/7/export.lbrn2', 'vector.lbrn2', 'Download LightBurn');
  await got.button.dispatch('click'); await tick();
  out.unreadable = got.failure.textContent;
  ctx.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await got.button.dispatch('click'); await tick();
  out.offline = got.failure.textContent;
""")
    assert out["unreadable"].startswith("File not received: Server error (500). The file was not received.")
    assert out["offline"].startswith("File not received: Cannot reach the local service")
    assert "undefined" not in out["unreadable"] + out["offline"] and "fetch" not in out["offline"]


@node
def test_the_export_card_is_the_one_place_for_the_action_the_readiness_and_the_files_and_says_the_file_does_not_go_to_the_laser(tmp_path):
    files = [file_record(1, stage="verified", results=[accepted()]), file_record(2, stage="file", current=True, download_url=None, downloadable=False)]
    ready = lifecycle("file", files=files)
    blocked = lifecycle("prepared", ready=False, blockers=[{"code": "draft"}], files=[])
    out = run(tmp_path, {"ready": ready, "blocked": blocked}, """
  const recipe = ctx.document.createElement('div'); recipe.textContent = 'LAYER TABLE';
  const card = LC.exportCard(data.ready, {path: '/vector/7/export.lbrn2', name: 'vector.lbrn2', recipe, recipeLabel: 'Complete recipe and layers (3)'});
  const button = byText(card, 'button', 'Download LightBurn');
  out.main = [button.disabled, button.className];
  out.text = card.textContent;
  out.summaries = card.querySelectorAll('summary').map((s) => s.textContent);
  out.hasRecipe = card.querySelectorAll('details').some((d) => d.textContent.includes('LAYER TABLE'));
  out.fileButtons = card.querySelectorAll('button').map((b) => [b.textContent, b.disabled]);
  out.chain = card.querySelectorAll('ol').length;
  const nochain = LC.exportCard(data.ready, {path: '/vector/7/export.lbrn2', name: 'v', withChain: false});
  out.nochain = nochain.querySelectorAll('ol').length;
  const stopped = LC.exportCard(data.blocked, {path: '/vector/7/export.lbrn2', name: 'v'});
  out.stopped = [byText(stopped, 'button', 'Download LightBurn').disabled, stopped.textContent.includes('The plan is a draft')];
  out.oldSummary = stopped.querySelectorAll('summary').map((s) => s.textContent);
  await byText(card, 'button', 'Download LightBurn').dispatch('click'); await tick();
  out.requests = ctx.requests.map((r) => r.path);
""")
    assert out["main"][0] is False and "primary" in out["main"][1].split() and "Open and run it in LightBurn when ready" in out["text"]
    assert out["summaries"] == ["Complete recipe and layers (3)", "Previous files (2)"] and out["hasRecipe"]
    assert out["chain"] == 1 and out["nochain"] == 0                                         # the chain is drawn once, where the screen wants it
    assert out["stopped"] == [True, True] and out["oldSummary"] == ["Previous files"]                  # no files yet, no recipe given: the one fold
    assert ["Download", False] in out["fileButtons"] and ["Download", True] not in out["fileButtons"]      # a file whose bytes are gone has no button
    assert "file not retained" in out["text"] and out["requests"] == ["/api/vector/7/export.lbrn2"]


@node
def test_the_previous_files_list_each_file_with_its_own_stage_its_photographs_and_a_download_of_that_file_only(tmp_path):
    first = file_record(1, stage="verified", results=[accepted(3), waiting(4, linked_by="time")], current=False)
    second = file_record(2, stage="file", current=True)
    lc = lifecycle("file", files=[first, second], unlinked=[accepted(9, photo_name="OLD.DNG")])
    out = run(tmp_path, {"lc": lc, "routes": {"/api/vector/7/exports/1": {"status": 200, "text": "<xml/>", "type": "application/xml"}}}, """
  const list = LC.files(data.lc);
  out.text = list.textContent;
  out.pills = list.querySelectorAll('.pill').map((p) => p.textContent);
  out.links = list.querySelectorAll('a').map((a) => [a.textContent, a.getAttribute('href')]);
  await list.querySelectorAll('button')[0].dispatch('click'); await tick();
  out.requests = ctx.requests.map((r) => r.path);
  out.empty = LC.files({files: [], unlinked: []}).textContent;
""")
    assert "File #1" in out["text"] and "File #2" in out["text"] and "work has since changed or been exported again" in out["text"]
    assert "current for work" in out["text"] and "prediction saved with file" in out["text"] and "linked by time" in out["text"]
    assert out["pills"] == ["Verified", "File downloaded"]
    assert ["analysis", "#/analysis/3"] in out["links"] and ["review and accept", "#/ingest?pair=4"] in out["links"] and ["analysis", "#/analysis/9"] in out["links"]
    assert "Results without a file" in out["text"] and "OLD.DNG" in out["text"] and "photographed before the first file record" in out["text"]
    assert out["requests"] == ["/api/vector/7/exports/1"]                                     # the first file's own address, with no /api twice
    assert out["empty"] == "No file has been created yet."


# -- the basis of a comparison --------------------------------------------------------------------------------------------------------
@node
def test_the_basis_of_a_comparison_is_named_plainly_and_a_reconstruction_is_never_called_the_promise_of_the_file(tmp_path):
    saved = {"kind": "saved", "export_number": 2, "exported_at": "2026-10-20T10:00:00", "document_version": 3, "ambiguous": []}
    tie = {**saved, "ambiguous": [1]}
    rebuilt = {**saved, "kind": "reconstructed"}
    never = {"kind": "reconstructed", "export_number": None, "exported_at": None, "document_version": None, "ambiguous": []}
    lost = {**saved, "kind": "lost"}
    out = run(tmp_path, {"b": [saved, tie, rebuilt, never, lost]}, """
  out.notes = data.b.map((b) => LC.basisNote(b));
""")
    saved_note, tie_note, rebuilt_note, never_note, lost_note = out["notes"]
    assert saved_note.startswith("Basis: prediction saved with file #2 (exported 2026-10-20 10:00). This is what the file itself predicted.")
    assert "#1, #2 match the engraving equally; file #2 was chosen as the latest before the photograph" in tie_note
    assert rebuilt_note.startswith("Basis: reconstruction.") and "No prediction was saved" in rebuilt_note and "This is not the file’s original prediction." in rebuilt_note
    assert "file itself predicted" not in rebuilt_note and "has not been exported" in never_note and "This is not a file prediction." in never_note
    assert lost_note.startswith("Basis: none. No prediction was saved for file #2") and "no comparison is available" in lost_note


# -- the way back to a work -----------------------------------------------------------------------------------------------------------
def summary(**over):
    base = {"work": "Inna + Boris", "plan_id": 7, "pair_id": 3, "route": "/vector?plan=7&accepted=3", "export_number": 1, "next": "compare",
            "basis": {"kind": "saved", "export_number": 1, "exported_at": "2026-10-20T10:00:00", "document_version": 3, "ambiguous": []},
            "result": {"matched": 4, "promised": 5, "beyond_layers": 2, "mean_delta_e": 6.25},
            "prediction": {"known": True, "before": {"layers": 0}, "after": {"layers": 2, "proposals": 1}}}
    return {**base, **over}


@node
def test_the_summary_of_an_accepted_result_tells_the_basis_how_it_came_out_how_the_current_prediction_moved_and_what_to_do(tmp_path):
    cases = [summary(), summary(next="replace"), summary(prediction={"known": False, "before": None, "after": None}),
             summary(prediction={"known": True, "before": None, "after": None}), summary(result={"matched": None, "promised": 5, "beyond_layers": 0, "mean_delta_e": None})]
    out = run(tmp_path, {"cases": cases}, """
  const seen = [];
  out.cards = data.cases.map((s) => {
    const card = LC.summary(s, {onNext: (code) => seen.push(code), onClose: () => seen.push('closed')});
    return [card.textContent, card.querySelectorAll('button').map((b) => b.textContent), card.getAttribute('role')];
  });
  const first = LC.summary(data.cases[0], {onNext: (c) => seen.push(c), onClose: () => seen.push('closed')});
  for (const b of first.querySelectorAll('button')) await b.dispatch('click');
  out.seen = seen;
  out.bare = LC.summary(data.cases[0]).querySelectorAll('button').length;
""")
    text = out["cards"][0][0]
    assert text.startswith("Result accepted: “Inna + Boris”") and "Basis: prediction saved with file #1" in text
    assert "Matched layers: 4 of 5, noticeably different (2), mean ΔE 6" in text
    assert "2 layer colors shifted since the file (was 0); closer color replacements available: 1. File #1 is unchanged." in text
    assert out["cards"][0][1] == ["Compare with expected", "Close summary"] and out["cards"][1][1][0] == "View color replacements" and out["cards"][0][2] == "status"
    assert "not recorded for this result" in out["cards"][2][0] and "prediction cannot be compared" in out["cards"][3][0]
    assert "Layers were not matched to the file." in out["cards"][4][0] and out["seen"] == ["compare", "closed"] and out["bare"] == 0


@node
def test_returning_to_a_work_goes_there_with_a_short_note_and_leaves_every_other_result_where_it_was(tmp_path):
    out = run(tmp_path, {"concluded": {"plan_id": 7, "work": "Inna + Boris", "review": {"summary": {"beyond_layers": 2}}, "summary": summary()},
                         "clean": {"plan_id": 7, "work": "W", "review": {"summary": {"beyond_layers": 0}}, "summary": summary(work="W")},
                         "photo": {"plan_id": 9, "work": "Photo", "review": {"summary": {}}}}, """
  out.back = LC.returnToWork(data.concluded);
  out.went = ctx.__went.slice(); out.toast = toasts();
  out.clean = LC.returnToWork(data.clean); out.toast2 = toasts().slice(-1);
  ctx.__went.length = 0;
  out.photo = LC.returnToWork(data.photo); out.none = LC.returnToWork(null); out.undef = LC.returnToWork(undefined);
  out.stayed = ctx.__went.slice();
""")
    assert out["back"] is True and out["went"] == ["/vector?plan=7&accepted=3"]
    assert out["toast"] == ["Result accepted. Returning to “Inna + Boris”: noticeable differences found"]
    assert out["clean"] is True and out["toast2"] == ["Result accepted. Returning to “W”: no noticeable differences"]
    assert out["photo"] is False and out["none"] is False and out["undef"] is False and out["stayed"] == []           # no summary: the screen stays as it was


# -- the comparison against the engraving the operator chose --------------------------------------------------------------------------
def review(number=1, name="IMG_1.DNG", engraving="e1", at="2026-10-21T10:00:00", kind="saved", rows=3, photo=None, promise_lost=False, **over):
    layer_rows = [{"name": f"C0{i + 1} layer", "promised_name": f"C0{i + 1}", "promised_lab": [60.0, 5.0, 10.0], "got_lab": [60.0 - i, 5.0, 10.0],
                   "promised_srgb": [200, 190, 180], "got_srgb": [190, 180, 170], "delta_e": 1.0 + i, "dL": -float(i), "dC": 0.0, "dh": None, "area_mm2": 100.0 * (i + 1),
                   "beyond": i > 1, "causes": []} for i in range(rows)]
    return {"engraving_id": engraving, "photo_name": name, "reviewed_at": at, "export_number": number, "approximate": kind == "reconstructed", "promise_lost": promise_lost,
            "basis": {"kind": kind, "export_number": number, "exported_at": "2026-10-20T10:00:00", "document_version": 3, "ambiguous": []},
            "limit": 3.0, "notes": [], "photo": photo or [], "rows": layer_rows, "not_engraved": [], "unmatched": [],
            "summary": {"matched": rows, "promised": rows, "mean_delta_e": 2.0, "beyond_layers": 1, "area_share_beyond": 0.25}, **over}


def work_view(reviews, **over):
    return {"id": 7, "reviews": reviews, "attention": None, "undo": 0, "redo": 0, "colours": [], **over}


@node
def test_the_result_tab_lets_the_operator_choose_the_engraving_and_names_the_file_and_the_basis_of_each(tmp_path):
    old = review(1, "OLD.DNG", "e1", "2026-10-21T10:00:00")
    new = review(2, "NEW.DNG", "e2", "2026-10-22T10:00:00", kind="reconstructed")
    out = run(tmp_path, {"job": work_view([new, old])}, """
  const view = VR.view(data.job, run = async () => true);
  const picker = view.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Engraving');
  out.options = picker.querySelectorAll('option').map((o) => o.textContent);
  out.first = view.textContent;
  picker.value = 'e1';
  await picker.dispatch('change');
  out.second = view.textContent;
  out.pictures = view.querySelectorAll('img').map((i) => i.getAttribute('src'));
""")
    assert out["options"] == ["NEW.DNG · file #2 · 2026-10-22 10:00", "OLD.DNG · file #1 · 2026-10-21 10:00"]
    assert "Basis: reconstruction." in out["first"] and "This is not the file’s original prediction." in out["first"] and "file itself predicted" not in out["first"]
    assert "Basis: prediction saved with file #1" in out["second"] and "Basis: reconstruction" not in out["second"]
    assert all("engraving=e1" in src for src in out["pictures"]) and len(out["pictures"]) == 2          # the pictures follow the chosen engraving, at one scale


@node
def test_a_single_engraving_still_shows_which_file_it_is_compared_with_and_a_lost_promise_is_stated_instead_of_a_comparison(tmp_path):
    lost = review(2, kind="lost", promise_lost=True, rows=0, summary={"matched": 0, "promised": 0, "mean_delta_e": None, "beyond_layers": 0, "area_share_beyond": 0})
    out = run(tmp_path, {"one": work_view([review()]), "lost": work_view([lost])}, """
  const one = VR.view(data.one, async () => true), gone = VR.view(data.lost, async () => true);
  out.one = one.querySelectorAll('option').map((o) => o.textContent);
  out.lost = gone.textContent;
  out.lostPictures = gone.querySelectorAll('img').length;
""")
    assert out["one"] == ["IMG_1.DNG · file #1 · 2026-10-21 10:00"]
    assert "Basis: none. No prediction was saved for file #2" in out["lost"] and "cannot be reconstructed, so no comparison is available" in out["lost"]
    assert out["lostPictures"] == 0                                                              # nothing is drawn as if it were the promise


@node
def test_the_colour_and_the_photo_assessments_are_separate_sections_and_neither_stands_in_for_the_other(tmp_path):
    photo = [{"name": "Photo zone 1", "zone": 1, "median_de": 2.5, "max_de": 4.0, "profile_usable": True, "tone": {"levels": 9, "steps": 10, "black_L": 20.0, "white_L": 80.0},
              "changed_settings": [], "latest_export": 1, "settings": {}, "latest_settings": {}}]
    both, colour_only = review(photo=photo), review()
    out = run(tmp_path, {"both": work_view([both]), "colour": work_view([colour_only])}, """
  const sections = (v) => v.querySelectorAll('section').map((s) => [s.getAttribute('aria-label'), s.textContent]);
  out.both = sections(VR.view(data.both, async () => true));
  out.colour = sections(VR.view(data.colour, async () => true));
""")
    assert [label for label, _ in out["both"]] == ["Color assessment", "Photo layer assessment"]
    assert "Matched 3 of 3 expected layers" in out["both"][0][1] and "Photo zone" not in out["both"][0][1]
    assert "Photo layer prediction from earlier measurements: median error 2.5 ΔE" in out["both"][1][1]
    assert [label for label, _ in out["colour"]] == ["Color assessment"]                              # no photograph layer: no empty section


@node
def test_the_largest_differences_come_first_and_the_rest_wait_for_a_press(tmp_path):
    out = run(tmp_path, {"job": work_view([review(rows=8)])}, """
  const view = VR.view(data.job, async () => true);
  const rows = () => view.querySelectorAll('button').filter((b) => (b.className || '').includes('vw-review-row')).map((b) => b.textContent);
  out.heading = view.querySelectorAll('h6').map((h) => h.textContent);
  out.few = rows();
  await byText(view, 'button', 'Show all (8)').dispatch('click');
  out.all = rows().length;
  out.back = !!byText(view, 'button', 'Show only largest');
  await byText(view, 'button', 'Show only largest').dispatch('click');
  out.few2 = rows().length;
""")
    assert out["heading"] == ["Largest differences"] and len(out["few"]) == 5 and out["few"][0].find("ΔE 8.0") > 0       # the worst layer first
    assert out["all"] == 8 and out["back"] and out["few2"] == 5


@node
def test_a_replacement_says_what_it_did_can_be_undone_and_stops_offering_the_undo_once_anything_else_was_done(tmp_path):
    """A replacement is an ordinary edit of the work; right after it the tab says so and offers «Undo replacement». The offer is only for the
    replacement itself: another edit after it, or a colour no longer as the replacement left it, withdraws it."""
    proposal = {"colour": 1, "entry_id": "e9", "srgb": [200, 190, 180], "entry_srgb": [201, 191, 181], "delta_e_now": 6.0, "delta_e_proposed": 1.5}
    drift = {"layers": [{"name": "C01", "was_srgb": [200, 190, 180], "now_srgb": [190, 180, 170], "missing": False, "delta_e": 6.0, "area_mm2": 100.0,
                         "proposals": [proposal, {**proposal, "colour": 2, "entry_id": "e8"}]}], "layers_total": 3, "visible_de": 3.0, "area_share": 0.4, "approximate": False}
    job = work_view([], attention=drift, colours=[{"index": 1, "entry_id": "e1"}, {"index": 2, "entry_id": "e2"}])
    out = run(tmp_path, {"job": job}, """
  const ran = [];
  const runOp = async (op) => { ran.push(op); return true; };
  const draw = (j) => VR.view(j, runOp);
  let view = draw(data.job);
  out.before = byText(view, 'button', 'Undo replacement') ? 'offered' : 'none';
  await view.querySelectorAll('button').find((b) => b.textContent === 'Replace').dispatch('click'); await tick();
  const after = {...data.job, undo: 0, colours: [{index: 1, entry_id: 'e9'}, {index: 2, entry_id: 'e2'}]};
  view = draw(after);
  out.said = status(view).textContent;
  await byText(view, 'button', 'Undo replacement').dispatch('click'); await tick();
  out.ran = ran.splice(0);
  out.gone = byText(draw(after), 'button', 'Undo replacement') ? 'offered' : 'none';
  // all replacements at once: one undo per replacement
  view = draw(data.job);
  await view.querySelectorAll('button').find((b) => b.textContent.startsWith('Apply all replacements')).dispatch('click'); await tick(); await tick();
  ran.splice(0);
  const both = {...data.job, undo: 0, colours: [{index: 1, entry_id: 'e9'}, {index: 2, entry_id: 'e8'}]};
  view = draw(both);
  out.all = status(view).textContent;
  await byText(view, 'button', 'Undo replacement').dispatch('click'); await tick(); await tick();
  out.undone = ran.splice(0);
  // another edit after a replacement (the depth of the undo grew): the offer is withdrawn
  view = draw(data.job);
  await view.querySelectorAll('button').find((b) => b.textContent === 'Replace').dispatch('click'); await tick();
  out.later = byText(draw({...after, undo: 1}), 'button', 'Undo replacement') ? 'offered' : 'none';
  // the replaced colour changed since: the offer is withdrawn too
  view = draw(data.job);
  await view.querySelectorAll('button').find((b) => b.textContent === 'Replace').dispatch('click'); await tick();
  out.changed = byText(draw({...after, colours: [{index: 1, entry_id: 'e5'}, {index: 2, entry_id: 'e2'}]}), 'button', 'Undo replacement') ? 'offered' : 'none';
""")
    assert out["before"] == "none"
    assert out["said"].startswith("Original color replaced with the nearest measured color (ΔE 1") and "The engraved file was not changed." in out["said"]
    assert out["ran"] == [{"op": "set_colour", "colour": 1, "entry_id": "e9"}, {"op": "undo"}] and out["gone"] == "none"
    assert out["all"].startswith("Colors replaced: 2.") and out["undone"] == [{"op": "undo"}, {"op": "undo"}]
    assert out["later"] == "none" and out["changed"] == "none"


@node
def test_a_replacement_the_server_refused_leaves_no_undo_to_offer(tmp_path):
    proposal = {"colour": 1, "entry_id": "e9", "srgb": [200, 190, 180], "entry_srgb": [201, 191, 181], "delta_e_now": 6.0, "delta_e_proposed": 1.5}
    drift = {"layers": [{"name": "C01", "was_srgb": [200, 190, 180], "now_srgb": [190, 180, 170], "missing": False, "delta_e": 6.0, "area_mm2": 100.0, "proposals": [proposal]}],
             "layers_total": 3, "visible_de": 3.0, "area_share": 0.4, "approximate": False}
    out = run(tmp_path, {"job": work_view([], attention=drift)}, """
  const ran = [];
  const view = VR.view(data.job, async (op) => { ran.push(op); return false; });
  const button = byText(view, 'button', 'Replace');
  await button.dispatch('click'); await tick();
  out.again = !button.disabled;
  out.offer = byText(VR.view(data.job, async () => false), 'button', 'Undo replacement') ? 'offered' : 'none';
  out.ran = ran.length;
""")
    assert out["again"] and out["offer"] == "none" and out["ran"] == 1


@node
def test_new_measurements_are_said_to_change_only_the_current_prediction_never_the_file_that_was_made(tmp_path):
    out = run(tmp_path, {"none": work_view([]), "same": work_view([], attention={"layers": [], "layers_total": 3, "visible_de": 3.0, "area_share": 0, "approximate": False})}, """
  out.none = VR.view(data.none, async () => true).textContent;
  out.same = VR.view(data.same, async () => true).textContent;
""")
    for text in (out["none"], out["same"]):
        assert "Current work prediction: colors after new measurements" in text
        assert "New measurements update only the current work prediction" in text and "do not change the engraved file or the expected colors in an exported file" in text


# -- the prediction review ------------------------------------------------------------------------------------------------------------
@node
def test_the_prediction_review_names_its_basis_as_a_reconstruction_and_lists_the_tones_furthest_from_the_prediction(tmp_path):
    bands = [{"power": 10 + 10 * i, "predicted": [60.0, 0.0, 0.0], "lab": [60.0 - i, 0.0, 0.0], "de": 1.0 + i} for i in range(6)]
    layer = {"name": "G", "engravings": 2, "compared": 6, "median_de": 3.5, "max_de": 6.0, "within": 0.5, "tolerance_de": 3.0, "median_dL": -2.0, "median_db": 0.0,
             "bands": bands, "causes": [], "reason": None}
    out = run(tmp_path, {"review": {"layers": [layer]}, "none": {"layers": []}}, """
  const card = PR.card(data.review, null);
  out.text = card.textContent;
  out.note = card.querySelectorAll('p').find((p) => p.getAttribute('role') === 'note').textContent;
  out.largest = card.querySelectorAll('p').map((p) => p.textContent).find((t) => t.startsWith('Largest differences'));
  out.empty = PR.card(data.none, null);
""")
    assert out["note"].startswith("Basis: reconstruction.") and "not a promise stored in the file" in out["note"]
    assert out["largest"] == "Largest differences: 60 % — 6 ΔE; 50 % — 5 ΔE; 40 % — 4 ΔE." and out["empty"] is None


# -- the stylesheet and the page ----------------------------------------------------------------------------------------------------
CSS = (UI / "styles.css").read_text(encoding="utf-8")


def rule(selector: str) -> str:
    start = CSS.index(selector)
    return CSS[start:CSS.index("}", start)]


def test_the_state_words_and_the_hint_of_a_narrow_header_stay_readable_to_a_screen_reader_and_the_current_step_differs_in_more_than_colour():
    """display:none would remove the words «done / current / upcoming» and the hint from assistive technology; they are clipped instead."""
    for selector in (".lc-word {", ".vw-chain .lc-hint {"):
        assert "clip:rect(0 0 0 0)" in rule(selector) and "display:none" not in rule(selector), selector
    current = rule(".lc-step.lc-current {")
    assert "font-weight" in current and "border-color" in current and "background" in current          # weight and a filled mark, not colour alone
    assert "@media (max-width:760px) {.lc-step" in CSS


def test_the_lifecycle_script_is_loaded_before_every_screen_that_draws_it_and_after_the_helpers_it_calls_lazily():
    order = {s: i for i, s in enumerate(re.findall(r'<script src="(/[^"]+)"', (UI / "index.html").read_text(encoding="utf-8")))}
    for user in ("plan", "experiment", "vector", "vector-review", "ingest-review"):
        assert order["/router.js"] < order["/screens/lifecycle.js"] < order[f"/screens/{user}.js"], user
