/** Separate provider credentials; saved keys are never returned or cached in the browser. */
import { apiGet, apiPost } from './api/client';

type ProviderID = 'openai' | 'gemini' | 'grok' | 'ollama';
type ProviderStatus = { id: ProviderID; name: string; model: string; configured: boolean };
export type LLMStatus = { provider: ProviderID; model: string; available: boolean; providers: ProviderStatus[] };

const keyProviders = [
  { id: 'gemini', name: 'Gemini', keyName: 'GEMINI_API_KEY', url: 'https://aistudio.google.com/apikey' },
  { id: 'grok', name: 'Grok', keyName: 'XAI_API_KEY', url: 'https://console.x.ai/' },
  { id: 'ollama', name: 'Ollama Cloud', keyName: 'OLLAMA_API_KEY', url: 'https://ollama.com/settings/keys' },
] as const;

export const providerKeysHTML = keyProviders.map(provider => `
  <div class="settings-field">
    <label for="input-${provider.id}-key">${provider.name} API Key</label>
    <a href="${provider.url}" target="_blank" rel="noreferrer">Create API key</a>
    <input type="password" id="input-${provider.id}-key" placeholder="Enter ${provider.name} API key"
           autocomplete="new-password" spellcheck="false" maxlength="2048">
    <div class="settings-actions">
      <button class="settings-btn" id="save-${provider.id}-key">Save</button>
      <button class="settings-btn" id="test-${provider.id}-key">Test</button>
      <button class="settings-btn" id="remove-${provider.id}-key">Remove</button>
    </div>
    <p class="google-help" id="${provider.id}-key-status" role="status" aria-live="polite">Checking configuration…</p>
  </div>`).join('');

export async function readLLMStatus(): Promise<LLMStatus> {
  return apiGet<LLMStatus>('/api/settings/llm');
}

export async function loadProviderKeys() {
  try {
    const status = await readLLMStatus();
    for (const provider of keyProviders) {
      const element = document.getElementById(`${provider.id}-key-status`);
      const entry = status.providers.find(item => item.id === provider.id);
      if (element) element.textContent = entry?.configured
        ? `${entry.model} · Key saved. Use Test to check the connection.` : 'No API key saved.';
    }
  } catch {
    for (const provider of keyProviders) {
      const element = document.getElementById(`${provider.id}-key-status`);
      if (element) element.textContent = 'Configuration status unavailable.';
    }
  }
}

export function wireProviderKeys(refresh: () => Promise<unknown>) {
  for (const provider of keyProviders) {
    const field = document.getElementById(`input-${provider.id}-key`) as HTMLInputElement;
    const feedback = document.getElementById(`${provider.id}-key-status`)!;
    const buttons = ['save', 'test', 'remove'].map(action =>
      document.getElementById(`${action}-${provider.id}-key`) as HTMLButtonElement);
    for (const [index, action] of ['save', 'test', 'remove'].entries()) {
      buttons[index].addEventListener('click', async () => {
        buttons.forEach(button => { button.disabled = true; });
        try {
          if (action === 'test') {
            feedback.textContent = 'Testing connection…';
            const result = await apiPost<{ valid: boolean; error?: string }>('/api/settings/test-llm',
              { provider: provider.id, key_value: field.value.trim() || undefined });
            feedback.textContent = result.valid ? 'Connection successful.' : result.error || 'Connection failed.';
          } else {
            if (action === 'save' && !field.value.trim()) throw new Error('Enter an API key first.');
            await apiPost('/api/settings/keys', { key_name: provider.keyName,
              key_value: action === 'remove' ? '' : field.value.trim() });
            field.value = '';
            await refresh();
            feedback.textContent = action === 'remove' ? 'API key removed.' : 'Key saved in Windows Credential Manager. Use Test to check it.';
          }
        } catch (error) {
          feedback.textContent = error instanceof Error ? error.message : 'The setting could not be updated.';
        } finally { buttons.forEach(button => { button.disabled = false; }); }
      });
    }
  }
}
