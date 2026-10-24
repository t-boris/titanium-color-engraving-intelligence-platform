"""``python -m titanium_platform``: the command line entry point (the desktop shell starts the core this way in development)."""
from .cli import main

raise SystemExit(main())
