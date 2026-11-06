"""The creation screen against the real server (feature ux-work-creation-p0, REQ-002 + DEC-001): the screen's own code runs in node over the
small DOM and talks to the application over HTTP, so that the field names, answers and files the screen relies on are the ones the routes really
give. The picture of an unfinished task is read back from the workshop by a second, fresh run of the screen (a restart of the application)."""
import json
import shutil
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

from test_grey_scales import app_world, picture_png  # noqa: F401  (a laser, lens and titanium with four measured grey scales)
from test_creation_ui import SCRIPTS
from test_vector_photo_zones import world  # noqa: F401  (flat colours of the picture's five colours on the same laser, lens and titanium)
from test_vector_work import PAPER, RED, UI, picture  # noqa: F401
from titanium_platform import plans as pl

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = r"""
const {context, load, El} = require(__DOM__);
Object.defineProperty(El.prototype, 'style', {get() { return this._style || (this._style = {}); }});
const ctx = context({});
const BASE = __BASE__;
ctx.fetch = (url, opts) => fetch(BASE + url, opts);                          // the real server, the real multipart and the real answers
ctx.FormData = FormData; ctx.Blob = Blob;
const GLUE = `globalThis.__screens = {}; globalThis.__went = []; App.register = (d) => { globalThis.__screens[d.id] = d; }; App.render = () => {}; App.go = (r) => { globalThis.__went.push(r); };`;
const EXPORT = 'globalThis.Creation = Creation; globalThis.WorkContext = WorkContext;';
load(ctx, __UI__, __SCRIPTS__.map((s) => (s === 'GLUE' ? {code: GLUE} : s === 'EXPORT' ? {code: EXPORT} : s)));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const settle = async () => { for (let i = 0; i < 40; i++) await wait(5); };
const body = ctx.document.body;
const button = (root, text) => root.querySelectorAll('button').find((b) => b.textContent === text);
// a box is named by its aria-label or, in a field, by the label of the field (the unit and the permitted values are read after the name, not in it)
const labelled = (root, label) => root.querySelectorAll('[aria-label]').find((el) => el.getAttribute('aria-label') === label)
  || (root.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === label.replace(/, mm$/, '')) || {firstControl: () => undefined}).firstControl();
const tiles = (tree) => tree.querySelectorAll('button').filter((b) => b.getAttribute('role') === 'radio');
const heading = (root) => root.querySelector('h2').textContent;
const alerts = (root) => root.querySelectorAll('[role]').filter((a) => a.getAttribute('role') === 'alert' && !a.hidden).map((a) => a.textContent);
async function screen(query = {}) {
  const tree = await ctx.__screens.new.render({query});
  body.append(tree);
  await settle();
  return tree;
}
const PNG = Buffer.from(__PICTURE__, 'base64');
async function fillPicture(tree, name, width) {
  const input = tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file');
  const file = new Blob([PNG], {type: 'image/png'}); file.name = 'portrait.png';
  input.files = [file];
  await input.dispatch('change');
  labelled(tree, 'Work name').value = name;
  labelled(tree, 'Width on titanium, mm').value = width;
}
(async () => {
  const out = {};
__BODY__
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


@contextmanager
def serve(app):
    """The application on a port of this computer, as the desktop shell serves it (the lifespan is the test client's)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "the server did not start"
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def run(tmp_path, base, body, name="screen.js"):
    import base64
    script = tmp_path / name
    script.write_text(HARNESS.replace("__DOM__", json.dumps(str(Path(__file__).with_name("ui_dom.js")))).replace("__BASE__", json.dumps(base))
                      .replace("__UI__", json.dumps(str(UI) + "/")).replace("__SCRIPTS__", json.dumps(SCRIPTS))
                      .replace("__PICTURE__", json.dumps(base64.b64encode(picture()).decode())).replace("__BODY__", body), encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@node
def test_a_work_is_made_from_the_picture_through_the_three_steps_and_the_task_is_closed_by_the_real_routes(world, tmp_path):  # noqa: F811
    client = world["client"]
    laser, lens, titanium = world["laser"], world["lens"], world["titanium"]
    assert client.put("/api/creation/context", json={"device_id": laser["id"], "lens_id": lens["id"], "material_id": titanium["id"]}).status_code == 200
    with serve(client.app) as base:
        out = run(tmp_path, base, """
  const tree = await screen();
  out.context = tree.querySelector('.work-context').textContent;
  await fillPicture(tree, 'Портрет Инны', '60');
  await button(tree, 'Next →').dispatch('click'); await settle();
  out.second = heading(tree);
  out.tiles = tiles(tree).map((t) => [t.querySelector('strong').textContent, t.querySelector('img') !== null, t.textContent.includes('ready to create'), t.textContent.includes('measurements needed')]);
  out.alts = tiles(tree).map((t) => t.querySelector('img') && t.querySelector('img').getAttribute('alt'));
  await tiles(tree)[0].dispatch('click');
  await button(tree, 'Next →').dispatch('click'); await settle();
  out.third = [heading(tree), button(tree, 'Create work').disabled, alerts(tree)];
  await button(tree, 'Create work').dispatch('click'); await settle();
  out.refused = [[(tree.querySelectorAll('label').find((l) => (l.querySelector('span') || {}).textContent === 'ΔE tolerance') || {errorText: () => undefined}).errorText()], [...ctx.__went]];                                        // the workshop holds no tolerance: the person is asked, nothing is made
  const thr = tree.querySelectorAll('input').find((i) => i.getAttribute('placeholder') === 'enter a value');
  thr.value = '5'; await thr.dispatch('input');
  await button(tree, 'Create work').dispatch('click'); await settle();
  out.went = [...ctx.__went];
  out.alerts = alerts(tree);
""")
    assert "JPT M7" in out["context"] and "Grade 5" in out["context"]
    assert out["second"].startswith("New work · step 2 of 3")
    assert [t[0] for t in out["tiles"]] == ["Color regions", "Photo engraving", "Silhouette", "Lines"]
    assert all(t[1] for t in out["tiles"]), out["tiles"]                                  # the real preview routes drew all four
    assert "regions:" in out["alts"][0] and "colors:" in out["alts"][0] and "grayscale levels in image:" in out["alts"][1]
    assert "lines:" in out["alts"][3]
    assert out["tiles"][0][2] and out["tiles"][1][2]                                       # colours and a scale are measured in this workshop
    assert out["third"][0].endswith("Settings and creation") and out["third"][1] is False and out["third"][2] == []
    assert out["refused"] == [["Enter a ΔE tolerance; none is saved for this laser and lens"], []]
    assert out["alerts"] == [], out["alerts"]
    [went] = out["went"]
    plan_id = int(went.split("=")[1])
    assert went == f"/vector?plan={plan_id}"
    plan = pl.get_plan(world["store"], plan_id)
    assert plan["name"] == "Портрет Инны" and plan["device_id"] == laser["id"] and plan["material_id"] == titanium["id"]
    assert client.get("/api/rules", params={"device_id": laser["id"], "lens_id": lens["id"]}).json()["delta_tolerance"] == 5.0   # typed once, kept for the next
    assert [d for d in client.get("/api/creation/drafts").json() if d["name"] == "Портрет Инны"] == []   # the made work closed its task: nothing is offered again
    assert not list((Path(world["store"].data_dir) / "files" / "drafts").glob("*"))      # ... and its picture is not kept


@node
def test_a_restarted_screen_finds_the_task_the_first_one_left_with_its_picture_and_goes_on_without_choosing_it_again(world, tmp_path):  # noqa: F811
    client = world["client"]
    laser, lens, titanium = world["laser"], world["lens"], world["titanium"]
    assert client.put("/api/creation/context", json={"device_id": laser["id"], "lens_id": lens["id"], "material_id": titanium["id"]}).status_code == 200
    assert client.put("/api/rules", json={"device_id": laser["id"], "lens_id": lens["id"], "delta_tolerance": 5.0}).status_code == 200
    with serve(client.app) as base:
        first = run(tmp_path, base, """
  const tree = await screen();
  await fillPicture(tree, 'До перезапуска', '45');
  await button(tree, 'Next →').dispatch('click'); await settle();
  await tiles(tree)[0].dispatch('click');
  await button(tree, 'Next →').dispatch('click'); await settle();
  const colours = tree.querySelectorAll('input').find((i) => i.getAttribute('max') === '29');
  colours.value = '9'; await colours.dispatch('input');
  await wait(900); await settle();
  out.step = heading(tree);
""", name="first.js")
        assert first["step"].endswith("Settings and creation")
        # the application is closed here: the second run knows nothing of the first but what the workshop kept
        [draft] = [d for d in client.get("/api/creation/drafts").json() if d["name"] == "До перезапуска"]
        assert draft["image"]["name"] == "portrait.png" and draft["state"]["result"] == "colour" and draft["state"]["step"] == "method"
        assert draft["state"]["method"]["colours"] == "9" and draft["state"]["width_mm"] == "45"
        second = run(tmp_path, base, f"""
  const tree = await screen({{draft: '{draft['id']}'}});
  out.head = heading(tree);
  out.colours = tree.querySelectorAll('input').filter((i) => i.getAttribute('max') === '29').map((i) => i.value);
  out.create = button(tree, 'Create work').disabled;
  out.picture = tree.querySelectorAll('img').map((i) => i.getAttribute('src')).filter((src) => src.includes('/picture'));
  const res = await fetch(BASE + out.picture[0]);
  out.pictureStatus = [res.status, res.headers.get('content-type')];
  await button(tree, '← Back').dispatch('click'); await settle();
  await button(tree, '← Back').dispatch('click'); await settle();
  out.first = [labelled(tree, 'Work name').value, labelled(tree, 'Width on titanium, mm').value, tree.querySelector('.file-name').textContent];
  await button(tree, 'Next →').dispatch('click'); await settle();
  out.tiles = tiles(tree).map((t) => t.getAttribute('aria-checked'));
  await button(tree, 'Next →').dispatch('click'); await settle();
  await button(tree, 'Create work').dispatch('click'); await settle();
  out.went = [...ctx.__went];
  out.alerts = alerts(tree);
""", name="second.js")
        assert second["head"].endswith("Settings and creation") and second["colours"] == ["9"] and second["create"] is False
        assert second["picture"] == [f"/api/creation/drafts/{draft['id']}/picture?v=0"] and second["pictureStatus"][0] == 200
        assert second["pictureStatus"][1].startswith("image/")
        assert second["first"][:2] == ["До перезапуска", "45"] and "portrait.png" in second["first"][2]
        assert second["tiles"] == ["true", "false", "false", "false"]
        assert second["alerts"] == [] and second["went"][0].startswith("/vector?plan="), second
        plan = pl.get_plan(world["store"], int(second["went"][0].split("=")[1]))
        assert plan["name"] == "До перезапуска"
        assert [d for d in client.get("/api/creation/drafts").json() if d["name"] == "До перезапуска"] == []


@node
def test_a_photograph_asks_which_kind_on_the_real_routes_going_back_deletes_the_work_and_the_chosen_kind_reaches_the_work(world, tmp_path):  # noqa: F811
    client = world["client"]
    laser, lens, titanium = world["laser"], world["lens"], world["titanium"]
    assert client.put("/api/creation/context", json={"device_id": laser["id"], "lens_id": lens["id"], "material_id": titanium["id"]}).status_code == 200
    with serve(client.app) as base:
        out = run(tmp_path, base, """
  const FORWARD = 'Next: engraving mode →';
  const dialog = () => body.querySelector('.modal');
  const kinds = () => dialog().querySelectorAll('.ge-kind');
  const named = async () => (await (await fetch(BASE + '/api/photo-works')).json()).filter((w) => w.name === 'Фото Инны');
  const tree = await screen();
  await fillPicture(tree, 'Фото Инны', '60');
  await button(tree, 'Next →').dispatch('click'); await settle();
  await tiles(tree)[1].dispatch('click');
  await button(tree, 'Next →').dispatch('click'); await settle();
  out.line = tree.textContent.includes('Engraving mode:');
  let pending = button(tree, FORWARD).dispatch('click'); await wait(600); await settle();       // the click stays unanswered while the question is open
  out.title = dialog().querySelector('h3').textContent;
  out.kinds = kinds().map((k) => [k.querySelector('strong').textContent, k.querySelector('img').getAttribute('src')]);
  const picture = await fetch(BASE + out.kinds[1][1]);
  out.picture = [picture.status, picture.headers.get('content-type')];
  out.made = (await named()).length;
  await dialog().querySelectorAll('button').find((b) => b.textContent === '← Back').dispatch('click'); await settle(); await pending; await wait(300);
  out.afterBack = (await named()).length;
  out.back = [heading(tree), !button(tree, FORWARD).disabled, [...ctx.__went]];
  pending = button(tree, FORWARD).dispatch('click'); await wait(600); await settle();
  await kinds()[1].dispatch('click');
  out.label = dialog().querySelectorAll('button').find((b) => b.textContent.startsWith('Create in')).textContent;
  await dialog().querySelectorAll('button').find((b) => b.textContent.startsWith('Create in')).dispatch('click'); await settle(); await pending; await wait(300);
  out.went = [...ctx.__went];
  out.alerts = alerts(tree);
""")
    assert out["line"] is True and out["title"] == "New work · engraving mode"
    assert len(out["kinds"]) >= 3 and out["kinds"][0][1].split("?")[0].endswith("/kinds/grayscale.png")                  # the person's own picture in each kind, drawn by the server
    assert out["picture"][0] == 200 and out["picture"][1] == "image/png"
    assert out["made"] == 1 and out["afterBack"] == 0                                                       # made to show the kinds, deleted by «← Back»
    assert out["back"] == ["New work · step 3 of 3: Settings and creation", True, []]
    chosen = out["kinds"][1][1].split("?")[0].rsplit("/", 1)[1].removesuffix(".png")
    assert out["label"].startswith("Create in “") and out["alerts"] == [], out["alerts"]
    [went] = out["went"]
    work_id = int(went.split("=")[1])
    assert went == f"/photo-engraving?work={work_id}"
    kept = client.get(f"/api/photo-works/{work_id}").json()
    assert kept["name"] == "Фото Инны" and kept["kind"] == chosen != "grayscale"                          # the kind marked in the question is the kind of the work
    assert [w["id"] for w in client.get("/api/photo-works").json() if w["name"] == "Фото Инны"] == [work_id]
    assert [d for d in client.get("/api/creation/drafts").json() if d["name"] == "Фото Инны"] == []        # the task is closed only now


@node
def test_in_a_workshop_with_nothing_measured_the_gate_names_the_starter_test_and_no_work_is_made(tmp_path):
    from titanium_platform import devices, lenses, plans, vector_job
    from titanium_platform import setup as su
    from titanium_platform.api.app import create_app
    from fastapi.testclient import TestClient
    app = create_app(tmp_path / "bare")
    store = app.state.store
    plans.save_marker_layer_settings(store, 25, 60, 150, pulse_width=200, line_interval=0.01, passes=1)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r", name="JPT M7", serial="E2E-1")
    lens = lenses.create_lens(store, "F-Theta", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    su.save_material(store, "Grade 5 sheet", grade="Grade 5", thickness_mm=1.0)
    (tmp_path / "run").mkdir()
    with TestClient(app) as client, serve(app) as base:
        out = run(tmp_path / "run", base, """
  const tree = await screen();
  await fillPicture(tree, 'Первый опыт', '50');
  await button(tree, 'Next →').dispatch('click'); await settle();
  out.status = tiles(tree).map((t) => t.textContent.includes('measurements needed'));
  await tiles(tree)[1].dispatch('click');
  await button(tree, 'Next →').dispatch('click'); await settle();
  const gate = labelled(tree, 'Missing prerequisites');
  out.gate = gate.textContent;
  out.disabled = button(tree, 'Next: engraving mode →').disabled;
  await button(tree, '← Back').dispatch('click'); await settle();
  await tiles(tree)[2].dispatch('click');
  await button(tree, 'Next →').dispatch('click'); await settle();
  out.silhouette = labelled(tree, 'Missing prerequisites').textContent;
  const make = button(tree, 'Create starter test');
  out.makeEnabled = make && !make.disabled;
  if (make) { await make.dispatch('click'); await settle(); }
  out.made = labelled(tree, 'Missing prerequisites').textContent;
  out.links = labelled(tree, 'Missing prerequisites').querySelectorAll('a').map((a) => a.getAttribute('href'));
  await wait(900); await settle();
""")
        drafts = client.get("/api/creation/drafts").json()
        assert all(out["status"]), out["status"]
        assert "Measurements needed" in out["gate"] and "Starter test: Gray scales" in out["gate"]
        assert "a measured grayscale scale will become available" in out["gate"] and out["disabled"] is True
        assert "Measurements needed" in out["silhouette"] and "Accepted test measurements" in out["silhouette"]
        assert out["makeEnabled"] is True and "Test created: Calibration matrix" in out["made"]                  # the vector starter test is made on the real route
        assert any(href.startswith("#/experiment/plan-") for href in out["links"]), out["links"]
        assert "What becomes available: Accepted test measurements" in out["made"]                           # ... and still says what its measurements will give
        assert len(drafts) == 1 and drafts[0]["name"] == "Первый опыт" and drafts[0]["status"] == "open"        # the task waits, with its picture
        assert drafts[0]["image"]["name"] == "portrait.png" and drafts[0]["state"]["waiting"]["result"] == "silhouette"
        assert client.get("/api/photo-works").json() == []                                                         # nothing half-made: no work was created
        assert vector_job.listing(store) == []
