/**
 * First-run setup: name, cloud or local AI (with Hugging Face downloads),
 * the voice keys and a summary. Every step can be changed later in Settings.
 */
import { apiGet, apiPost } from './api/client';
import { agentRequest, cloudProviders } from './agent-settings';
import { localAiHTML, mountLocalAi } from './local-ai';
import { DEFAULT_FISH_VOICE, readLLMStatus, saveKey, savedKeys, testKey, type KeyID } from './provider-settings';

const STEPS = ['Welcome', 'AI', 'Voice & keys', 'Done'] as const;
const EXTRA_KEYS = cloudProviders.filter(p => p.id !== 'openai');
const keyLinks: Record<string, string> = {
  openai: 'https://platform.openai.com/api-keys', gemini: 'https://aistudio.google.com/apikey',
  grok: 'https://console.x.ai/', ollama: 'https://ollama.com/settings/keys', fish: 'https://fish.audio/app/api-keys/',
};

let root: HTMLElement | null = null;
let step = 0;
let mode: 'cloud' | 'local' = 'cloud';
let provider: string = 'openai';
let saved: Record<KeyID, boolean> = { openai: false, fish: false, gemini: false, grok: false, ollama: false };
let local: ReturnType<typeof mountLocalAi> | null = null;
let previousFocus: HTMLElement | null = null;
// First start: every step must be completed, and the screen cannot be closed.
let required = false;

const html = () => `
  <div class="wizard-backdrop"></div>
  <div class="wizard-card" role="dialog" aria-modal="true" aria-labelledby="wizard-title">
    <header class="wizard-header">
      <ol class="wizard-progress">${STEPS.map((name, i) => `<li data-index="${i}"><span>${i + 1}</span>${name}</li>`).join('')}</ol>
      <button type="button" class="wizard-close" data-action="later" aria-label="Finish setup later">&times;</button>
    </header>

    <section class="wizard-step" data-step="0">
      <div class="wizard-hero" aria-hidden="true"><span></span></div>
      <p class="wizard-eyebrow">SETUP · ABOUT TWO MINUTES</p>
      <h2 id="wizard-title">Welcome to Jarvis</h2>
      <p class="wizard-lead">Your voice assistant for Windows. Let’s choose how Jarvis thinks, how it hears you and how it speaks.</p>
      <div class="wizard-fields two">
        <label>Your name<input id="wizard-name" type="text" autocomplete="name" maxlength="60" placeholder="e.g. Alex"></label>
        <label>Jarvis calls you<select id="wizard-honorific"><option value="sir">Sir</option><option value="ma'am">Ma'am</option><option value="none">By name</option></select></label>
      </div>
    </section>

    <section class="wizard-step" data-step="1" hidden>
      <h2>How should Jarvis think?</h2>
      <p class="wizard-lead">Use a cloud AI with your own API key, or run an AI model on this PC.</p>
      <div class="mode-cards" role="radiogroup" aria-label="AI mode">
        <button type="button" class="mode-card" data-wizard-mode="cloud" role="radio">
          <span class="mode-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M7 18h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.1 9.2 4.5 4.5 0 0 0 7 18Z"/></svg></span>
          <strong>Cloud AI with API key</strong><small>Smartest and fastest. You pay the provider per use.</small>
        </button>
        <button type="button" class="mode-card" data-wizard-mode="local" role="radio">
          <span class="mode-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></span>
          <strong>Local AI on this PC</strong><small>Private and free. Models from Hugging Face; needs a capable PC.</small>
        </button>
      </div>
      <div class="wizard-pane" data-wizard-pane="cloud">
        <div class="provider-list" role="radiogroup" aria-label="Cloud provider">
          ${cloudProviders.map(p => `<button type="button" class="provider-option" data-provider="${p.id}" role="radio"><strong>${p.name}</strong><small>${p.detail}</small><span class="provider-saved" hidden>Key saved</span></button>`).join('')}
        </div>
        <label class="wizard-key">
          <span><b id="wizard-provider-name">OpenAI</b> API key <a id="wizard-provider-link" href="${keyLinks.openai}" target="_blank" rel="noreferrer">Get a key</a></span>
          <input id="wizard-provider-key" type="password" autocomplete="new-password" spellcheck="false" maxlength="2048" placeholder="Paste your key">
        </label>
      </div>
      <div class="wizard-pane" data-wizard-pane="local" hidden id="wizard-local-ai">${localAiHTML()}</div>
    </section>

    <section class="wizard-step" data-step="2" hidden>
      <h2>Hearing, voice and keys</h2>
      <p class="wizard-lead">Jarvis listens with OpenAI speech recognition and speaks with a Fish Audio voice.</p>
      <label class="wizard-key">
        <span><b>OpenAI</b> key for speech recognition <a href="${keyLinks.openai}" target="_blank" rel="noreferrer">Get a key</a></span>
        <input id="wizard-openai-key" type="password" autocomplete="new-password" spellcheck="false" maxlength="2048" placeholder="sk-…">
        <small id="wizard-openai-note"></small>
      </label>
      <label class="wizard-key">
        <span><b>Fish Audio</b> key for Jarvis’s voice <a href="${keyLinks.fish}" target="_blank" rel="noreferrer">Get a key</a></span>
        <input id="wizard-fish-key" type="password" autocomplete="new-password" spellcheck="false" maxlength="2048" placeholder="Fish Audio key">
        <small id="wizard-fish-note"></small>
      </label>
      <label class="wizard-key">
        <span><b>Voice ID</b> <a href="https://fish.audio/m/${DEFAULT_FISH_VOICE}/" target="_blank" rel="noreferrer">Listen to the Jarvis voice</a></span>
        <input id="wizard-voice-id" type="text" spellcheck="false" maxlength="64" placeholder="${DEFAULT_FISH_VOICE}">
        <small>Leave empty for the Jarvis voice, or paste the ID of any Fish Audio voice.</small>
      </label>
      <details class="settings-details wizard-more">
        <summary>More API keys (optional) — Gemini, Grok, Ollama Cloud</summary>
        <p class="wizard-key-help">Only needed if you want to switch to these AIs later. Each key is checked before it is saved.</p>
        ${EXTRA_KEYS.map(p => `<label class="wizard-key">
          <span><b>${p.name}</b> <a href="${keyLinks[p.id]}" target="_blank" rel="noreferrer">Get a key</a></span>
          <input id="wizard-extra-${p.id}" type="password" autocomplete="new-password" spellcheck="false" maxlength="2048" placeholder="Paste your key">
        </label>`).join('')}
      </details>
    </section>

    <section class="wizard-step" data-step="3" hidden>
      <h2>Jarvis is ready</h2>
      <p class="wizard-lead">Here is your setup. You can change everything later in Settings.</p>
      <ul class="wizard-summary" id="wizard-summary"></ul>
      <p class="wizard-tip">Tap the microphone on the home screen and speak. Say “stop” at any time to interrupt.</p>
    </section>

    <footer class="wizard-nav">
      <button type="button" class="settings-btn ghost" data-action="back">Back</button>
      <p class="wizard-status" id="wizard-status" role="status" aria-live="polite"></p>
      <button type="button" class="settings-btn ghost" data-action="skip">Skip for now</button>
      <button type="button" class="settings-btn primary" data-action="next">Continue</button>
    </footer>
  </div>`;

const $ = <T extends HTMLElement>(selector: string) => root!.querySelector<T>(selector)!;
const status = (text: string, error = false) => { const el = $('#wizard-status'); el.textContent = text; el.classList.toggle('error', error); };

function setMode(next: 'cloud' | 'local') {
  mode = next;
  root!.querySelectorAll<HTMLElement>('[data-wizard-mode]').forEach(card => {
    const on = card.dataset.wizardMode === next;
    card.classList.toggle('selected', on);
    card.setAttribute('aria-checked', String(on));
  });
  root!.querySelectorAll<HTMLElement>('[data-wizard-pane]').forEach(pane => { pane.hidden = pane.dataset.wizardPane !== next; });
  if (next === 'local') void local?.refresh();
  status('');
}

function setProvider(next: string) {
  provider = next;
  root!.querySelectorAll<HTMLElement>('.provider-option').forEach(option => {
    const on = option.dataset.provider === next;
    option.classList.toggle('selected', on);
    option.setAttribute('aria-checked', String(on));
    (option.querySelector('.provider-saved') as HTMLElement).hidden = !saved[option.dataset.provider as KeyID];
  });
  const info = cloudProviders.find(p => p.id === next)!;
  $('#wizard-provider-name').textContent = info.name;
  ($('#wizard-provider-link') as HTMLAnchorElement).href = keyLinks[next];
  ($('#wizard-provider-key') as HTMLInputElement).placeholder = saved[next as KeyID] ? 'Key saved — paste a new one to replace it' : 'Paste your key';
  status('');
}

function show(next: number) {
  step = next;
  root!.querySelectorAll<HTMLElement>('.wizard-step').forEach(section => { section.hidden = Number(section.dataset.step) !== step; });
  root!.querySelectorAll<HTMLElement>('.wizard-progress li').forEach(item => {
    const index = Number(item.dataset.index);
    item.classList.toggle('done', index < step);
    item.classList.toggle('current', index === step);
  });
  $('[data-action="back"]').style.visibility = step === 0 || step === 3 ? 'hidden' : 'visible';
  $('[data-action="skip"]').hidden = required || !(step === 1 || step === 2);
  $('[data-action="later"]').hidden = required;
  $('[data-action="next"]').textContent = step === 3 ? 'Start Jarvis' : 'Continue';
  status('');
  if (step === 2) {
    const openaiReady = saved.openai;
    $('#wizard-openai-note').textContent = openaiReady ? 'Saved. Leave empty to keep it.' : 'Without this key Jarvis cannot hear you.';
    $('#wizard-fish-note').textContent = saved.fish ? 'Saved. Leave empty to keep it.' : 'Without this key Jarvis answers silently.';
    for (const extra of EXTRA_KEYS) $<HTMLInputElement>(`#wizard-extra-${extra.id}`).placeholder = saved[extra.id as KeyID] ? 'Key saved — paste a new one to replace it' : 'Paste your key';
  }
  if (step === 3) void renderSummary();
  root!.querySelector<HTMLElement>(`.wizard-step[data-step="${step}"] h2`)?.focus();
}

async function renderSummary() {
  const list = $('#wizard-summary');
  list.replaceChildren();
  const [keys, llm] = await Promise.all([savedKeys().catch(() => saved), readLLMStatus().catch(() => null)]);
  const brain = llm?.providers.find(p => p.id === llm.provider);
  const rows: Array<[boolean, string, string]> = [
    [!!llm?.available, 'AI', llm?.available ? `${brain?.name || llm.provider} · ${(llm.model || '').replace(/^hf\.co\//, '')}` : 'Not set up — choose it in Settings, AI'],
    [keys.openai, 'Hearing', keys.openai ? 'OpenAI speech recognition' : 'Needs an OpenAI key'],
    [keys.fish, 'Voice', keys.fish ? 'Fish Audio' : 'Needs a Fish Audio key'],
  ];
  for (const [ok, title, detail] of rows) {
    const item = document.createElement('li');
    item.className = ok ? 'ok' : 'missing';
    const strong = document.createElement('strong'); strong.textContent = title;
    const span = document.createElement('span'); span.textContent = detail;
    item.append(strong, span);
    list.append(item);
  }
}

async function finishCloud(): Promise<boolean> {
  const field = $('#wizard-provider-key') as HTMLInputElement;
  const value = field.value.trim();
  const name = cloudProviders.find(p => p.id === provider)!.name;
  if (value) {
    status(`Checking your ${name} key…`);
    const result = await testKey(provider as KeyID, value);
    if (!result.valid) { status(result.error || `${name} did not accept this key.`, true); return false; }
    await saveKey(provider as KeyID, value);
    saved[provider as KeyID] = true;
    field.value = '';
  } else if (!saved[provider as KeyID]) {
    status(`Paste your ${name} key, or choose Local AI.`, true);
    return false;
  }
  await agentRequest('settings', { llm_provider: provider });
  return true;
}

async function finishLocal(): Promise<boolean> {
  await local?.refresh();
  const current = local?.current();
  if (current?.pull.state === 'downloading') { status('Wait until the download is finished.', true); return false; }
  if (!current?.selected || !current.models.length) { status(required ? 'Download a model and select Use.' : 'Download a model and select Use, or skip for now.', true); return false; }
  await agentRequest('settings', { llm_provider: 'local' });
  return true;
}

async function finishVoice(): Promise<boolean> {
  const openai = ($('#wizard-openai-key') as HTMLInputElement).value.trim();
  const fish = ($('#wizard-fish-key') as HTMLInputElement).value.trim();
  const voice = ($('#wizard-voice-id') as HTMLInputElement).value.trim();
  if (voice && !/^[A-Za-z0-9_-]{8,64}$/.test(voice)) { status('Enter a valid Fish Audio voice ID.', true); return false; }
  if (openai) {
    status('Checking your OpenAI key…');
    const result = await testKey('openai', openai);
    if (!result.valid) { status(result.error || 'OpenAI did not accept this key.', true); return false; }
    await saveKey('openai', openai); saved.openai = true;
  }
  if (fish) {
    status('Checking your Fish Audio key…');
    const result = await testKey('fish', fish);
    if (!result.valid) { status(result.error || 'Fish Audio did not accept this key.', true); return false; }
    await saveKey('fish', fish); saved.fish = true;
  }
  if (voice) await apiPost('/api/settings/keys', { key_name: 'FISH_VOICE_ID', key_value: voice });
  if (required && !saved.openai) { status('Jarvis needs an OpenAI key to hear you.', true); $('#wizard-openai-key').focus(); return false; }
  if (required && !saved.fish) { status('Jarvis needs a Fish Audio key to speak.', true); $('#wizard-fish-key').focus(); return false; }
  for (const extra of EXTRA_KEYS) {
    const field = $<HTMLInputElement>(`#wizard-extra-${extra.id}`);
    const value = field.value.trim();
    if (!value) continue;
    status(`Checking your ${extra.name} key…`);
    const result = await testKey(extra.id as KeyID, value);
    if (!result.valid) { status(result.error || `${extra.name} did not accept this key.`, true); field.focus(); return false; }
    await saveKey(extra.id as KeyID, value); saved[extra.id as KeyID] = true; field.value = '';
  }
  return true;
}

async function next(skip = false) {
  const button = $<HTMLButtonElement>('[data-action="next"]');
  button.disabled = true;
  try {
    if (step === 0) {
      const user_name = ($('#wizard-name') as HTMLInputElement).value.trim();
      if (required && !user_name) { status('Enter your name.', true); $('#wizard-name').focus(); return; }
      const honorific = ($('#wizard-honorific') as HTMLSelectElement).value;
      const prefs = await apiGet<{ stt_keywords: string }>('/api/settings/preferences').catch(() => ({ stt_keywords: '' }));
      await apiPost('/api/settings/preferences', { user_name, honorific, stt_keywords: prefs.stt_keywords || '' });
    } else if (step === 1 && !skip) {
      if (!(mode === 'cloud' ? await finishCloud() : await finishLocal())) return;
    } else if (step === 2 && !skip) {
      if (!(await finishVoice())) return;
    } else if (step === 3) {
      await agentRequest('settings', { setup_done: true });
      document.dispatchEvent(new Event('jarvis-ai-settings-changed'));
      closeSetupWizard();
      return;
    }
    show(step + 1);
  } catch (error) {
    status(error instanceof Error ? error.message : 'Something went wrong. Try again.', true);
  } finally {
    button.disabled = false;
  }
}

function build() {
  root = document.createElement('div');
  root.id = 'setup-wizard';
  root.innerHTML = html();
  document.body.appendChild(root);
  root.querySelectorAll<HTMLElement>('.wizard-step h2').forEach(h => h.setAttribute('tabindex', '-1'));
  local = mountLocalAi($('#wizard-local-ai'));
  root.querySelectorAll<HTMLElement>('[data-wizard-mode]').forEach(card => card.addEventListener('click', () => setMode(card.dataset.wizardMode as 'cloud' | 'local')));
  root.querySelectorAll<HTMLElement>('.provider-option').forEach(option => option.addEventListener('click', () => setProvider(option.dataset.provider!)));
  $('[data-action="next"]').addEventListener('click', () => { void next(); });
  $('[data-action="skip"]').addEventListener('click', () => { void next(true); });
  $('[data-action="back"]').addEventListener('click', () => show(Math.max(0, step - 1)));
  $('[data-action="later"]').addEventListener('click', closeSetupWizard);
  root.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); if (!required) closeSetupWizard(); }
    if (event.key === 'Enter' && (event.target as HTMLElement).tagName === 'INPUT' && (event.target as HTMLInputElement).type !== 'search') {
      event.preventDefault(); void next();
    }
  });
}

export async function openSetupWizard(options: { required?: boolean } = {}) {
  if (!root) build();
  required = !!options.required;
  root!.classList.toggle('required', required);
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  root!.classList.add('open');
  try {
    saved = await savedKeys();
    const prefs = await apiGet<{ user_name: string; honorific: string }>('/api/settings/preferences');
    ($('#wizard-name') as HTMLInputElement).value = prefs.user_name || '';
    ($('#wizard-honorific') as HTMLSelectElement).value = prefs.honorific || 'sir';
    const agent = await agentRequest('settings') as { llm_provider: string };
    setMode(agent.llm_provider === 'local' ? 'local' : 'cloud');
    setProvider(agent.llm_provider === 'local' ? 'openai' : agent.llm_provider);
  } catch {
    setMode('cloud'); setProvider('openai');
  }
  show(0);
}

export function closeSetupWizard() {
  if (!root) return;
  root.classList.remove('open');
  local?.destroy();
  if (previousFocus?.isConnected) previousFocus.focus();
}

export function isSetupWizardOpen() {
  return !!root?.classList.contains('open');
}
