/** API keys in one place; saved keys are never returned or cached in the browser. */
import { apiGet, apiPost } from './api/client';
import { showToast } from './toast';

type ProviderID = 'openai' | 'gemini' | 'grok' | 'ollama' | 'local';
type ProviderStatus = { id: ProviderID; name: string; model: string; configured: boolean; local?: boolean };
export type LLMStatus = { provider: ProviderID; model: string; available: boolean; providers: ProviderStatus[] };
type KeyStatus = { env_keys_set: { openai: boolean; fish_audio: boolean; fish_voice_id: boolean } };

export const DEFAULT_FISH_VOICE = '612b878b113047d9a770c069c8b4fdfe';

export const keyDefs = [
  { id: 'openai', name: 'OpenAI', keyName: 'OPENAI_API_KEY', url: 'https://platform.openai.com/api-keys', purpose: 'Speech recognition, and the AI when OpenAI is selected', placeholder: 'sk-…' },
  { id: 'fish', name: 'Fish Audio', keyName: 'FISH_API_KEY', url: 'https://fish.audio/app/api-keys/', purpose: 'Jarvis’s voice', placeholder: 'Fish Audio key' },
  { id: 'gemini', name: 'Google Gemini', keyName: 'GEMINI_API_KEY', url: 'https://aistudio.google.com/apikey', purpose: 'AI when Gemini is selected', placeholder: 'AIza…' },
  { id: 'grok', name: 'xAI Grok', keyName: 'XAI_API_KEY', url: 'https://console.x.ai/', purpose: 'AI when Grok is selected', placeholder: 'xai-…' },
  { id: 'ollama', name: 'Ollama Cloud', keyName: 'OLLAMA_API_KEY', url: 'https://ollama.com/settings/keys', purpose: 'AI when Ollama Cloud is selected', placeholder: 'Ollama Cloud key' },
] as const;
export type KeyID = typeof keyDefs[number]['id'];

const keyCard = (key: typeof keyDefs[number]) => `
  <div class="key-card" id="key-card-${key.id}">
    <div class="key-card-head">
      <span class="key-avatar" data-key="${key.id}" aria-hidden="true">${key.name.replace(/^(Google|xAI) /, '')[0]}</span>
      <div class="key-card-title"><strong>${key.name}</strong><small>${key.purpose}</small></div>
      <span class="key-chip" id="key-chip-${key.id}">Checking…</span>
    </div>
    <div class="settings-input-row">
      <input type="password" id="input-${key.id}-key" placeholder="${key.placeholder}" autocomplete="new-password" spellcheck="false" maxlength="2048" aria-label="${key.name} API key">
      <button type="button" class="settings-btn primary" id="save-${key.id}-key">Save</button>
    </div>
    <div class="key-card-foot">
      <a href="${key.url}" target="_blank" rel="noreferrer">Get a key</a>
      <span class="key-card-buttons">
        <button type="button" class="settings-btn ghost" id="test-${key.id}-key">Test</button>
        <button type="button" class="settings-btn ghost" id="remove-${key.id}-key">Remove</button>
      </span>
    </div>
  </div>`;

export const keysHTML = `
<section class="settings-section" id="section-api-keys">
  <h3>API keys</h3>
  <p class="google-help">Keys are stored in Windows Credential Manager on this PC and are never shown again after saving. You only need the keys for the services you use.</p>
  <div class="key-grid">${keyDefs.map(keyCard).join('')}</div>
</section>`;

export async function readLLMStatus(): Promise<LLMStatus> {
  return apiGet<LLMStatus>('/api/settings/llm');
}

/** Which keys are saved: OpenAI and Fish from the status, the others from the AI providers. */
export async function savedKeys(): Promise<Record<KeyID, boolean>> {
  const [status, llm] = await Promise.all([apiGet<KeyStatus>('/api/settings/status'), readLLMStatus()]);
  const provider = (id: ProviderID) => !!llm.providers.find(p => p.id === id)?.configured;
  return { openai: status.env_keys_set.openai, fish: status.env_keys_set.fish_audio,
           gemini: provider('gemini'), grok: provider('grok'), ollama: provider('ollama') };
}

export async function saveKey(id: KeyID, value: string) {
  const key = keyDefs.find(k => k.id === id)!;
  await apiPost('/api/settings/keys', { key_name: key.keyName, key_value: value });
}

export async function testKey(id: KeyID, value?: string): Promise<{ valid: boolean; error?: string }> {
  const key_value = value?.trim() || undefined;
  if (id === 'openai') return apiPost('/api/settings/test-openai', { key_value });
  if (id === 'fish') return apiPost('/api/settings/test-fish', { key_value });
  return apiPost('/api/settings/test-llm', { provider: id, key_value });
}

function setChip(id: KeyID, state: 'saved' | 'missing' | 'testing' | 'ok' | 'failed', text?: string) {
  const chip = document.getElementById(`key-chip-${id}`);
  if (!chip) return;
  chip.dataset.state = state;
  chip.textContent = text || { saved: 'Saved', missing: 'Not set', testing: 'Testing…', ok: 'Working', failed: 'Not working' }[state];
}

export async function loadProviderKeys() {
  try {
    const saved = await savedKeys();
    for (const key of keyDefs) setChip(key.id, saved[key.id] ? 'saved' : 'missing');
  } catch {
    for (const key of keyDefs) setChip(key.id, 'missing', 'Unknown');
  }
}

export function wireProviderKeys(refresh: () => Promise<unknown>) {
  for (const key of keyDefs) {
    const field = document.getElementById(`input-${key.id}-key`) as HTMLInputElement;
    const buttons = (['save', 'test', 'remove'] as const).map(action => document.getElementById(`${action}-${key.id}-key`) as HTMLButtonElement);
    const run = (work: () => Promise<void>) => async () => {
      buttons.forEach(button => { button.disabled = true; });
      try { await work(); }
      catch (error) { showToast(error instanceof Error ? error.message : 'The key could not be updated.', false); }
      finally { buttons.forEach(button => { button.disabled = false; }); }
    };
    buttons[0].addEventListener('click', run(async () => {
      if (!field.value.trim()) throw new Error(`Enter your ${key.name} key first.`);
      await saveKey(key.id, field.value.trim());
      field.value = '';
      setChip(key.id, 'saved');
      showToast(`${key.name} key saved. Use Test to check it.`);
      await refresh();
    }));
    buttons[1].addEventListener('click', run(async () => {
      setChip(key.id, 'testing');
      const result = await testKey(key.id, field.value);
      setChip(key.id, result.valid ? 'ok' : 'failed');
      showToast(result.valid ? `${key.name} works.` : result.error || `${key.name} did not answer.`, result.valid);
    }));
    buttons[2].addEventListener('click', run(async () => {
      if (!confirm(`Remove the saved ${key.name} key from this PC?`)) return;
      await saveKey(key.id, '');
      setChip(key.id, 'missing');
      showToast(`${key.name} key removed.`);
      await refresh();
    }));
    field.addEventListener('keydown', event => { if (event.key === 'Enter') buttons[0].click(); });
  }
}
