/* Electron Forge: the shell packaged with the Python core built by PyInstaller (packaging/sidecar.spec) under resources/core.
   macOS arm64 is signed with the owner's Developer ID only when TCE_SIGN=1 (DEC-044: no notarization yet); Windows x64 is unsigned.
   Signing keys are never in the repository: the identity is read from the keychain. */
'use strict';
const path = require('node:path');
const fs = require('node:fs');

const CORE = path.resolve(__dirname, '..', 'dist', 'titanium-core');      // PyInstaller's onedir output
const SIGN = process.env.TCE_SIGN === '1';
const IDENTITY = 'Developer ID Application: Boris Tsekinovsky (3M68DG8S7N)';

/** The version of the built core, from the dist-info PyInstaller copied next to it (null when there is none). */
function coreVersion() {
  const internal = path.join(CORE, '_internal');
  const info = fs.existsSync(internal) ? fs.readdirSync(internal).find((n) => /^titanium_color_engraving_platform-.*\.dist-info$/.test(n)) : null;
  if (!info) return null;
  const meta = fs.readFileSync(path.join(internal, info, 'METADATA'), 'utf8');
  const found = meta.match(/^Version:\s*(\S+)/m);
  return found ? found[1] : null;
}

module.exports = {
  packagerConfig: {
    asar: true,
    appBundleId: 'com.tsekinovsky.titanium-workshop',
    executableName: 'titanium-workshop',
    icon: path.join(__dirname, 'assets', 'icon'),                           // .icns on macOS, .ico on Windows (packaging/make_icon.py)
    extraResource: fs.existsSync(CORE) ? [CORE] : [],
    ignore: [/^\/test($|\/)/, /^\/out($|\/)/, /\.md$/],
    ...(SIGN && process.platform === 'darwin' ? {osxSign: {identity: IDENTITY, hardenedRuntime: true, 'gatekeeper-assess': false,
      entitlements: path.join(__dirname, 'entitlements.plist'), 'entitlements-inherit': path.join(__dirname, 'entitlements.plist')}} : {}),
  },
  rebuildConfig: {},
  makers: [
    {name: '@electron-forge/maker-squirrel', platforms: ['win32'],
      config: {name: 'TitaniumWorkshop', setupExe: 'TitaniumWorkshop-Setup.exe', noMsi: true}},
    {name: '@electron-forge/maker-zip', platforms: ['darwin']},
  ],
  hooks: {
    prePackage: async () => {
      if (!fs.existsSync(CORE)) {
        console.warn(`[forge] the Python core is not built at ${CORE}: the package will run the development core (.venv) only`);
        return;
      }
      // The core reads its version from the package metadata PyInstaller copied; an editable install keeps the metadata of the version
      // it was installed at, so a core built after a version bump can still say the old number. The two versions must agree.
      const shell = require('./package.json').version;
      const core = coreVersion();
      if (core !== shell) {
        throw new Error(`[forge] the built core says ${core}, the shell ${shell}: refresh the core's metadata ` +
          '(uv pip install --python .venv/bin/python -e . --no-deps) and rebuild it with packaging/sidecar.spec');
      }
    },
  },
};
