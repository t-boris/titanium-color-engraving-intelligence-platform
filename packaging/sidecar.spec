# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec of the core the desktop shell runs (feature electron, DEC-022): one folder ``dist/titanium-core`` with the
executable ``titanium-core`` and everything the package imports or opens at run time: the UI, the models and the schemas as package
data, the metadata of the packages that read their own version, and the native libraries of OpenCV, SciPy, scikit-learn, rawpy,
Shapely, HarfBuzz and fontTools.

    pip install -e ".[desktop]"
    pyinstaller --noconfirm packaging/sidecar.spec
    dist/titanium-core/titanium-core --smoke
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

datas, binaries, hiddenimports = [], [], []
datas += collect_data_files("titanium_platform", includes=["ui/*", "ui/screens/*", "models/*", "schemas/*"])
for package in ("titanium-color-engraving-platform", "fastapi", "starlette", "uvicorn", "openai", "mcp", "rawpy", "certifi", "fonttools", "uharfbuzz"):
    try:
        datas += copy_metadata(package)
    except Exception:            # a package without metadata in this environment: nothing to copy
        pass
for package in ("scipy", "sklearn", "shapely", "rawpy", "uharfbuzz", "fontTools", "certifi"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("titanium_platform") + collect_submodules("uvicorn") + ["multipart", "python_multipart"]

a = Analysis(["sidecar_entry.py"], pathex=["../src"], binaries=binaries, datas=datas, hiddenimports=hiddenimports, hookspath=[],
             runtime_hooks=[], excludes=["tkinter", "matplotlib", "IPython", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="titanium-core", debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=True, disable_windowed_traceback=False, target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="titanium-core")
