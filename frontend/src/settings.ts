import { apiGet, apiPost } from './api/client';
/**
 * JARVIS — Settings window
 *
 * A centered window with a sidebar of tabs: General, AI, Voice, API keys,
 * Accounts, PC & apps, Calls and System. First-run setup lives in the
 * separate setup wizard.
 */
import { openPersonalPanel } from './personal-panel';
import { aiSettingsHTML, appsSettingsHTML, callsSettingsHTML, emailSettingsHTML, loadAgentSettings, refreshLocalAi, stopLocalAiPolling, wireAgentSettings, agentRequest } from './agent-settings';
import { DEFAULT_FISH_VOICE, keysHTML, loadProviderKeys, readLLMStatus, wireProviderKeys } from './provider-settings';
import { openSetupWizard, isSetupWizardOpen } from './setup-wizard';
import { showToast } from './toast';

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
  env_keys_set: { openai: boolean; fish_audio: boolean; fish_voice_id: boolean; user_name: string };
}

interface PreferencesResponse {
  user_name: string;
  honorific: string;
  stt_keywords: string;
}

let panelEl: HTMLElement | null = null;
let isOpen = false;
let previousFocus: HTMLElement | null = null;
let closeTimer: ReturnType<typeof setTimeout> | undefined;

const icon = (path: string) => `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">${path}</svg>`;
const TABS = [
  { id: 'general', label: 'General', icon: icon('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>') },
  { id: 'ai', label: 'AI', icon: icon('<path d="M12 3v3M12 18v3M3 12h3M18 12h3M6 6l2 2M16 16l2 2M6 18l2-2M16 8l2-2"/><circle cx="12" cy="12" r="3.5"/>') },
  { id: 'voice', label: 'Voice', icon: icon('<path d="M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v3"/>') },
  { id: 'keys', label: 'API keys', icon: icon('<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M14 9l2 2"/>') },
  { id: 'accounts', label: 'Accounts', icon: icon('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>') },
  { id: 'pc', label: 'PC & apps', icon: icon('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>') },
  { id: 'calls', label: 'Calls & alerts', icon: icon('<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2Z"/>') },
  { id: 'system', label: 'System', icon: icon('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>') },
] as const;
type TabID = typeof TABS[number]['id'];

function buildPanelHTML(): string {
  return `
    <div class="settings-backdrop" id="settings-backdrop" aria-hidden="true"></div>
    <div class="settings-panel" id="settings-panel-inner" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div class="settings-header">
        <div class="settings-heading">
          <span class="settings-eyebrow">JARVIS</span>
          <h2 id="settings-title">Settings</h2>
        </div>
        <button class="settings-close" id="settings-close" type="button" aria-label="Close settings">&times;</button>
      </div>

      <nav class="settings-nav" role="tablist" aria-label="Settings sections" aria-orientation="vertical">
        ${TABS.map(tab => `<button type="button" class="settings-tab" role="tab" id="tab-${tab.id}" data-tab="${tab.id}" aria-controls="pane-${tab.id}" aria-selected="false" tabindex="-1">${tab.icon}<span>${tab.label}</span></button>`).join('')}
      </nav>

      <div class="settings-body">
        <div class="settings-pane" id="pane-general" role="tabpanel" aria-labelledby="tab-general" hidden>
          <div class="voice-only-card" role="note">
            <span class="voice-only-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v3m-4 0h8"/></svg></span>
            <div><strong>Speak naturally. Jarvis answers with voice.</strong><p>Use the microphone on the home screen for every request. Typing is only needed here for setup.</p></div>
          </div>
          <section class="settings-section" id="section-profile">
            <h3>About you</h3>
            <div class="settings-grid two">
              <div class="settings-field">
                <label for="input-user-name">Your name</label>
                <input type="text" id="input-user-name" placeholder="Your name" autocomplete="name" maxlength="60" />
              </div>
              <div class="settings-field">
                <label for="input-honorific">Jarvis calls you</label>
                <select id="input-honorific">
                  <option value="sir">Sir</option>
                  <option value="ma'am">Ma'am</option>
                  <option value="none">By name</option>
                </select>
              </div>
            </div>
          </section>
          <section class="settings-section" id="section-jarvis">
            <h3>Your Jarvis</h3>
            <p class="google-help">Your own calendar and editable memory, saved on this PC. No account needed.</p>
            <div class="settings-actions start">
              <button type="button" class="settings-btn" id="settings-custom-memory">My memory</button>
              <button type="button" class="settings-btn" id="settings-custom-calendar">My calendar</button>
              <button type="button" class="settings-btn" id="btn-open-memory">Open MEMORY.md</button>
            </div>
          </section>
          <section class="settings-section" id="section-setup">
            <h3>Setup assistant</h3>
            <p class="google-help">Walk through the AI choice, keys and voice again.</p>
            <div class="settings-actions start"><button type="button" class="settings-btn" id="btn-run-setup">Run setup again</button></div>
          </section>
        </div>

        <div class="settings-pane" id="pane-ai" role="tabpanel" aria-labelledby="tab-ai" hidden>
          ${aiSettingsHTML}
        </div>

        <div class="settings-pane" id="pane-voice" role="tabpanel" aria-labelledby="tab-voice" hidden>
          <section class="settings-section" id="section-preferences">
            <h3>Listening</h3>
            <div class="settings-grid two">
              <div class="settings-field">
                <label for="input-mic-sensitivity">Microphone sensitivity</label>
                <select id="input-mic-sensitivity">
                  <option value="auto">Automatic</option>
                  <option value="sensitive">Quiet voice</option>
                  <option value="noisy">Noisy room</option>
                </select>
              </div>
              <div class="settings-field">
                <label for="input-stt-accuracy">Speech recognition</label>
                <select id="input-stt-accuracy">
                  <option value="minimal">Fastest — recommended</option>
                  <option value="low">Low latency</option>
                  <option value="medium">Balanced</option>
                  <option value="high">More accurate</option>
                </select>
              </div>
            </div>
            <div class="settings-field">
              <label for="input-speech-pause">Pause before replying</label>
              <select id="input-speech-pause">
                <option value="0">No extra delay</option>
                <option value="100">100 ms</option>
                <option value="200">200 ms</option>
                <option value="300">300 ms</option>
                <option value="500">500 ms</option>
                <option value="1000">1 second</option>
                <option value="2000">2 seconds — longer thinking pauses</option>
                <option value="3500">3.5 seconds — take your time</option>
                <option value="5000">5 seconds — long pauses</option>
              </select>
              <p class="google-help">Speak to interrupt Jarvis; say “stop” to cancel a task. Use headphones if Jarvis hears its own voice.</p>
            </div>
            <div class="settings-field">
              <label for="input-stt-keywords">Names and unusual terms</label>
              <input type="text" id="input-stt-keywords" maxlength="800" placeholder="Häner, Branko, project names" />
              <p class="google-help">Up to 12, separated by commas. They are sent with the audio to improve spelling; leave out anything private.</p>
            </div>
          </section>
          <section class="settings-section" id="section-speaking">
            <h3>Speaking</h3>
            <div class="settings-field">
              <label for="input-fish-voice-id">Fish Audio voice ID <a href="https://fish.audio/m/${DEFAULT_FISH_VOICE}/" target="_blank" rel="noreferrer">Listen to the Jarvis voice</a></label>
              <div class="settings-input-row">
                <input type="text" id="input-fish-voice-id" placeholder="${DEFAULT_FISH_VOICE}" spellcheck="false" maxlength="64" />
                <button type="button" class="settings-btn primary" id="btn-save-voice-id">Save</button>
              </div>
              <p class="google-help">The Fish Audio key is under API keys.</p>
            </div>
          </section>
        </div>

        <div class="settings-pane" id="pane-keys" role="tabpanel" aria-labelledby="tab-keys" hidden>
          ${keysHTML}
        </div>

        <div class="settings-pane" id="pane-accounts" role="tabpanel" aria-labelledby="tab-accounts" hidden>
          <section class="settings-section" id="section-google">
            <h3>Google account</h3>
            <p class="google-help">Connect your account to read Gmail, calendar events, Drive files, tasks and contacts. Jarvis sends mail only when you explicitly say “send”. Calendar times use Europe/Zurich.</p>
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
            <p class="google-help">Create a Desktop OAuth client in Google Cloud with the APIs you want. Tokens are stored in Windows Credential Manager.</p>
            <div class="google-buttons">
              <button type="button" id="google-connect">Connect Google</button>
              <button type="button" id="google-refresh">Refresh status</button>
              <button type="button" id="google-disconnect">Disconnect</button>
              <button type="button" id="google-setup">Setup guide</button>
            </div>
            <p id="google-status" class="status-box" role="status" aria-live="polite">Not connected.</p>
          </section>
          ${emailSettingsHTML}
          <section class="settings-section" id="section-google-key">
            <h3>Google API key (optional)</h3>
            <p class="google-help">Only for public YouTube data with YouTube Data API v3. Private Gmail, Calendar and Drive use the account connection above.</p>
            <div class="settings-input-row">
              <input id="google-api-key" type="password" placeholder="AIza…" autocomplete="new-password" spellcheck="false" maxlength="100" aria-label="Google API key">
              <button type="button" class="settings-btn primary" id="google-save-key">Save</button>
            </div>
            <div class="settings-actions start">
              <button type="button" class="settings-btn ghost" id="google-test-key">Test YouTube API</button>
              <button type="button" class="settings-btn ghost" id="google-remove-key">Remove</button>
            </div>
            <p id="google-key-status" class="status-box" role="status">No API key saved.</p>
          </section>
        </div>

        <div class="settings-pane" id="pane-pc" role="tabpanel" aria-labelledby="tab-pc" hidden>
          <section class="settings-section" id="section-voice-automation">
            <h3>PC tasks by voice</h3>
            <p id="local-pc-status" class="status-box" role="status">Checking AI configuration…</p>
            <p class="google-help">Say “Use Word to …” or “Open ChatGPT and prompt it to …”. Jarvis reads app controls, acts and checks the result. Say “task status” for progress or “stop” to cancel. Up to 12 actions, five minutes per task.</p>
            <p class="google-help">Existing drafts are kept. “Write” prepares a draft; only an explicit “send” submits. Passwords, security changes, purchases and deletion stay manual.</p>
            <div class="settings-actions start"><button type="button" class="settings-btn" id="refresh-autonomy">Refresh task history</button></div>
            <pre id="autonomy-history" class="settings-pre" role="status">No task history loaded.</pre>
          </section>
          ${appsSettingsHTML}
        </div>

        <div class="settings-pane" id="pane-calls" role="tabpanel" aria-labelledby="tab-calls" hidden>
          ${callsSettingsHTML}
        </div>

        <div class="settings-pane" id="pane-system" role="tabpanel" aria-labelledby="tab-system" hidden>
          <section class="settings-section" id="section-status">
            <h3>Connections</h3>
            <div class="status-grid">
              <div class="status-row"><span class="status-dot" id="status-server"></span><span>Jarvis server</span><span class="status-detail" id="status-server-detail"></span></div>
              <div class="status-row"><span class="status-dot" id="status-openai"></span><span>Speech recognition (OpenAI)</span></div>
              <div class="status-row"><span class="status-dot" id="status-fish"></span><span>Voice (Fish Audio)</span></div>
              <div class="status-row"><span class="status-dot" id="status-calendar"></span><span>Jarvis calendar</span></div>
              <div class="status-row"><span class="status-dot" id="status-notes"></span><span>Jarvis notes</span></div>
              <div class="status-row"><span class="status-dot" id="status-mail"></span><span>Mail actions</span></div>
              <div class="status-row"><span class="status-dot" id="status-outlook-mail"></span><span>Outlook account</span></div>
              <div class="status-row"><span class="status-dot" id="status-google-mail"></span><span>Google mail</span></div>
              <div class="status-row"><span class="status-dot" id="status-codex"></span><span>Codex desktop</span></div>
            </div>
          </section>
          <section class="settings-section" id="section-sysinfo">
            <h3>System info</h3>
            <div class="sysinfo-grid">
              <div class="sysinfo-row"><span class="sysinfo-label">Memory entries</span><span id="sysinfo-memory">--</span></div>
              <div class="sysinfo-row"><span class="sysinfo-label">Tasks</span><span id="sysinfo-tasks">--</span></div>
              <div class="sysinfo-row"><span class="sysinfo-label">Server port</span><span id="sysinfo-port">--</span></div>
              <div class="sysinfo-row"><span class="sysinfo-label">Uptime</span><span id="sysinfo-uptime">--</span></div>
            </div>
          </section>
        </div>
      </div>
      <div class="settings-toast" id="settings-toast" role="status" aria-live="polite"></div>
    </div>
  `;
}

function createPanel(): HTMLElement {
  const container = document.createElement("div");
  container.id = "settings-container";
  container.innerHTML = buildPanelHTML();
  document.body.appendChild(container);
  return container;
}

function selectTab(id: TabID, focus = false) {
  for (const tab of TABS) {
    const button = document.getElementById(`tab-${tab.id}`)!;
    const pane = document.getElementById(`pane-${tab.id}`)!;
    const on = tab.id === id;
    button.setAttribute('aria-selected', String(on));
    button.tabIndex = on ? 0 : -1;
    pane.hidden = !on;
  }
  localStorage.setItem('jarvis_settings_tab', id);
  document.querySelector('.settings-body')?.scrollTo({ top: 0 });
  if (focus) document.getElementById(`tab-${id}`)?.focus();
  if (id === 'ai') refreshLocalAi();
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
    if (el) el.textContent = `${status.provider} · ${status.model.replace(/^hf\.co\//, '')}: ${status.available ? "ready" : "not set up yet — see AI"}`;
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
    setDotStatus("status-openai", status.env_keys_set.openai ? "green" : "red");
    setDotStatus("status-fish", status.env_keys_set.fish_audio ? "green" : "red");
    const serverDetail = document.getElementById("status-server-detail");
    if (serverDetail) serverDetail.textContent = `port ${status.server_port} · up ${formatUptime(status.uptime_seconds)}`;
    const set = (id: string, value: string) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    set("sysinfo-memory", String(status.memory_count));
    set("sysinfo-tasks", String(status.task_count));
    set("sysinfo-port", String(status.server_port));
    set("sysinfo-uptime", formatUptime(status.uptime_seconds));
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
    (document.getElementById("input-user-name") as HTMLInputElement).value = prefs.user_name || "";
    (document.getElementById("input-honorific") as HTMLSelectElement).value = prefs.honorific || "sir";
    (document.getElementById('input-stt-keywords') as HTMLInputElement).value = prefs.stt_keywords || '';
  } catch (e) {
    console.error("[settings] failed to load preferences:", e);
  }
}

async function savePreferencesFromInputs(): Promise<boolean> {
  const user_name = (document.getElementById("input-user-name") as HTMLInputElement).value.trim();
  const honorific = (document.getElementById("input-honorific") as HTMLSelectElement).value;
  const stt_keywords = (document.getElementById('input-stt-keywords') as HTMLInputElement).value.trim();
  try {
    await apiPost("/api/settings/preferences", { user_name, honorific, stt_keywords });
    showToast("Saved.");
    return true;
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Could not save preferences.", false);
    return false;
  }
}

function trapFocus(event: KeyboardEvent) {
  if (event.key !== "Tab" || !panelEl) return;
  const items = Array.from(panelEl.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
  )).filter(element => element.offsetParent !== null);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (!panelEl.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
  else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

function wireEvents() {
  wireAgentSettings();
  wireProviderKeys(loadStatus);
  document.addEventListener('jarvis-ai-settings-changed', () => { if (isOpen) void loadStatus(); });
  document.addEventListener("keydown", (event) => {
    if (!isOpen || isSetupWizardOpen()) return;
    // Another modal (personal memory/calendar) owns the keyboard while open.
    if (document.querySelector("dialog[open]")) return;
    if (event.key === "Escape") { event.preventDefault(); closeSettings(); return; }
    trapFocus(event);
  });

  // Tabs: click, and arrow keys within the tab list.
  const nav = document.querySelector<HTMLElement>('.settings-nav')!;
  nav.addEventListener('click', event => {
    const tab = (event.target as HTMLElement).closest<HTMLElement>('[data-tab]');
    if (tab) selectTab(tab.dataset.tab as TabID);
  });
  nav.addEventListener('keydown', event => {
    const index = TABS.findIndex(tab => tab.id === (document.activeElement as HTMLElement)?.dataset?.tab);
    if (index < 0) return;
    const move = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
    if (move) { event.preventDefault(); selectTab(TABS[(index + move + TABS.length) % TABS.length].id, true); }
    if (event.key === 'Home') { event.preventDefault(); selectTab(TABS[0].id, true); }
    if (event.key === 'End') { event.preventDefault(); selectTab(TABS[TABS.length - 1].id, true); }
  });

  document.getElementById("refresh-autonomy")?.addEventListener("click", loadAutonomy);
  const speechPause = document.getElementById("input-speech-pause") as HTMLSelectElement;
  speechPause.value = localStorage.getItem("jarvis_reply_delay_ms") ?? "0";
  speechPause.addEventListener("change", () => { localStorage.setItem("jarvis_reply_delay_ms", speechPause.value); showToast("Saved."); });
  const sttAccuracy = document.getElementById('input-stt-accuracy') as HTMLSelectElement;
  sttAccuracy.value = localStorage.getItem('jarvis_stt_delay') || 'minimal';
  sttAccuracy.addEventListener('change', () => { localStorage.setItem('jarvis_stt_delay', sttAccuracy.value); showToast("Saved."); });
  const micSensitivity = document.getElementById('input-mic-sensitivity') as HTMLSelectElement;
  micSensitivity.value = localStorage.getItem('jarvis_mic_sensitivity') || 'auto';
  micSensitivity.addEventListener('change', () => { localStorage.setItem('jarvis_mic_sensitivity', micSensitivity.value); showToast("Saved."); });
  for (const id of ['input-user-name', 'input-honorific', 'input-stt-keywords']) {
    document.getElementById(id)?.addEventListener('change', () => { void savePreferencesFromInputs(); });
  }

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
    try { await apiPost("/api/memory/open", {}); showToast("Memory file opened."); }
    catch { showToast("Could not open the memory file.", false); }
  });
  for (const view of ['memory', 'calendar'] as const) {
    document.getElementById('settings-custom-' + view)?.addEventListener('click', () => {
      closeSettings();
      void openPersonalPanel(view);
    });
  }
  document.getElementById("btn-run-setup")?.addEventListener("click", () => {
    closeSettings();
    void openSetupWizard();
  });
  document.getElementById("settings-close")?.addEventListener("click", closeSettings);
  document.getElementById("settings-backdrop")?.addEventListener("click", closeSettings);

  document.getElementById("btn-save-voice-id")?.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    const field = document.getElementById("input-fish-voice-id") as HTMLInputElement;
    const voiceId = field.value.trim();
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(voiceId)) { showToast("Enter a valid Fish Audio voice ID.", false); return; }
    button.disabled = true;
    try {
      await apiPost("/api/settings/keys", { key_name: "FISH_VOICE_ID", key_value: voiceId });
      showToast("Voice saved.");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Could not save the voice ID.", false);
    } finally { button.disabled = false; }
  });
}

async function loadGoogleStatus() {
  const element = document.getElementById("google-status");
  if (!element) return;
  try {
    const status = await apiGet<{ configured: boolean; connected: boolean; connecting: boolean; services: string[]; error: string; api_key_set: boolean }>("/api/google/status");
    const keyStatus = document.getElementById("google-key-status");
    if (keyStatus) keyStatus.textContent = status.api_key_set ? "API key saved. Use Test YouTube API to check access." : "No API key saved.";
    element.textContent = status.error || (status.connecting ? "Waiting for Google sign-in…" : status.connected ? `Connected: ${status.services.join(", ")}. Ready for voice commands.` : status.configured ? "OAuth client saved. Click Connect Google." : "Import your Desktop OAuth client JSON first.");
    if (status.configured) document.querySelectorAll<HTMLInputElement>('input[name="google-service"]').forEach(el => { el.checked = status.services.includes(el.value); });
  } catch { element.textContent = "Google connection status is unavailable."; }
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

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function openSettings(tab?: TabID) {
  if (isOpen) { if (tab) selectTab(tab); return; }
  isOpen = true;
  if (closeTimer) clearTimeout(closeTimer);
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;

  if (!panelEl) {
    panelEl = createPanel();
    wireEvents();
  }
  panelEl.style.display = "block";
  const remembered = localStorage.getItem('jarvis_settings_tab') as TabID | null;
  selectTab(tab || (remembered && TABS.some(t => t.id === remembered) ? remembered : 'general'));
  requestAnimationFrame(() => {
    panelEl!.classList.add("open");
    document.querySelector<HTMLElement>('.settings-tab[aria-selected="true"]')?.focus();
  });

  void loadAgentSettings();
  await loadStatus();
  await loadPreferences();
}

export function closeSettings() {
  if (!panelEl || !isOpen) return;
  isOpen = false;
  stopLocalAiPolling();
  panelEl.classList.remove("open");
  if (closeTimer) clearTimeout(closeTimer);
  closeTimer = setTimeout(() => {
    if (panelEl) panelEl.style.display = "none";
    if (previousFocus?.isConnected) previousFocus.focus();
    previousFocus = null;
    closeTimer = undefined;
  }, 260);
}

export function isSettingsOpen(): boolean {
  return isOpen;
}

/** Opens the setup wizard on first start, until the AI is configured or setup was finished. */
export async function checkFirstTimeSetup(): Promise<boolean> {
  try {
    const [llm, agent] = await Promise.all([readLLMStatus(), agentRequest('settings') as Promise<{ setup_done?: boolean }>]);
    if (!llm.available && !agent.setup_done) {
      void openSetupWizard();
      return true;
    }
  } catch {
    // Server not ready yet, skip
  }
  return false;
}
