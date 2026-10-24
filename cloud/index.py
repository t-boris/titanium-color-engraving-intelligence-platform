"""The entrypoint Vercel's FastAPI runtime looks for: a FastAPI instance named ``app`` in index.py at the project root (``cloud/``)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from titanium_cloud.app import create_app  # noqa: E402

app = create_app()
