# PyInstaller spec for the Skein Windows bundle.
#
# Produces a single onedir distribution with:
#   - skein.exe       (runs `skein serve` by default)
#   - skein-mcp.exe   (the MCP stdio server)
#
# Build from the repo root with:
#   pyinstaller packaging/windows/skein.spec --clean --noconfirm
# Output: dist/skein/

# ruff: noqa
# pyright: ignore

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Resolve repo root from this spec's location (packaging/windows/skein.spec)
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
REPO_ROOT = os.path.abspath(os.path.join(SPEC_DIR, "..", ".."))

skein_datas = [
    (os.path.join(REPO_ROOT, "skein", "schema.sql"), "skein"),
    (os.path.join(REPO_ROOT, "skein", "dashboard", "templates"), "skein/dashboard/templates"),
    (os.path.join(REPO_ROOT, "skein", "dashboard", "static"), "skein/dashboard/static"),
]

hidden = (
    collect_submodules("flask")
    + collect_submodules("apscheduler")
    + collect_submodules("rich")
    + collect_submodules("skein")
    + collect_submodules("skein_mcp")
)

# ---- skein serve binary --------------------------------------------------
skein_a = Analysis(
    [os.path.join(SPEC_DIR, "entry_skein.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=skein_datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
skein_pyz = PYZ(skein_a.pure, skein_a.zipped_data, cipher=block_cipher)
skein_exe = EXE(
    skein_pyz,
    skein_a.scripts,
    [],
    exclude_binaries=True,
    name="skein",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)

# ---- skein-mcp binary ----------------------------------------------------
mcp_a = Analysis(
    [os.path.join(SPEC_DIR, "entry_skein_mcp.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=skein_datas,
    # Avoid collect_submodules("mcp") because mcp.cli imports the optional
    # `typer` package and fails at analysis time. Pull in just what MCPServer
    # needs. `mcp_types` is its own distribution as of SDK v2 and is not
    # reached by walking `mcp`, so it has to be named explicitly.
    hiddenimports=hidden + [
        "mcp",
        "mcp.server",
        "mcp.server.mcpserver",
        "mcp.server.caching",
        "mcp.server.stdio",
        "mcp.types",
        "mcp_types",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
mcp_pyz = PYZ(mcp_a.pure, mcp_a.zipped_data, cipher=block_cipher)
mcp_exe = EXE(
    mcp_pyz,
    mcp_a.scripts,
    [],
    exclude_binaries=True,
    name="skein-mcp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)

# ---- Combined onedir distribution ---------------------------------------
coll = COLLECT(
    skein_exe,
    skein_a.binaries,
    skein_a.zipfiles,
    skein_a.datas,
    mcp_exe,
    mcp_a.binaries,
    mcp_a.zipfiles,
    mcp_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="skein",
)
