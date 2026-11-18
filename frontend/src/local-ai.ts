/**
 * Local AI manager: the Ollama engine, models from Hugging Face, downloads
 * with progress and the model Jarvis uses. Shared by the setup wizard and the
 * AI settings. Names from Hugging Face are untrusted and only set as text.
 */
import { apiGet, apiPost } from './api/client';

type InstalledModel = { name: string; size: number; parameters: string; quantization: string };
type Recommended = { repo: string; quant: string; label: string; size_gb: number; badge: string; note: string; model: string; installed: boolean };
type Progress = { state: string; model?: string; status?: string; completed?: number; total?: number; error?: string };
export type LocalAiStatus = {
  installed: boolean; running: boolean; version: string | null; winget: boolean;
  install: { state: string; message?: string }; pull: Progress;
  models: InstalledModel[]; selected: string; active: boolean; recommended: Recommended[];
};

export const localAiHTML = () => `
  <div class="lai">
    <div class="lai-engine" data-role="engine">
      <span class="lai-engine-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9zM9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/></svg></span>
      <div class="lai-engine-text"><strong data-role="engine-title">Checking local AI…</strong><p data-role="engine-text"></p></div>
      <button type="button" class="settings-btn primary" data-role="install" hidden>Install local AI</button>
      <button type="button" class="settings-btn" data-role="start" hidden>Start</button>
    </div>
    <div class="lai-progress" data-role="progress" hidden>
      <div class="lai-bar"><span data-role="bar"></span></div>
      <p data-role="progress-text" role="status" aria-live="polite"></p>
    </div>
    <h4 class="lai-heading">Your models</h4>
    <div class="lai-list" data-role="installed"><p class="lai-empty">No models downloaded yet.</p></div>
    <h4 class="lai-heading">Recommended for Jarvis</h4>
    <div class="lai-cards" data-role="recommended"></div>
    <h4 class="lai-heading">Search Hugging Face</h4>
    <form class="lai-search" data-role="search-form">
      <input type="search" data-role="query" placeholder="Model name, e.g. qwen, llama, mistral" maxlength="80" aria-label="Search Hugging Face models" spellcheck="false">
      <button type="submit" class="settings-btn">Search</button>
    </form>
    <div class="lai-list" data-role="results"></div>
    <p class="lai-note">Models are GGUF files from Hugging Face and run on this PC through Ollama, a free and signed app. Answers are created locally; speech recognition and the voice still use their own services.</p>
  </div>`;

const gb = (bytes: number) => bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`;
const shortName = (model: string) => model.replace(/^hf\.co\//i, '');
const same = (a: string, b: string) => {
  const norm = (m: string) => { const l = m.trim().toLowerCase(); return l.includes(':') ? l : `${l}:latest`; };
  return norm(a) === norm(b);
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}
function button(text: string, primary = false): HTMLButtonElement {
  const node = el('button', primary ? 'settings-btn primary' : 'settings-btn', text);
  node.type = 'button';
  return node;
}

export function mountLocalAi(root: HTMLElement, onChange?: (status: LocalAiStatus) => void) {
  const q = <T extends HTMLElement>(role: string) => root.querySelector<T>(`[data-role="${role}"]`)!;
  let status: LocalAiStatus | null = null;
  let poll: ReturnType<typeof setInterval> | undefined;
  let lastPullState = '';
  let rendered = false;
  let busy = false;

  const message = (text: string, error = false) => {
    const box = q('progress');
    box.hidden = false;
    box.classList.toggle('error', error);
    q('bar').parentElement!.hidden = true;
    q('progress-text').textContent = text;
  };

  async function act(work: () => Promise<unknown>) {
    if (busy) return;
    busy = true;
    try { await work(); } catch (error) { message(error instanceof Error ? error.message : 'Request failed.', true); }
    finally { busy = false; await refresh(); }
  }

  function renderEngine(s: LocalAiStatus) {
    const title = q('engine-title'); const text = q('engine-text');
    const install = q<HTMLButtonElement>('install'); const start = q<HTMLButtonElement>('start');
    install.hidden = true; start.hidden = true;
    const installing = s.install.state === 'installing' || s.install.state === 'starting';
    q('engine').dataset.state = installing ? 'installing' : s.running ? 'ready' : s.installed ? 'stopped'
      : s.install.state === 'failed' ? 'failed' : 'missing';
    if (installing) {
      title.textContent = 'Installing local AI…';
      text.textContent = s.install.message || 'This can take a few minutes.';
    } else if (s.running) {
      title.textContent = 'Local AI is ready';
      text.textContent = `Ollama ${s.version || ''} runs on this PC.`.replace('  ', ' ');
    } else if (s.installed) {
      title.textContent = 'Local AI is installed but not running';
      text.textContent = 'Start it here; Jarvis also starts it when needed.';
      start.hidden = false;
    } else {
      title.textContent = 'Install the local AI engine';
      text.textContent = s.install.state === 'failed' && s.install.message ? s.install.message
        : 'Jarvis runs local models with Ollama, a free and signed app. Installing takes about a minute and needs no restart.';
      install.hidden = false;
      install.textContent = s.winget ? 'Install local AI' : 'Download Ollama';
    }
  }

  function renderProgress(s: LocalAiStatus) {
    const pull = s.pull;
    const box = q('progress');
    if (pull.state === 'downloading') {
      box.hidden = false; box.classList.remove('error');
      q('bar').parentElement!.hidden = false;
      const total = pull.total || 0; const done = pull.completed || 0;
      const percent = total ? Math.min(100, Math.round(done / total * 100)) : 0;
      q('bar').style.width = `${percent}%`;
      q('progress-text').textContent = total
        ? `Downloading ${shortName(pull.model || '')}: ${percent} % (${gb(done)} of ${gb(total)})`
        : `Preparing ${shortName(pull.model || '')}: ${pull.status || 'starting'}…`;
    } else if (pull.state === 'failed' && lastPullState === 'downloading') {
      message(`Download failed: ${pull.error || 'unknown error'}`, true);
    } else if (pull.state === 'done' && lastPullState === 'downloading') {
      message(`${shortName(pull.model || '')} is downloaded${same(s.selected, pull.model || '') ? ' and in use' : ''}.`);
    } else if (!rendered) {
      box.hidden = true;
    }
    lastPullState = pull.state;
    rendered = true;
  }

  function modelRow(name: string, detail: string, actions: HTMLElement[], selected: boolean) {
    const row = el('div', 'lai-row' + (selected ? ' selected' : ''));
    const info = el('div', 'lai-row-info');
    info.append(el('strong', '', shortName(name)), el('span', '', detail));
    const buttons = el('div', 'lai-row-actions');
    buttons.append(...actions);
    row.append(info, buttons);
    return row;
  }

  function renderInstalled(s: LocalAiStatus) {
    const list = q('installed');
    list.replaceChildren();
    if (!s.models.length) {
      list.append(el('p', 'lai-empty', s.running ? 'No models downloaded yet. Pick a recommended one below.' : 'Install and start local AI to see your models.'));
      return;
    }
    for (const model of s.models) {
      const inUse = same(s.selected, model.name);
      const use = button(inUse ? (s.active ? 'In use' : 'Use') : 'Use', !inUse);
      use.disabled = inUse && s.active;
      use.addEventListener('click', () => act(async () => {
        await apiPost('/api/local-ai/select', { model: model.name });
        document.dispatchEvent(new Event('jarvis-ai-settings-changed'));
      }));
      const remove = button('Remove');
      remove.addEventListener('click', () => {
        if (!confirm(`Remove ${shortName(model.name)} from this PC? You can download it again later.`)) return;
        void act(() => apiPost('/api/local-ai/delete', { model: model.name }));
      });
      const detail = [model.parameters, model.quantization, gb(model.size)].filter(Boolean).join(' · ');
      list.append(modelRow(model.name, detail, [use, remove], inUse && s.active));
    }
  }

  function pullButton(model: string, s: LocalAiStatus, label = 'Download') {
    const node = button(label, true);
    node.disabled = !s.installed || s.pull.state === 'downloading';
    if (!s.installed) node.title = 'Install the local AI engine first.';
    node.addEventListener('click', () => act(() => apiPost('/api/local-ai/pull', { model })));
    return node;
  }

  function renderRecommended(s: LocalAiStatus) {
    const cards = q('recommended');
    cards.replaceChildren();
    for (const rec of s.recommended) {
      const installed = s.models.find(m => same(m.name, rec.model));
      const inUseHere = !!installed && same(s.selected, installed.name) && s.active;
      const card = el('div', 'lai-card' + (inUseHere ? ' in-use' : installed ? ' downloaded' : ''));
      const head = el('div', 'lai-card-head');
      head.append(el('strong', '', rec.label));
      if (rec.badge) {
        const badge = el('span', 'lai-badge', rec.badge);
        badge.dataset.kind = rec.badge.toLowerCase().replace(/\s+/g, '-');
        head.append(badge);
      }
      const source = document.createElement('a');
      source.className = 'lai-source';
      source.href = `https://huggingface.co/${rec.repo}`;
      source.target = '_blank'; source.rel = 'noreferrer';
      source.textContent = rec.repo.split('/')[0];
      card.append(head, el('p', '', rec.note));
      const foot = el('div', 'lai-card-foot');
      const meta = el('span', 'lai-size', `${rec.size_gb.toFixed(1)} GB · `);
      meta.append(source);
      foot.append(meta);
      card.append(foot);
      if (installed) {
        const inUse = same(s.selected, installed.name) && s.active;
        const use = button(inUse ? 'In use' : 'Use', !inUse);
        use.disabled = inUse;
        use.addEventListener('click', () => act(async () => {
          await apiPost('/api/local-ai/select', { model: installed.name });
          document.dispatchEvent(new Event('jarvis-ai-settings-changed'));
        }));
        foot.append(use);
      } else {
        foot.append(pullButton(rec.model, s));
      }
      cards.append(card);
    }
  }

  async function showFiles(repo: string, container: HTMLElement) {
    container.replaceChildren(el('p', 'lai-empty', 'Loading versions…'));
    try {
      const data = await apiGet<{ files: Array<{ quant: string; size: number; model: string }> }>(`/api/local-ai/files?repo=${encodeURIComponent(repo)}`);
      container.replaceChildren();
      if (!data.files.length) { container.append(el('p', 'lai-empty', 'No single-file GGUF version that Ollama can download.')); return; }
      // ARM-only repacks (Q4_0_4_4 …) are slower on Windows PCs; leave them out.
      for (const file of data.files.filter(f => !/^Q4_0_\d_\d$/i.test(f.quant))) {
        const best = /^Q4_K_M$/i.test(file.quant);
        const row = el('div', 'lai-file' + (best ? ' best' : ''));
        const label = el('span', '', `${file.quant} · ${gb(file.size)}`);
        if (best) label.append(el('em', '', 'Recommended'));
        row.append(label, pullButton(file.model, status!));
        container.append(row);
      }
      container.append(el('p', 'lai-hint', 'Q4_K_M is a good balance of size and quality. Larger versions are more accurate but need more memory.'));
    } catch (error) {
      container.replaceChildren(el('p', 'lai-empty', error instanceof Error ? error.message : 'Could not load the versions.'));
    }
  }

  q<HTMLFormElement>('search-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const query = q<HTMLInputElement>('query').value.trim();
    const results = q('results');
    results.replaceChildren(el('p', 'lai-empty', 'Searching Hugging Face…'));
    try {
      const data = await apiGet<{ results: Array<{ repo: string; downloads: number; likes: number }> }>(`/api/local-ai/search?q=${encodeURIComponent(query)}`);
      results.replaceChildren();
      if (!data.results.length) { results.append(el('p', 'lai-empty', 'No GGUF models found.')); return; }
      for (const result of data.results) {
        const files = el('div', 'lai-files');
        files.hidden = true;
        const choose = button('Versions');
        choose.addEventListener('click', () => {
          files.hidden = !files.hidden;
          if (!files.hidden && !files.childElementCount) void showFiles(result.repo, files);
        });
        const row = modelRow(result.repo, `${result.downloads.toLocaleString('en-US')} downloads · ${result.likes.toLocaleString('en-US')} likes`, [choose], false);
        const wrapper = el('div', 'lai-result');
        wrapper.append(row, files);
        results.append(wrapper);
      }
    } catch (error) {
      results.replaceChildren(el('p', 'lai-empty', error instanceof Error ? error.message : 'Search failed.'));
    }
  });

  q<HTMLButtonElement>('install').addEventListener('click', () => {
    if (status && !status.winget) { window.open('https://ollama.com/download/windows', '_blank', 'noopener'); return; }
    void act(() => apiPost('/api/local-ai/install', {}));
  });
  q<HTMLButtonElement>('start').addEventListener('click', () => act(() => apiPost('/api/local-ai/start', {})));

  async function refresh() {
    try {
      status = await apiGet<LocalAiStatus>('/api/local-ai/status');
    } catch {
      q('engine-title').textContent = 'Local AI status is unavailable';
      return;
    }
    renderEngine(status);
    renderProgress(status);
    renderInstalled(status);
    renderRecommended(status);
    const working = status.pull.state === 'downloading' || ['installing', 'starting'].includes(status.install.state);
    if (working && !poll) poll = setInterval(() => { void refresh(); }, 1000);
    if (!working && poll) { clearInterval(poll); poll = undefined; }
    onChange?.(status);
  }

  return {
    refresh,
    current: () => status,
    destroy() { if (poll) clearInterval(poll); poll = undefined; },
  };
}
