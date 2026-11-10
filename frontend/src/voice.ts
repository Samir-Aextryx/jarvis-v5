/**
 * Voice input (Web Speech API) and audio output (AudioContext) for JARVIS.
 */
import { createStreamingVoiceInput } from "./voice-stream";

// ---------------------------------------------------------------------------
// Speech Recognition
// ---------------------------------------------------------------------------

export interface VoiceInput {
  start(): void;
  stop(): void;
  pause(): void;
  resume(): void;
  onMicState(cb: (state: MicState) => void): void;
}
export type MicState = "started" | "error";
export interface TranscriptMeta { id: string; speechEnd: number; sttFinal: number; }

export function createVoiceInput(
  onTranscript: (text: string, meta?: TranscriptMeta) => void,
  onError: (msg: string) => void,
  onSpeechStart: () => void = () => {},
  onMicState: (state: MicState) => void = () => {}
): VoiceInput {
  // Keep recognition consistent across the installed app and the local browser:
  // continuous PCM streaming handles German/English switching, partials and barge-in.
  return createStreamingVoiceInput(onTranscript, onError, onSpeechStart, onMicState);
}

// ---------------------------------------------------------------------------
// Audio Player
// ---------------------------------------------------------------------------

export interface AudioPlayer {
  enqueue(base64: string): Promise<void>;
  beginPCM(): void;
  enqueuePCM(base64: string, sampleRate: number): void;
  endPCM(): void;
  stop(): void;
  getAnalyser(): AnalyserNode;
  onFinished(cb: () => void): void;
  onFirstAudio(cb: () => void): void;
}

export function createAudioPlayer(): AudioPlayer {
  const audioCtx = new AudioContext();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.8;
  analyser.connect(audioCtx.destination);

  const queue: AudioBuffer[] = [];
  let isPlaying = false;
  let currentSource: AudioBufferSourceNode | null = null;
  let finishedCallback: (() => void) | null = null;
  let generation = 0;
  let pcmFinished = false;
  let nextPCMTime = 0;
  let firstAudioCallback: (() => void) | null = null;
  let firstAudioScheduled = false;
  const pcmSources = new Set<AudioBufferSourceNode>();

  function stopAudio() {
    generation++;
    queue.length = 0;
    const previous = currentSource;
    currentSource = null;
    try { previous?.stop(); } catch { /* already stopped */ }
    for (const source of pcmSources) { source.onended = null; try { source.stop(); } catch { /* ended */ } }
    pcmSources.clear();
    pcmFinished = false;
    nextPCMTime = 0;
    isPlaying = false;
    firstAudioScheduled = false;
  }

  function playNext() {
    if (queue.length === 0) {
      isPlaying = false;
      currentSource = null;
      finishedCallback?.();
      return;
    }

    isPlaying = true;
    const buffer = queue.shift()!;
    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(analyser);
    currentSource = source;

    source.onended = () => {
      if (currentSource === source) {
        playNext();
      }
    };

    source.start();
    firstAudioCallback?.();
  }

  return {
    async enqueue(base64: string) {
      const epoch = generation;
      // Resume audio context (browser autoplay policy)
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      try {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer.slice(0));
        if (epoch !== generation) return;
        queue.push(audioBuffer);
        if (!isPlaying) playNext();
      } catch (err) {
        console.error("[audio] decode error:", err);
        // Skip bad audio, continue
        if (!isPlaying && queue.length > 0) playNext();
      }
    },

    beginPCM() {
      stopAudio();
      void audioCtx.resume();
    },
    enqueuePCM(base64: string, sampleRate: number) {
      const raw = atob(base64);
      if (!raw.length || raw.length % 2 || ![24000, 44100].includes(sampleRate)) return;
      const buffer = audioCtx.createBuffer(1, raw.length / 2, sampleRate);
      const samples = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i++) {
        const value = raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8);
        samples[i] = (value >= 32768 ? value - 65536 : value) / 32768;
      }
      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(analyser);
      pcmSources.add(source);
      source.onended = () => {
        pcmSources.delete(source);
        source.disconnect();
        if (pcmFinished && pcmSources.size === 0) finishedCallback?.();
      };
      const start = Math.max(audioCtx.currentTime + 0.015, nextPCMTime);
      source.start(start);
      if (!firstAudioScheduled) {
        firstAudioScheduled = true;
        const epoch = generation;
        setTimeout(() => { if(epoch === generation) firstAudioCallback?.(); }, Math.max(0,(start-audioCtx.currentTime)*1000));
      }
      nextPCMTime = start + buffer.duration;
    },
    endPCM() {
      pcmFinished = true;
      if (pcmSources.size === 0) finishedCallback?.();
    },
    stop: stopAudio,

    getAnalyser() {
      return analyser;
    },

    onFinished(cb: () => void) {
      finishedCallback = cb;
    },
    onFirstAudio(cb: () => void) { firstAudioCallback = cb; },
  };
}
