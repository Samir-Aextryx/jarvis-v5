const { app, BrowserWindow, dialog, session, shell, nativeTheme, ipcMain } = require('electron');
const { spawn, execFile } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

app.setName('Jarvis v5');
nativeTheme.themeSource = 'dark';
app.setAppUserModelId('local.jarvis.v5');
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
let window;
let backend;
let adoptedWatch = null;
let mapWindow;
let started = false;
let quitting = false;
let backendRestarts = 0;
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const port = 8345;
const origin = `http://127.0.0.1:${port}`;
// Jarvis runs from source: stock electron.exe and the venv Python, no own executable,
// so Smart App Control (which blocks unsigned executables) can stay on.
const repoRoot = path.dirname(__dirname);
const dataDir = process.env.JARVIS_DATA_DIR || path.join(app.getPath('documents'), 'Jarvis v5', 'config');
const backendCommand = [path.join(repoRoot, '.venv', 'Scripts', 'python.exe'), path.join(repoRoot, 'scripts', 'desktop-server.py')];

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

async function health() {
  try {
    const response = await fetch(origin + '/api/health', { signal: AbortSignal.timeout(1000) });
    const data = await response.json();
    // Accept any 5.x backend: a patch release must not make the shell refuse to start.
    return data.name === 'JARVIS' && String(data.version || '').split('.')[0] === '5';
  } catch { return false; }
}

function spawnBackend() {
  const log = fs.openSync(path.join(dataDir, 'server.log'), 'a');
  const child = spawn(backendCommand[0], backendCommand.slice(1), { cwd: dataDir, windowsHide: true,
    // The shell owns the process: /api/restart exits and we start it again here.
    env: { ...process.env, JARVIS_DATA_DIR: dataDir, JARVIS_PORT: String(port), PYTHONUTF8: '1',
      JARVIS_DESKTOP_MANAGED: '1' },
    stdio: ['ignore', log, log] });
  fs.closeSync(log);
  watchBackend(child);
  return child;
}

function watchBackend(child) {
  child.on('error', () => {
    if (!quitting) { dialog.showErrorBox('Jarvis v5', 'Der Server konnte nicht gestartet werden.'); app.quit(); }
  });
  child.on('exit', async () => {
    if (!started || quitting) return;
    // /api/restart intentionally exits the child so this shell can replace it.
    // Tolerate one crash restart, then stop instead of respawning forever.
    backendRestarts += 1;
    if (backendRestarts > 2) {
      dialog.showErrorBox('Jarvis v5', 'Der Server wurde unerwartet beendet. Bitte Jarvis neu starten.');
      app.quit();
      return;
    }
    backend = spawnBackend();
    for (let n = 0; n < 50; n++) {
      await sleep(200);
      if (await health()) { backendRestarts = 0; return; }
      if (backend.exitCode !== null) break;
    }
    if (backend.exitCode === null) { backendRestarts = 0; return; }
    dialog.showErrorBox('Jarvis v5', 'Der Server wurde unerwartet beendet. Bitte Jarvis neu starten.');
    app.quit();
  });
}

function watchAdoptedBackend() {
  // A backend left over from a previous shell is usable, but this shell did
  // not spawn it. Without a watcher, /api/restart would exit it and nothing
  // would bring it back. Poll and take over ownership when it stops.
  let checking = false;
  let failures = 0;
  adoptedWatch = setInterval(async () => {
    if (quitting || !started || checking) return;
    checking = true;
    try {
      if (await health()) { failures = 0; return; }
      failures += 1;
      if (failures < 3) return;
      clearInterval(adoptedWatch);
      adoptedWatch = null;
      if (quitting) return;
      backendRestarts = 0;
      backend = spawnBackend();
      for (let n = 0; n < 50; n++) {
        await sleep(200);
        if (await health() || backend.exitCode !== null) break;
      }
    } finally { checking = false; }
  }, 1000);
}

async function start() {
  fs.mkdirSync(dataDir, { recursive: true });
  if (!(await health())) {
    backend = spawnBackend();
    for (let n = 0; n < 100; n++) {
      if (await health()) break;
      if (backend.exitCode !== null) break;
      await sleep(200);
    }
  } else {
    watchAdoptedBackend();
  }
  if (!(await health())) throw new Error('Server nicht erreichbar. Details: config/server.log');
  const token = await new Promise((resolve, reject) => {
    execFile(backendCommand[0], [...backendCommand.slice(1), '--print-auth-token'],
      { windowsHide: true, timeout: 10000, env: { ...process.env, JARVIS_DATA_DIR: dataDir } },
      (error, stdout) => error ? reject(new Error('Credential Manager could not be read.')) : resolve(stdout.trim()));
  });
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
  started = true;
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { window?.restore(); window?.focus(); });
  app.whenReady().then(start).catch(error => { dialog.showErrorBox('Jarvis v5', error.message); app.quit(); });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', () => {
    quitting = true;
    if (adoptedWatch) { clearInterval(adoptedWatch); adoptedWatch = null; }
    if (backend && backend.exitCode === null) backend.kill();
  });
}
