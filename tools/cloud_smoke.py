"""Smoke test of the cloud API of laboratories (DEC-058) against a running service: an author publishes a small release, a reader
downloads and connects it with the desktop importer, their palettes agree, and a withdrawal reaches the reader.

    .venv/bin/python tools/cloud_smoke.py                      # starts the API locally (in-memory catalogue, an ephemeral key)
    CLOUD_BASE_URL=https://… CLOUD_TOKEN=… .venv/bin/python tools/cloud_smoke.py     # against a deployment, with a real token

What it does, in order: builds a workshop in a temporary folder (``tests/labworld.bulk``), creates a public laboratory, reserves a
publication, exports the release with the reserved identity, uploads it in chunks and finalizes; downloads the chunks with plain
``urllib`` (certifi for TLS) and no token, connects them into a second temporary workshop with ``lab_import.stage``/``start``, compares
the colours ``evidence_source.release_palette`` finds with the author's own ``palette.vector_palette``; withdraws one measurement and
reads it back from ``/withdrawals``. It writes ``docs/features/electron/cloud-smoke-<date>.md`` and exits 0 only when every step passed.
Local mode runs ``uvicorn cloud.index:app`` on a free port (never 8765) with ``CLOUD_REPOSITORY=memory``."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / "src", ROOT / "tests", ROOT / "cloud"):
    sys.path.insert(0, str(folder))

import labworld  # noqa: E402
from titanium_platform import evidence_source, lab_export, lab_format as lf, lab_import, palette  # noqa: E402
from titanium_platform.db import Store  # noqa: E402

SSL = ssl.create_default_context(cafile=certifi.where())
TERMS = "CC-BY-4.0"


# -- HTTP without a client library -------------------------------------------------------------------------------------------------
class Api:
    def __init__(self, base: str, token: str | None):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, body=None, *, raw: bytes | None = None, token: bool = True) -> tuple[int, object, dict]:
        headers = {"Accept": "application/json"}
        if token and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif raw is not None:
            headers["Content-Type"] = "application/octet-stream"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, context=SSL, timeout=120) as response:
                return response.status, _decode(response.read(), response.headers), dict(response.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, _decode(exc.read(), exc.headers), dict(exc.headers)


def _decode(payload: bytes, headers) -> object:
    if "json" in (headers.get("Content-Type") or ""):
        return json.loads(payload or b"null")
    return payload


# -- the steps ---------------------------------------------------------------------------------------------------------------------
class Steps:
    def __init__(self):
        self.rows: list[dict] = []

    def run(self, name: str, fn):
        started = time.perf_counter()
        try:
            detail = fn()
            self.rows.append({"step": name, "ok": True, "detail": str(detail or ""), "ms": round((time.perf_counter() - started) * 1000)})
            print(f"  ok   {name}: {detail or ''}")
            return detail
        except Exception as exc:  # noqa: BLE001  (the report shows the failure)
            self.rows.append({"step": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}", "ms": round((time.perf_counter() - started) * 1000)})
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
            raise

    @property
    def passed(self) -> bool:
        return all(r["ok"] for r in self.rows)


def expect(status: int, wanted: int, body) -> None:
    if status != wanted:
        raise RuntimeError(f"HTTP {status} instead of {wanted}: {body if isinstance(body, dict) else body[:200]}")


def smoke(api: Api, work: Path, steps: Steps, measurements: int) -> dict:
    out: dict = {}
    author = Store(work / "author")
    reader = Store(work / "reader")
    try:
        def build():
            ids = labworld.bulk(author, work / "author" / "files", measurements)
            lab_export.set_public_info(author, {"name": "Smoke laboratory", "author": "Smoke author", "url": "https://example.org/smoke"})
            out["ids"] = ids
            out["origin"] = lab_export.identity(author)["origin_lab_id"]
            return f"{measurements} measurements, origin {out['origin'][:8]}…"
        steps.run("build a workshop", build)

        def health():
            status, body, _ = api.call("GET", "/health", token=False)
            expect(status, 200, body)
            return body.get("version")
        steps.run("GET /health", health)

        def create():
            status, body, _ = api.call("POST", "/labs", {"name": "Smoke laboratory", "author": "Smoke author", "origin_lab_id": out["origin"],
                                                         "visibility": "public", "url": "https://example.org/smoke"})
            expect(status, 201, body)
            out["lab"] = body
            return body["id"]
        steps.run("POST /labs", create)

        def reserve():
            status, body, _ = api.call("POST", f"/labs/{out['lab']['id']}/publications", {"idempotency_key": str(uuid.uuid4())})
            expect(status, 201, body)
            out["publication"] = body
            return f"release {body['release_id'][:8]}… number {body['release_number']}, chunks of {body['chunk_bytes']} bytes"
        steps.run("POST /labs/{id}/publications", reserve)

        def export():
            pub = out["publication"]
            path = work / "release.tcelab"
            lab_export.export(author, path, None, TERMS, release_id=pub["release_id"], release_number=pub["release_number"])
            out["data"] = path.read_bytes()
            return f"{len(out['data'])} bytes"
        steps.run("export the release with the reserved identity", export)

        def upload():
            pub, data, size = out["publication"], out["data"], out["publication"]["chunk_bytes"]
            pieces = [data[i:i + size] for i in range(0, len(data), size)] or [b""]
            for n, piece in enumerate(pieces):
                status, body, _ = api.call("PUT", f"/publications/{pub['id']}/chunks/{n}", raw=piece)
                expect(status, 200, body)
            out["declared"] = {"file_sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data), "chunk_count": len(pieces)}
            return f"{len(pieces)} chunks"
        steps.run("PUT /publications/{id}/chunks/{n}", upload)

        def finalize():
            status, body, _ = api.call("POST", f"/publications/{out['publication']['id']}/finalize", out["declared"])
            expect(status, 200, body)
            out["release"] = body["release"]
            return f"release {body['release']['id'][:8]}… number {body['release']['number']}, {body['release']['counts']['measurements']} measurements"
        steps.run("POST /publications/{id}/finalize", finalize)

        def catalogue():
            status, body, _ = api.call("GET", f"/labs/{out['lab']['id']}", token=False)
            expect(status, 200, body)
            if body["latest_release"]["id"] != out["release"]["id"]:
                raise RuntimeError("the laboratory does not show the new release as its latest")
            status, body, _ = api.call("GET", f"/releases/{out['release']['id']}/manifest", token=False)
            expect(status, 200, body)
            if body["manifest"]["content_sha256"] != out["release"]["content_sha256"]:
                raise RuntimeError("the manifest's content hash differs from the catalogue's")
            return "latest release and manifest agree"
        steps.run("GET /labs/{id} and /releases/{id}/manifest without a token", catalogue)

        def download():
            release, chunks = out["release"], []
            for n in range(release["chunk_count"]):
                status, body, headers = api.call("GET", f"/releases/{release['id']}/chunks/{n}", token=False)
                expect(status, 200, body)
                chunks.append(body)
            whole = b"".join(chunks)
            if hashlib.sha256(whole).hexdigest() != release["file_sha256"] or whole != out["data"]:
                raise RuntimeError("the downloaded bytes differ from the uploaded file")
            out["chunks"] = chunks
            return f"{len(chunks)} chunks, {len(whole)} bytes, hash agrees"
        steps.run("GET /releases/{id}/chunks/{n} with urllib", download)

        def connect():
            token = lab_import.stage(reader, out["chunks"])
            job = lab_import.start(reader, token, origin="cloud", url=f"{api.base}/releases/{out['release']['id']}", verified=True, wait=True)
            if not job["done"] or job["error"]:
                raise RuntimeError(f"the import did not finish: {job}")
            return f"connected as source «{lab_import.sources(reader)[0]['name']}»"
        steps.run("lab_import.stage/start into a second workshop", connect)

        def palettes():
            ids = out["ids"]
            mine = palette.vector_palette(author, ids["laser"], ids["lens"], ids["material"])["entries"]
            snapshot = lab_import.reader(reader, out["release"]["id"], [])
            records = {r["kind"]: r["uuid"] for r in snapshot.query("SELECT kind, uuid FROM release_record WHERE kind IN ('laser','lens','material')")}
            theirs = evidence_source.release_palette(reader, {"release_id": out["release"]["id"], "laser": records["laser"],
                                                              "lens": records.get("lens"), "material": records["material"]})["entries"]
            a = sorted(tuple(round(v, 3) for v in e["lab"]) for e in mine)
            b = sorted(tuple(round(v, 3) for v in e["lab"]) for e in theirs)
            if not a or a != b:
                raise RuntimeError(f"the palettes differ: author {len(a)} colours, reader {len(b)}")
            return f"{len(a)} colours agree"
        steps.run("release_palette equals the author's vector_palette", palettes)

        def withdraw():
            import io
            measurement = next(record["id"] for kind, record in lf.read(io.BytesIO(out["data"])) if kind == "measurements")
            body = {"targets": [{"kind": "measurement", "id": measurement}], "reason": "smoke test: withdrawn on purpose", "idempotency_key": str(uuid.uuid4())}
            status, answer, _ = api.call("POST", f"/releases/{out['release']['id']}/withdraw", body)
            expect(status, 201, answer)
            status, seen, _ = api.call("GET", f"/releases/{out['release']['id']}/withdrawals", token=False)
            expect(status, 200, seen)
            if not any(w["target_id"] == measurement for w in seen["withdrawals"]):
                raise RuntimeError("the withdrawal is not listed")
            return f"measurement {measurement[:8]}… withdrawn and listed"
        steps.run("POST /releases/{id}/withdraw and GET /withdrawals", withdraw)
    finally:
        author.close()
        reader.close()
    return out


# -- a local service ---------------------------------------------------------------------------------------------------------------
def free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port != 8765:
            return port


def local_service(env_extra: dict) -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = {**os.environ, "CLOUD_REPOSITORY": "memory", "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")]), **env_extra}
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "cloud.index:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                               cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(base + "/health", timeout=2) as response:
                if response.status == 200:
                    return process, base
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    process.terminate()
    raise RuntimeError("the local service did not start")


def ephemeral_auth() -> tuple[dict, str]:
    """A fresh RSA key as a JWKS for the local service, and a token signed with it."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = {"keys": [{**jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True), "kid": "smoke", "use": "sig", "alg": "RS256"}]}
    token = jwt.encode({"sub": "smoke-author", "iss": "smoke", "iat": int(time.time()), "exp": int(time.time()) + 3600}, key, algorithm="RS256",
                       headers={"kid": "smoke"})
    return jwks, token


# -- the note ----------------------------------------------------------------------------------------------------------------------
def write_note(path: Path, base: str, mode: str, steps: Steps, out: dict) -> None:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Cloud smoke test — {when}", "",
             f"Target: `{base}` ({mode}). Tool: `tools/cloud_smoke.py`. Result: **{'passed' if steps.passed else 'FAILED'}**.", "",
             "| Step | Result | Detail | ms |", "|---|---|---|---:|"]
    for row in steps.rows:
        lines.append(f"| {row['step']} | {'ok' if row['ok'] else 'FAIL'} | {row['detail'].replace('|', '/')} | {row['ms']} |")
    if "release" in out:
        release = out["release"]
        lines += ["", f"Laboratory `{out['lab']['id']}`, release `{release['id']}` number {release['number']}, {release['byte_size']} bytes in "
                      f"{release['chunk_count']} chunks, counts {json.dumps(release['counts'])}."]
    lines += ["", "The author's workshop and the reader's were temporary folders; nothing of this run is kept but this note and the rows on the service."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("CLOUD_BASE_URL"), help="the service (default: CLOUD_BASE_URL; unset = start one locally)")
    parser.add_argument("--token", default=os.environ.get("CLOUD_TOKEN"), help="a bearer token of the author (default: CLOUD_TOKEN)")
    parser.add_argument("--measurements", type=int, default=60)
    parser.add_argument("--note", type=Path, default=None, help="where to write the note (default: docs/features/electron/cloud-smoke-<date>.md)")
    args = parser.parse_args()
    process = None
    if args.base_url:
        if not args.token:
            print("CLOUD_TOKEN is needed against a deployment", file=sys.stderr)
            return 2
        base, token, mode = args.base_url, args.token, "deployment"
    else:
        jwks, token = ephemeral_auth()
        process, base = local_service({"NEON_AUTH_JWKS_JSON": json.dumps(jwks), "NEON_AUTH_ISSUER": "smoke"})
        mode = "local uvicorn, in-memory catalogue"
    print(f"smoke against {base} ({mode})")
    steps, out = Steps(), {}
    work = Path(tempfile.mkdtemp(prefix="cloud-smoke-"))
    try:
        try:
            out = smoke(Api(base, token), work, steps, args.measurements)
        except Exception:  # noqa: BLE001  (recorded in the steps)
            pass
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
    note = args.note or ROOT / "docs" / "features" / "electron" / f"cloud-smoke-{datetime.now(timezone.utc):%Y-%m-%d}.md"
    write_note(note, base, mode, steps, out)
    print(f"{'passed' if steps.passed else 'FAILED'}; note: {note.relative_to(ROOT) if note.is_relative_to(ROOT) else note}")
    return 0 if steps.passed else 1


if __name__ == "__main__":
    sys.exit(main())
