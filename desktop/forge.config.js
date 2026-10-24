/* Electron Forge: the shell packaged with the Python core built by PyInstaller (packaging/sidecar.spec) under resources/core.
   macOS arm64 is signed with the owner's Developer ID only when TCE_SIGN=1 (DEC-044: no notarization yet); Windows x64 is unsigned.
   Signing keys are never in the repository: the identity is read from the keychain. */
'use strict';
const path = require('node:path');
const fs = require('node:fs');

const CORE = path.resolve(__dirname, '..', 'dist', 'titanium-core');      // PyInstaller's onedir output
const SIGN = process.env.TCE_SIGN === '1';
const IDENTITY = 'Developer ID Application: Boris Tsekinovsky (3M68DG8S7N)';

module.exports = {
  packagerConfig: {
    asar: true,
    appBundleId: 'com.tsekinovsky.titanium-workshop',
    executableName: 'titanium-workshop',
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
      }
    },
  },
};
