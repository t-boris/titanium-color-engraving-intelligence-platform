/* The only bridge between the pages and the shell: the versions, and the start screen's calls (choose a folder, open a workshop).
   contextIsolation and the sandbox are on; the pages of the core get `versions` only. */
'use strict';
const {contextBridge, ipcRenderer} = require('electron');

contextBridge.exposeInMainWorld('shell', {
  versions: {electron: process.versions.electron, chrome: process.versions.chrome},
  picker: {
    choices: () => ipcRenderer.invoke('picker:choices'),
    browse: (mode) => ipcRenderer.invoke('picker:browse', mode),
    open: (folder) => ipcRenderer.invoke('picker:open', folder),
  },
});
