const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('jarvisDesktop', {
  openMap: url => ipcRenderer.invoke('jarvis-open-map', url),
  onMapVisible: callback => ipcRenderer.on('jarvis-map-visible', (_event, visible) => callback(Boolean(visible))),
  getAuthToken: () => ipcRenderer.sendSync('jarvis-get-token'),
});
