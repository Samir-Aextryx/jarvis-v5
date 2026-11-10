import { apiGet, apiPost } from './api/client';
/**
 * JARVIS — Settings Panel
 *
 * Overlay panel for API keys, connection status, preferences, and system info.
 * Slides in from the right with glass-morphism styling.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
import { openPersonalPanel } from './personal-panel';
import { agentSettingsHTML, loadAgentSettings, wireAgentSettings } from './agent-settings';
import { providerKeysHTML, loadProviderKeys, wireProviderKeys, readLLMStatus } from './provider-settings';

interface StatusResponse {
  codex_installed: boolean;
  calendar_accessible: boolean;
  mail_accessible: boolean;
  outlook_accessible: boolean;
  google_mail_accessible: boolean;
  notes_accessible: boolean;
  memory_count: number;
  task_count: number;
  server_port: number;
  uptime_seconds: number;
  env_keys_set: {
    openai: boolean;
    fish_audio: boolean;
    fish_voice_id: boolean;
    user_name: string;
  };
}

interface PreferencesResponse {
  user_name: string;
  honorific: string;
  stt_keywords: string;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let panelEl: HTMLElement | null = null;
let isOpen = false;
let setupStep = 0; // 0=openai, 1=fish, 2=name, 3=done
let previousFocus: HTMLElement | null = null;
let closeTimer: ReturnType<typeof setTimeout> | undefined;

function setSaveStatus(message: string, ok = true) {
  const element = document.getElementById("settings-save-status");
  if (!element) return;
  element.textContent = message;
  element.dataset.state = ok ? "ok" : "error";
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Panel HTML
// ---------------------------------------------------------------------------

function buildPanelHTML(): string {
  return `
    <div class="settings-backdrop" id="settings-backdrop" aria-hidden="true"></div>
    <div class="settings-panel" id="settings-panel-inner" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div class="settings-header">
        <div class="settings-heading">
          <span class="settings-eyebrow">PERSONAL VOICE ASSISTANT</span>
          <h2 id="settings-title">Settings</h2>
          <p>Set up how JARVIS listens, thinks and speaks.</p>
        </div>
        <button class="settings-close" id="settings-close" type="button" aria-label="Close settings">&times;</button>
      </div>

      <nav class="settings-nav" aria-label="Settings sections">
        <a href="#section-preferences">Voice</a>
        <a href="#section-voice-automation">PC actions</a>
        <a href="#section-agent">AI</a>
        <a href="#section-google">Accounts</a>
        <a href="#section-api-keys">Voice & AI keys</a>
        <a href="#section-jarvis">Personal</a>
        <a href="#section-status">Status</a>
        <a href="#section-sysinfo">System</a>
      </nav>

      <div class="settings-welcome" id="settings-welcome" style="display:none">
        <p>Welcome to JARVIS. Let's get you set up.</p>
      </div>

      <div class="settings-body">
        <div class="voice-only-card" role="note">
          <span class="voice-only-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v3m-4 0h8"/></svg></span>
          <div><strong>Speak naturally. Jarvis answers with voice.</strong><p>Use the microphone on the home screen for every request. There is no text chat; typing is only used here for setup.</p></div>
          <span class="voice-only-badge">VOICE ONLY</span>
        </div>
        ${agentSettingsHTML}

        <section class="settings-section" id="section-jarvis">
          <h3>Your Jarvis</h3>
          <p class="google-help">Your own calendar and editable memory, saved on this PC. No Google account needed. Voice commands use your Jarvis calendar unless you name Google.</p>
          <button class="settings-btn" id="settings-custom-memory">My memory</button>
          <button class="settings-btn" id="settings-custom-calendar">My calendar</button>
        </section>

        <section class="settings-section" id="section-voice-automation">
          <h3>Voice automation</h3>
          <p id="local-pc-status" role="status">Checking AI configuration…</p>
          <p class="google-help">Multi-step PC requests start automatically. Say “Use Word to …” or “Open ChatGPT and prompt it to …”. Jarvis reads accessible app controls, acts, and checks the result. Say “task status” for progress or “stop” to cancel. Up to 12 task actions and 8 planning rounds; five-minute limit.</p>
          <p class="google-help">App control needs an accessible, signed-in app window. Existing drafts are preserved. Provide the exact contact and message text; “write” prepares a draft, while an explicit “send” allows submission. Jarvis verifies submission separately from delivery or a reply. Passwords, security changes, purchases and deletion require manual handling.</p>
          <button class="settings-btn" id="refresh-autonomy">Refresh task history</button>
          <pre id="autonomy-history" role="status" style="white-space:pre-wrap;max-height:240px;overflow:auto;font:12px/1.6 inherit">No task history loaded.</pre>
          <p class="google-help">Your selected AI plans autonomous tasks; Windows executes supported PC actions. API usage is billed to that provider. Speech recognition and Fish Audio use their existing services. Sending a prompt to ChatGPT or Codex uses that app and your account.</p>
        </section>

        <section class="settings-section" id="section-google">
          <h3>Google</h3>
          <label class="google-help" for="google-api-key">Google API key — public APIs</label>
          <input id="google-api-key" type="password" placeholder="AIza…" autocomplete="new-password" spellcheck="false" maxlength="100">
          <div class="google-buttons">
            <button type="button" id="google-save-key">Save API key</button>
            <button type="button" id="google-test-key">Test YouTube API</button>
            <button type="button" id="google-remove-key">Remove API key</button>
          </div>
          <p id="google-key-status" class="google-help" role="status">No API key saved.</p>
          <p class="google-help">The key supports public YouTube data when YouTube Data API v3 is enabled. Private Gmail, Calendar and Drive need the account connection below.</p>
          <p class="google-help">Connect your account to read Gmail, calendar events, Drive files, tasks and contacts. Gmail drafts saves drafts directly in your account. Enable the services you want, then reconnect Google to grant access. Jarvis requires Gmail sending and an explicit send request before API sending. Calendar times use Europe/Zurich.</p>
          <div class="google-services">
            <label><input type="checkbox" name="google-service" value="gmail" checked> Gmail reading</label>
            <label><input type="checkbox" name="google-service" value="gmail_send"> Gmail sending</label>
            <label><input type="checkbox" name="google-service" value="gmail_drafts"> Gmail drafts</label>
            <label><input type="checkbox" name="google-service" value="calendar" checked> Calendar reading</label>
            <label><input type="checkbox" name="google-service" value="calendar_write"> Calendar editing</label>
            <label><input type="checkbox" name="google-service" value="drive" checked> Drive</label>
            <label><input type="checkbox" name="google-service" value="tasks"> Tasks</label>
            <label><input type="checkbox" name="google-service" value="contacts"> Contacts</label>
          </div>
          <label class="google-help" for="google-client-file">Import Google OAuth client JSON (Desktop app)</label>
          <input id="google-client-file" type="file" accept=".json,application/json">
          <p class="google-help">A regular API key cannot access your private account. Enable the selected APIs and create a Desktop OAuth client in Google Cloud. Tokens are stored in Windows Credential Manager.</p>
          <div class="google-buttons">
            <button type="button" id="google-setup">Setup guide</button>
            <button type="button" id="google-connect">Connect Google</button>
            <button type="button" id="google-refresh">Refresh status</button>
            <button type="button" id="google-disconnect">Disconnect</button>
          </div>
          <p id="google-status" role="status" aria-live="polite">Not connected.</p>
        </section>

        <!-- API Keys -->
        <section class="settings-section" id="section-api-keys">
          <h3>API Keys</h3>

          <div class="settings-field">
            <label for="input-openai-key">OpenAI API Key (AI and speech recognition)</label><a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">API-Schlüssel erstellen</a>
            <div class="settings-input-row">
              <input type="password" id="input-openai-key" placeholder="sk-..." autocomplete="new-password" spellcheck="false" />
              <button class="settings-btn" id="btn-test-openai">Test</button>
              <span class="status-dot" id="status-openai"></span>
            </div>
          </div>

          <div class="settings-field">
            <label for="input-fish-key">Fish Audio API Key</label><a href="https://fish.audio/app/api-keys/" target="_blank" rel="noreferrer">Fish API-Schlüssel erstellen</a>
            <div class="settings-input-row">
              <input type="password" id="input-fish-key" placeholder="Fish Audio key..." autocomplete="new-password" spellcheck="false" />
              <button class="settings-btn" id="btn-test-fish">Test</button>
              <span class="status-dot" id="status-fish"></span>
            </div>
          </div>

          <div class="settings-field">
            <label for="input-fish-voice-id">Fish Voice ID</label><a href="https://fish.audio/m/612b878b113047d9a770c069c8b4fdfe/" target="_blank" rel="noreferrer">JARVIS-Stimme anhören</a>
            <div class="settings-input-row">
              <input type="text" id="input-fish-voice-id" placeholder="612b878b113047d9a770c069c8b4fdfe" spellcheck="false" />
              <button class="settings-btn" id="btn-save-voice-id">Save</button>
            </div>
          </div>

          <div class="settings-actions">
            <button class="settings-btn primary" id="btn-save-keys">Save Keys</button>
          </div>
          <p id="settings-save-status" role="status" aria-live="polite"></p>
          ${providerKeysHTML}
        </section>

        <!-- Connection Status -->
        <section class="settings-section" id="section-status">
          <h3>Connection Status</h3><p>Jarvis listens and speaks through the voice interface. Local apps, your Jarvis calendar and notes are available on this PC.</p>
          <div class="status-grid">
            <div class="status-row"><span class="status-dot" id="status-codex"></span><span>Codex desktop access</span></div>
            <div class="status-row"><span class="status-dot" id="status-calendar"></span><span>Jarvis calendar</span></div>
            <div class="status-row"><span class="status-dot" id="status-mail"></span><span>Mail actions available</span></div>
            <div class="status-row"><span class="status-dot" id="status-outlook-mail"></span><span>Outlook account</span></div>
            <div class="status-row"><span class="status-dot" id="status-google-mail"></span><span>Google mail authorization</span></div>
            <div class="status-row"><span class="status-dot" id="status-notes"></span><span>Jarvis notes</span></div>
            <div class="status-row"><span class="status-dot" id="status-server"></span><span>Server</span><span class="status-detail" id="status-server-detail"></span></div>
          </div>
        </section>

        <!-- User Preferences -->
        <section class="settings-section" id="section-preferences">
          <h3>User Preferences</h3>

          <div class="settings-field">
            <label for="input-mic-sensitivity">Microphone sensitivity</label>
            <select id="input-mic-sensitivity">
              <option value="auto">Automatic</option>
              <option value="sensitive">Quiet voice</option>
              <option value="noisy">Noisy room</option>
            </select>
            <p class="google-help">Adjusts speech detection. Quiet voice reacts to softer speech; Noisy room reduces triggers from background sound. Use headphones if Jarvis hears its own voice.</p>
          </div>
          <div class="settings-field">
            <label for="input-stt-accuracy">Speech recognition</label>
            <select id="input-stt-accuracy">
              <option value="minimal">Fastest — recommended</option>
              <option value="low">Low latency</option>
              <option value="medium">Balanced</option>
              <option value="high">More accurate</option>
            </select>
            <p class="google-help">Fastest starts replies sooner; Low latency or Balanced may improve recognition of names and German/English switching. Add important names below when needed.</p>
          </div>
          <div class="settings-field">
            <label for="input-stt-keywords">Names and unusual terms</label>
            <input type="text" id="input-stt-keywords" maxlength="800" placeholder="Häner, Branko, project names" />
            <p class="google-help">Separate up to 12 names or terms with commas. These hints are sent to OpenAI with the live audio to improve spelling; do not add anything you want to keep private.</p>
          </div>
          <div class="settings-field">
            <label for="input-speech-pause">Pause before replying</label>
            <select id="input-speech-pause">
              <option value="0">0 ms — no extra delay</option>
              <option value="100">100 ms</option>
              <option value="200">200 ms</option>
              <option value="300">300 ms</option>
              <option value="500">500 ms</option>
              <option value="1000">1 second</option>
              <option value="2000">2 seconds — longer thinking pauses</option>
              <option value="3500">3.5 seconds — take your time</option>
              <option value="5000">5 seconds — long pauses</option>
            </select>
            <p class="google-help">Extra delay after speech detection. Default: 0 ms. A short 160 ms silence check separates speech turns. Speak to interrupt Jarvis; say “stop” to cancel the task.</p>
          </div>

          <div class="settings-field">
            <label for="input-user-name">Your Name</label>
            <input type="text" id="input-user-name" placeholder="Your name" autocomplete="name" />
          </div>

          <div class="settings-field">
            <label for="input-honorific">Honorific</label>
            <select id="input-honorific">
              <option value="sir">Sir</option>
              <option value="ma'am">Ma'am</option>
              <option value="none">None</option>
            </select>
          </div>

          <div class="settings-actions">
            <button class="settings-btn primary" id="btn-save-prefs">Save Preferences</button>
          </div>
        </section>

        <!-- System Info -->
        <section class="settings-section" id="section-sysinfo">
          <h3>System Info</h3>
          <button class="settings-btn" id="btn-open-memory">Persönliches Gedächtnis (MEMORY.md) öffnen</button>
          <div class="sysinfo-grid">
            <div class="sysinfo-row"><span class="sysinfo-label">Memory entries</span><span id="sysinfo-memory">--</span></div>
            <div class="sysinfo-row"><span class="sysinfo-label">Tasks</span><span id="sysinfo-tasks">--</span></div>
            <div class="sysinfo-row"><span class="sysinfo-label">Server port</span><span id="sysinfo-port">--</span></div>
            <div class="sysinfo-row"><span class="sysinfo-label">Uptime</span><span id="sysinfo-uptime">--</span></div>
          </div>
        </section>

        <!-- Setup Navigation (first-time only) -->
        <div class="setup-nav" id="setup-nav" style="display:none">
          <div id="setup-status" class="settings-save-status" role="status" aria-live="polite"></div>
          <button class="settings-btn primary" id="btn-setup-next">Next</button>
        </div>

      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Panel lifecycle
// ---------------------------------------------------------------------------

function createPanel(): HTMLElement {
  const container = document.createElement("div");
  container.id = "settings-container";
  container.innerHTML = buildPanelHTML();
  document.body.appendChild(container);
  return container;
}

function setDotStatus(id: string, status: "green" | "red" | "yellow" | "off") {
  const dot = document.getElementById(id);
  if (!dot) return;
  dot.className = "status-dot";
  if (status !== "off") dot.classList.add(`status-${status}`);
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

async function loadStatus() {
  void loadProviderKeys();
  void loadAutonomy();
  void apiGet<{provider: string; model: string; available: boolean}>("/api/local-pc/status").then(status => {
    const el = document.getElementById("local-pc-status");
    if (el) el.textContent = `${status.provider} · ${status.model}: ${status.available ? "API key configured" : "API key missing"}`;
  }).catch(() => {
    const el = document.getElementById("local-pc-status");
    if (el) el.textContent = "AI configuration status unavailable.";
  });
  void loadGoogleStatus();
  try {
    const status = await apiGet<StatusResponse>("/api/settings/status");

    setDotStatus("status-codex", status.codex_installed ? "green" : "red");
    setDotStatus("status-calendar", status.calendar_accessible ? "green" : "red");
    setDotStatus("status-mail", status.mail_accessible ? "green" : "red");
    setDotStatus("status-outlook-mail", status.outlook_accessible ? "green" : "red");
    setDotStatus("status-google-mail", status.google_mail_accessible ? "green" : "red");
    setDotStatus("status-notes", status.notes_accessible ? "green" : "red");
    setDotStatus("status-server", "green");

    const serverDetail = document.getElementById("status-server-detail");
    if (serverDetail) serverDetail.textContent = `port ${status.server_port} | up ${formatUptime(status.uptime_seconds)}`;

    // API key status dots
    setDotStatus("status-openai", status.env_keys_set.openai ? "green" : "red");
    setDotStatus("status-fish", status.env_keys_set.fish_audio ? "green" : "red");

    // System info
    const memEl = document.getElementById("sysinfo-memory");
    if (memEl) memEl.textContent = String(status.memory_count);
    const taskEl = document.getElementById("sysinfo-tasks");
    if (taskEl) taskEl.textContent = String(status.task_count);
    const portEl = document.getElementById("sysinfo-port");
    if (portEl) portEl.textContent = String(status.server_port);
    const upEl = document.getElementById("sysinfo-uptime");
    if (upEl) upEl.textContent = formatUptime(status.uptime_seconds);

    return status;
  } catch (e) {
    console.error("[settings] failed to load status:", e);
    setDotStatus("status-server", "red");
    return null;
  }
}

async function loadPreferences() {
  try {
    const prefs = await apiGet<PreferencesResponse>("/api/settings/preferences");
    const nameEl = document.getElementById("input-user-name") as HTMLInputElement;
    const honEl = document.getElementById("input-honorific") as HTMLSelectElement;
    const keywordsEl = document.getElementById('input-stt-keywords') as HTMLInputElement;
    if (nameEl) nameEl.value = prefs.user_name || "";
    if (honEl) honEl.value = prefs.honorific || "sir";
    if (keywordsEl) keywordsEl.value = prefs.stt_keywords || '';
  } catch (e) {
    console.error("[settings] failed to load preferences:", e);
  }
}

function wireEvents() {
  wireAgentSettings();
  wireProviderKeys(loadStatus);
  document.addEventListener('jarvis-ai-settings-changed', () => { void loadStatus(); });
  // Escape closes the panel; Tab stays inside the modal while it is open.
  document.addEventListener("keydown", (event) => {
    if (!isOpen) return;
    // Another modal (personal memory/calendar) owns the keyboard while open.
    if (document.querySelector("dialog[open]")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeSettings();
      return;
    }
    if (event.key !== "Tab" || !panelEl) return;
    const items = Array.from(panelEl.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(element => element.offsetParent !== null);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (!panelEl.contains(document.activeElement)) {
      event.preventDefault();
      first.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  const settingsNav = document.querySelector<HTMLElement>('.settings-nav');
  settingsNav?.querySelectorAll<HTMLAnchorElement>('a[href^="#section-"]').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      const section = document.getElementById(link.hash.slice(1));
      if (!section) return;
      settingsNav.querySelectorAll('a').forEach((item) => item.removeAttribute('aria-current'));
      link.setAttribute('aria-current', 'true');
      // Move focus too: scrollIntoView alone leaves screen-reader users on the
      // nav link with no announcement of the newly shown section.
      if (!section.hasAttribute('tabindex')) section.setAttribute('tabindex', '-1');
      section.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
      section.focus({ preventScroll: true });
    });
  });
  document.getElementById("refresh-autonomy")?.addEventListener("click", loadAutonomy);
  const speechPause = document.getElementById("input-speech-pause") as HTMLSelectElement;
  speechPause.value = localStorage.getItem("jarvis_reply_delay_ms") ?? "0";
  speechPause.addEventListener("change", () => localStorage.setItem("jarvis_reply_delay_ms", speechPause.value));
  const sttAccuracy = document.getElementById('input-stt-accuracy') as HTMLSelectElement;
  sttAccuracy.value = localStorage.getItem('jarvis_stt_delay') || 'minimal';
  sttAccuracy.addEventListener('change', () => localStorage.setItem('jarvis_stt_delay', sttAccuracy.value));
  const keyStatus = document.getElementById("google-key-status")!;
  document.getElementById("google-save-key")?.addEventListener("click", async () => {
    const input = document.getElementById("google-api-key") as HTMLInputElement;
    if (!input.value.trim()) { keyStatus.textContent = "Enter your Google API key first."; return; }
    try {
      await apiPost("/api/google/api-key", { key: input.value.trim() });
      input.value = "";
      keyStatus.textContent = "API key saved securely. Not yet tested.";
    } catch (error) { keyStatus.textContent = error instanceof Error ? error.message : "Could not save key."; }
  });
  document.getElementById("google-test-key")?.addEventListener("click", async () => {
    keyStatus.textContent = "Testing YouTube Data API…";
    try {
      const result = await apiPost<{message:string}>("/api/google/test-api-key", {});
      keyStatus.textContent = result.message;
    } catch (error) { keyStatus.textContent = error instanceof Error ? error.message : "API test failed."; }
  });
  document.getElementById("google-remove-key")?.addEventListener("click", async () => {
    try { await apiPost("/api/google/api-key", { key: "" }); keyStatus.textContent = "API key removed."; }
    catch { keyStatus.textContent = "Could not remove key."; }
  });
  const googleStatus = document.getElementById("google-status")!;
  document.getElementById("google-client-file")?.addEventListener("change", async (event) => {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    try {
      if (file.size > 16000) throw new Error("Select the OAuth client JSON, maximum 16 KB.");
      const config = JSON.parse(await file.text());
      const services = Array.from(document.querySelectorAll<HTMLInputElement>('input[name="google-service"]:checked')).map(el => el.value);
      await apiPost("/api/google/config", { config, services });
      googleStatus.textContent = "OAuth client saved. Click Connect Google to sign in.";
    } catch (error) { googleStatus.textContent = error instanceof Error ? error.message : "Import failed."; }
    input.value = "";
  });
  document.getElementById("google-connect")?.addEventListener("click", async () => {
    try {
      const services = Array.from(document.querySelectorAll<HTMLInputElement>('input[name="google-service"]:checked')).map(el => el.value);
      await apiPost("/api/google/connect", { services });
      googleStatus.textContent = "Complete Google sign-in in your browser, then refresh the status here.";
    } catch (error) { googleStatus.textContent = error instanceof Error ? error.message : "Connection failed."; }
  });
  document.getElementById("google-refresh")?.addEventListener("click", loadGoogleStatus);
  document.getElementById("google-disconnect")?.addEventListener("click", async () => {
    try { await apiPost("/api/google/disconnect", {}); await loadGoogleStatus(); }
    catch (error) { googleStatus.textContent = error instanceof Error ? error.message : "Disconnect failed."; }
  });
  document.getElementById("google-setup")?.addEventListener("click", () => {
    window.open("https://developers.google.com/identity/protocols/oauth2/native-app", "_blank", "noopener");
  });
  document.getElementById("btn-open-memory")?.addEventListener("click", async () => {
    try {
      await apiPost("/api/memory/open", {});
      setSaveStatus("Memory file opened.");
    } catch {
      setSaveStatus("Could not open the memory file.", false);
    }
  });
  for (const view of ['memory', 'calendar'] as const) {
    document.getElementById('settings-custom-' + view)?.addEventListener('click', () => {
      closeSettings();
      void openPersonalPanel(view);
    });
  }
  // Close
  document.getElementById("settings-close")?.addEventListener("click", closeSettings);
  document.getElementById("settings-backdrop")?.addEventListener("click", closeSettings);

  // Save keys
  document.getElementById("btn-save-keys")?.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    const openaiKey = (document.getElementById("input-openai-key") as HTMLInputElement).value.trim();
    const fishKey = (document.getElementById("input-fish-key") as HTMLInputElement).value.trim();
    if (!openaiKey && !fishKey) {
      setSaveStatus("Enter at least one API key.", false);
      return;
    }
    button.disabled = true;
    try {
      if (openaiKey) {
        await apiPost("/api/settings/keys", { key_name: "OPENAI_API_KEY", key_value: openaiKey });
      }
      if (fishKey) {
        await apiPost("/api/settings/keys", { key_name: "FISH_API_KEY", key_value: fishKey });
      }
      (document.getElementById("input-openai-key") as HTMLInputElement).value = "";
      (document.getElementById("input-fish-key") as HTMLInputElement).value = "";
      setSaveStatus("Keys saved in Windows Credential Manager.");
      await loadStatus();
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : "Could not save the keys.", false);
    } finally {
      button.disabled = false;
    }
  });

  // Save voice ID
  document.getElementById("btn-save-voice-id")?.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    const voiceId = (document.getElementById("input-fish-voice-id") as HTMLInputElement).value.trim();
    if (!voiceId) {
      setSaveStatus("Enter a Fish voice ID.", false);
      return;
    }
    button.disabled = true;
    try {
      await apiPost("/api/settings/keys", { key_name: "FISH_VOICE_ID", key_value: voiceId });
      setSaveStatus("Voice ID saved.");
      await loadStatus();
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : "Could not save the voice ID.", false);
    } finally {
      button.disabled = false;
    }
  });

  // Test OpenAI
  document.getElementById("btn-test-openai")?.addEventListener("click", async () => {
    setDotStatus("status-openai", "yellow");
    const key = (document.getElementById("input-openai-key") as HTMLInputElement).value.trim();
    try {
      const result = await apiPost<{ valid: boolean; error?: string }>("/api/settings/test-openai", { key_value: key || undefined });
      setDotStatus("status-openai", result.valid ? "green" : "red");
    } catch {
      setDotStatus("status-openai", "red");
    }
  });

  // Test Fish
  document.getElementById("btn-test-fish")?.addEventListener("click", async () => {
    setDotStatus("status-fish", "yellow");
    const key = (document.getElementById("input-fish-key") as HTMLInputElement).value.trim();
    try {
      const result = await apiPost<{ valid: boolean; error?: string }>("/api/settings/test-fish", { key_value: key || undefined });
      setDotStatus("status-fish", result.valid ? "green" : "red");
    } catch {
      setDotStatus("status-fish", "red");
    }
  });

  // Save preferences
  const micSensitivity = document.getElementById('input-mic-sensitivity') as HTMLSelectElement;
  micSensitivity.value = localStorage.getItem('jarvis_mic_sensitivity') || 'auto';
  micSensitivity.addEventListener('change', () => localStorage.setItem('jarvis_mic_sensitivity', micSensitivity.value));

  document.getElementById("btn-save-prefs")?.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    button.disabled = true;
    try {
      if (await savePreferencesFromInputs()) await loadStatus();
    } finally {
      button.disabled = false;
    }
  });

  // Setup next button
  document.getElementById("btn-setup-next")?.addEventListener("click", advanceSetup);
}

async function loadGoogleStatus() {
  const element = document.getElementById("google-status");
  if (!element) return;
  try {
    const status = await apiGet<{ configured: boolean; connected: boolean; connecting: boolean; services: string[]; error: string; api_key_set: boolean }>("/api/google/status");
    const keyStatus = document.getElementById("google-key-status");
    if (keyStatus) keyStatus.textContent = status.api_key_set ? "API key saved. Use Test YouTube API to check access." : "No API key saved.";
    element.textContent = status.error || (status.connecting ? "Waiting for Google sign-in…" : status.connected ? `Connection saved: ${status.services.join(", ")}. Ready for voice commands.` : status.configured ? "OAuth client saved. Click Connect Google." : "Import your Desktop OAuth client JSON first.");
    if (status.configured) document.querySelectorAll<HTMLInputElement>('input[name="google-service"]').forEach(el => { el.checked = status.services.includes(el.value); });
  } catch { element.textContent = "Google connection status is unavailable."; }
}

// ---------------------------------------------------------------------------
// First-time setup wizard
// ---------------------------------------------------------------------------
function enterSetupMode() {
  setupStep = 0;

  const welcome = document.getElementById("settings-welcome");
  if (welcome) welcome.style.display = "block";

  const nav = document.getElementById("setup-nav");
  if (nav) nav.style.display = "flex";
  const sectionNav = document.querySelector<HTMLElement>(".settings-nav");
  if (sectionNav) sectionNav.style.display = "none";

  // Hide sections except API keys
  showSetupStep(0);
}

function showSetupStep(step: number) {
  document.querySelectorAll<HTMLElement>(".settings-section").forEach((section) => {
    const visible = step < 2 ? section.id === "section-api-keys" || (step === 0 && section.id === "section-agent") : section.id === "section-preferences";
    section.style.display = visible ? "" : "none";
  });

  const nextBtn = document.getElementById("btn-setup-next");
  if (nextBtn) {
    if (step === 0) nextBtn.textContent = "Next: Test Keys";
    else if (step === 1) nextBtn.textContent = "Next: Set Your Name";
    else if (step === 2) nextBtn.textContent = "Finish Setup";
    else nextBtn.style.display = "none";
  }
}

async function savePreferencesFromInputs(): Promise<boolean> {
  const user_name = (document.getElementById("input-user-name") as HTMLInputElement).value.trim();
  const honorific = (document.getElementById("input-honorific") as HTMLSelectElement).value;
  const stt_keywords = (document.getElementById('input-stt-keywords') as HTMLInputElement).value.trim();
  try {
    await apiPost("/api/settings/preferences", { user_name, honorific, stt_keywords });
    setSaveStatus("Preferences saved.");
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Could not save preferences.";
    setSaveStatus(message, false);
    return false;
  }
}

async function advanceSetup() {
  // The last wizard step shows the name fields; "Finish Setup" must persist
  // them, not silently discard what the user just typed.
  if (setupStep === 2) {
    const setupStatus = document.getElementById("setup-status");
    if (setupStatus) setupStatus.textContent = "";
    if (!(await savePreferencesFromInputs())) {
      if (setupStatus) setupStatus.textContent = "Your name could not be saved. Check the server and try again.";
      return;
    }
  }
  setupStep++;
  if (setupStep >= 3) {
    // Done — everything is saved and the wizard can close.
    const welcome = document.getElementById("settings-welcome");
    if (welcome) welcome.style.display = "none";
    const nav = document.getElementById("setup-nav");
    if (nav) nav.style.display = "none";
    const sectionNav = document.querySelector<HTMLElement>(".settings-nav");
    if (sectionNav) sectionNav.style.display = "";

    // Show all sections
    document.querySelectorAll<HTMLElement>(".settings-section").forEach((section) => { section.style.display = ""; });

    closeSettings();
    return;
  }
  showSetupStep(setupStep);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function openSettings() {
  if (isOpen) return;
  isOpen = true;
  if (closeTimer) clearTimeout(closeTimer);
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;

  if (!panelEl) {
    panelEl = createPanel();
    wireEvents();
  }

  panelEl.style.display = "block";

  // Trigger animation
  requestAnimationFrame(() => {
    panelEl!.classList.add("open");
    document.getElementById("settings-close")?.focus();
  });

  // Load data
  void loadAgentSettings();
  const status = await loadStatus();
  await loadPreferences();

  // Check for first-time setup
  const reasoning = await readLLMStatus().catch(() => null);
  if (status && reasoning && !reasoning.available) {
    enterSetupMode();
  }
}

export function closeSettings() {
  if (!panelEl || !isOpen) return;
  isOpen = false;
  panelEl.classList.remove("open");
  if (closeTimer) clearTimeout(closeTimer);
  closeTimer = setTimeout(() => {
    if (panelEl) panelEl.style.display = "none";
    if (previousFocus?.isConnected) previousFocus.focus();
    previousFocus = null;
    closeTimer = undefined;
  }, 300);
}

export function isSettingsOpen(): boolean {
  return isOpen;
}

/**
 * Check if first-time setup is needed and auto-open.
 */
export async function checkFirstTimeSetup(): Promise<boolean> {
  try {
    const status = await readLLMStatus();
    if (!status.available) {
      openSettings();
      return true;
    }
  } catch {
    // Server not ready yet, skip
  }
  return false;
}

async function loadAutonomy() {
  const el = document.getElementById('autonomy-history');
  if (!el) return;
  try {
    const data = await apiGet<{jobs: Array<{goal: string; state: string; duration_ms?:number; planning_ms?:number; action_ms?:number; steps: Array<{action:string;state:string;result?:string;duration_ms?:number}>; message?:string}>}>('/api/autonomy/jobs');
    const seconds = (milliseconds?:number) => typeof milliseconds === 'number' && Number.isFinite(milliseconds)
      ? `${(milliseconds / 1000).toFixed(1)} s` : null;
    el.textContent = data.jobs.length ? data.jobs.map(job => {
      const duration = seconds(job.duration_ms);
      const planning = seconds(job.planning_ms);
      const actions = seconds(job.action_ms);
      const timing = duration ? `\nTime: ${duration} total${planning ? ` · plan ${planning}` : ''}${actions ? ` · step work ${actions}` : ''}` : '';
      const steps = job.steps.map(step => {
        const stepTime = seconds(step.duration_ms);
        return `  ${step.state}: ${step.action}${stepTime ? ` · ${stepTime}` : ''}${step.result ? ' — ' + step.result : ''}`;
      }).join('\n');
      return `${job.state.replace(/_/g, ' ')}: ${job.goal}${timing}\n${steps}\n${job.message || ''}`;
    }).join('\n\n') : 'No autonomous tasks yet.';
  } catch { el.textContent = 'Task history unavailable.'; }
}

