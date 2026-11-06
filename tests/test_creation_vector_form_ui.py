"""The vector work entry and the shared context (feature ux-work-creation-p0, REQ-001): «Новая работа» opens the three-step creation screen, the
one-page form stays at ``&classic=1`` and starts from the laser, lens and titanium the workshop chose last (the address wins), and an opened
photograph work names its own measurements. Run in node over the small DOM of the other screen tests."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import test_vector_form_ui as form
from test_ui_labs import SOURCE, ok, run as labs_run
from test_vector_work import GLUE, TABLES, UI, job, routes_of, work    # noqa: F401  (fixtures)

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

TAIL = "'screens/vector.js']);"
assert TAIL in form.HARNESS, "the vector form harness changed: update the tail"
HARNESS = form.HARNESS.split("(async () => {")[0].replace(TAIL, "'screens/vector.js', 'context.js', 'screens/plate-dialog.js', 'screens/creation.js']);") + """
const settle = async () => { for (let i = 0; i < 8; i++) await tick(); };
const labelled = (root, label) => root.querySelectorAll('[aria-label]').find((el) => el.getAttribute('aria-label') === label);
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""

OK = lambda body, status=200: {"status": status, "json": body}  # noqa: E731
DEVICES = [{"id": 1, "name": "JPT", "title": "JPT 60", "lens": {"id": 2}}, {"id": 2, "name": "Mopa", "title": "Mopa 30", "lens": None}]
ROUTES = {"/api/devices": OK(DEVICES), "/api/lenses": OK([{"id": 2, "kind": "F-Theta", "focal_length_mm": 174}, {"id": 3, "kind": "F-Theta", "focal_length_mm": 100}]),
          "/api/materials": OK([{"id": 3, "name": "Small Plate", "grade": "Grade 5"}, {"id": 4, "name": "Sheet", "grade": "Grade 2"}]),
          "/api/materials/3": OK({"id": 3, "name": "Small Plate", "grade": "Grade 5"}), "/api/materials/4": OK({"id": 4, "name": "Sheet", "grade": "Grade 2"}),
          "/api/vector-palette": OK({"entries": []}), "/api/rules": OK({"delta_tolerance": 5.0}), "/api/vector": OK({"id": 99}, 201),
          "/api/creation/drafts": OK([])}


def context(**changes):
    return {"device_id": 2, "lens_id": 3, "lens_basis": "chosen", "material_id": 4, "capture_setup_id": None, "source": None, "stale": [],
            "device": {"id": 2, "name": "Mopa", "title": "Mopa 30"}, "lens": {"id": 3, "name": "F-Theta", "focal_length_mm": 100},
            "material": {"id": 4, "name": "Sheet", "grade": "Grade 2"}, "capture_setup": None, **changes}


def run(tmp_path, body, routes=None, shared=None):
    table = {**ROUTES, **(routes or {})}
    if shared is not None:
        table["/api/creation/context"] = OK(shared)
    (tmp_path / "data.json").write_text(json.dumps({"routes": table}), encoding="utf-8")
    script = tmp_path / "form.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "glue": json.dumps(GLUE + form.FORM_DATA), "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


STARTS = """
  const tree = await ctx.__screens.vector.render({query: %s});
  await settle();
  const stock = tree.querySelectorAll('.matpick').find((s) => s.getAttribute('aria-label') === 'Титан');       // the titanium is the stock selector, no longer a drop-down
  await settle();
  out.chosen = [labelled(tree, 'Laser').value, labelled(tree, 'Lens').value, stock ? stock.value : null];
"""


@node
def test_new_vector_work_opens_the_three_step_screen_and_the_one_page_form_stays_at_classic(tmp_path):
    out = run(tmp_path, """
  const wizard = await ctx.__screens.vector.render({query: {new: '1'}});
  await settle();
  out.wizard = wizard.querySelector('h2').textContent;
  const classic = await ctx.__screens.vector.render({query: {new: '1', classic: '1'}});
  await settle();
  out.classic = classic.querySelector('h2').textContent;
""", shared=context())
    assert out["wizard"] == "New work · step 1 of 3: Image and size" and out["classic"] == "Новая векторная работа"


@node
def test_the_classic_form_starts_on_the_laser_lens_and_titanium_the_workshop_chose_last(tmp_path):
    out = run(tmp_path, STARTS % "{new: '1', classic: '1'}", shared=context())
    assert out["chosen"] == ["2", "3", "4"]                                           # not the first laser, its installed lens or the first stock


@node
def test_the_address_names_the_laser_and_lens_and_wins_over_the_shared_choice_which_still_gives_the_titanium(tmp_path):
    out = run(tmp_path, STARTS % "{new: '1', classic: '1', device: '1', lens: '2'}", shared=context())
    assert out["chosen"] == ["1", "2", "4"]
    out = run(tmp_path, STARTS % "{new: '1', classic: '1', device: '1'}", shared=context())
    assert out["chosen"] == ["1", "2", "4"]                                           # a laser from the address takes its installed lens, not the shared lens


@node
def test_a_shared_choice_that_cannot_be_read_leaves_the_form_as_it_always_was(tmp_path):
    out = run(tmp_path, STARTS % "{new: '1', classic: '1'}", routes={"/api/creation/context": {"status": 500, "json": {"error": "workshop is busy"}}})
    assert out["chosen"] == ["1", "2", "3"]                                           # the first laser, its installed lens, the first stock
    out = run(tmp_path, STARTS % "{new: '1', classic: '1'}")
    assert out["chosen"] == ["1", "2", "3"]


AFTER = context(device_id=1, lens_id=2, material_id=3, device={"id": 1, "name": "JPT", "title": "JPT 60"}, lens={"id": 2, "name": "F-Theta", "focal_length_mm": 174},
                material={"id": 3, "name": "Small Plate", "grade": "Grade 5"})
CHANGE = """
  const real = ctx.fetch, puts = [];
  ctx.fetch = async (url, opts = {}) => {                    // the saved context is the answer of the PUT; the other routes are the table's
    if (String(url).split('?')[0] === '/api/creation/context' && opts.method === 'PUT') {
      puts.push(JSON.parse(opts.body));
      return {ok: true, status: 200, headers: {get: () => 'application/json'}, json: async () => (%s), text: async () => '', blob: async () => ({size: 0})};
    }
    return real(url, opts);
  };
""" % json.dumps(AFTER)


@node
def test_the_classic_form_changes_the_shared_choice_by_the_same_dialog_with_the_warnings_before_apply_and_follows_it(tmp_path):
    out = run(tmp_path, CHANGE + """
  const tree = await ctx.__screens.vector.render({query: {new: '1', classic: '1'}});
  ctx.document.body.append(tree);                           // in the page, as the router places it: only then can the keyboard focus be followed
  await settle();
  const strip = tree.querySelector('.work-context');
  out.strip = strip.textContent;
  out.first = [labelled(tree, 'Laser').value, labelled(tree, 'Lens').value, labelled(tree, 'Титан').value];
  const open = strip.querySelectorAll('button').find((b) => b.textContent === 'Change…');
  await open.dispatch('click'); await settle();
  const dialog = ctx.document.body.querySelector('.modal');
  out.title = dialog.querySelector('h3').textContent;
  out.hasSource = dialog.textContent.includes('Measurement source');
  const laser = dialog.querySelectorAll('select').find((x) => x.getAttribute('aria-label') === 'Laser');
  laser.value = '1'; await laser.dispatch('change'); await settle();
  out.warned = [dialog.textContent.includes('The titanium grade is different'), puts.length];
  out.impactBody = JSON.parse(ctx.requests.filter((r) => r.path === '/api/creation/context/impact').pop().body);
  const apply = dialog.querySelectorAll('button').find((b) => b.textContent === 'Apply');
  await apply.dispatch('click'); await settle();
  out.puts = puts;
  out.closed = ctx.document.body.querySelector('.modal') === null;
  out.after = [labelled(tree, 'Laser').value, labelled(tree, 'Lens').value, labelled(tree, 'Титан').value];
  out.strip2 = tree.querySelector('.work-context').textContent;
  out.focus = ctx.document.activeElement && ctx.document.activeElement.textContent;
  out.palette = ctx.requests.filter((r) => r.path === '/api/vector-palette').length;
""", shared=context(), routes={"/api/creation/context/impact": OK({"changed": True, "warnings": [{"code": "titanium_differs"}], "now": {}, "after": {}})})
    assert "Общий выбор мастерской" in out["strip"] and "Mopa 30" in out["strip"] and out["first"] == ["2", "3", "4"]
    assert out["title"] == "New work context" and out["hasSource"] is False                 # the form has its own source picker: the dialog leaves it out
    assert out["warned"] == [True, 0]                                                            # the warning is read before «Apply», and nothing is saved yet
    assert out["impactBody"] == {"device_id": 1, "lens_id": 2, "material_id": 4, "source": None}
    assert out["puts"] == [{"device_id": 1, "lens_id": 2, "material_id": 4, "source": None}] and out["closed"] is True
    assert out["after"] == ["1", "2", "3"] and "JPT 60" in out["strip2"] and out["focus"] == "Change…"      # the form follows the saved choice; the keyboard returns to the button
    assert out["palette"] >= 2                                                                    # and reads the colours of the new laser, lens and titanium


@node
def test_an_opened_photograph_work_names_its_own_measurements_under_its_parameters_and_the_shared_choice_does_not_change_them(work, job, tmp_path):
    routes = routes_of(work, job)
    pinned = {**routes[f"/api/vector/{job['id']}"]["json"], "source": SOURCE}
    body = """
  const tree = await ctx.__screens.vector.render({query: {plan: String(data.plan)}});
  await tick();
  const dts = tree.querySelectorAll('dt');
  const row = dts.find((d) => d.textContent === 'Измерения');
  out.row = [row.textContent, row.parentNode.querySelectorAll('dd')[dts.indexOf(row)].textContent];
  out.laser = dts.find((d) => d.textContent === 'Лазер') !== undefined;
"""
    (tmp_path / "own").mkdir()
    own = labs_run(tmp_path / "own", routes, body, plan=job["id"])
    assert own["row"][0] == "Измерения" and own["row"][1] == "этой мастерской"
    routes[f"/api/vector/{job['id']}"] = ok(pinned)
    (tmp_path / "release").mkdir()
    release = labs_run(tmp_path / "release", routes, body, plan=job["id"])
    assert release["row"][1] == "лаборатория Лаборатория <b>Север</b>"                  # the laboratory's name is shown as text, never as markup
