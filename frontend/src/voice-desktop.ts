import type { VoiceInput, TranscriptMeta, MicState } from "./voice";
import { VoiceActivity } from './voice-activity';

/** Silence-delimited microphone recording for the Electron app. */
export function createDesktopVoiceInput(onTranscript: (text: string, meta?: TranscriptMeta) => void, onError: (msg: string) => void, onSpeechStart: () => void = () => {}, reportMic: (state: MicState) => void = () => {}): VoiceInput {
  let enabled = false;
  let paused = false;
  let acquiring = false;
  let media: MediaStream | null = null;
  let context: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let recorder: MediaRecorder | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  const requests = new Set<AbortController>();
  const transcripts = new Map<number, string>();
  let segmentId = 0;
  let turnSpeechEnd = 0;
  let speechActive = false;
  let incompleteTurn = false;
  let activity = new VoiceActivity();

  function deliver() {
    if (requests.size || speechActive || !enabled || paused) return;
    if (incompleteTurn) {
      transcripts.clear();
      incompleteTurn = false;
      return;
    }
    const parts = [...transcripts.entries()].sort((a, b) => a[0] - b[0]).map(([, text]) => text);
    const stop = parts.some(text => /^(?:(?:jarvis|please)[, ]+)?(?:stop|stopp|stop talking|be quiet|halt)[.!? ]*$/i.test(text));
    const text = stop ? "stop" : parts.join(" ");
    transcripts.clear();
    if (text) onTranscript(text, {id: crypto.randomUUID(), speechEnd: turnSpeechEnd, sttFinal: performance.now()});
  }
  let generation = 0;

  function cancel(releaseDevice = true) {
    generation++;
    if (timer) clearInterval(timer);
    timer = null;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    recorder = null;
    for (const request of requests) request.abort();
    requests.clear();
    transcripts.clear();
    incompleteTurn = false;
    speechActive = false;
    activity = new VoiceActivity();
    if (releaseDevice || !analyser) {
      media?.getTracks().forEach(track => track.stop());
      media = null;
      void context?.close();
      context = null;
      analyser = null;
    } else {
      // Pause capture during Jarvis speech; keep the device ready for the next turn.
      media?.getAudioTracks().forEach(track => { track.enabled = false; });
    }
  }

  function record() {
    if (!enabled || paused || !media || !analyser || recorder) return;
    const epoch = generation;
    const current = new MediaRecorder(media, { mimeType: "audio/webm;codecs=opus", audioBitsPerSecond: 32000 });
    recorder = current;
    const chunks: BlobPart[] = [];
    const samples = new Float32Array(analyser.fftSize);
    let speechFrames = 0;
    let consecutiveSpeechFrames = 0;
    let notifiedSpeech = false;
    let lastSpeech = Date.now();
    const started = Date.now();
    current.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    current.onstop = async () => {
      if (epoch !== generation) return;
      if (timer) clearInterval(timer);
      timer = null;
      recorder = null;
      if (!enabled || paused) return;
      speechActive = false;
      if (speechFrames < 6) { record(); deliver(); return; }
      if (requests.size >= 2) {
        incompleteTurn = true;
        onError("Speech recognition is taking too long. Please wait a moment and repeat the last phrase.");
        record();
        return;
      }
      turnSpeechEnd = performance.now() - Math.max(0, Date.now() - lastSpeech);
      const id = ++segmentId;
      const request = new AbortController();
      requests.add(request);
      const timeout = setTimeout(() => request.abort(), 20000);
      record();
      try {
        const response = await fetch("/api/transcribe", {
          method: "POST",
          headers: { "Content-Type": "audio/webm", Authorization: `Bearer ${localStorage.getItem("jarvis_auth_token") || ""}` },
          body: new Blob(chunks, { type: "audio/webm" }), signal: request.signal,
        });
        if (response.status === 423) {
          paused = true;
          cancel();
          return;
        }
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || `Spracherkennung: HTTP ${response.status}`);
        if (epoch === generation && enabled && !paused && result.text?.trim()) transcripts.set(id, result.text.trim());
      } catch (error) {
        if (epoch === generation) {
          incompleteTurn = true;
          onError("Speech recognition failed. Please repeat the complete request.");
        }
      } finally {
        clearTimeout(timeout);
        requests.delete(request);
        if (epoch === generation) deliver();
      }
    };
    current.start(250);
    timer = setInterval(() => {
      analyser?.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
      if (activity.speech(rms, speechActive, localStorage.getItem('jarvis_mic_sensitivity') || 'auto')) { speechActive = true; speechFrames++; consecutiveSpeechFrames++; lastSpeech = Date.now(); }
      else { consecutiveSpeechFrames = 0; }
      if (consecutiveSpeechFrames >= 6 && !notifiedSpeech) {
        notifiedSpeech = true;
        speechActive = true;
        onSpeechStart();
      }
      const silence = Date.now() - lastSpeech;
      const configured = Number(localStorage.getItem("jarvis_reply_delay_ms") ?? "0");
      const pauseMs = 160 + Math.max(0, Math.min(5000, Number.isFinite(configured) ? configured : 0));
      const idleSegment = speechFrames < 6 && silence > 300 && Date.now() - started > 1000;
      if (idleSegment || (speechFrames >= 6 && silence > pauseMs) || Date.now() - started > 120000) {
        if (current.state === "recording") current.stop();
      }
    }, 25);
  }

  async function begin() {
    if (!enabled || paused || acquiring || media) return;
    acquiring = true;
    const epoch = generation;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (!enabled || paused || epoch !== generation) { stream.getTracks().forEach(t => t.stop()); return; }
      media = stream;
      reportMic("started");
      context = new AudioContext();
      await context.resume();
      if (epoch !== generation || !context) return;
      analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      context.createMediaStreamSource(stream).connect(analyser);
      record();
    } catch {
      if (epoch !== generation) return;
      reportMic("error");
      enabled = false;
      cancel();
      onError("Mikrofon nicht verfügbar. Bitte den Mikrofonzugriff in Windows erlauben.");
    } finally {
      acquiring = false;
      if (enabled && !paused && !media) void begin();
    }
  }

  return {
    start() { enabled = true; paused = false; void begin(); },
    stop() { enabled = false; cancel(); },
    pause() { paused = true; cancel(false); },
    resume() {
      paused = false;
      if (enabled) {
        if (media) { media.getAudioTracks().forEach(track => { track.enabled = true; }); record(); }
        else void begin();
      }
    },
    onMicState(cb) { reportMic = cb; },
  };
}
