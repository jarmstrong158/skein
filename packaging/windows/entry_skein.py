"""PyInstaller entry point: `skein.exe` -> `skein.cli:main`."""

import sys

from skein.cli import main

if __name__ == "__main__":
    sys.exit(main())
