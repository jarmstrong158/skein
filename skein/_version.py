"""Single source of truth for the Skein version.

Read at runtime from the installed package metadata so we don't drift between
pyproject.toml and __init__.py.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("skein")
except PackageNotFoundError:
    # Editable install before metadata exists, or running from source tree
    __version__ = "0.0.0+local"
