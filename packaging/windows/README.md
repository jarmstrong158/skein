# Skein Windows packaging

Two-step build: PyInstaller produces the bundled `dist/skein/` directory, NSIS wraps it in a single `Skein-X.Y.Z-Setup.exe` installer.

## Prerequisites
- Python 3.10+ with the dev install: `pip install -e ".[dev]" && pip install pyinstaller`
- [NSIS 3.x](https://nsis.sourceforge.io/) on `PATH` (for the installer step)

## Build

```powershell
# From repo root
pyinstaller packaging/windows/skein.spec --clean --noconfirm
# -> dist/skein/skein.exe, dist/skein/skein-mcp.exe, + dependencies

makensis packaging/windows/skein.nsi
# -> dist/Skein-0.1.0-Setup.exe
```

## What ships in the bundle
- `skein.exe` — `skein serve` / `skein demo` (same CLI as the pip install)
- `skein-mcp.exe` — stdio MCP server for Claude Desktop / Claude Code
- `config.example.json` — default configuration

## Installer behavior
- Installs to `%PROGRAMFILES%\Skein` (admin required).
- Creates Start Menu shortcuts for `skein serve` and the dashboard URL.
- Registers an Add/Remove Programs entry.
- Uninstaller removes install dir and shortcuts. (User databases in `%USERPROFILE%\...` are left alone.)
