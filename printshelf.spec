# PyInstaller spec for PrintShelf — Windows .exe packaging.
#
# Build with:   uv run pyinstaller printshelf.spec --noconfirm
# Output:       dist/PrintShelf/PrintShelf.exe   (onedir bundle)
#
# Onedir (not onefile) is deliberate: PrintShelf spawns child processes
# (scan ProcessPoolExecutor, optional uvicorn Multiprocess) that re-launch the
# executable. Onefile would re-extract the whole VTK payload to a temp dir on
# every child spawn — slow and fragile. Onedir shares the unpacked tree.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
hiddenimports = []

# App's own static frontend (index.html, js/, css). Bundled under
# printshelf/static so Path(__file__).parent / "static" resolves at runtime.
datas += [("printshelf/static", "printshelf/static")]

# Heavy native deps: pull in their data files and any dynamically imported
# submodules the static analysis would otherwise miss.
for pkg in ("pyvista", "vtkmodules", "trimesh"):
    datas += collect_data_files(pkg)

# VTK exposes its modules dynamically; collect them so offscreen rendering works.
hiddenimports += collect_submodules("vtkmodules")
# pyvista.plotting.colors imports matplotlib at import time — must NOT be excluded.
datas += collect_data_files("matplotlib")
# uvicorn worker factory is imported by string ("printshelf.desktop:...").
hiddenimports += collect_submodules("printshelf")
# pywebview's Windows backend is selected at runtime.
hiddenimports += ["webview.platforms.winforms", "webview.platforms.edgechromium"]


a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PrintShelf",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PrintShelf",
)
