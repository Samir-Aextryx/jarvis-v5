type AgentPrefs = {work_apps:string[]; fallback:boolean; automation:boolean; activity_log:boolean; large_model:string; llm_provider:string; gemini_model:string; grok_model:string; ollama_model:string; reasoning_effort:string; default_email:string; jev_configured:boolean; jev_status:string; jev_error:string; jev_error_code:string|null};

export const agentSettingsHTML = `<section class="settings-section" id="section-agent">
  <h3>AI Settings</h3>
  <label for="agent-provider">Jarvis AI provider</label>
  <select id="agent-provider"><option value="openai">OpenAI</option><option value="gemini">Google Gemini</option><option value="grok">xAI Grok</option><option value="ollama">Ollama Cloud (DeepSeek Flash)</option></select>
  <p class="google-help">Choose the AI for conversation, writing and task planning. Add its API key in Voice &amp; AI keys. Only the selected provider receives these requests; switching takes effect after saving. Fish Audio keeps the Jarvis voice. Speech recognition still uses your OpenAI key.</p>
  <label for="agent-model">OpenAI model ID</label><input id="agent-model" type="text" maxlength="80">
  <label for="agent-gemini-model">Gemini model ID</label><input id="agent-gemini-model" type="text" maxlength="100">
  <label for="agent-grok-model">Grok model ID</label><input id="agent-grok-model" type="text" maxlength="100">
  <label for="agent-ollama-model">Ollama Cloud model ID</label><input id="agent-ollama-model" type="text" maxlength="151">
  <label for="agent-reasoning">OpenAI / Gemini / Ollama reasoning effort</label><select id="agent-reasoning"><option>none</option><option>low</option><option>medium</option><option>high</option><option>xhigh</option><option>max</option></select>
  <p class="google-help">Gemini uses low when the selected effort is unsupported. For Ollama, none answers fastest without a thinking pass. Models and API credit must be available in each provider account. Chat app subscriptions do not configure these API keys.</p>
  <h3>Jev routing (optional)</h3>
  <p class="google-help">TypeSafe Jev routes commands and filters mail previews. Writing and complex planning use the selected AI provider. Jev keys go only to the official TypeSafe API.</p>
  <label for="jev-key">Jev API key</label>
  <input id="jev-key" type="password" autocomplete="off" placeholder="Enter your TypeSafe API key">
  <button class="settings-btn" id="jev-show">Show</button>
  <button class="settings-btn" id="jev-save">Save Jev key</button>
  <button class="settings-btn" id="jev-test">Test Connection</button>
  <button class="settings-btn" id="jev-remove">Remove Jev key</button>
  <p id="jev-status" role="status" aria-live="polite">Checking Jev configuration…</p>
  <label><input id="agent-fallback" type="checkbox"> Use existing routing and selected AI when Jev is unavailable</label>
  <h3>Applications</h3><label for="agent-apps">Open Everything Apps — one installed app name per line</label>
  <textarea id="agent-apps" rows="5"></textarea>
  <h3>Email and calendar</h3>
  <label for="agent-email">Default email account</label><select id="agent-email"><option>Gmail</option><option>Outlook</option></select>
  <p class="google-help">Gmail: connect in Google settings below. Outlook: existing desktop automation; Microsoft Graph is not connected. Teams notifications are unavailable. Local calendar is the default; explicitly say Google to use Google Calendar.</p>
  <h3>WhatsApp Beta calls and urgent mail</h3>
  <p class="google-help">Jarvis watches new urgent mail headers while its backend is running. It shows an in-app alert. Automatic WhatsApp calls require a verified two-way audio bridge.</p>
  <label for="boss-phone">My WhatsApp contact number (Boss)</label>
  <input id="boss-phone" type="tel" autocomplete="off" placeholder="Swiss mobile number">
  <button class="settings-btn" id="boss-phone-save">Save number securely</button>
  <p id="whatsapp-call-status" role="status">Checking call readiness…</p>
  <h3>Automation and privacy</h3>
  <label><input id="agent-automation" type="checkbox"> Enable automatic tool execution</label>
  <label><input id="agent-log" type="checkbox"> Keep local activity counts (no message content)</label>
  <button class="settings-btn" id="agent-save">Save agent settings</button>
  <button class="settings-btn" id="agent-logs">Show activity</button>
  <button class="settings-btn" id="agent-clear">Clear activity log</button>
  <p id="agent-status" role="status"></p><pre id="agent-activity"></pre>
</section>`;

async function request(path:string, body?:unknown) {
  const response = await fetch('/api/agent/'+path, {method:body===undefined?'GET':'POST',
    headers:{'Content-Type':'application/json','Authorization':'Bearer '+(localStorage.getItem('jarvis_auth_token')||'')},
    ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const result = await response.json();
  if(!response.ok) throw new Error((result.code ? '['+result.code+'] ' : '')+(result.error||'The setting could not be updated.'));
  return result;
}
function input(id:string) {return document.getElementById(id) as HTMLInputElement;}
export async function loadAgentSettings() {
  const controls=['agent-apps','agent-provider','agent-model','agent-gemini-model','agent-grok-model','agent-ollama-model','agent-reasoning','agent-email','agent-fallback','agent-automation','agent-log','agent-save'];
  controls.forEach(id=>input(id).disabled=true);
  try {
    const s:AgentPrefs=await request('settings');
    input('agent-apps').value=s.work_apps.join('\n'); input('agent-model').value=s.large_model; input('agent-reasoning').value=s.reasoning_effort;
    input('agent-provider').value=s.llm_provider;
    input('agent-gemini-model').value=s.gemini_model; input('agent-grok-model').value=s.grok_model; input('agent-ollama-model').value=s.ollama_model;
    input('agent-email').value=s.default_email;
    input('agent-fallback').checked=s.fallback; input('agent-automation').checked=s.automation; input('agent-log').checked=s.activity_log;
    document.getElementById('jev-status')!.textContent=(s.jev_error_code?'['+s.jev_error_code+'] ':'')+s.jev_status+(s.jev_configured?' · Key saved':' · No key saved')+(s.jev_error?' · '+s.jev_error:'');
  } catch {document.getElementById('agent-status')!.textContent='Could not load agent settings.';}
  finally {controls.forEach(id=>input(id).disabled=false);}
  try {
    const call = await request('whatsapp-call/status') as {contact_saved:boolean;whatsapp_beta_installed:boolean;automatic_call_ready:boolean;reason:string};
    document.getElementById('whatsapp-call-status')!.textContent =
      `${call.contact_saved ? 'Boss contact saved' : 'Boss contact missing'} · ${call.whatsapp_beta_installed ? 'WhatsApp Beta installed' : 'WhatsApp Beta missing'} · ${call.automatic_call_ready ? 'Calls ready' : call.reason}`;
  } catch {document.getElementById('whatsapp-call-status')!.textContent = 'Call readiness could not be checked.';}
}
export function wireAgentSettings() {
  const key=input('jev-key');
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
  const action=(id:string, fn:()=>Promise<void>, statusId='agent-status')=>document.getElementById(id)!.addEventListener('click',async()=>{
    const button=document.getElementById(id) as HTMLButtonElement; button.disabled=true;
    try {await fn();} catch(e){document.getElementById(statusId)!.textContent=e instanceof Error?e.message:'Request failed.';} finally{button.disabled=false;}
  });
  document.getElementById('jev-show')!.addEventListener('click',()=>{key.type=key.type==='password'?'text':'password';document.getElementById('jev-show')!.textContent=key.type==='password'?'Show':'Hide';});
  action('jev-save',async()=>{if(!key.value.trim())throw new Error('[JEV_KEY_MISSING] Enter a Jev API key first.');await request('jev/key',{key:key.value.trim()});key.value='';document.getElementById('jev-status')!.textContent='Not Connected · Key saved securely. Test the connection.';},'jev-status');
  action('jev-remove',async()=>{await request('jev/key',{key:''});key.value='';document.getElementById('jev-status')!.textContent='[JEV_KEY_MISSING] Key removed. Add a Jev API key to connect.';},'jev-status');
  action('jev-test',async()=>{document.getElementById('jev-status')!.textContent='Testing…';const s=await request('jev/test',{});document.getElementById('jev-status')!.textContent=s.status;},'jev-status');
  action('agent-save',async()=>{await request('settings',{work_apps:input('agent-apps').value.split('\n').map(x=>x.trim()).filter(Boolean),fallback:input('agent-fallback').checked,automation:input('agent-automation').checked,activity_log:input('agent-log').checked,large_model:input('agent-model').value.trim(),llm_provider:input('agent-provider').value,gemini_model:input('agent-gemini-model').value.trim(),grok_model:input('agent-grok-model').value.trim(),ollama_model:input('agent-ollama-model').value.trim(),reasoning_effort:input('agent-reasoning').value,default_email:input('agent-email').value});document.getElementById('agent-status')!.textContent='AI provider and settings saved. New requests use this selection.';document.dispatchEvent(new Event('jarvis-ai-settings-changed'));});
  action('agent-logs',async()=>{const s=await request('activity');document.getElementById('agent-activity')!.textContent=s.items.map((r:{time:string;tool:string;success:boolean;count:number})=>`${r.time} ${r.tool} ${r.success?'OK':'Not completed'} ${r.count}`).join('\n')||'No activity yet.';});
  action('agent-clear',async()=>{await request('activity/clear',{});document.getElementById('agent-activity')!.textContent='Activity log cleared.';});
}
