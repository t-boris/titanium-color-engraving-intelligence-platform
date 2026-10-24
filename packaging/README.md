# Packaging the desktop workshop (feature electron)

The desktop application is the Electron shell in `desktop/` around the Python core of this repository, packaged by PyInstaller
(DEC-022, DEC-046). The core keeps working as the console command `titanium-platform`; the shell starts the same package as a hidden
child on a free loopback port with a per-launch session secret.

## The core

```sh
uv pip install --python .venv/bin/python -e ".[desktop]"   # adds pyinstaller (the venv is uv-managed, no pip)
cd packaging && PYTHONPATH=../src ../.venv/bin/python -m PyInstaller --noconfirm --distpath ../dist --workpath ../build/pyinstaller sidecar.spec && cd ..
dist/titanium-core/titanium-core --smoke       # starts on a temporary workshop, opens a session, asks /api/health, exits 0
```

`sidecar.spec` builds one folder `dist/titanium-core` (onedir: starts faster than a single file and is what the shell copies into its
resources). It collects the package data (UI, models, schemas), the metadata of packages that read their own version, and the native
libraries of OpenCV, SciPy, scikit-learn, rawpy, Shapely, HarfBuzz and fontTools.

## The shell

```sh
cd desktop
npm ci
npm test                                       # node --test test (also run by tests/test_desktop_shell.py)
npm run package                                # out/<product>-<platform>-<arch>/ with dist/titanium-core under resources/
npm run make                                   # macOS: zip; Windows: Squirrel installer TitaniumWorkshop-Setup.exe
```

Without `dist/titanium-core` the packaged shell falls back to the repository's `.venv` (development only; `forge` warns).

Signing (DEC-044): macOS is signed with «Developer ID Application: Boris Tsekinovsky (3M68DG8S7N)» from the keychain only when
`TCE_SIGN=1` is set, without notarization; Windows is unsigned. No key or certificate is in the repository. Builds are GitHub
pre-releases marked «internal beta» (DEC-048) until notarization and a Windows signing service exist.

The Windows build runs on GitHub Actions by hand: workflow `desktop` (`workflow_dispatch`), which builds the core on
`windows-latest`, runs its `--smoke`, and makes the installer.

## Run modes (DEC-046)

| mode | command | who may use it |
|---|---|---|
| console | `titanium-platform --port 8765` | a browser on this computer (Host and Origin checked; `TCE_ALLOWED_HOSTS` for a named host) |
| desktop | `titanium-platform --desktop --port 0 --parent-pid <shell>` with `TCE_SESSION_SECRET` | the shell's window only: it opens `/session/<secret>` once, which sets the session cookie |
| smoke | `titanium-platform --smoke` | the build check |

Under the desktop shell the core never reads `.env.local`; the AI key comes from the environment only.
