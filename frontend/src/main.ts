/**
 * JARVIS — Main entry point.
 *
 * Wires together the orb visualization, WebSocket communication,
 * speech recognition, and audio playback into a single experience.
 */

import { createOrb, type OrbState } from "./orb";
import { createVoiceInput, createAudioPlayer } from "./voice";
import { createSocket } from "./ws";
import { openSettings, closeSettings, checkFirstTimeSetup, isSettingsOpen } from "./settings";
import { openPersonalPanel } from './personal-panel';
import "./style.css";

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

type State = "idle" | "listening" | "thinking" | "speaking";
let currentState: State = "idle";
let suppressReply = false;
let currentTurn = '';
let metricsSent = false;
let timings: Record<string, number> = {};
function finishTimings(cancelled = false) {
  if (!currentTurn || metricsSent) return;
  metricsSent = true;
  timings.response_complete = performance.now();
  socket.send({type:'playback_metrics',id:currentTurn,cancelled,timings});
  console.info('[voice latency]',{id:currentTurn,cancelled,...Object.fromEntries(Object.entries(timings).map(([k,v])=>[k,Math.round(v-(timings.speech_end ?? v))]))});
}
const dashboardMode = new URLSearchParams(window.location.search).get("dashboard") === "1";
let isMuted = dashboardMode || localStorage.getItem("jarvis_mic_muted") === "true";
let phoneCallActive = false;
let phonePrivacyEvents = 0;
let microphoneStarted = false;
let microphoneError = "";
let authBlocked = false;

const statusEl = document.getElementById("status-text")!;
const errorEl = document.getElementById("error-text")!;

const taskCard = document.createElement("section");
taskCard.id = "task-card";
taskCard.hidden = true;
const taskMessage = document.createElement("p");
taskMessage.setAttribute("role", "status");
const taskControl = document.createElement("button");
taskControl.type = "button";
taskControl.onclick = () => {
  if (taskCard.dataset.active === "true") interruptReply(true);
  else taskCard.hidden = true;
};
taskCard.append(taskMessage, taskControl);
document.body.append(taskCard);

let errorTimer: ReturnType<typeof setTimeout> | undefined;
function showError(msg: string, sticky = false) {
  errorEl.textContent = msg;
  errorEl.style.opacity = "1";
  // A stale timer used to hide a newer (and possibly safety-critical) error.
  if (errorTimer) {
    clearTimeout(errorTimer);
    errorTimer = undefined;
  }
  if (sticky) return;
  errorTimer = setTimeout(() => {
    errorEl.style.opacity = "0";
    errorTimer = undefined;
  }, 5000);
}

// Visible transcript when speech output fails: #voice-caption is visually
// clipped (screen-reader only), so a silent failure used to hide the reply.
const replyCaption = document.createElement("div");
replyCaption.id = "reply-caption";
replyCaption.setAttribute("role", "status");
replyCaption.setAttribute("aria-live", "polite");
replyCaption.hidden = true;
document.body.append(replyCaption);
let replyCaptionTimer: ReturnType<typeof setTimeout> | undefined;
function showReplyCaption(text: string) {
  if (!text) return;
  replyCaption.textContent = text;
  replyCaption.hidden = false;
  if (replyCaptionTimer) clearTimeout(replyCaptionTimer);
  replyCaptionTimer = setTimeout(() => { replyCaption.hidden = true; }, 15000);
}
function hideReplyCaption() {
  if (replyCaptionTimer) clearTimeout(replyCaptionTimer);
  replyCaptionTimer = undefined;
  replyCaption.hidden = true;
}

const urgentMailBanner = document.createElement('div');
urgentMailBanner.setAttribute('role', 'alert');
urgentMailBanner.hidden = true;
urgentMailBanner.style.cssText = 'position:fixed;top:72px;left:50%;transform:translateX(-50%);z-index:1000;max-width:min(540px,90vw);padding:14px 18px;border:1px solid #d29922;border-radius:12px;background:#191919;color:#fff;box-shadow:0 8px 32px #0009;font:14px system-ui';
const urgentMailText = document.createElement('span');
const urgentMailDismiss = document.createElement('button');
urgentMailDismiss.textContent = '×';
urgentMailDismiss.setAttribute('aria-label', 'Dismiss urgent email alert');
urgentMailDismiss.style.cssText = 'margin-left:16px;border:0;background:transparent;color:#fff;font-size:20px;cursor:pointer';
urgentMailDismiss.addEventListener('click', () => { urgentMailBanner.hidden = true; });
urgentMailBanner.append(urgentMailText, urgentMailDismiss);
document.body.append(urgentMailBanner);
const mailMonitorBanner = document.createElement('div');
mailMonitorBanner.setAttribute('role', 'alert');
mailMonitorBanner.hidden = true;
mailMonitorBanner.style.cssText = 'position:fixed;top:138px;left:50%;transform:translateX(-50%);z-index:1000;max-width:min(540px,90vw);padding:12px 16px;border:1px solid #d04a4a;border-radius:12px;background:#241414;color:#fff;box-shadow:0 8px 32px #0009;font:14px system-ui';
document.body.append(mailMonitorBanner);
const mailMonitorIssues = new Set<string>();
function updateMailMonitorIssue(source: string, available: boolean) {
  if (!['outlook', 'gmail', 'storage'].includes(source)) return;
  if (available) mailMonitorIssues.delete(source);
  else mailMonitorIssues.add(source);
  mailMonitorBanner.textContent = mailMonitorIssues.size
    ? `Urgent email monitoring unavailable: ${Array.from(mailMonitorIssues).join(', ')}. Jarvis may miss new urgent mail.`
    : '';
  mailMonitorBanner.hidden = mailMonitorIssues.size === 0;
}
function displayUrgentMail(mail: {source?:unknown;subject?:unknown;sender?:unknown;call_state?:unknown}) {
  const callState = String(mail.call_state || '');
  const callMessage = callState === 'blocked' ? ' · WhatsApp call unavailable; setup needed'
    : callState === 'connected' ? ' · Jarvis spoke on the call'
    : callState === 'uncertain' ? ' · Call outcome uncertain; check WhatsApp'
    : callState === 'expired' ? ' · Call window expired'
    : '';
  urgentMailText.textContent = `Urgent email in ${String(mail.source || 'mail')}: ${String(mail.subject || '(no subject)')} · ${String(mail.sender || 'unknown sender')}${callMessage}`;
  urgentMailBanner.hidden = false;
}
function updateStatus(state: State) {
  const labels: Record<State, string> = {
    idle: "ready for voice",
    listening: "listening...",
    thinking: "thinking...",
    speaking: "speaking...",
  };
  if (authBlocked) {
    statusEl.textContent = "Authentication failed: reopen Jarvis from the desktop app.";
    return;
  }
  if (!authToken) {
    statusEl.textContent = "Authentication required: open Jarvis from the desktop app.";
    return;
  }
  if (phoneCallActive) {
    statusEl.textContent = "Phone call · laptop microphone off";
    return;
  }
  if (isMuted) {
    statusEl.textContent = "Mikrofon stummgeschaltet";
    return;
  }
  if (microphoneError) {
    statusEl.textContent = microphoneError;
    return;
  }
  if (!microphoneStarted) {
    // Never claim readiness before getUserMedia actually succeeded.
    statusEl.textContent = "Mikrofon wird vorbereitet…";
    return;
  }
  statusEl.textContent = labels[state];
}

// ---------------------------------------------------------------------------
// Init components
// ---------------------------------------------------------------------------

const canvas = document.getElementById("orb-canvas") as HTMLCanvasElement;
const orb = createOrb(canvas);
window.addEventListener('beforeunload', () => orb.destroy());
const desktopBridge = (window as Window & {jarvisDesktop?: {
  openMap(url: string): Promise<void>;
  onMapVisible(callback: (visible: boolean) => void): void;
  getAuthToken?(): string;
}}).jarvisDesktop;
desktopBridge?.onMapVisible(visible => orb.setSuspended(visible));

const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
function resolveAuthToken(): string {
  const bridgeToken = desktopBridge?.getAuthToken ? desktopBridge.getAuthToken() : "";
  // URL tokens are a bootstrap for the local browser mode only; never accept
  // them from a non-loopback host (a crafted link could otherwise replace the
  // saved token).
  const loopback = ["127.0.0.1", "localhost", "[::1]"].includes(window.location.hostname);
  const urlToken = loopback
    ? (new URLSearchParams(window.location.search).get("token")
      || new URLSearchParams(window.location.hash.slice(1)).get("token") || "")
    : "";
  const token = bridgeToken || urlToken || localStorage.getItem("jarvis_auth_token") || "";
  if (token) localStorage.setItem("jarvis_auth_token", token);
  return token;
}

const authToken = resolveAuthToken();
async function refreshUrgentStatus(showLatest: boolean) {
  try {
    const response = await fetch('/api/agent/urgent-mail/status', {
      headers: {'Authorization': 'Bearer ' + authToken},
    });
    if (!response.ok) return;
    const status = await response.json() as {alerts?:Array<{source:string;subject:string;sender:string;time:string;call_state?:string}>;errors?:Record<string,string>};
    if (showLatest) {
      const latest = status.alerts?.[status.alerts.length - 1];
      if (latest && Date.now() - Date.parse(latest.time) < 24 * 60 * 60 * 1000) displayUrgentMail(latest);
    }
    for (const source of ['outlook', 'gmail', 'storage']) {
      updateMailMonitorIssue(source, !status.errors?.[source]);
    }
  } catch { /* The socket's connection state reports backend outages. */ }
}
void refreshUrgentStatus(true);
setInterval(() => { void refreshUrgentStatus(false); }, 60_000);
if (window.location.search.includes("token=") || window.location.hash.includes("token=")) {
  history.replaceState(null, "", window.location.pathname + (dashboardMode ? "?dashboard=1" : ""));
}
const getWsUrl = () => {
  resolveAuthToken();
  return `${wsProto}//${window.location.host}/ws/voice`;
};
const socket = createSocket(getWsUrl, (state) => {
  if (state === "auth-error") {
    authBlocked = true;
    updateStatus(currentState);
    showError("Authentication failed. Reopen Jarvis from the desktop app.", true);
  } else if (state === "disconnected") {
    // The backend may have crashed or be restarting: abandon the dead turn so
    // the orb does not stay on "thinking"/"speaking" during the outage.
    finishTimings(true);
    audioPlayer.stop();
    pcmStreamId = "";
    currentTurn = "";
    suppressReply = false;
    transition("idle");
    statusEl.textContent = "Connection lost — reconnecting…";
  } else if (state === "connected") {
    if (authBlocked) {
      authBlocked = false;
    }
    updateStatus(currentState);
  }
});

if (!authToken) {
  statusEl.textContent = "Authentifizierung erforderlich: Bitte über die Desktop-App starten.";
}

const audioPlayer = createAudioPlayer();
orb.setAnalyser(audioPlayer.getAnalyser());

function transition(newState: State) {
  if (newState === currentState) return;
  currentState = newState;
  orb.setState(newState as OrbState);
  updateStatus(newState);

  switch (newState) {
    case "idle":
      if (!isMuted && !phoneCallActive) voiceInput.resume();
      break;
    case "listening":
      if (!isMuted && !phoneCallActive) voiceInput.resume();
      break;
    case "thinking":
      if (!isMuted && !phoneCallActive) voiceInput.resume();
      break;
    case "speaking":
      if (!isMuted && !phoneCallActive) voiceInput.resume();
      break;
  }
}

// ---------------------------------------------------------------------------
// Voice input
// ---------------------------------------------------------------------------

const voiceInput = createVoiceInput(
  (text, meta) => {
    if (isMuted || phoneCallActive) return;
    if (/^(?:mute|mute microphone|microphone off|mikrofon aus|stumm)[.!? ]*$/i.test(text)) {
      interruptReply();
      isMuted = true;
      localStorage.setItem('jarvis_mic_muted','true');
      renderMuteButton();
      voiceInput.stop();
      return;
    }
    if (/^\s*(?:(?:jarvis|please)[, ]+)?(?:stop|stopp|stop talking|be quiet|quiet|halt)(?:[,.! ]+please)?[.!? ]*$/i.test(text)) {
      interruptReply(true);
      return;
    }
    // Cancel any current JARVIS response before sending new input
    audioPlayer.stop();
    suppressReply = false;
    currentTurn = meta?.id || crypto.randomUUID();
    metricsSent = false;
    timings = {speech_end:meta?.speechEnd ?? performance.now(),stt_final:meta?.sttFinal ?? performance.now()};
    hideReplyCaption();
    // User spoke — send transcript
    if (!socket.isConnected()) { showError('Jarvis is reconnecting. Please repeat the request.'); return; }
    socket.send({ type: "transcript", text, isFinal: true, streamAudio: true, turn_id:currentTurn });
    transition("thinking");
  },
  (msg: string) => {
    showError(msg);
  },
  () => {
    if (!isMuted && !phoneCallActive && (currentState === "speaking" || currentState === "thinking")) interruptReply();
  },
  (micState) => {
    if (micState === "started") {
      microphoneStarted = true;
      microphoneError = "";
    } else {
      microphoneStarted = false;
      microphoneError = "Mikrofon nicht verfügbar: Zugriff in Windows erlauben.";
    }
    updateStatus(currentState);
  }
);

function interruptReply(cancelTasks = false) {
  finishTimings(true);
  currentTurn = '';
  suppressReply = true;
  pcmStreamId = "";
  audioPlayer.stop();
  hideReplyCaption();
  const delivered = socket.send({ type: "stop", cancelTasks, stop_id:crypto.randomUUID() });
  if (!delivered && authToken) showError("Jarvis is offline; the reply could not be stopped.");
  transition("listening");
}

document.addEventListener("keydown", event => {
  if (event.key !== "Escape" || event.defaultPrevented) return;
  // Escape belongs to the settings panel / dialogs and to text fields first.
  if (isSettingsOpen() || document.querySelector("dialog[open]")) return;
  const target = event.target as HTMLElement | null;
  if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
  interruptReply(true);
});

// ---------------------------------------------------------------------------
// Audio playback finished
// ---------------------------------------------------------------------------

audioPlayer.onFinished(() => {
  finishTimings();
  transition("idle");
});
audioPlayer.onFirstAudio(() => { timings.first_audio ??= performance.now(); });
window.addEventListener('jarvis-partial', ((event: CustomEvent) => {
  if (!isMuted && !phoneCallActive && currentState === 'listening') statusEl.textContent = 'listening…';
}) as EventListener);

function applyPhoneCallPrivacy(active: boolean) {
  const wasActive = phoneCallActive;
  phoneCallActive = active;
  if (active) {
    // stop() releases MediaStream tracks, including a pending getUserMedia grant.
    microphoneStarted = false;
    voiceInput.stop();
    audioPlayer.stop();
    suppressReply = true;
    currentTurn = '';
    transition('idle');
    updateStatus(currentState);
  } else if (wasActive && !isMuted) {
    voiceInput.start();
    transition('listening');
  } else {
    updateStatus(currentState);
  }
}

// ---------------------------------------------------------------------------
// WebSocket messages
// ---------------------------------------------------------------------------

let pcmStreamId = "";
socket.onMessage((msg) => {
  const type = msg.type as string;
  if (type === 'phone_call_privacy') {
    phonePrivacyEvents++;
    const active = msg.active === true;
    applyPhoneCallPrivacy(active);
    if (active && typeof msg.session === 'string') {
      socket.send({type: 'phone_call_privacy_ready', session: msg.session});
    }
    return;
  }
  if (phoneCallActive && ['pcm_start','pcm_chunk','pcm_end','audio','status','text','turn_start'].includes(type)) return;
  if (msg.turn_id && msg.turn_id !== currentTurn) return;
  if (typeof msg.text === 'string' && ['text','audio','pcm_start'].includes(type)) {
    document.getElementById('voice-caption')!.textContent=msg.text;
  }
  if (type === 'open_personal' && (msg.view === 'memory' || msg.view === 'calendar')) {
    // A native modal on top of the settings panel would leave its focus trap
    // and Escape handler fighting the dialog.
    closeSettings();
    void openPersonalPanel(msg.view);
    return;
  }
  if (type === 'latency') { timings[String(msg.stage)] ??= performance.now(); return; }
  if (type === 'urgent_mail' || type === 'urgent_call_status') {
    displayUrgentMail(msg);
    return;
  }
  if (type === 'urgent_mail_source_status') {
    updateMailMonitorIssue(String(msg.source || ''), msg.available === true);
    return;
  }
  if (type === "open_map") {
    if (desktopBridge) void desktopBridge.openMap(String(msg.url)).catch(() => showError("The map could not open inside Jarvis."));
    else showError("Open the Jarvis desktop app to use its integrated map.");
    return;
  }
  if (type === "task_update") {
    taskCard.hidden = false;
    const active = ["planning", "running", "needs_input"].includes(String(msg.state));
    taskCard.dataset.active = String(active);
    taskControl.textContent = active ? "Stop task" : "Hide";
    taskMessage.textContent = `${String(msg.state).replace(/_/g, " ")} · ${Number(msg.completed || 0)}/${Number(msg.total || 0)} steps\n${String(msg.message || "")}`;
    if (currentState === "idle" || currentState === "listening") statusEl.textContent = `Task: ${String(msg.state).replace(/_/g, " ")}${msg.message ? " — " + String(msg.message) : ""}`;
    return;
  }
  if (type === "stopped") {
    // Stop also cancels background output for this turn; keeping the flag set
    // silently dropped later dispatch summaries and left the orb on "speaking".
    suppressReply = false;
    audioPlayer.stop();
    if (currentTurn) return;
    transition("listening");
    return;
  }
  if (type === "turn_start") { suppressReply = false; return; }
  if (suppressReply) return;

  if (type === "pcm_start") {
    pcmStreamId = msg.id as string;
    transition("speaking");
    audioPlayer.beginPCM();
  } else if (type === "pcm_chunk" && msg.id === pcmStreamId) {
    audioPlayer.enqueuePCM(msg.data as string, 44100);
  } else if (type === "pcm_end" && msg.id === pcmStreamId) {
    audioPlayer.endPCM();
  } else if (type === "audio") {
    const audioData = msg.data as string;
    console.log("[audio] received", audioData ? `${audioData.length} chars` : "EMPTY", "state:", currentState);
    if (audioData) {
      if (currentState !== "speaking") {
        transition("speaking");
      }
      audioPlayer.enqueue(audioData);
    } else {
      // TTS failed — no audio but the reply must still be readable.
      console.warn("[audio] no data received, returning to idle");
      if (msg.text) showReplyCaption(String(msg.text));
      transition("idle");
    }
    // Log text for debugging
    if (msg.text) console.log("[JARVIS]", msg.text);
  } else if (type === "status") {
    const state = msg.state as string;
    if (state === "thinking" && currentState !== "thinking") {
      transition("thinking");
    } else if (state === "working") {
      // Task spawned — show thinking with a different label
      transition("thinking");
      statusEl.textContent = "working...";
    } else if (state === "idle") {
      suppressReply = false;
      transition("idle");
    }
  } else if (type === "text") {
    // Text fallback when TTS fails — must stay visible, not only in the console.
    showReplyCaption(String(msg.text || ""));
    if (currentState === "speaking") transition("idle");
    console.log("[JARVIS]", msg.text);
  } else if (type === "task_spawned") {
    console.log("[task]", "spawned:", msg.task_id, msg.prompt);
  } else if (type === "task_complete") {
    console.log("[task]", "complete:", msg.task_id, msg.status, msg.summary);
  }
});

// ---------------------------------------------------------------------------
// Kick off
// ---------------------------------------------------------------------------

// Check phone-call privacy before acquiring the physical microphone. If the
// backend is unavailable, keep the microphone closed until status is known.
requestAnimationFrame(() => { void (async () => {
  if (!authToken) { updateStatus(currentState); return; }
  const observedEvents = phonePrivacyEvents;
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch('/api/agent/phone-privacy/status', {
        headers: {'Authorization': 'Bearer ' + authToken},
        cache: 'no-store',
      });
      if (!response.ok) throw new Error('Phone privacy status unavailable');
      const status = await response.json() as {active?: boolean};
      if (phonePrivacyEvents !== observedEvents) return;
      applyPhoneCallPrivacy(status.active === true);
      if (!isMuted && !phoneCallActive) {
        voiceInput.start();
        transition('listening');
      }
      return;
    } catch {
      if (phonePrivacyEvents !== observedEvents) return;
      if (attempt >= 3) {
        // Fail closed: no microphone until the call state is known. The error
        // stays visible instead of fading after five seconds.
        microphoneStarted = false;
        microphoneError = "Mikrofon bleibt aus: Telefonstatus nicht verfügbar.";
        updateStatus(currentState);
        showError('Phone privacy status unavailable; laptop microphone remains off. Restart Jarvis.', true);
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 1000 * 2 ** attempt));
    }
  }
})(); });

// Resume AudioContext on ANY user interaction (browser autoplay policy)
function ensureAudioContext() {
  const ctx = audioPlayer.getAnalyser().context as AudioContext;
  if (ctx.state === "suspended") {
    ctx.resume().then(() => console.log("[audio] context resumed"));
  }
}
document.addEventListener("click", ensureAudioContext);
document.addEventListener("touchstart", ensureAudioContext);
document.addEventListener("keydown", ensureAudioContext, { once: true });

// Try to resume audio context on load
ensureAudioContext();

// ---------------------------------------------------------------------------
// UI Controls
// ---------------------------------------------------------------------------

const btnMute = document.getElementById("btn-mute")!;
const btnMenu = document.getElementById("btn-menu")!;
const menuDropdown = document.getElementById("menu-dropdown")!;
const btnRestart = document.getElementById("btn-restart")!;
const btnFixSelf = document.getElementById("btn-fix-self")!;

function renderMuteButton() {
  btnMute.classList.toggle("muted", isMuted);
  btnMute.setAttribute("aria-pressed", String(isMuted));
  const action = isMuted ? "Mikrofon einschalten" : "Mikrofon stummschalten";
  btnMute.setAttribute("aria-label", action);
  btnMute.setAttribute("title", action);
  updateStatus(currentState);
}
renderMuteButton();

btnMute.addEventListener("click", (e) => {
  e.stopPropagation();
  isMuted = !isMuted;
  localStorage.setItem("jarvis_mic_muted", String(isMuted));
  renderMuteButton();
  if (isMuted) {
    microphoneStarted = false;
    voiceInput.stop();
  } else if (phoneCallActive) {
    voiceInput.stop();
    updateStatus(currentState);
  } else if (currentState !== "thinking" && currentState !== "speaking") {
    voiceInput.start();
    transition("listening");
  } else {
    voiceInput.start();
    voiceInput.resume();
  }
});

btnMenu.addEventListener("click", (e) => {
  e.stopPropagation();
  const open = menuDropdown.style.display === "none";
  menuDropdown.style.display = open ? "block" : "none";
  btnMenu.setAttribute("aria-expanded", String(open));
});

document.addEventListener("click", () => {
  menuDropdown.style.display = "none";
  btnMenu.setAttribute("aria-expanded", "false");
});

btnRestart.addEventListener("click", async (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  if (!authToken) {
    statusEl.textContent = "Restart requires the Jarvis desktop app.";
    return;
  }
  statusEl.textContent = "restarting...";
  try {
    const response = await fetch("/api/restart", {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    // Give the old process time to exit, then wait until the new one answers.
    await new Promise(resolve => setTimeout(resolve, 3000));
    for (let attempt = 0; attempt < 40; attempt++) {
      try {
        const health = await fetch("/api/health", { cache: "no-store" });
        if (health.ok) { window.location.reload(); return; }
      } catch { /* backend is still starting */ }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    statusEl.textContent = "Restart did not complete. Close and reopen Jarvis.";
  } catch {
    statusEl.textContent = "Restart failed. Close and reopen Jarvis.";
  }
});

btnFixSelf.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  // Activate Codex work mode on the WebSocket session.
  if (!socket.send({ type: "fix_self" })) {
    statusEl.textContent = "Jarvis is offline. Work mode was not started.";
    return;
  }
  statusEl.textContent = "entering work mode...";
});

// Settings button
const btnSettings = document.getElementById("btn-settings")!;
for (const view of ['memory', 'calendar'] as const) {
  document.getElementById('btn-custom-' + view)?.addEventListener('click', (event) => {
    event.stopPropagation();
    menuDropdown.style.display = 'none';
    closeSettings();
    void openPersonalPanel(view);
  });
}
btnSettings.addEventListener("click", (e) => {
  e.stopPropagation();
  menuDropdown.style.display = "none";
  openSettings();
});

// First-time setup detection — check after a short delay for server readiness
setTimeout(() => {
  if (dashboardMode) openSettings();
  else checkFirstTimeSetup();
}, 2000);

