"""The local network (feature electron, REQ-082, DEC-047) and the switches of what the application may reach outside this computer
(REQ-080): ``/api/lan`` for the operator's computer (status with the pairing code, settings, codes, devices), ``/api/lan/pair`` and
``/api/lan/ca`` for a tablet, the pairing page ``/pair``, and ``/api/network`` for the switches. ``api.security`` keeps everything but the
pairing page, the pairing call and the CA download away from the network."""
from __future__ import annotations

import html

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from .. import lan, outbound, research
from .common import store_of

router = APIRouter(prefix="/api/lan")
settings_router = APIRouter(prefix="/api/network")
pages = APIRouter()
CA_FILE = "titanium-workshop-ca.crt"


def lan_of(request: Request) -> lan.Lan:
    return request.app.state.lan


def from_network(request: Request) -> bool:
    return bool(request.scope.get(lan.MARK))


@router.get("")
def status(request: Request):
    """The local network as the screen shows it: settings, whether the server runs, addresses, the CA fingerprint, the devices and (on the
    workshop's own computer only) the pairing code."""
    return lan_of(request).status(owner=not from_network(request))


@router.put("")
def configure(request: Request, body: dict):
    """Switch the local network on or off, change its port or the name tablets see; the server follows at once."""
    lan_of(request).apply(body or {})
    return lan_of(request).status(owner=not from_network(request))


@router.post("/code", status_code=201)
def new_code(request: Request):
    """A new pairing code (five minutes, one use); it replaces the previous one."""
    return lan_of(request).codes.new()


@router.post("/pair")
def pair(request: Request, response: Response, body: dict):
    """From the tablet: the code and the tablet's name; the device cookie is set and the tablet is in."""
    body = body or {}
    name = lan.clean_name(body.get("name"))
    lan_of(request).codes.redeem(body.get("code"))
    device, token = lan.pair(store_of(request), name)
    response.set_cookie(lan.COOKIE, token, max_age=lan.COOKIE_MAX_AGE_S, httponly=True, secure=True, samesite="lax", path="/")
    return {"device": device, "workshop": lan.settings(store_of(request))["name"]}


@router.get("/ca")
def certificate(request: Request):
    """The workshop's CA certificate, to install on the tablet once (DEC-047)."""
    certs = lan_of(request).ensure_certificates()
    return Response(certs.ca_pem(), media_type="application/x-x509-ca-cert", headers={"Content-Disposition": f'attachment; filename="{CA_FILE}"'})


@router.get("/devices")
def devices(request: Request):
    return lan.devices(store_of(request))


@router.put("/devices/{device_id}")
def rename_device(device_id: int, request: Request, body: dict):
    return lan.rename(store_of(request), device_id, (body or {}).get("name"))


@router.post("/devices/{device_id}/revoke")
def revoke_device(device_id: int, request: Request):
    """End the device's access: its next request is refused."""
    return lan.revoke(store_of(request), device_id)


@settings_router.get("")
def network_settings(request: Request):
    return outbound.get(store_of(request))


@settings_router.put("")
def set_network_settings(request: Request, body: dict):
    return outbound.save(store_of(request), body)


@settings_router.get("/ai-key")
def ai_key(request: Request):
    """Whether the AI has a key and where it comes from (BUG-007); the key itself is never sent back."""
    outbound.apply(store_of(request))
    return research.key_status()


@settings_router.put("/ai-key")
def set_ai_key(request: Request, body: dict):
    outbound.apply(store_of(request))
    return research.save_key((body or {}).get("key"))


@settings_router.delete("/ai-key")
def forget_ai_key(request: Request):
    outbound.apply(store_of(request))
    return research.forget_key()


PAIR_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Подключение планшета</title>
<style>
  body {margin:0;padding:32px 20px;background:#0f1522;color:#e6ecf7;font:16px/1.5 -apple-system,system-ui,"Segoe UI",sans-serif}
  main {max-width:460px;margin:0 auto}
  h1 {font-size:22px;margin:0 0 6px} p {margin:8px 0} .muted {color:#9aa8c2;font-size:14px}
  label {display:block;margin:16px 0 6px;font-weight:600}
  input {width:100%;box-sizing:border-box;padding:12px 14px;border:1px solid #3a4860;border-radius:10px;background:#18213a;color:#fff;font-size:20px}
  input.code {letter-spacing:.3em;font-size:28px;text-align:center}
  button {margin-top:18px;width:100%;padding:13px;border:0;border-radius:10px;background:#b7c7ff;color:#11192d;font-size:17px;font-weight:700}
  button:disabled {opacity:.5} a {color:#b7c7ff}
  code {display:block;word-break:break-all;padding:10px 12px;border-radius:8px;background:#18213a;font-size:13px}
  #note {min-height:24px;color:#ffa9bb}
</style>
</head>
<body>
<main>
  <h1>Подключение планшета</h1>
  <p class="muted">Мастерская «__NAME__». Введите код с экрана «Сеть» на компьютере мастерской: он действует пять минут и один раз.</p>
  <form>
    <label for="code">Код</label>
    <input id="code" name="code" class="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required>
    <label for="name">Имя этого планшета</label>
    <input id="name" name="name" maxlength="64" placeholder="Планшет">
    <button type="submit">Подключить</button>
  </form>
  <p id="note" role="alert"></p>
  <p class="muted">Если браузер предупреждает о сертификате, сравните отпечаток центра сертификации мастерской, затем продолжите; чтобы
    предупреждений не было, <a href="/api/lan/ca">скачайте сертификат</a> и установите его один раз как профиль.</p>
  <code>__FINGERPRINT__</code>
</main>
<script>
(() => {
  const RU = {
    'there is no pairing code now: ask for a new one on the network screen of the workshop': 'Кода сейчас нет: попросите новый на экране «Сеть» мастерской',
    'the pairing code was entered wrongly too many times and is cancelled: ask for a new one on the network screen of the workshop':
      'Код введён неверно слишком много раз и отменён: попросите новый на экране «Сеть» мастерской',
    'the pairing code is wrong: check the six digits on the network screen of the workshop': 'Код неверный: сверьте шесть цифр на экране «Сеть» мастерской',
    'the name of the device is one to 64 characters': 'Имя планшета — от 1 до 64 знаков'};
  const form = document.querySelector('form'), note = document.getElementById('note'), button = form.querySelector('button');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    note.textContent = '';
    button.disabled = true;
    try {
      const body = {code: form.code.value.trim(), name: form.name.value.trim() || 'Планшет'};
      const answer = await fetch('/api/lan/pair', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      let data = null;
      try { data = await answer.json(); } catch (_) { data = null; }
      if (!answer.ok) { const raw = data && data.error ? data.error : 'Ошибка ' + answer.status; note.textContent = RU[raw] || raw; return; }
      location.href = '/';
    } catch (_) {
      note.textContent = 'Нет связи с мастерской';
    } finally {
      button.disabled = false;
    }
  });
})();
</script>
</body>
</html>
"""


@pages.get("/pair", response_class=HTMLResponse, include_in_schema=False)
def pair_page(request: Request):
    """The page a tablet opens to enter the pairing code; it carries the CA fingerprint to compare with the browser's warning."""
    certs = lan_of(request).ensure_certificates()
    name = lan.settings(store_of(request))["name"]
    return HTMLResponse(PAIR_PAGE.replace("__NAME__", html.escape(name)).replace("__FINGERPRINT__", html.escape(certs.fingerprint)),
                        headers={"Cache-Control": "no-store"})
