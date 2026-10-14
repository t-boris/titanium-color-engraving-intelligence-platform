"""Titanium Color Engraving Intelligence Platform."""
from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("titanium-color-engraving-platform")
except _metadata.PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0.0.0+source"
