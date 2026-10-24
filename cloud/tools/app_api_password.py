"""Give the service's role ``app_api`` a new random password and write its connection string, derived from the owner's DATABASE_URL,
as APP_API_DATABASE_URL into an environment file outside the repository (the owner's ``~/.titanium-cloud.env`` by default; the same
value goes into the Vercel project as DATABASE_URL). The password is never printed.

    set -a; source ~/.titanium-cloud.env; set +a
    python cloud/tools/app_api_password.py [--env-file ~/.titanium-cloud.env]
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", type=Path, default=Path.home() / ".titanium-cloud.env")
    parser.add_argument("--url", default=None, help="the owner connection (default: DATABASE_URL of the environment or the env file)")
    args = parser.parse_args()
    if args.env_file.is_file():
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not line.lstrip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip())
    args.url = args.url or os.environ.get("DATABASE_URL")
    if not args.url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    password = secrets.token_urlsafe(32)
    with psycopg.connect(args.url, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER ROLE app_api WITH LOGIN PASSWORD {}").format(sql.Literal(password)))
    parts = urlsplit(args.url)
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    derived = urlunsplit((parts.scheme, f"app_api:{quote(password, safe='')}@{host}", parts.path, parts.query, ""))
    lines = [line for line in args.env_file.read_text(encoding="utf-8").splitlines() if not line.startswith("APP_API_DATABASE_URL=")] \
        if args.env_file.is_file() else []
    lines.append(f"APP_API_DATABASE_URL={derived}")
    args.env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args.env_file.chmod(0o600)
    print(f"app_api password set; APP_API_DATABASE_URL written to {args.env_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
