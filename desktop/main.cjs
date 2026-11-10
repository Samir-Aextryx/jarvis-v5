const { app, BrowserWindow, dialog, session, shell, nativeTheme, ipcMain } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

app.setName('Jarvis v5');
nativeTheme.themeSource = 'dark';
app.setAppUserModelId('local.jarvis.v5');
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
let window;
let mapWindow;
const port = 8345;
const origin = `http://127.0.0.1:${port}`;
// Jarvis runs from source with stock electron.exe and no executable of its own,
// so Smart App Control (which blocks unsigned executables) can stay on. The
// backend is Rust compiled to WebAssembly (desktop/backend, built from rust/)
// and runs inside this process; host.cjs gives it sockets, files and processes.
const repoRoot = path.dirname(__dirname);
const dataDir = process.env.JARVIS_DATA_DIR || path.join(app.getPath('documents'), 'Jarvis v5', 'config');

ipcMain.handle('jarvis-open-map', async (event, value) => {
  if (event.sender !== window?.webContents || new URL(event.senderFrame.url).origin !== origin) throw new Error('Invalid map sender');
  const target = new URL(value);
  if (target.origin !== 'http://127.0.0.1:4173' || target.pathname !== '/' || target.username || target.password) throw new Error('Invalid map address');
  if (!mapWindow || mapWindow.isDestroyed()) {
    mapWindow = new BrowserWindow({ parent: window, width: 1280, height: 850, minWidth: 800, minHeight: 600,
      title: 'Jarvis v5 — Map', backgroundColor: '#050505', autoHideMenuBar: true,
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, partition: 'persist:jarvis-map' } });
    mapWindow.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    mapWindow.webContents.session.setPermissionCheckHandler(() => false);
    mapWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    mapWindow.webContents.on('will-navigate', (e, url) => { if (new URL(url).origin !== target.origin) e.preventDefault(); });
    mapWindow.on('focus', () => window?.webContents.send('jarvis-map-visible', true));
    mapWindow.on('closed', () => { mapWindow = null; if (!window?.isDestroyed()) window?.webContents.send('jarvis-map-visible', false); });
  }
  // Hash-only changes are not restored by the map application; load a fresh document.
  target.searchParams.set('viewRequest', String(Date.now()));
  await mapWindow.loadURL(target.href);
  mapWindow.show();
  mapWindow.focus();
});

async function start() {
  fs.mkdirSync(dataDir, { recursive: true });
  require('./host.cjs').install({
    data: dataDir, resources: repoRoot, home: app.getPath('home'), desktop: app.getPath('desktop'),
    documents: app.getPath('documents'), appData: app.getPath('appData'),
    localAppData: process.env.LOCALAPPDATA || path.join(app.getPath('home'), 'AppData', 'Local'),
    temp: app.getPath('temp'),
  }, { onRestart: () => { app.relaunch(); app.exit(0); } });
  const backend = require('./backend/jarvis.js');
  const token = await backend.start(JSON.stringify({ port, data: dataDir }));
  if (!token) throw new Error('Local credential unavailable.');
  ipcMain.on('jarvis-get-token', (event) => {
    try {
      if (event.senderFrame && new URL(event.senderFrame.url).origin === origin) {
        event.returnValue = token;
        return;
      }
    } catch {}
    event.returnValue = '';
  });
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(contents.getURL().startsWith(origin + '/') && permission === 'media' && !details.mediaTypes?.includes('video'));
  });
  session.defaultSession.setPermissionCheckHandler((contents, permission, requestingOrigin) =>
    requestingOrigin === origin && permission === 'media');
  window = new BrowserWindow({ width: 1050, height: 800, minWidth: 600, minHeight: 500,
    title: 'Jarvis v5', backgroundColor: '#050505', autoHideMenuBar: true,
    icon: path.join(__dirname, 'icon.ico'),
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true } });
  window.on('focus', () => window.webContents.send('jarvis-map-visible', false));
  window.on('closed', () => { mapWindow?.close(); });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => { if (!url.startsWith(origin + '/')) event.preventDefault(); });
  await window.webContents.session.clearCache();
  await window.loadURL(origin + '/');
  window.show();
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { window?.restore(); window?.focus(); });
  app.whenReady().then(start).catch(error => { dialog.showErrorBox('Jarvis v5', error.message); app.quit(); });
  app.on('window-all-closed', () => app.quit());
}
