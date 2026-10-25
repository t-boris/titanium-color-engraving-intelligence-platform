"""The laboratories screens (feature electron, REQ-083..085): the menu entry «Лаборатории», the source picker of a new vector or photo work,
the source banner of an open pinned work with «Обновить источник» and «Вернуться к прежнему источнику», and the card of a connected laboratory.
Run in node over the small DOM of the other screen tests with a fake server; the text a release carries reaches the screen as text only."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import GLUE, TABLES, UI, job, routes_of, work    # noqa: F401  (fixtures)
from titanium_platform.api.app import UI_DIR

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
HELPERS = ["app.js", "photo-modes.js", "photo-quality.js", "dialogs.js", "list.js", "hardware.js", "filepick.js", "tasks.js"]
SCRIPTS = ["screens/lab-source.js", "screens/vector-split.js",
           "screens/vector-photo.js", "screens/lettering.js", "screens/vector-editor.js", "screens/vector-colours.js", "screens/vector-review.js",
           "screens/vector-workspace.js", "screens/vector.js", "screens/photo-panels.js", "screens/labs-cloud.js", "screens/labs.js"]
FORM_DATA = "globalThis.FormData = class { constructor() { this.items = []; } append(k, v) { this.items.push([k, typeof v === 'object' && v ? v.name : String(v)]); } };"
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
const plain = ctx.fetch;
ctx.fetch = async (url, opts = {}) => {            // POST answers may differ from GET ones: a route may be given as {GET: ..., POST: ...}
  const path = String(url).split('?')[0], r = data.routes[path];
  if (r && (r.GET || r.POST)) { ctx.requests.push({path, url: String(url), method: opts.method || 'GET', body: opts.body}); const a = r[opts.method || 'GET'] || {status: 404, json: {error: 'none'}};
    return {ok: a.status < 300, status: a.status, headers: {get: () => 'application/json'}, json: async () => a.json}; }
  return plain(url, opts);
};
load(ctx, %(ui)s, [...%(tables)s, 'i18n-labs.js', ...%(helpers)s, {code: %(glue)s}, ...%(scripts)s, {code: 'globalThis.LabSource = LabSource;'}]);
const tick = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const sent = () => ctx.requests.filter((r) => r.method !== 'GET').map((r) => [r.method, r.path, typeof r.body === 'string' ? JSON.parse(r.body) : r.body && r.body.items]);
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""

CHOICES = [{"source_id": 4, "name": "Лаборатория <b>Север</b>", "release": {"release_id": "r-1", "release_number": 3, "created_at": "2026-10-20T09:00:00Z",
                                                                             "content_sha256": "abcdef0123456789ffff", "verified": False, "terms": {"id": "CC-BY-4.0"}, "attribution": {"name": "Автор"}},
            "setups": [{"laser": {"uuid": "L1", "public_name": "Волоконный 60 Вт", "manufacturer": "JPT", "model": "M7"}, "lens": {"uuid": "N1", "focal_length_mm": 174},
                        "material": {"uuid": "M1", "family": "titanium", "grade": "Grade 5", "thickness_mm": 1.0}, "photographs": 12},
                       {"laser": {"uuid": "L1", "public_name": "Волоконный 60 Вт"}, "lens": None, "material": None, "photographs": 2}]}]
SOURCE = {"kind": "release", "release_id": "r-1", "source_id": 4, "lab_name": "Лаборатория <b>Север</b>", "content_sha256": "abcdef0123456789ffff",
          "release_created_at": "2026-10-20T09:00:00Z", "laser": {"uuid": "L1", "id": 1, "public_name": "Волоконный 60 Вт"}, "lens": {"uuid": "N1", "id": 2, "focal_length_mm": 174},
          "material": {"uuid": "M1", "id": 3, "family": "titanium", "grade": "Grade 5", "thickness_mm": 1.0}, "pinned_at": "2026-10-21T10:00:00", "algorithm_versions": {},
          "withdrawn_hidden": 1, "conditions": ["the colours and curves are another laboratory's measurements on its laser: the same colour on this laser is not promised",
                                                "a newer release of this laboratory is connected: the work keeps its own until its source is updated"],
          "frozen": None, "versions": 1}
FROZEN = "this work was calculated with other versions of the algorithms (palette): its confirmed result is kept and not calculated again; update its source to calculate it with this version"


def ok(body, status=200):
    return {"status": status, "json": body}


def run(tmp_path, routes, body, plan=None) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes, "plan": plan}), encoding="utf-8")
    script = tmp_path / "labs.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "helpers": json.dumps(HELPERS), "scripts": json.dumps(SCRIPTS), "glue": json.dumps(GLUE + FORM_DATA),
                                 "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_menu_has_laboratories_with_an_icon_of_its_own_and_the_screens_are_loaded_in_order():
    router = (UI_DIR / "router.js").read_text(encoding="utf-8")
    nav = re.findall(r"\['(/[\w-]+)', '", router[router.index("const NAV"):router.index("const ROUTE_ID")])
    icons = re.findall(r"^\s+'<", router[router.index("const ICONS"):router.index("function icon")], re.M)
    assert nav[-2:] == ["/labs", "/workshop"] and "['/labs', 'Лаборатории']" in router and "labs: 'labs'" in router and len(icons) == len(nav)
    scripts = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
    order = {s: i for i, s in enumerate(scripts)}
    assert order["/i18n-labs.js"] < order["/i18n-gaps.js"] < order["/app.js"]
    assert order["/screens/lab-source.js"] < order["/screens/photo-engraving.js"] and order["/screens/lab-source.js"] < order["/screens/vector.js"]
    assert order["/screens/photo-panels.js"] < order["/screens/labs-cloud.js"] < order["/screens/labs.js"]
    labs = (UI_DIR / "screens" / "labs.js").read_text(encoding="utf-8")
    source = (UI_DIR / "screens" / "lab-source.js").read_text(encoding="utf-8")
    assert "App.register({id: 'labs'" in labs and "innerHTML" not in labs and "innerHTML" not in source      # release text is never markup
    for route in ("'/labs/own'", "'/labs/own/preview'", "'/labs/own/releases'", "'/labs/own/withdrawals'", "'/labs/files'", "/connect`", "/cancel`",
                  "'/labs/sources'", "'/labs/choices'", "'/labs/palette'", "'/labs/scales'", "'/labs/transfers'", "/differences`", "/disconnect`", "/reconnect`"):
        assert route in labs, route


@node
def test_a_new_vector_work_offers_the_own_measurements_first_and_sends_the_chosen_release_as_its_source(tmp_path):
    routes = {"/api/devices": ok([{"id": 1, "name": "JPT", "title": "JPT YDFLP-E-60", "lens": {"id": 2}}]), "/api/lenses": ok([{"id": 2, "kind": "F-Theta", "focal_length_mm": 174}]),
              "/api/materials": ok([{"id": 3, "name": "Small Plate", "grade": "Grade 5"}]), "/api/vector-palette": ok({"entries": [{"basis": "chart"}]}),
              "/api/rules": ok({"delta_tolerance": 5.0}), "/api/vector": ok({"id": 99}, 201), "/api/labs/choices": ok(CHOICES),
              "/api/labs/palette": ok({"source": SOURCE, "conditions": SOURCE["conditions"], "entries": [{"basis": "clean"}, {"basis": "as-shot"}]})}
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.vector.render({query: {new: '1'}});
  await tick();
  const select = tree.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Источник измерений');
  out.options = select.options.map((o) => [o.value, o.textContent]);
  out.first = [select.value, tree.querySelectorAll('p').filter((p) => p.textContent.includes('Измеренных цветов заливки')).map((p) => p.textContent).pop()];
  select.value = '1'; await select.dispatch('change'); await tick();
  out.info = tree.querySelectorAll('p').filter((p) => p.textContent.includes('Измеренных цветов заливки')).map((p) => p.textContent).pop();
  out.hint = select.parentNode.textContent;
  tree.querySelectorAll('input').find((i) => i.getAttribute('type') === 'file').files = [{name: 'portrait.jpg'}];
  await byText(tree, 'button', 'Создать работу').dispatch('click'); await tick();
  out.created = sent().filter(([, path]) => path === '/api/vector');
  const strategy = tree.querySelectorAll('select').find((sel) => sel.getAttribute('aria-label') === 'Стратегия');
  strategy.value = 'fill'; await strategy.dispatch('change'); await tick();
  out.hiddenForTrace = select.parentNode.hidden;
""")
    assert out["options"][0] == ["", "Мои измерения"] and out["first"][0] == ""                                            # the own measurements, chosen
    assert "этого лазера, линзы и титана этой марки (с любой плиты): 1" in out["first"][1]
    assert out["options"][1] == ["1", "Лаборатория <b>Север</b>: Волоконный 60 Вт · линза 174 мм · titanium · Grade 5 · 1 мм (фото 12)"]
    assert len(out["options"]) == 2                                                                                          # a setup without titanium colours nothing
    assert "лаборатории «Лаборатория <b>Север</b>» (выпуск от 2026-10-20 · abcdef012345; Волоконный 60 Вт · линза 174 мм · titanium · Grade 5 · 1 мм): 2" in out["info"]
    assert "без привязки к эталону: 1" in out["info"] and "тот же цвет на этом лазере не обещан" in out["info"]           # the conditions, translated
    assert "подпись не проверена" in out["hint"]
    [(method, path, items)] = out["created"]
    assert method == "POST" and json.loads(dict(items)["source"]) == {"release_id": "r-1", "laser": "L1", "lens": "N1", "material": "M1"}
    assert out["hiddenForTrace"] is True                                                                                     # a traced work takes the own measurements


@node
def test_an_open_pinned_vector_work_shows_its_source_and_updates_it_only_through_a_confirmed_preview(work, job, tmp_path):
    routes = routes_of(work, job)
    base = {**routes[f"/api/vector/{job['id']}"]["json"], "source": SOURCE}
    preview = {"from": SOURCE, "to": {**SOURCE, "content_sha256": "0123456789abcdefffff", "release_created_at": "2026-10-23T09:00:00Z", "frozen": None},
               "back": False, "entries": [{"entry_id": "e1", "before": {"lab": [50, 10, 10], "srgb": [140, 110, 100]}, "after": {"lab": [52, 10, 10], "srgb": [145, 112, 102]}, "delta_e": 2.0, "missing": False},
                                          {"entry_id": "e2", "before": {"lab": [60, 0, 0], "srgb": [145, 145, 145]}, "after": None, "delta_e": None, "missing": True}],
               "missing": 1, "changed": 1, "max_delta_e": 2.0, "zones": [{"zone": 1, "problem": None}]}
    after = {**base, "source": {**SOURCE, "content_sha256": "0123456789abcdefffff", "versions": 2, "conditions": [SOURCE["conditions"][0]]}}
    routes[f"/api/vector/{job['id']}"] = ok(base)
    routes[f"/api/vector/{job['id']}/source"] = {"POST": ok({**preview, "work": after})}
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.vector.render({query: {plan: String(data.plan)}});
  await tick();
  const banner = tree.querySelector('.lab-banner');
  out.banner = [banner.hidden, banner.textContent, banner.querySelector('.lab-name').childNodes.map((n) => n.nodeType)];
  out.buttons = banner.querySelectorAll('button').map((b) => b.textContent);
  await byText(banner, 'button', 'Обновить источник').dispatch('click'); await tick();
  const dialog = ctx.document.body.querySelector('.modal');
  out.dialog = dialog.textContent;
  out.colours = [dialog.querySelectorAll('.lst-main').map((m) => m.textContent), dialog.querySelectorAll('.lst-chip').map((c) => c.textContent)];
  out.beforeConfirm = sent().filter(([, path]) => path.endsWith('/source'));
  await byText(dialog, 'button', 'Подтвердить').dispatch('click'); await tick();
  out.afterConfirm = sent().filter(([, path]) => path.endsWith('/source'));
  out.updated = tree.querySelector('.lab-banner').textContent;
""", plan=job["id"])
    hidden, text, kinds = out["banner"]
    assert hidden is False and kinds == [3]                                                                                  # the laboratory's name is a text node
    assert "Лаборатория <b>Север</b>" in text and "выпуск от 2026-10-20 · abcdef012345" in text and "отозванных измерений исключено: 1" in text
    assert "Волоконный 60 Вт · линза 174 мм · titanium · Grade 5 · 1 мм" in text
    assert "тот же цвет на этом лазере не обещан" in text and "Подключён более новый выпуск этой лаборатории" in text        # every condition, translated
    assert "заморожен" not in text and out["buttons"] == ["Обновить источник", "Вернуться к прежнему источнику"]             # versions > 0
    assert out["beforeConfirm"] == [["POST", f"/api/vector/{job['id']}/source", {}]]                                                  # the preview changes nothing
    assert "Работа перейдёт на источник: Лаборатория <b>Север</b>, выпуск от 2026-10-23 · 0123456789ab" in out["dialog"]
    assert "изменятся: 1; пропадут: 1; наибольшая разница ΔE 2.0" in out["dialog"] and "в новом источнике не измерен" in out["dialog"]
    assert "зона 1: шкала измерена в новом источнике" in out["dialog"]
    colours, chips = out["colours"]                                                                        # a colour a line, the lost and the largest changes first
    assert "в новом источнике не измерен" in colours[0] and colours[1].endswith("ΔE 2.0") and chips == ["Все · 2", "пропадут · 1", "изменятся · 1"]
    assert out["afterConfirm"][-1] == ["POST", f"/api/vector/{job['id']}/source", {"confirm": True}]
    assert "0123456789ab" in out["updated"] and "прежних источников: 2" in out["updated"] and "более новый выпуск" not in out["updated"]   # drawn from the returned work


@node
def test_a_frozen_source_is_shown_apart_and_the_connected_laboratory_card_offers_the_palette_and_a_check_on_the_own_laser(tmp_path):
    card = {"id": 4, "name": "Лаборатория <b>Север</b>", "status": "connected", "connected_at": "2026-10-20T10:00:00", "kept": 1, "withdrawals": 0, "release_withdrawn": False,
            "lab": {"name": "Лаборатория <b>Север</b>", "description": "<script>alert(1)</script>", "url": "https://north.example"},
            "current": {"release_id": "r-1", "release_number": 3, "created_at": "2026-10-20T09:00:00Z", "content_sha256": "abcdef0123456789ffff", "verified": False, "status": "kept",
                        "terms": {"id": "CC-BY-4.0"}, "attribution": {"name": "Автор"}, "counts": {"measurements": 40}},
            "releases": [{"release_id": "r-1", "release_number": 3, "created_at": "2026-10-20T09:00:00Z", "content_sha256": "abcdef0123456789ffff", "verified": False, "status": "kept",
                          "withdrawn": False, "works": [{"plan_id": 12, "name": "Портрет", "mode": "vector"}]}], "withdrawal_list": []}
    palette = {"source": SOURCE, "conditions": [SOURCE["conditions"][0]], "entries": [
        {"id": "e1", "lab": [50, 10, 10], "srgb": [140, 110, 100], "basis": "chart", "engravings": 2, "agreement": {"engravings": 2, "agreeing": 2, "differing": 0}, "caution": None,
         "recipe": {"power": 40, "frequency": 30, "speed": 500, "pulse_width": 200, "line_interval": 0.02, "passes": 1}, "observation_ids": [1]}]}
    routes = {"/api/labs/sources/4": ok(card), "/api/labs/choices": ok(CHOICES), "/api/labs/palette": ok(palette),
              "/api/devices": ok([{"id": 1, "name": "JPT", "title": "JPT YDFLP-E-60"}]), "/api/materials": ok([{"id": 3, "name": "Small Plate", "grade": "Grade 5"}]),
              "/api/labs/transfers": {"GET": ok([]), "POST": ok({"plan_id": 77, "name": "Перенос · TCE-77"}, 201)}}
    out = run(tmp_path, routes, """
  const banner = ctx.LabSource.banner('/photo-works/7', 'photo', () => {});
  banner.update({source: {...data.frozenSource}, confirmed: {name: 'portrait.lbrn2', at: '2026-10-21T10:00:00', file: '/api/photo-works/7/export.lbrn2'}});
  out.frozen = [banner.el.querySelector('.lab-frozen').textContent, banner.el.querySelectorAll('li').map((l) => l.textContent), banner.el.querySelector('a').getAttribute('href'),
    banner.el.querySelectorAll('button').map((b) => b.textContent)];
  const tree = await ctx.__screens.labs.render({query: {source: '4'}});
  await tick();
  out.head = tree.querySelector('h2').textContent;
  out.sub = tree.querySelector('p').textContent;
  out.setups = tree.querySelectorAll('div').filter((d) => d.classList.contains('lab-setup-card')).map((d) => [d.querySelector('strong').textContent, d.querySelectorAll('button').map((b) => b.textContent)]);
  await byText(tree, 'button', 'Палитра').dispatch('click'); await tick();
  out.palette = sent();
  const colour = tree.querySelector('.lab-colours').querySelector('.lst-row');                // a colour is a line of the short list
  out.colour = colour.textContent;
  await byText(colour, 'button', 'Проверить у себя').dispatch('click'); await tick();
  const dialog = ctx.document.body.querySelector('.modal');
  out.dialogSelects = dialog.querySelectorAll('select').map((s) => s.getAttribute('aria-label'));
  await byText(dialog, 'button', 'Создать пластину').dispatch('click'); await tick();
  out.transfer = sent().pop();
  out.notice = tree.querySelectorAll('a').map((a) => a.getAttribute('href')).filter((href) => href.includes('/plans/'));
""".replace("data.frozenSource", json.dumps({**SOURCE, "frozen": FROZEN, "conditions": [SOURCE["conditions"][0], FROZEN], "versions": 0})))
    reason, conditions, file, buttons = out["frozen"]
    assert "Результат заморожен." in reason and "другими версиями алгоритмов (palette)" in reason
    assert conditions == ["Цвета и кривые — измерения другой лаборатории на её лазере: тот же цвет на этом лазере не обещан"]   # the frozen reason stands apart
    assert file == "/api/photo-works/7/export.lbrn2" and buttons == ["Обновить источник"]                                    # no earlier source to go back to
    assert out["head"].startswith("Лаборатория <b>Север</b>") and "<script>alert(1)</script>" in out["sub"]                   # the release's text, as text
    assert out["setups"] == [["Волоконный 60 Вт · линза 174 мм · titanium · Grade 5 · 1 мм", ["Палитра", "Шкалы серого"]],
                             ["Волоконный 60 Вт · линза неизвестна", ["Шкалы серого"]]]
    assert out["palette"] == [["POST", "/api/labs/palette", {"release_id": "r-1", "laser": "L1", "lens": "N1", "material": "M1"}]]
    assert "L 50.0 · a 10.0 · b 10.0" in out["colour"] and "по эталонной карте" in out["colour"] and "гравировок 2" in out["colour"] and "все 2 совпали" in out["colour"]
    assert "40.0 % · 30.0 кГц · 500 мм/с · 200 нс · шаг 0.0200 мм · проходов 1" in out["colour"]
    assert out["dialogSelects"] == ["Свой лазер", "Свой титан"]
    assert out["transfer"] == ["POST", "/api/labs/transfers", {"release_id": "r-1", "laser": "L1", "lens": "N1", "material": "M1", "entry_id": "e1", "device_id": 1, "material_id": 3}]
    assert out["notice"] == ["#/plans/77"]


@node
def test_a_laboratorys_releases_palette_and_transfers_are_short_lists_with_their_filters_and_orders(tmp_path):
    """REQ-005 of findings-you-can-manage-short-lists-re-check (DEC-090): a line per release, colour and transfer; details under a line."""
    release = lambda i, **more: {"release_id": f"r-{i}", "release_number": i, "created_at": f"2026-10-{i:02d}T09:00:00Z", "content_sha256": f"{i:02d}cdef0123456789ffff",   # noqa: E731
                                 "verified": True, "status": "kept", "withdrawn": False, "works": [], **more}
    card = {"id": 4, "name": "Север", "status": "connected", "connected_at": "2026-10-20T10:00:00", "kept": 3, "withdrawals": 0, "release_withdrawn": False,
            "lab": {"name": "Север"}, "current": release(3), "withdrawal_list": [],
            "releases": [release(1, status="removed"), release(3, works=[{"plan_id": 12, "name": "Портрет", "mode": "vector"}]), release(2, withdrawn=True)]}
    entries = [{"id": f"e{i}", "lab": [20 + i * 2, 0, 0], "srgb": [0, 0, 0], "basis": ["chart", "clean", "as-shot"][i % 3], "engravings": i % 4 + 1,
                "agreement": {"engravings": 1, "agreeing": 1, "differing": 0}, "caution": "contradicted" if i % 5 == 0 else None,
                "recipe": {"power": 40, "frequency": 30, "speed": 500, "passes": 1}, "observation_ids": [i]} for i in range(25)]
    transfers = [{"plan_id": 70 + i, "name": f"Перенос {i}", "identifier": f"TCE-{70 + i}", "source": {"lab": [50, 0, 0]}, "own_material": {"name": "Small Plate"},
                  "recipe": {"power": 40, "frequency": 30, "speed": 500, "passes": 1}, "created_at": f"2026-10-2{i}T10:00:00",
                  "measurements": [{"lab": [51, 0, 0], "pair_id": 90 + i, "delta_e": 1.5, "measured_at": "2026-10-24T10:00:00"}] if i == 1 else [],
                  "mean_delta_e": 1.5 if i == 1 else None} for i in range(3)]
    routes = {"/api/labs/sources/4": ok(card), "/api/labs/choices": ok(CHOICES), "/api/labs/palette": ok({"source": SOURCE, "conditions": [], "entries": entries}),
              "/api/labs/transfers": ok(transfers)}
    out = run(tmp_path, routes, """
  const tree = await ctx.__screens.labs.render({query: {source: '4'}});
  await tick();
  const card = (title) => tree.querySelectorAll('.card').find((c) => c.querySelector('h3') && c.querySelector('h3').textContent === title);
  const lines = (root) => root.querySelectorAll('.lst-main').map((m) => m.textContent);
  const releases = card('Выпуски');
  out.releases = [lines(releases), releases.querySelectorAll('.lst-row').map((r) => r.querySelectorAll('button').map((b) => b.textContent))];
  out.releaseChips = releases.querySelectorAll('.lst-chip').map((c) => c.textContent);
  await releases.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  const open = releases.querySelectorAll('.lst-det').find((d) => !d.hidden);
  out.releaseDetails = [open.querySelectorAll('dt').map((d) => d.textContent), open.querySelectorAll('a').map((a) => a.getAttribute('href'))];
  await byText(tree, 'button', 'Палитра').dispatch('click'); await tick();
  const palette = tree.querySelector('.lab-colours');
  out.palette = [palette.querySelectorAll('.lst-row').length, palette.querySelector('.lst-count').textContent, palette.querySelector('.lst-foot').textContent];
  out.paletteChips = palette.querySelectorAll('.lst-chip').map((c) => c.textContent);
  const order = palette.querySelectorAll('select').find((s) => s.getAttribute('aria-label') === 'Порядок');
  out.orders = order.options.map((o) => o.textContent);
  order.value = 'light'; await order.dispatch('change'); await tick();
  out.lightest = palette.querySelector('strong').textContent;
  await palette.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith('с оговоркой')).dispatch('click'); await tick();
  out.cautious = palette.querySelectorAll('.lst-row').map((r) => r.querySelector('strong').textContent);
  const done = card('Проверено у себя');
  out.transfers = [lines(done), done.querySelectorAll('.lst-act').map((a) => a.querySelector('a').getAttribute('href'))];
  await done.querySelectorAll('.lst-chip').find((c) => c.textContent.startsWith('измерены')).dispatch('click'); await tick();
  await done.querySelectorAll('.lst-main')[0].dispatch('click'); await tick();
  out.transferDetails = done.querySelectorAll('.lst-det').find((d) => !d.hidden).querySelectorAll('a').map((a) => a.getAttribute('href'));
""")
    lines, buttons = out["releases"]
    assert [x[:16] for x in lines] == ["2026-10-03 09:00", "2026-10-02 09:00", "2026-10-01 09:00"]                    # the newest first
    assert "текущий" in lines[0] and "работ: 1" in lines[0] and "отозван" in lines[1] and "файлы удалены" in lines[2]
    assert buttons == [["Различия", "Удалить файлы"], ["Различия", "Удалить файлы"], ["Различия"]]
    assert out["releaseChips"] == ["Все · 3", "на компьютере · 2", "файлы удалены · 1"]
    assert out["releaseDetails"] == [["Хеш", "Подпись", "Файлы", "Работы"], ["#/vector?plan=12"]]
    assert out["palette"] == [20, "показано 20 из 25", "Показать ещё 5"]
    assert out["paletteChips"] == ["Все · 25", "по эталонной карте · 9", "относительно чистого титана · 8", "как снято, без привязки · 8",
                                   "Все · 25", "без оговорок · 20", "с оговоркой · 5"]
    assert out["orders"] == ["Как в выпуске", "Сначала светлые", "Сначала тёмные", "Больше гравировок"]
    assert out["lightest"] == "L 68.0 · a 0.0 · b 0.0"
    assert out["cautious"] == ["L 60.0 · a 0.0 · b 0.0", "L 50.0 · a 0.0 · b 0.0", "L 40.0 · a 0.0 · b 0.0", "L 30.0 · a 0.0 · b 0.0", "L 20.0 · a 0.0 · b 0.0"]
    transfers, plans = out["transfers"]
    assert [x.split(" · ")[0] for x in transfers] == ["Перенос 2", "Перенос 1", "Перенос 0"] and "средняя ΔE 1.5" in transfers[1] and "ждёт фото" in transfers[0]
    assert plans == ["#/plans/72", "#/plans/71", "#/plans/70"] and out["transferDetails"] == ["#/analysis/91"]
