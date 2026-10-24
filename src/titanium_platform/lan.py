"""Access from a tablet on the local network (feature electron, REQ-082, DEC-047): the workshop's own certificate authority, the second
server that speaks TLS on the LAN address, the pairing of a tablet with a six-digit code, and the devices that were paired.

The loopback server of the application (``cli.serve``) is never touched by any of this. When the operator switches the local network on,
a second uvicorn server starts in a thread of the same process on ``0.0.0.0:<port>`` (8766 by default) with the workshop's server
certificate, and serves the same FastAPI application through :class:`Entry`, which marks every request as one from the network
(``scope[MARK]``). ``api.security`` then asks for the device cookie instead of the desktop session: a request without a known device
is refused (a page request is sent to ``/pair``), the desktop session is never opened from the network, and what belongs to the
workshop's own computer (the network settings, the backups) is refused even to a paired device.

Certificates: a CA of this workshop (``lan/ca.pem``, its key ``lan/ca.key`` with mode 0600) is made once and lives ten years; the
tablet installs it once as a profile, or compares its SHA-256 fingerprint when the browser warns. A server certificate for the
computer's current names and addresses (``lan/server.pem``) is made from it and remade whenever the addresses change or it nears
its end; it keeps within what tablets accept (at most 825 days, subject alternative names, server authentication).

Pairing: the operator asks for a code on the network screen; the tablet opens ``https://<address>:<port>/pair`` and enters it. The code
lives five minutes, is spent by one use and cancelled after five wrong attempts. The tablet then holds a random token in a Secure
HttpOnly cookie; the workshop keeps only the token's SHA-256, so a copy of the database pairs nothing. Revoking a device ends its
access on its next request. The tablet never receives the desktop session secret.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from . import setup as su
from .db import Store, now

SETTING = "lan"                               # setting: {"enabled": bool, "port": int, "name": str}
DEFAULT_PORT = 8766
FOLDER = "lan"                                # under the data folder: the CA, the server certificate and their keys
MARK = "tce.lan"                              # the ASGI scope key Entry sets on a request from the network
COOKIE = "tce_device"
COOKIE_MAX_AGE_S = 365 * 24 * 3600
BIND_ENV = "TCE_LAN_BIND"                     # the address the LAN server binds (all interfaces unless set; the tests set loopback)
CODE_TTL_S = 300
CODE_ATTEMPTS = 5
CA_DAYS = 3650
CERT_DAYS = 820                               # tablets refuse a server certificate that lives longer than 825 days
RENEW_BEFORE_DAYS = 30
NAME_LIMIT = 64
SEEN_EVERY_S = 60                             # how often a device's last_seen_at is written
START_TIMEOUT_S = 15.0


# -- settings --------------------------------------------------------------------------------------------------------------------
def default_name() -> str:
    return socket.gethostname().split(".")[0] or "workshop"


def settings(store: Store) -> dict:
    kept = store.get_setting(SETTING) or {}
    return {"enabled": bool(kept.get("enabled", False)), "port": int(kept.get("port") or DEFAULT_PORT), "name": kept.get("name") or default_name()}


def save_settings(store: Store, body: dict) -> dict:
    """Keep what the operator chose: whether the local network is on, the port and the name shown to tablets."""
    body = body if isinstance(body, dict) else {}
    cur = settings(store)
    if "enabled" in body:
        cur["enabled"] = bool(body["enabled"])
    if "port" in body:
        port = body["port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise su.ValidationError("the port of the local network server must be a number between 1024 and 65535")
        cur["port"] = port
    if "name" in body:
        name = body["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > NAME_LIMIT:
            raise su.ValidationError("the name of this workshop on the network is one to 64 characters")
        cur["name"] = name.strip()
    store.set_setting(SETTING, cur)
    return cur


# -- this computer on the network ------------------------------------------------------------------------------------------------
def addresses() -> list[str]:
    """The IPv4 addresses of this computer on its networks (loopback and link-local left out)."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))          # no packet is sent: the routing table names the outgoing address
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith(("127.", "169.254.")))


def names() -> list[str]:
    """The names this computer answers to on the network: its host name, with ``.local`` and as the system reports it."""
    host = socket.gethostname().lower().strip(".")
    short = host.split(".")[0]
    return [n for n in dict.fromkeys([short, f"{short}.local", host]) if n]


# -- certificates ----------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Certificates:
    ca_path: Path
    cert_path: Path
    key_path: Path
    fingerprint: str                  # SHA-256 of the CA certificate, hex pairs with colons
    hosts: tuple[str, ...]
    not_after: str

    def ca_pem(self) -> bytes:
        return self.ca_path.read_bytes()


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _key_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _make_ca(folder: Path, name: str) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Titanium workshop CA ({name})"[:64]),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Titanium colour engraving platform")])
    begins = datetime.now(timezone.utc) - timedelta(days=1)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(begins).not_valid_after(begins + timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_private(folder / "ca.key", _key_pem(key))
    (folder / "ca.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _make_server(folder: Path, ca, ca_key, hosts: tuple[str, ...]) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    alternatives = []
    for host in hosts:
        try:
            alternatives.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            alternatives.append(x509.DNSName(host))
    begins = datetime.now(timezone.utc) - timedelta(days=1)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[-1][:64])]))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(begins).not_valid_after(begins + timedelta(days=CERT_DAYS))
            .add_extension(x509.SubjectAlternativeName(alternatives), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, key_cert_sign=False, crl_sign=False, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_private(folder / "server.key", _key_pem(key))
    (folder / "server.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "server.json").write_text(json.dumps({"hosts": list(hosts), "not_after": cert.not_valid_after_utc.isoformat(timespec="seconds")}),
                                        encoding="utf-8")


def certificates(data_dir: Path, hosts, name: str = "workshop") -> Certificates:
    """The workshop's CA (made once) and a server certificate for ``hosts`` (names and addresses; localhost and 127.0.0.1 are always among
    them), remade when the hosts changed or the certificate ends within a month."""
    folder = Path(data_dir) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    if not ((folder / "ca.key").is_file() and (folder / "ca.pem").is_file()):
        _make_ca(folder, name)
    ca = x509.load_pem_x509_certificate((folder / "ca.pem").read_bytes())
    ca_key = serialization.load_pem_private_key((folder / "ca.key").read_bytes(), password=None)
    wanted = ("localhost", "127.0.0.1") + tuple(sorted({str(h).strip().lower() for h in hosts if str(h).strip()} - {"localhost", "127.0.0.1"}))
    try:
        meta = json.loads((folder / "server.json").read_text(encoding="utf-8"))
        ends = datetime.fromisoformat(meta["not_after"])
        fresh = (tuple(meta["hosts"]) == wanted and (folder / "server.pem").is_file() and (folder / "server.key").is_file()
                 and ends - datetime.now(timezone.utc) > timedelta(days=RENEW_BEFORE_DAYS))
    except (OSError, ValueError, KeyError, TypeError):
        fresh = False
    if not fresh:
        _make_server(folder, ca, ca_key, wanted)
        meta = json.loads((folder / "server.json").read_text(encoding="utf-8"))
    fingerprint = ":".join(f"{b:02X}" for b in ca.fingerprint(hashes.SHA256()))
    return Certificates(folder / "ca.pem", folder / "server.pem", folder / "server.key", fingerprint, wanted, meta["not_after"])


# -- pairing codes ---------------------------------------------------------------------------------------------------------------
class PairingCodes:
    """One pairing code at a time: six digits, alive ``ttl_s`` seconds, spent by one use, cancelled after ``attempts`` wrong tries."""

    def __init__(self, ttl_s: float = CODE_TTL_S, attempts: int = CODE_ATTEMPTS, clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.attempts, self.clock = ttl_s, attempts, clock
        self.code: str | None = None
        self.expires = 0.0
        self.tried = 0
        self.lock = threading.Lock()

    def new(self) -> dict:
        with self.lock:
            self.code = f"{secrets.randbelow(10 ** 6):06d}"
            self.expires = self.clock() + self.ttl_s
            self.tried = 0
            return self._current()

    def current(self) -> dict | None:
        with self.lock:
            return self._current()

    def _current(self) -> dict | None:
        if self.code is None or self.clock() >= self.expires:
            self.code = None
            return None
        return {"code": self.code, "expires_in_s": int(self.expires - self.clock())}

    def redeem(self, given) -> None:
        """Spend the code when ``given`` is it; otherwise count the attempt and say why it was refused."""
        with self.lock:
            if self._current() is None:
                raise su.ValidationError("there is no pairing code now: ask for a new one on the network screen of the workshop")
            if not hmac.compare_digest(str(given or "").strip(), self.code):
                self.tried += 1
                if self.tried >= self.attempts:
                    self.code = None
                    raise su.ValidationError("the pairing code was entered wrongly too many times and is cancelled: ask for a new one on the network "
                                             "screen of the workshop")
                raise su.ValidationError("the pairing code is wrong: check the six digits on the network screen of the workshop")
            self.code = None


# -- devices ---------------------------------------------------------------------------------------------------------------------
_seen_at: dict[tuple[str, int], float] = {}        # (workshop, device) -> when last_seen_at was last written
DEVICE_COLUMNS = "id, name, created_at, last_seen_at, revoked_at"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clean_name(name) -> str:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > NAME_LIMIT:
        raise su.ValidationError("the name of the device is one to 64 characters")
    return name.strip()


def device(store: Store, device_id: int) -> dict:
    row = store.one(f"SELECT {DEVICE_COLUMNS} FROM device WHERE id=?", (device_id,))
    if row is None:
        raise KeyError(f"there is no device {device_id}")
    return dict(row)


def devices(store: Store) -> list[dict]:
    """Every device that was paired, the active ones first, the newest first."""
    return [dict(r) for r in store.query(f"SELECT {DEVICE_COLUMNS} FROM device ORDER BY revoked_at IS NOT NULL, id DESC")]


def pair(store: Store, name) -> tuple[dict, str]:
    """A new device: its record and the token the tablet keeps (never stored: only its hash is)."""
    name = clean_name(name)
    token = secrets.token_urlsafe(32)
    with store.transaction():
        device_id = store.execute("INSERT INTO device(name, token_hash, created_at) VALUES (?,?,?)", (name, _hash(token), now())).lastrowid
    store.audit("lan_device_paired", device_id=device_id, name=name)
    return device(store, device_id), token


def authenticate(store: Store, token: str | None) -> dict | None:
    """The device that holds ``token``, or None when none does or it was revoked; its last visit is noted now and then."""
    if not token:
        return None
    row = store.one(f"SELECT {DEVICE_COLUMNS} FROM device WHERE token_hash=?", (_hash(token),))
    if row is None or row["revoked_at"]:
        return None
    moment, key = time.monotonic(), (str(store.data_dir), row["id"])
    if moment - _seen_at.get(key, -1e9) >= SEEN_EVERY_S:
        _seen_at[key] = moment
        store.execute("UPDATE device SET last_seen_at=? WHERE id=?", (now(), row["id"]))
    return dict(row)


def revoke(store: Store, device_id: int) -> dict:
    """End a device's access: its next request is refused. The record stays, marked, so the list shows what was paired once."""
    found = device(store, device_id)
    if not found["revoked_at"]:
        store.execute("UPDATE device SET revoked_at=? WHERE id=?", (now(), device_id))
        store.audit("lan_device_revoked", device_id=device_id)
    return device(store, device_id)


def rename(store: Store, device_id: int, name) -> dict:
    device(store, device_id)
    store.execute("UPDATE device SET name=? WHERE id=?", (clean_name(name), device_id))
    return device(store, device_id)


# -- the LAN server --------------------------------------------------------------------------------------------------------------
class Entry:
    """The ASGI entry of the LAN server: the same application, every request marked as one from the network; the application's
    lifespan belongs to the loopback server and is answered here without running it again."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        scope[MARK] = True
        await self.app(scope, receive, send)


class Lan:
    """The local network of one application: its settings, certificates, pairing codes and the TLS server, started and stopped at will."""

    def __init__(self, app, store: Store):
        self.app, self.store = app, store
        self.codes = PairingCodes()
        self.certs: Certificates | None = None
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.sock: socket.socket | None = None
        self.port: int | None = None
        self.error: str | None = None
        self.lock = threading.RLock()
        guard = app.state.guard
        guard.lan_hosts.update(names())
        guard.device_check = lambda token: authenticate(store, token) is not None

    # -- state ----------------------------------------------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.server is not None and self.thread is not None and self.thread.is_alive() and not self.server.should_exit

    def ensure_certificates(self) -> Certificates:
        chosen = settings(self.store)
        self.certs = certificates(self.store.data_dir, [*names(), *addresses()], chosen["name"])
        self.app.state.guard.lan_hosts.update(h for h in self.certs.hosts)
        return self.certs

    def status(self, *, owner: bool) -> dict:
        """What the screen shows; the pairing code only to the workshop's own computer (``owner``), never to a device on the network."""
        chosen = settings(self.store)
        certs = self.certs or self.ensure_certificates()
        found = addresses()
        port = self.port if self.running and self.port else chosen["port"]
        out = {**chosen, "running": self.running, "bound_port": self.port if self.running else None, "addresses": found, "hosts": names(),
               "urls": [f"https://{address}:{port}" for address in found], "fingerprint": certs.fingerprint, "certificate_until": certs.not_after,
               "error": self.error, "devices": devices(self.store)}
        if owner:
            out["code"] = self.codes.current()
        return out

    # -- the server -----------------------------------------------------------------------------------------------------------
    def start_if_enabled(self) -> None:
        if settings(self.store)["enabled"]:
            self.start()

    def start(self) -> bool:
        """Bind the LAN port and serve with the workshop's certificate; False (and ``error`` set) when the port cannot be opened."""
        with self.lock:
            if self.running:
                return True
            self.error = None
            chosen = settings(self.store)
            certs = self.ensure_certificates()
            host = os.environ.get(BIND_ENV, "0.0.0.0")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, chosen["port"]))
                sock.listen(64)
            except OSError as exc:
                sock.close()
                self.error = f"port {chosen['port']} could not be opened: {exc.strerror or exc}"
                return False
            self.port = sock.getsockname()[1]
            config = uvicorn.Config(Entry(self.app), host=host, port=self.port, log_level="warning", lifespan="off",
                                    ssl_certfile=str(certs.cert_path), ssl_keyfile=str(certs.key_path))
            server = uvicorn.Server(config)
            failure: dict = {}

            def run() -> None:
                try:
                    server.run(sockets=[sock])
                except BaseException as exc:                    # reported to the operator as the reason the network is off
                    failure["error"] = f"{type(exc).__name__}: {exc}"
            thread = threading.Thread(target=run, name="lan-server", daemon=True)
            thread.start()
            deadline = time.monotonic() + START_TIMEOUT_S
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            if not server.started:
                self.error = failure.get("error") or "the local network server did not start in time"
                server.should_exit = True
                sock.close()
                self.port = None
                return False
            self.server, self.thread, self.sock = server, thread, sock
            self.store.audit("lan_started", port=self.port, addresses=addresses())
            return True

    def stop(self) -> None:
        """Stop the LAN server only; the loopback server and the application go on."""
        with self.lock:
            server, thread, sock = self.server, self.thread, self.sock
            self.server = self.thread = self.sock = None
            self.port = None
        if server is None:
            return
        server.should_exit = True
        if thread is not None:
            thread.join(10.0)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self.store.audit("lan_stopped")

    def apply(self, body: dict) -> dict:
        """Keep the operator's settings and make the server match them: on, off, or restarted on another port."""
        before = settings(self.store)
        chosen = save_settings(self.store, body)
        if not chosen["enabled"]:
            self.stop()
        elif not self.running or chosen["port"] != before["port"]:
            self.stop()
            self.start()
        return chosen
