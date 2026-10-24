"""The cloud of laboratories over the local API (feature electron, REQ-086, REQ-087, DEC-058): the sign-in owned by the core
(:mod:`cloud_session`), the catalogue, connecting a release from the cloud, publishing, withdrawals, invitations, members and the check
for updates (:mod:`cloud_client`). Everything under ``/api/cloud`` is the workshop's own computer's (refused to a tablet on the LAN);
``GET /api/cloud/callback`` is the one address the browser reaches without the desktop session cookie, while its sign-in is pending
(the sign-in itself is Neon Auth's OAuth provider, DEC-060)."""
from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import cloud_client, cloud_session
from .. import setup as su
from ..cloud_http import CloudError
from .common import store_of

router = APIRouter(prefix="/api/cloud")

# The page the browser shows after the sign-in page sent it back: Russian, no script, nothing of the workshop in it.
PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>body{{margin:0;background:#f3f5f7;color:#1b1f23;font:16px/1.45 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}}
main{{max-width:420px;margin:12vh auto;padding:24px;background:#fff;border:1px solid #d5dbe1;border-radius:12px}}h1{{font-size:1.3rem;margin:0 0 8px}}
p{{margin:8px 0}}.muted{{color:#5f6b76;font-size:.92rem}}@media (prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}
main{{background:#161b22;border-color:#3a434d}}.muted{{color:#9aa7b4}}}}</style></head><body><main><h1>{title}</h1><p>{text}</p>{detail}</main></body></html>"""
REASONS = {"unknown_state": "Приложение не ждало этот вход: начните вход заново с экрана «Лаборатории».",
           "denied": "Вход отменён: вы не разрешили приложению доступ к облаку. Если передумаете, нажмите «Войти» ещё раз.",
           "provider_error": "Служба входа ответила ошибкой: начните вход заново с экрана «Лаборатории».",
           "bad_code": "Код входа не принят службой входа (он уже использован или принадлежит другому запуску): начните вход заново.",
           "no_session": "Служба входа не назвала аккаунт: начните вход заново.",
           "unreachable": "Служба входа или облако сейчас недоступны: проверьте подключение к интернету и попробуйте снова.",
           "switched_off": "Облако выключено в настройках сети этой мастерской."}


def _port(request: Request) -> int:
    """The port the browser reaches this core on: of the request's Host, else of the socket the server listens on."""
    if request.url.port:
        return int(request.url.port)
    server = request.scope.get("server") or (None, None)
    return int(server[1] or 80)


def _page(title: str, text: str, detail: str | None = None, status: int = 200) -> HTMLResponse:
    shown = f'<p class="muted">{html.escape(detail)}</p>' if detail else ""
    return HTMLResponse(PAGE.format(title=html.escape(title), text=html.escape(text), detail=shown), status_code=status,
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})


# -- the sign-in ----------------------------------------------------------------------------------------------------------------------
@router.get("/account")
def account(request: Request):
    """Who is signed in to the cloud from this workshop, if anyone, and where the cloud is."""
    return {**cloud_session.account(store_of(request)), "switched_on": cloud_session.switched_on()}


@router.post("/signin", status_code=201)
def signin(request: Request):
    """Start a sign-in: the address of the cloud's page for the operator's browser; the screen opens it in a new window."""
    return cloud_session.start(store_of(request), _port(request))


@router.get("/callback")
def callback(request: Request, state: str = "", code: str = "", error: str = "", error_description: str = ""):
    """Where the cloud's ``/auth/return`` sends the browser back from the sign-in service: the code is exchanged (or the refusal
    shown) and the browser sees a small page; the application learns of the sign-in by asking ``/account``."""
    try:
        cloud_session.complete(store_of(request), state, code, error or None, error_description or None)
    except CloudError as exc:
        reason = REASONS.get(exc.code, "Вход не выполнен. Вернитесь в приложение и попробуйте снова.")
        return _page("Вход не выполнен", reason, str(exc), status=422)
    return _page("Вход выполнен", "Вход выполнен, вернитесь в приложение. Эту страницу можно закрыть.")


@router.post("/signout")
def signout(request: Request):
    return cloud_session.sign_out(store_of(request))


@router.post("/signin/cancel")
def cancel_signin(request: Request, body: dict | None = None):
    return cloud_session.cancel(store_of(request), (body or {}).get("state"))


# -- where the cloud is ------------------------------------------------------------------------------------------------------------------
@router.get("/settings")
def settings(request: Request):
    return cloud_session.settings(store_of(request))


@router.put("/settings")
def change_settings(request: Request, body: dict):
    return cloud_session.set_api_url(store_of(request), (body or {}).get("api_url", ""))


# -- the catalogue and connecting ---------------------------------------------------------------------------------------------------------
@router.get("/catalogue")
def catalogue(request: Request):
    return cloud_client.catalogue(store_of(request))


@router.get("/labs/{lab_id}")
def lab(request: Request, lab_id: str):
    return cloud_client.lab(store_of(request), lab_id)


@router.post("/releases/{release_id}/connect", status_code=202)
def connect(request: Request, release_id: str):
    """Download and connect a release of the cloud in the background; the job to follow, as a file connection's."""
    return cloud_client.connect(store_of(request), release_id)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    return cloud_client.status(job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return cloud_client.cancel(job_id)


# -- the own laboratory in the cloud --------------------------------------------------------------------------------------------------------
@router.get("/own")
def own(request: Request):
    """The «Облако» block of «Моя лаборатория»: the account, the own cloud laboratory, its releases, publications, invitations and members."""
    return cloud_client.own(store_of(request))


@router.post("/publish", status_code=202)
def publish(request: Request, body: dict):
    """Publish a release of the own laboratory to the cloud under ``terms`` with the given visibility (chosen when the laboratory is first
    made in the cloud); the job to follow."""
    body = body or {}
    return cloud_client.publish(store_of(request), terms=body.get("terms"), visibility=body.get("visibility") or "public",
                                description=body.get("description"), selection=body.get("selection"))


@router.post("/publish/retry", status_code=202)
def retry(request: Request):
    return cloud_client.retry(store_of(request))


@router.post("/publish/abandon")
def abandon(request: Request):
    given_up = cloud_client.abandon(store_of(request))
    if given_up is None:
        raise su.ValidationError("there is no pending publication to give up")
    return given_up


@router.post("/withdrawals", status_code=201)
def withdraw(request: Request, body: dict):
    body = body or {}
    return cloud_client.withdraw(store_of(request), body.get("target_kind"), body.get("target_id"), body.get("reason"),
                                 body.get("replacement_release_id"))


@router.post("/invitations", status_code=201)
def invite(request: Request, body: dict | None = None):
    expires = (body or {}).get("expires_in_s")
    if expires is not None and (not isinstance(expires, int) or isinstance(expires, bool) or expires < 60):
        raise su.ValidationError("the lifetime of an invitation is a number of seconds, at least 60")
    return cloud_client.invite(store_of(request), expires)


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke(request: Request, invitation_id: str):
    cloud_client.revoke(store_of(request), invitation_id)


@router.delete("/members/{account_id}", status_code=204)
def remove_member(request: Request, account_id: str):
    cloud_client.remove_member(store_of(request), account_id)


@router.post("/invitations/accept")
def accept(request: Request, body: dict):
    return cloud_client.accept(store_of(request), (body or {}).get("link") or "")


# -- updates of the laboratories connected from the cloud -----------------------------------------------------------------------------------
@router.post("/updates/check")
def check_updates(request: Request, body: dict | None = None):
    source = (body or {}).get("source_id")
    if source is not None and (not isinstance(source, int) or isinstance(source, bool)):
        raise su.ValidationError("the laboratory to check is named by its number")
    return cloud_client.check_updates(store_of(request), source)


@router.post("/updates/automatic")
def automatic(request: Request):
    """The checks due now, when the laboratory and the network setting allow automatic checks; the screen calls it when it opens."""
    return cloud_client.automatic_checks(store_of(request))


@router.put("/sources/{source_id}")
def source_settings(request: Request, source_id: int, body: dict):
    return cloud_client.set_update_checks(store_of(request), source_id, (body or {}).get("update_checks"))
