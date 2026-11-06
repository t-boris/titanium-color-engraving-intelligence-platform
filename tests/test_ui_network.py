"""The network screen (feature electron, REQ-082, DEC-047, REQ-080; REQ-086): the menu entry «Network», the local network card with its addresses,
the pairing code with its countdown, the certificate fingerprint and download, the devices with rename and revoke, the switches of what
may be reached outside this computer and the address of the cloud of laboratories. Run in node over the small DOM of the other screen tests with a fake server; a device's name
reaches the screen as text only."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_vector_work import GLUE, TABLES, UI
from titanium_platform.api.app import UI_DIR

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
HELPERS = ["app.js", "forms.js", "dialogs.js", "list.js"]
HARNESS = """
const fs = require('fs');
const {context, load} = require(%(dom)s);
const data = JSON.parse(fs.readFileSync(%(data)s, 'utf8'));
const ctx = context(data.routes);
const plain = ctx.fetch;
ctx.fetch = async (url, opts = {}) => {
  const path = String(url).split('?')[0], r = data.routes[path];
  if (r && (r.GET || r.PUT || r.POST)) { ctx.requests.push({path, url: String(url), method: opts.method || 'GET', body: opts.body});
    const a = r[opts.method || 'GET'] || {status: 404, json: {error: 'none'}};
    return {ok: a.status < 300, status: a.status, headers: {get: () => 'application/json'}, json: async () => a.json}; }
  return plain(url, opts);
};
load(ctx, %(ui)s, [...%(tables)s, 'i18n-lan.js', ...%(helpers)s, {code: %(glue)s}, 'screens/network.js']);
const tick = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };
const byText = (root, tag, text) => root.querySelectorAll(tag).find((el) => el.textContent === text);
const sent = () => ctx.requests.filter((r) => r.method !== 'GET').map((r) => [r.method, r.path, typeof r.body === 'string' ? JSON.parse(r.body) : r.body]);
(async () => {
  const out = {};
%(body)s
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""
STATUS = {"enabled": True, "port": 8766, "name": "Bench", "running": True, "bound_port": 8766, "addresses": ["192.168.1.20"], "hosts": ["studio", "studio.local"],
          "urls": ["https://192.168.1.20:8766"], "fingerprint": "AB:CD:" * 15 + "EF", "certificate_until": "2028-10-20T10:00:00+00:00", "error": None,
          "devices": [{"id": 5, "name": "iPad <b>bench</b>", "created_at": "2026-10-20T09:00:00+00:00", "last_seen_at": "2026-10-24T10:00:00+00:00", "revoked_at": None},
                      {"id": 2, "name": "Old", "created_at": "2026-09-01T09:00:00+00:00", "last_seen_at": None, "revoked_at": "2026-10-01T09:00:00+00:00"}],
          "code": {"code": "482913", "expires_in_s": 299}}
NETWORK = {"ai": True, "google_fonts": True, "update_checks": False, "cloud": True}
CLOUD = {"api_url": "https://labs.example.test", "default": "https://labs.example.test", "custom": False}


def ok(body, status=200):
    return {"status": status, "json": body}


def run(tmp_path, routes, body) -> dict:
    (tmp_path / "data.json").write_text(json.dumps({"routes": routes}), encoding="utf-8")
    script = tmp_path / "network.js"
    script.write_text(HARNESS % {"dom": json.dumps(str(Path(__file__).with_name("ui_dom.js"))), "data": json.dumps(str(tmp_path / "data.json")),
                                 "ui": json.dumps(str(UI) + "/"), "tables": json.dumps(TABLES), "helpers": json.dumps(HELPERS), "glue": json.dumps(GLUE),
                                 "body": body}, encoding="utf-8")
    done = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr[-2500:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_menu_has_the_network_screen_before_the_laboratories_and_its_files_are_loaded_in_order():
    router = (UI_DIR / "router.js").read_text(encoding="utf-8")
    nav = re.findall(r"\['(/[\w-]+)', '", router[router.index("const NAV"):router.index("const ROUTE_ID")])
    icons = re.findall(r"^\s+'<", router[router.index("const ICONS"):router.index("function icon")], re.M)
    assert nav[-3:] == ["/network", "/labs", "/workshop"] and "['/network', 'Network']" in router and "network: 'network'" in router and len(icons) == len(nav)
    scripts = re.findall(r'<script src="(/[^"]+)"', (UI_DIR / "index.html").read_text(encoding="utf-8"))
    order = {s: i for i, s in enumerate(scripts)}
    assert order["/i18n-lan.js"] < order["/i18n-gaps.js"] < order["/app.js"] < order["/screens/network.js"]
    screen = (UI_DIR / "screens" / "network.js").read_text(encoding="utf-8")
    assert "App.register({id: 'network'" in screen and "innerHTML" not in screen                 # a device's name is never markup
    assert "https://" not in screen                                                             # addresses come from the server, built there


@node
def test_the_screen_shows_the_network_the_code_the_certificate_and_the_devices_as_text(tmp_path):
    routes = {"/api/lan": {"GET": ok(STATUS)}, "/api/network": {"GET": ok(NETWORK)}, "/api/cloud/settings": {"GET": ok(CLOUD)}}
    out = run(tmp_path, routes, """
  const el = await ctx.__screens.network.render({query: {}});
  ctx.document.body.append(el);
  out.text = el.textContent;
  out.code = el.querySelector('.lan-code').textContent;
  out.fingerprint = el.querySelector('.fingerprint').textContent;
  out.download = el.querySelector('a[download]').getAttribute('href');
  out.urls = el.querySelector('.lan-urls').querySelectorAll('code').map((c) => c.textContent);
  out.devices = el.querySelectorAll('.device-name').map((d) => ({text: d.textContent, children: d.children.length}));
  out.pills = el.querySelectorAll('.pill').map((p) => p.textContent);
  out.enabled = el.querySelector('.lan-enabled').checked;
  out.switches = el.querySelectorAll('.switch').map((i) => i.checked);
  out.address = [el.querySelector('.cloud-address').textContent, el.querySelector('.cloud-address').querySelector('input').value];
""")
    assert "Local network" in out["text"] and "Tablet code" in out["text"] and "Workshop certificate" in out["text"] and "Connected tablets" in out["text"]
    assert out["code"] == "482913" and "expires in 4:59" in out["text"]
    assert out["fingerprint"] == STATUS["fingerprint"] and out["download"] == "/api/lan/ca"
    assert out["urls"] == ["https://192.168.1.20:8766"] and "https://192.168.1.20:8766/pair" in out["text"]
    assert out["devices"] == [{"text": "iPad <b>bench</b>", "children": 0}, {"text": "Old", "children": 0}]
    assert "running" in out["pills"] and "connected" in out["pills"] and any(p.startswith("revoked") for p in out["pills"])
    assert out["enabled"] is True
    assert "no telemetry" in out["text"] and "AI researcher" in out["text"] and "Google Fonts" in out["text"] and "update" in out["text"]
    assert out["switches"] == [True, True, False, True]                                                     # the cloud is on by default
    assert "Laboratory cloud" in out["text"] and out["address"][0].startswith("Laboratory cloud address") and out["address"][1] == ""   # the default address is not typed in
    assert "the default https://labs.example.test" in out["address"][0]


@node
def test_the_buttons_ask_for_a_code_apply_the_settings_revoke_after_confirmation_and_switch_the_services(tmp_path):
    routes = {"/api/lan": {"GET": ok(STATUS), "PUT": ok(STATUS)}, "/api/network": {"GET": ok(NETWORK), "PUT": ok({**NETWORK, "ai": False})},
              "/api/lan/code": {"POST": ok({"code": "111111", "expires_in_s": 300}, 201)},
              "/api/lan/devices/5/revoke": {"POST": ok({"id": 5, "revoked_at": "2026-10-24T11:00:00+00:00"})},
              "/api/lan/devices/5": {"PUT": ok({"id": 5, "name": "Bench"})},
              "/api/cloud/settings": {"GET": ok(CLOUD), "PUT": ok({**CLOUD, "api_url": "http://127.0.0.1:9000", "custom": True})}}
    out = run(tmp_path, routes, """
  const el = await ctx.__screens.network.render({query: {}});
  ctx.document.body.append(el);
  await byText(el, 'button', 'Another code').dispatch('click'); await tick();
  const inputs = el.querySelectorAll('input');
  inputs[0].checked = false; inputs[1].value = '9443'; inputs[2].value = 'Studio';
  await byText(el, 'button', 'Apply').dispatch('click'); await tick();
  await byText(el, 'button', 'Revoke').dispatch('click'); await tick();
  const dialog = ctx.document.body.querySelector('.modal');
  out.dialog = dialog.textContent;
  await byText(dialog, 'button', 'Revoke').dispatch('click'); await tick();
  await byText(el, 'button', 'Rename').dispatch('click'); await tick();
  const rename = ctx.document.body.querySelector('.modal');
  rename.querySelector('input').value = 'Bench';
  await byText(rename, 'button', 'Save').dispatch('click'); await tick();
  const ai = el.querySelectorAll('.switch')[0];
  ai.checked = false; await ai.dispatch('change'); await tick();
  const address = el.querySelector('.cloud-address');
  address.querySelector('input').value = ' http://127.0.0.1:9000 ';
  await byText(address, 'button', 'Save').dispatch('click'); await tick();
  out.address = address.querySelector('input').value;
  out.sent = sent();
  out.renders = ctx.__renders.length;
""")
    assert "iPad <b>bench</b>" in out["dialog"] and "its next request will be denied" in out["dialog"]
    assert out["sent"] == [["POST", "/api/lan/code", {}], ["PUT", "/api/lan", {"enabled": False, "port": 9443, "name": "Studio"}],
                           ["POST", "/api/lan/devices/5/revoke", {}], ["PUT", "/api/lan/devices/5", {"name": "Bench"}], ["PUT", "/api/network", {"ai": False}],
                           ["PUT", "/api/cloud/settings", {"api_url": "http://127.0.0.1:9000"}]]
    assert out["address"] == "http://127.0.0.1:9000"
    assert out["renders"] == 4                                                     # the code, the settings, the revoke and the rename reload the screen


@node
def test_the_openai_key_is_entered_on_the_network_screen_and_only_its_ending_is_shown(tmp_path):
    """BUG-007: the desktop application has no environment of a shell; the key is given to the workshop here."""
    key = {"set": True, "source": "workshop", "ending": "Zz99", "switched_on": True, "workshop_file": True}
    routes = {"/api/lan": {"GET": ok(STATUS)}, "/api/network": {"GET": ok(NETWORK)}, "/api/cloud/settings": {"GET": ok(CLOUD)},
              "/api/network/ai-key": {"GET": ok({"set": False, "source": None, "ending": None, "switched_on": True, "workshop_file": False}),
                                      "PUT": ok(key)}}
    out = run(tmp_path, routes, """
  const el = await ctx.__screens.network.render({query: {}});
  ctx.document.body.append(el);
  const box = el.querySelector('.ai-key');
  out.before = box.textContent;
  const input = box.querySelector('input');
  out.type = input.getAttribute('type');
  input.value = 'sk-proj-secret-secret-1234';
  await byText(box, 'button', 'Save key').dispatch('click'); await tick();
  out.cleared = input.value;
  out.sent = sent();
""")
    assert "key not set" in out["before"] and "ai/openai.key" in out["before"] and out["type"] == "password"
    assert out["sent"] == [["PUT", "/api/network/ai-key", {"key": "sk-proj-secret-secret-1234"}]] and out["cleared"] == ""


@node
def test_a_port_outside_the_servers_range_is_refused_beside_the_box_and_a_refused_address_stays_under_its_box(tmp_path):
    """ux-save-feedback-p0 REQ-003: the port is a whole number from 1024 to 65535 (lan.save_settings); what is typed is never corrected, and what the
    server says about the cloud address is shown under the address box with the typed text kept, not in a toast that goes away."""
    routes = {"/api/lan": {"GET": ok(STATUS), "PUT": ok(STATUS)}, "/api/network": {"GET": ok(NETWORK)},
              "/api/cloud/settings": {"GET": ok(CLOUD), "PUT": {"status": 422, "json": {"error": "the address must start with https://", "kind": "invalid"}}}}
    out = run(tmp_path, routes, """
  const el = await ctx.__screens.network.render({query: {}});
  ctx.document.body.append(el);
  const port = el.querySelectorAll('input')[1];
  const lan = () => el.querySelectorAll('label').filter((l) => l.textContent.startsWith('Port'))[0];
  const problems = [];
  for (const typed of ['80', '70000', '8766.5', 'abc', '']) {
    port.value = typed;
    await byText(el, 'button', 'Apply').dispatch('click'); await tick();
    problems.push([typed, lan().errorText(), port.value, port.getAttribute('aria-invalid')]);
  }
  out.problems = problems;
  out.sentWhileInvalid = sent().length;
  port.value = '1024';
  await byText(el, 'button', 'Apply').dispatch('click'); await tick();
  out.sent = sent();
  const address = el.querySelector('.cloud-address');
  address.querySelector('input').value = 'ftp://x';
  await byText(address, 'button', 'Save').dispatch('click'); await tick();
  out.refused = {kept: address.querySelector('input').value, message: address.querySelector('.f-form-error').textContent, shown: !address.querySelector('.f-form-error').hidden,
    toasts: ctx.document.body.querySelectorAll('.toast').map((t) => t.textContent)};
""")
    assert out["problems"] == [["80", "Allowed: whole number, from 1024 to 65535. Entered: 80", "80", "true"],
                               ["70000", "Allowed: whole number, from 1024 to 65535. Entered: 70000", "70000", "true"],
                               ["8766.5", "Enter a whole number. Entered: 8766.5", "8766.5", "true"],
                               ["abc", "Enter a number. Entered: “abc”", "abc", "true"],
                               ["", "Complete this field", "", "true"]]
    assert out["sentWhileInvalid"] == 0
    assert out["sent"][-1][:2] == ["PUT", "/api/lan"] and out["sent"][-1][2]["port"] == 1024
    assert out["refused"] == {"kept": "ftp://x", "shown": True, "toasts": ["Local network access enabled ×"],          # only the earlier success
                              "message": "The server rejected the data: the address must start with https://."
                                         " Your entries remain in the form; correct them and submit again."}
