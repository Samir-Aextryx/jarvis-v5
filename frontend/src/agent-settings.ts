/** AI choice (cloud or local), apps, email, calls and automation. Changes save automatically. */
import { localAiHTML, mountLocalAi } from './local-ai';
import { showToast } from './toast';

type AgentPrefs = {work_apps:string[]; automation:boolean; activity_log:boolean; large_model:string; llm_provider:string; gemini_model:string; grok_model:string; ollama_model:string; local_model:string; reasoning_effort:string; default_email:string; setup_done:boolean};

export const cloudProviders = [
  { id: 'openai', name: 'OpenAI', detail: 'GPT models · also used for speech recognition' },
  { id: 'gemini', name: 'Google Gemini', detail: 'Fast and affordable' },
  { id: 'grok', name: 'xAI Grok', detail: 'Grok models' },
  { id: 'ollama', name: 'Ollama Cloud', detail: 'GPT-OSS 120B, the fastest replies' },
] as const;

export const aiSettingsHTML = `
<section class="settings-section" id="section-agent">
  <h3>How Jarvis thinks</h3>
  <p class="google-help">Choose a cloud AI with your own API key, or run a model on this PC. You can switch at any time.</p>
  <div class="mode-cards" role="radiogroup" aria-label="AI mode">
    <button type="button" class="mode-card" data-mode="cloud" role="radio" aria-checked="false">
      <span class="mode-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M7 18h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.1 9.2 4.5 4.5 0 0 0 7 18Z"/></svg></span>
      <strong>Cloud AI</strong><small>OpenAI, Gemini, Grok or Ollama Cloud with your API key. Fastest and smartest.</small>
    </button>
    <button type="button" class="mode-card" data-mode="local" role="radio" aria-checked="false">
      <span class="mode-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></span>
      <strong>Local AI</strong><small>Runs on this PC with models from Hugging Face. Private, no API costs.</small>
    </button>
  </div>
  <div class="mode-pane" data-mode-pane="cloud">
    <div class="settings-field">
      <label for="agent-provider">Cloud provider</label>
      <select id="agent-provider">${cloudProviders.map(p => `<option value="${p.id}">${p.name}</option>`).join('')}</select>
      <p class="google-help">Add the provider's key under API keys. Only the selected provider receives your requests.</p>
    </div>
    <details class="settings-details">
      <summary>Model IDs and reasoning</summary>
      <label for="agent-model">OpenAI model</label><input id="agent-model" type="text" maxlength="80" spellcheck="false">
      <label for="agent-gemini-model">Gemini model</label><input id="agent-gemini-model" type="text" maxlength="100" spellcheck="false">
      <label for="agent-grok-model">Grok model</label><input id="agent-grok-model" type="text" maxlength="100" spellcheck="false">
      <label for="agent-ollama-model">Ollama Cloud model</label><input id="agent-ollama-model" type="text" maxlength="151" spellcheck="false">
    </details>
  </div>
  <div class="mode-pane" data-mode-pane="local" id="settings-local-ai">${localAiHTML()}</div>
  <div class="settings-field reasoning-field">
    <label for="agent-reasoning">Thinking effort</label>
    <select id="agent-reasoning"><option value="none">None — fastest</option><option value="low">Low — recommended</option><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">Extra high</option><option value="max">Maximum</option></select>
    <p class="google-help">Higher effort can improve hard tasks but makes spoken replies slower. Local models without a thinking mode ignore it.</p>
  </div>
</section>`;

export const appsSettingsHTML = `
<section class="settings-section" id="section-apps">
  <h3>Apps and automation</h3>
  <label for="agent-apps">“Open everything” apps — one installed app per line</label>
  <textarea id="agent-apps" rows="5" spellcheck="false"></textarea>
  <label class="toggle-row"><input id="agent-automation" type="checkbox"><span>Run PC tasks automatically</span></label>
  <label class="toggle-row"><input id="agent-log" type="checkbox"><span>Keep local activity counts (never message content)</span></label>
  <div class="settings-actions start">
    <button type="button" class="settings-btn" id="agent-logs">Show activity</button>
    <button type="button" class="settings-btn" id="agent-clear">Clear activity</button>
  </div>
  <pre id="agent-activity"></pre>
</section>`;

export const emailSettingsHTML = `
<section class="settings-section" id="section-email">
  <h3>Email and calendar</h3>
  <div class="settings-field">
    <label for="agent-email">Default email account</label>
    <select id="agent-email"><option>Gmail</option><option>Outlook</option></select>
    <p class="google-help">Gmail needs the Google connection above. Outlook uses the Classic Outlook app on this PC. Jarvis uses its own calendar unless you say “Google”.</p>
  </div>
</section>`;

export const callsSettingsHTML = `
<section class="settings-section" id="section-calls">
  <h3>WhatsApp calls and urgent mail</h3>
  <p class="google-help">While Jarvis runs, it watches new mail headers and shows an alert for urgent messages. Automatic WhatsApp calls need a verified two-way audio bridge.</p>
  <div class="settings-field">
    <label for="boss-phone">My WhatsApp contact number (Boss)</label>
    <div class="settings-input-row">
      <input id="boss-phone" type="tel" autocomplete="off" placeholder="Swiss mobile number">
      <button type="button" class="settings-btn" id="boss-phone-save">Save securely</button>
    </div>
  </div>
  <p id="whatsapp-call-status" class="status-box" role="status">Checking call readiness…</p>
</section>`;

async function request(path:string, body?:unknown) {
  const response = await fetch('/api/agent/'+path, {method:body===undefined?'GET':'POST',
    headers:{'Content-Type':'application/json','Authorization':'Bearer '+(localStorage.getItem('jarvis_auth_token')||'')},
    ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const result = await response.json();
  if(!response.ok) throw new Error((result.code ? '['+result.code+'] ' : '')+(result.error||'The setting could not be updated.'));
  return result;
}
export const agentRequest = request;

function input(id:string) {return document.getElementById(id) as HTMLInputElement;}
const providerName = () => cloudProviders.find(p => p.id === input('agent-provider').value)?.name || 'the cloud AI';
let prefs: AgentPrefs | null = null;
let localManager: ReturnType<typeof mountLocalAi> | null = null;

function setMode(mode: 'cloud' | 'local') {
  document.querySelectorAll<HTMLElement>('#section-agent .mode-card').forEach(card => {
    const on = card.dataset.mode === mode;
    card.classList.toggle('selected', on);
    card.setAttribute('aria-checked', String(on));
  });
  document.querySelectorAll<HTMLElement>('#section-agent [data-mode-pane]').forEach(pane => { pane.hidden = pane.dataset.modePane !== mode; });
  if (mode === 'local') void localManager?.refresh();
}

function collect(): Partial<AgentPrefs> {
  return {
    work_apps: input('agent-apps').value.split('\n').map(x => x.trim()).filter(Boolean),
    automation: input('agent-automation').checked, activity_log: input('agent-log').checked,
    large_model: input('agent-model').value.trim(), gemini_model: input('agent-gemini-model').value.trim(),
    grok_model: input('agent-grok-model').value.trim(), ollama_model: input('agent-ollama-model').value.trim(),
    reasoning_effort: input('agent-reasoning').value, default_email: input('agent-email').value,
  };
}

async function save(extra: Partial<AgentPrefs> = {}, note = 'Saved.') {
  try {
    prefs = await request('settings', { ...collect(), ...extra }) as AgentPrefs;
    showToast(note);
    document.dispatchEvent(new Event('jarvis-ai-settings-changed'));
  } catch (error) {
    showToast(error instanceof Error ? error.message : 'The setting could not be saved.', false);
  }
}

export async function loadAgentSettings() {
  try {
    prefs = await request('settings') as AgentPrefs;
    input('agent-apps').value = prefs.work_apps.join('\n'); input('agent-model').value = prefs.large_model;
    input('agent-reasoning').value = prefs.reasoning_effort;
    input('agent-provider').value = prefs.llm_provider === 'local' ? 'openai' : prefs.llm_provider;
    input('agent-gemini-model').value = prefs.gemini_model; input('agent-grok-model').value = prefs.grok_model;
    input('agent-ollama-model').value = prefs.ollama_model; input('agent-email').value = prefs.default_email;
    input('agent-automation').checked = prefs.automation; input('agent-log').checked = prefs.activity_log;
    setMode(prefs.llm_provider === 'local' ? 'local' : 'cloud');
  } catch { showToast('Could not load the AI settings.', false); }
  try {
    const call = await request('whatsapp-call/status') as {contact_saved:boolean;whatsapp_beta_installed:boolean;automatic_call_ready:boolean;reason:string};
    document.getElementById('whatsapp-call-status')!.textContent =
      `${call.contact_saved ? 'Boss contact saved' : 'Boss contact missing'} · ${call.whatsapp_beta_installed ? 'WhatsApp Beta installed' : 'WhatsApp Beta missing'} · ${call.automatic_call_ready ? 'Calls ready' : call.reason}`;
  } catch { document.getElementById('whatsapp-call-status')!.textContent = 'Call readiness could not be checked.'; }
}

export function wireAgentSettings() {
  const local = document.getElementById('settings-local-ai')!;
  localManager = mountLocalAi(local, status => {
    // Selecting a downloaded model switches Jarvis to Local AI on the server.
    if (status.active && prefs && prefs.llm_provider !== 'local') { prefs.llm_provider = 'local'; setMode('local'); }
  });
  document.querySelectorAll<HTMLButtonElement>('#section-agent .mode-card').forEach(card => card.addEventListener('click', async () => {
    const mode = card.dataset.mode as 'cloud' | 'local';
    setMode(mode);
    if (mode === 'cloud') {
      await save({ llm_provider: input('agent-provider').value }, `Jarvis now uses ${providerName()}.`);
    } else {
      const status = await localManager!.refresh().then(() => localManager!.current());
      if (status?.selected) await save({ llm_provider: 'local' }, `Jarvis now uses the local model ${status.selected.replace(/^hf\.co\//, '')}.`);
      else showToast('Download a model below and select Use to switch Jarvis to local AI.');
    }
  }));
  input('agent-provider').addEventListener('change', () => save({ llm_provider: input('agent-provider').value }, `Jarvis now uses ${providerName()}.`));
  for (const id of ['agent-model', 'agent-gemini-model', 'agent-grok-model', 'agent-ollama-model', 'agent-reasoning', 'agent-email', 'agent-automation', 'agent-log', 'agent-apps']) {
    input(id).addEventListener('change', () => save());
  }
  document.getElementById('boss-phone-save')!.addEventListener('click', async () => {
    const field = input('boss-phone');
    const status = document.getElementById('whatsapp-call-status')!;
    try {
      if (!field.value.trim()) throw new Error('Enter your Swiss mobile number first.');
      await request('whatsapp-call/contact', {number:field.value.trim()});
      field.value = '';
      status.textContent = 'Boss contact saved in Windows Credential Manager. Two-way WhatsApp audio is still unavailable.';
    } catch (error) { status.textContent = error instanceof Error ? error.message : 'Could not save the contact.'; }
  });
  const action=(id:string, fn:()=>Promise<void>)=>document.getElementById(id)!.addEventListener('click',async()=>{
    const button=document.getElementById(id) as HTMLButtonElement; button.disabled=true;
    try {await fn();} catch(e){showToast(e instanceof Error?e.message:'Request failed.', false);} finally{button.disabled=false;}
  });
  action('agent-logs',async()=>{const s=await request('activity');document.getElementById('agent-activity')!.textContent=s.items.map((r:{time:string;tool:string;success:boolean;count:number})=>`${r.time} ${r.tool} ${r.success?'OK':'Not completed'} ${r.count}`).join('\n')||'No activity yet.';});
  action('agent-clear',async()=>{await request('activity/clear',{});document.getElementById('agent-activity')!.textContent='Activity log cleared.';});
}

export function refreshLocalAi() { void localManager?.refresh(); }
export function stopLocalAiPolling() { localManager?.destroy(); }
