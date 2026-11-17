// Offline smoke check of the backend as the desktop shell starts it, isolated
// from personal data and provider keys. Run with plain Node: node scripts/verify-source.cjs
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const root = path.dirname(__dirname);
const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'jarvis-source-test-'));
const port = 8346;
const base = `http://127.0.0.1:${port}`;

async function main() {
  for (const key of ['OPENAI_API_KEY', 'FISH_API_KEY']) process.env[key] = '';
  require(path.join(root, 'desktop', 'host.cjs')).install({
    data: folder, resources: root, home: os.homedir(), desktop: folder, documents: folder,
    appData: process.env.APPDATA, localAppData: process.env.LOCALAPPDATA, temp: os.tmpdir(),
  }, { onRestart: () => {} });
  const token = await require(path.join(root, 'desktop', 'backend', 'jarvis.js')).start(JSON.stringify({ port, data: folder }));
  const health = await fetch(base + '/api/health');
  if (health.status !== 200) throw new Error('Backend did not become ready.');
  if ((await fetch(base + '/api/agent/settings')).status !== 401) throw new Error('A route answered without authentication.');
  for (const route of ['/api/agent/settings', '/api/settings/status', '/api/memory/profile', '/api/local-calendar/events', '/', '/pcm-capture.js']) {
    const response = await fetch(base + route, { headers: { Authorization: 'Bearer ' + token } });
    if (!response.ok) throw new Error(`${route} returned ${response.status}`);
  }
  const env = path.join(folder, '.env');
  if (fs.existsSync(env) && fs.readFileSync(env, 'utf8').includes('JARVIS_AUTH_TOKEN=')) throw new Error('The auth token leaked into .env.');
  console.log('Backend, authentication, assets, settings, memory and calendar: passed.');
}

function cleanup() {
  // Remove the disposable test credential, never the installed app credential.
  const service = 'Jarvis-v5-Keys-' + crypto.createHash('sha256').update(folder).digest('hex').slice(0, 16);
  for (const target of [service, 'JARVIS_AUTH_TOKEN@' + service]) {
    try { execFileSync('cmdkey', ['/delete:' + target], { stdio: 'ignore' }); } catch { /* not present */ }
  }
  // Open SQLite handles can keep the folder until this process exits.
  try { fs.rmSync(folder, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* temp folder */ }
}

main().then(() => { cleanup(); process.exit(0); }, (error) => { console.error(error.message || error); cleanup(); process.exit(1); });
