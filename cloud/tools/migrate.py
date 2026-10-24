"""Apply cloud/migrations/*.sql in name order to the database of DATABASE_URL (the owner role), once each, recorded in
``schema_migration``. Each file runs in one transaction.

    set -a; source ~/.titanium-cloud.env; set +a
    python cloud/tools/migrate.py            # applies what is missing
    python cloud/tools/migrate.py --status   # lists applied and pending
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

FOLDER = Path(__file__).resolve().parents[1] / "migrations"


def load_env(path: Path | None) -> None:
    """KEY=VALUE lines of an environment file outside the repository into os.environ (values are never printed). A value may be quoted
    as a shell would quote it (``KEY='value'``), since the same file is sourced by the shell."""
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not line.lstrip().startswith("#"):
                os.environ.setdefault(key.strip(), unquoted(value))


def unquoted(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path.home() / ".titanium-cloud.env", help="an environment file read first")
    parser.add_argument("--url", default=None, help="the owner connection (default: DATABASE_URL)")
    args = parser.parse_args()
    load_env(args.env_file)
    args.url = args.url or os.environ.get("DATABASE_URL")
    if not args.url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    files = sorted(p for p in FOLDER.glob("*.sql"))
    with psycopg.connect(args.url, autocommit=False) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migration(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        conn.commit()
        applied = {r[0] for r in conn.execute("SELECT name FROM schema_migration").fetchall()}
        for path in files:
            if path.name in applied:
                print(f"applied  {path.name}")
                continue
            if args.status:
                print(f"pending  {path.name}")
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migration(name) VALUES (%s)", (path.name,))
            print(f"applied  {path.name} (now)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
