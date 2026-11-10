import type { VoiceInput, TranscriptMeta, MicState } from './voice';
import { createDesktopVoiceInput } from './voice-desktop';
import { VoiceActivity } from './voice-activity';

export function replyDelay(): number {
  const value = Number(localStorage.getItem('jarvis_reply_delay_ms') ?? '0');
  return [0,100,200,300,500,1000,2000,3500,5000].includes(value) ? value : 0;
}

export function createStreamingVoiceInput(onTranscript: (text: string, meta?: TranscriptMeta) => void,
  onError: (text: string) => void, onSpeechStart: () => void,
  reportMic: (state: MicState) => void = () => {}): VoiceInput {
  let enabled=false, paused=false, starting=false, epoch=0;
  let socket: WebSocket | null=null, media: MediaStream | null=null, context: AudioContext | null=null;
  let processor: AudioWorkletNode | null=null;
  let fallback: VoiceInput | null=null;
  let ready=false, active='', loudFrames=0, quietFrames=0, duration=0, speechStartNotified=false;
  let pre: ArrayBuffer[]=[];
  // Keep the first three seconds while the authenticated STT session starts;
  // otherwise speech begun during the handshake would be silently discarded.
  let startup: ArrayBuffer[]=[];
  const turns: {id: string; text?: string; end?: number; final?: number}[]=[];
  let readyTimer: ReturnType<typeof setTimeout> | null=null;
  let activity=new VoiceActivity();

  function release() {
    epoch++;
    if (readyTimer) clearTimeout(readyTimer);
    readyTimer=null;
    ready=false;
    socket?.close(); socket=null;
    processor?.disconnect(); processor=null;
    media?.getTracks().forEach(t=>t.stop()); media=null;
    void context?.close(); context=null;
    pre=[]; startup=[]; active=''; loudFrames=0; quietFrames=0; speechStartNotified=false; turns.length=0;
    activity=new VoiceActivity();
  }
  function degrade() {
    if (!enabled || paused || fallback) return;
    release();
    onError('Live speech recognition unavailable. File recognition is active; please repeat the last request.');
    fallback=createDesktopVoiceInput(onTranscript,onError,onSpeechStart,reportMic);
    fallback.start();
  }
  function deliver() {
    if (active || !enabled || paused || !turns.length || turns.some(t=>t.text===undefined)) return;
    const finished=turns.splice(0);
    const text=finished.map(t=>t.text).filter(Boolean).join(' ').trim();
    if (!text) return;
    const last=finished[finished.length-1];
    const stop=finished.some(t=>/^(?:(?:jarvis|please)[, ]+)?(?:stop|stopp|stop talking|be quiet|halt)[.!? ]*$/i.test(t.text || ''));
    onTranscript(stop ? 'stop' : text, {id:last.id,speechEnd:last.end ?? performance.now(),sttFinal:last.final ?? performance.now()});
  }
  function frame(buffer: ArrayBuffer) {
    if (!enabled || paused) return;
    const samples=new Int16Array(buffer);
    let energy=0;
    for (const value of samples) energy+=(value/32768)**2;
    const rms=Math.sqrt(energy/samples.length);
    const loud=activity.speech(rms,Boolean(active),localStorage.getItem('jarvis_mic_sensitivity') || 'auto');
    loudFrames=loud ? loudFrames+1 : 0;
    if (!ready || !socket) {
      startup.push(buffer);
      if (startup.length>150) startup.shift();
      // Barge-in must not wait for the STT handshake to finish. Audio is
      // retained above and replayed once the session becomes ready.
      if (loudFrames>=4 && !speechStartNotified) {
        speechStartNotified=true;
        onSpeechStart();
      }
      return;
    }
    if(turns.some(t=>t.end !== undefined && t.text === undefined && performance.now()-t.end>20000)) { degrade(); return; }
    if (socket.bufferedAmount>192000) { degrade(); return; }
    if (!active) {
      pre.push(buffer); if (pre.length>12) pre.shift();
      if (loudFrames<4) { deliver(); return; }
      active=crypto.randomUUID(); duration=0; quietFrames=0;
      turns.push({id:active});
      if (turns.length>8) { degrade(); return; }
      if (!speechStartNotified) onSpeechStart();
      speechStartNotified=true;
      socket.send(JSON.stringify({type:'start',id:active}));
      for (const data of pre) socket.send(data);
      duration=pre.length*20; pre=[];
      return;
    }
    socket.send(buffer); duration+=20;
    quietFrames=loud ? 0 : quietFrames+1;
    if (quietFrames*20>=160+replyDelay() || duration>=120000) {
      const turn=turns.find(t=>t.id===active)!;
      turn.end=performance.now()-quietFrames*20;
      socket.send(JSON.stringify({type:'commit',id:active}));
      active=''; loudFrames=0; quietFrames=0;
      speechStartNotified=false;
      deliver();
    }
  }
  async function begin() {
    if (!enabled || paused || starting || media || fallback) return;
    starting=true;
    const generation=epoch;
    try {
      const sttToken = localStorage.getItem('jarvis_auth_token') || '';
      if (!sttToken) {
        console.warn("[stt] No auth token in storage; switching to fallback");
        degrade();
        return;
      }
      // Warm up the authenticated live recognizer while Windows grants the
      // microphone and the audio worklet loads. The startup audio buffer below
      // preserves speech if the first frames arrive before this socket is ready.
      const proto=location.protocol==='https:' ? 'wss:' : 'ws:';
      const delay=localStorage.getItem('jarvis_stt_delay') || 'minimal';
      const accuracy=['minimal','low','medium','high','xhigh'].includes(delay) ? delay : 'minimal';
      socket=new WebSocket(`${proto}//${location.host}/ws/stt`, ["jarvis", "jarvis.auth." + sttToken, `jarvis.stt.delay.${accuracy}`]);
      readyTimer=setTimeout(()=>{if(epoch===generation) degrade();},20000);
      socket.onmessage=event=>{
        if(epoch!==generation) return;
        try {
          const msg=JSON.parse(event.data);
          if(msg.type==='ready') {
            ready=true; if(readyTimer) clearTimeout(readyTimer);
            const queued=startup; startup=[];
            for (const data of queued) {
              if(epoch!==generation || !ready || !socket) break;
              frame(data);
            }
          }
          else if(msg.type==='error') degrade();
          else if(msg.type==='partial') {
            window.dispatchEvent(new CustomEvent('jarvis-partial',{detail:{id:msg.id,text:msg.text}}));
          } else if(msg.type==='final') {
            const turn=turns.find(t=>t.id===msg.id);
            if(turn && turn.text===undefined) { turn.text=String(msg.text); turn.final=performance.now(); deliver(); }
          }
        } catch { degrade(); }
      };
      socket.onclose=event=>{
        if(epoch!==generation) return;
        if(event.code===4004) { paused=true; release(); return; }
        degrade();
      };
      socket.onerror=()=>{if(epoch===generation) degrade();};
      const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      if (epoch!==generation || !enabled || paused) { stream.getTracks().forEach(t=>t.stop()); return; }
      media=stream;
      reportMic('started');
      context=new AudioContext({sampleRate:24000});
      await context.audioWorklet.addModule('/pcm-capture.js');
      if (epoch!==generation || !context) return;
      processor=new AudioWorkletNode(context,'pcm-capture');
      const gain=context.createGain(); gain.gain.value=0;
      context.createMediaStreamSource(stream).connect(processor);
      processor.connect(gain).connect(context.destination);
      processor.port.onmessage=event=>frame(event.data);
      await context.resume();
      if (epoch!==generation) return;
    } catch { if(epoch===generation) { reportMic('error'); degrade(); } }
    finally { starting=false; if(enabled && !paused && !media && !fallback) void begin(); }
  }
  return {
    start() {enabled=true; paused=false; if(fallback) fallback.start(); else void begin();},
    stop() {enabled=false; release(); fallback?.stop(); fallback=null;},
    pause() {paused=true; release(); fallback?.pause();},
    resume() {paused=false; if(enabled) { if(fallback) fallback.resume(); else void begin(); }},
    onMicState(cb) {reportMic=cb; fallback?.onMicState(cb);}
  };
}
