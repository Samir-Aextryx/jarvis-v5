const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('jarvisDesktop', {
  getAuthToken: () => ipcRenderer.sendSync('jarvis-get-token'),
});
