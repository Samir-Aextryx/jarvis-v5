'use strict';
// I/O shim for the Rust backend (desktop/backend/jarvis_bg.wasm).
// WebAssembly cannot reach the operating system by itself, so this file hands
// Rust plain primitives: TCP sockets, HTTP and WebSocket clients, files,
// processes, a PowerShell bridge for Windows APIs, and SQLite. It holds no
// Jarvis logic; routing, auth, prompts and every decision live in rust/src.
const net = require('node:net');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');

let nextId = 1;
const handles = new Map();
const keep = value => { const id = nextId++; handles.set(id, value); return id; };
const bytes = view => Buffer.from(view.buffer ? Buffer.from(view.buffer, view.byteOffset, view.byteLength) : view);
const u8 = buffer => new Uint8Array(buffer.buffer, buffer.byteOffset, buffer.byteLength);

// Turns an event stream into awaitable reads; null marks the end.
class Inbox {
  constructor(onDrain) { this.items = []; this.waiters = []; this.ended = false; this.error = null; this.onDrain = onDrain; }
  push(item) { const waiter = this.waiters.shift(); if (waiter) waiter.resolve(item); else this.items.push(item); }
  end(error) {
    if (this.ended) return;
    this.ended = true; this.error = error || null;
    for (const waiter of this.waiters.splice(0)) error ? waiter.reject(error) : waiter.resolve(null);
  }
  next() {
    if (this.items.length) { const item = this.items.shift(); if (this.items.length < 8) this.onDrain?.(); return Promise.resolve(item); }
    if (this.ended) return this.error ? Promise.reject(this.error) : Promise.resolve(null);
    this.onDrain?.();
    return new Promise((resolve, reject) => this.waiters.push({ resolve, reject }));
  }
}

let childEnvBlocklist = new Set();
const childEnv = extra => {
  const env = {};
  for (const [key, value] of Object.entries(process.env)) if (!childEnvBlocklist.has(key.toUpperCase())) env[key] = value;
  return Object.assign(env, extra || {});
};

const powershell = { child: null, pending: new Map(), buffer: '', script: '' };
function startPowerShell() {
  const child = spawn('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command',
    '[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); $s=[Console]::In.ReadLine(); . ([ScriptBlock]::Create([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($s))))'],
  { windowsHide: true, env: childEnv(), stdio: ['pipe', 'pipe', 'ignore'] });
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    powershell.buffer += chunk;
    let newline;
    while ((newline = powershell.buffer.indexOf('\n')) >= 0) {
      const line = powershell.buffer.slice(0, newline).trim();
      powershell.buffer = powershell.buffer.slice(newline + 1);
      if (!line.startsWith('{')) continue;
      try {
        const reply = JSON.parse(line);
        const waiter = powershell.pending.get(reply.id);
        if (waiter) { powershell.pending.delete(reply.id); waiter.resolve(line); }
      } catch {}
    }
  });
  const fail = () => {
    if (powershell.child !== child) return;
    powershell.child = null; powershell.buffer = '';
    for (const waiter of powershell.pending.values()) waiter.reject(new Error('PowerShell bridge stopped'));
    powershell.pending.clear();
  };
  child.on('exit', fail); child.on('error', fail);
  child.stdin.on('error', fail);
  child.stdin.write(Buffer.from(powershell.script, 'utf8').toString('base64') + '\n');
  powershell.child = child;
}

const host = {
  paths: {},
  onRestart: null,
  log(level, message) {
    const line = `${new Date().toISOString()} [${level}] ${message}`;
    (level === 'error' ? console.error : console.log)(line);
    if (host.paths.data) try { fs.appendFileSync(path.join(host.paths.data, 'server.log'), line + '\n'); } catch {}
  },
  env(name) { return process.env[name]; },
  envJson() { return JSON.stringify(process.env); },
  pathsJson() { return JSON.stringify(host.paths); },
  setChildEnvBlocklist(json) { childEnvBlocklist = new Set(JSON.parse(json).map(name => name.toUpperCase())); },
  randomBytes(count) { return u8(crypto.randomBytes(count)); },
  monotonic() { return performance.now(); },
  sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); },
  restart() { if (host.onRestart) host.onRestart(); else process.exit(0); },
  exit(code) { process.exit(code); },

  // TCP server
  listen(address, port) {
    return new Promise((resolve, reject) => {
      const inbox = new Inbox();
      const server = net.createServer({ noDelay: true }, socket => inbox.push(host._keepSocket(socket)));
      server.once('error', reject);
      server.listen(port, address, () => { server.off('error', reject); resolve(keep({ server, inbox })); });
    });
  },
  accept(id) { return handles.get(id).inbox.next(); },
  _keepSocket(socket) {
    socket.setNoDelay(true);
    const inbox = new Inbox(() => socket.isPaused() && socket.resume());
    socket.on('data', data => { inbox.push(u8(data)); if (inbox.items.length > 32) socket.pause(); });
    socket.on('end', () => inbox.end());
    socket.on('close', () => inbox.end());
    socket.on('error', () => inbox.end());
    return keep({ socket, inbox });
  },
  read(id) { const entry = handles.get(id); return entry ? entry.inbox.next() : Promise.resolve(null); },
  write(id, data) { const entry = handles.get(id); if (entry && !entry.socket.destroyed) entry.socket.write(bytes(data)); },
  close(id) {
    const entry = handles.get(id);
    if (!entry) return;
    handles.delete(id);
    entry.socket.end();
    setTimeout(() => entry.socket.destroy(), 2000).unref();
  },

  // Outbound HTTP; the idle timeout restarts with every received chunk.
  async fetchStart(url, method, headersJson, body, idleMs) {
    const controller = new AbortController();
    const entry = { controller, timer: null, reader: null };
    const arm = () => { clearTimeout(entry.timer); if (idleMs) entry.timer = setTimeout(() => controller.abort(), idleMs); };
    arm();
    try {
      const response = await fetch(url, { method, headers: JSON.parse(headersJson), redirect: 'follow',
        body: body && body.length ? bytes(body) : undefined, signal: controller.signal });
      entry.reader = response.body ? response.body.getReader() : null;
      entry.arm = arm;
      arm();
      return JSON.stringify({ id: keep(entry), status: response.status, headers: Object.fromEntries(response.headers) });
    } catch (error) {
      clearTimeout(entry.timer);
      throw new Error(controller.signal.aborted ? 'timeout' : String(error?.cause?.code || error?.message || error));
    }
  },
  async bodyRead(id) {
    const entry = handles.get(id);
    if (!entry || !entry.reader) return null;
    try {
      const { done, value } = await entry.reader.read();
      if (done) { host.bodyClose(id); return null; }
      entry.arm();
      return value;
    } catch (error) {
      host.bodyClose(id);
      throw new Error(entry.controller.signal.aborted ? 'timeout' : String(error?.message || error));
    }
  },
  bodyClose(id) {
    const entry = handles.get(id);
    if (!entry) return;
    handles.delete(id);
    clearTimeout(entry.timer);
    try { entry.controller.abort(); } catch {}
  },

  // Outbound WebSocket (Node's built-in client).
  wsConnect(url, protocolsJson, headersJson, timeoutMs) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url, { protocols: JSON.parse(protocolsJson), headers: JSON.parse(headersJson) });
      socket.binaryType = 'arraybuffer';
      const inbox = new Inbox();
      let open = false;
      const timer = setTimeout(() => { if (!open) { socket.close(); reject(new Error('timeout')); } }, timeoutMs || 12000);
      socket.onopen = () => { open = true; clearTimeout(timer); resolve(keep({ socket, inbox })); };
      socket.onmessage = event => inbox.push(typeof event.data === 'string' ? event.data : new Uint8Array(event.data));
      socket.onerror = () => { if (!open) { clearTimeout(timer); reject(new Error('connect failed')); } };
      socket.onclose = () => { inbox.end(); if (!open) { clearTimeout(timer); reject(new Error('closed')); } };
    });
  },
  wsRecv(id) { const entry = handles.get(id); return entry ? entry.inbox.next() : Promise.resolve(null); },
  wsSendText(id, text) { handles.get(id)?.socket.send(text); },
  wsSendBinary(id, data) { handles.get(id)?.socket.send(bytes(data)); },
  wsClose(id) { const entry = handles.get(id); if (entry) { handles.delete(id); try { entry.socket.close(); } catch {} entry.inbox.end(); } },

  // Files (small, synchronous; null when missing)
  readFile(file) { try { return u8(fs.readFileSync(file)); } catch { return null; } },
  writeFile(file, data) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const temp = `${file}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`;
    fs.writeFileSync(temp, bytes(data));
    fs.renameSync(temp, file);
  },
  appendFile(file, data) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.appendFileSync(file, bytes(data)); },
  remove(file) { try { fs.rmSync(file, { force: true }); return true; } catch { return false; } },
  rename(from, to) { fs.renameSync(from, to); },
  mkdirp(dir) { fs.mkdirSync(dir, { recursive: true }); },
  stat(file) {
    try { const s = fs.statSync(file); return JSON.stringify({ dir: s.isDirectory(), file: s.isFile(), size: s.size, mtime: s.mtimeMs }); }
    catch { return null; }
  },
  listDir(dir) {
    try {
      return JSON.stringify(fs.readdirSync(dir, { withFileTypes: true }).map(entry => ({
        name: entry.name, dir: entry.isDirectory(), file: entry.isFile(), link: entry.isSymbolicLink() })));
    } catch { return null; }
  },

  // Processes. Children never inherit the secrets in the blocklist.
  run(file, argsJson, optionsJson) {
    const options = JSON.parse(optionsJson || '{}');
    return new Promise(resolve => {
      let child;
      try {
        child = spawn(file, JSON.parse(argsJson), { cwd: options.cwd, env: childEnv(options.env), windowsHide: true,
          windowsVerbatimArguments: !!options.verbatim, stdio: ['pipe', 'pipe', 'pipe'] });
      } catch (error) { resolve(JSON.stringify({ code: -1, stdout: '', stderr: String(error.message) })); return; }
      const out = []; const err = []; let size = 0; const limit = options.maxBytes || 8 * 1024 * 1024;
      const collect = list => chunk => { size += chunk.length; if (size <= limit) list.push(chunk); };
      child.stdout.on('data', collect(out)); child.stderr.on('data', collect(err));
      const timer = options.timeoutMs ? setTimeout(() => child.kill(), options.timeoutMs) : null;
      child.on('error', error => { clearTimeout(timer); resolve(JSON.stringify({ code: -1, stdout: '', stderr: String(error.message) })); });
      child.on('close', code => {
        clearTimeout(timer);
        const decode = list => Buffer.concat(list).toString(options.encoding || 'utf8');
        resolve(JSON.stringify({ code: code ?? -1, stdout: decode(out), stderr: decode(err) }));
      });
      child.stdin.on('error', () => {});
      child.stdin.end(options.stdin || undefined);
    });
  },
  spawnDetached(file, argsJson, optionsJson) {
    const options = JSON.parse(optionsJson || '{}');
    try {
      const child = spawn(file, JSON.parse(argsJson), { cwd: options.cwd, env: childEnv(options.env), detached: true,
        windowsHide: options.hide !== false, windowsVerbatimArguments: !!options.verbatim, stdio: 'ignore' });
      child.on('error', () => {});
      child.unref();
      return child.pid || 0;
    } catch { return 0; }
  },

  // One long-lived PowerShell process for Win32/COM/UI Automation calls.
  psSetScript(script) { powershell.script = script; },
  psCall(requestJson) {
    if (!powershell.child) startPowerShell();
    const request = JSON.parse(requestJson);
    request.id = nextId++;
    return new Promise((resolve, reject) => {
      powershell.pending.set(request.id, { resolve, reject });
      powershell.child.stdin.write(JSON.stringify(request) + '\n');
    });
  },

  // SQLite (node:sqlite, synchronous)
  sqlOpen(file) {
    const { DatabaseSync } = require('node:sqlite');
    fs.mkdirSync(path.dirname(file), { recursive: true });
    return keep(new DatabaseSync(file));
  },
  sqlExec(id, sql) { handles.get(id).exec(sql); },
  sqlQuery(id, sql, paramsJson) {
    const rows = handles.get(id).prepare(sql).all(...JSON.parse(paramsJson || '[]'));
    return JSON.stringify(rows, (_key, value) => typeof value === 'bigint' ? Number(value) : value);
  },
  sqlRun(id, sql, paramsJson) {
    const result = handles.get(id).prepare(sql).run(...JSON.parse(paramsJson || '[]'));
    return JSON.stringify({ changes: Number(result.changes), lastId: Number(result.lastInsertRowid) });
  },
};

// Install before the generated wasm-bindgen glue resolves `jarvisHost`.
function install(paths, options = {}) {
  host.paths = paths;
  host.onRestart = options.onRestart || null;
  globalThis.jarvisHost = host;
  return host;
}

module.exports = { install };
