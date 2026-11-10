const ts = require('../frontend/node_modules/typescript');
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = ts.transpileModule(fs.readFileSync('frontend/src/voice-desktop.ts','utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
let now=0, level=0, acquired=0, stopped=0, sent=0, hold=false; const pending=[];
const intervals = new Map(); let intervalId=0;
const track={enabled:true, stop(){stopped++;}};
const media={getTracks:()=>[track],getAudioTracks:()=>[track]};
class Recorder {
  constructor(){this.state='inactive';}
  start(){this.state='recording';}
  stop(){this.state='inactive';this.ondataavailable?.({data:new Blob(['sample'])});void this.onstop?.();}
}
class Context {
  async resume(){} async close(){}
  createAnalyser(){return {fftSize:2048,getFloatTimeDomainData(buffer){buffer.fill(track.enabled?level:0);}};}
  createMediaStreamSource(){return {connect(){}};}
}
const activity={exports:{}}; vm.runInNewContext(ts.transpileModule(fs.readFileSync('frontend/src/voice-activity.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,activity);
const sandbox={require:()=>activity.exports,exports:{},navigator:{mediaDevices:{getUserMedia:async()=>{acquired++;return media;}}},AudioContext:Context,MediaRecorder:Recorder,
  performance:{now:()=>now},crypto:{randomUUID:()=>String(now)},Float32Array,Blob,AbortController,setTimeout,clearTimeout,Date:{now:()=>now},localStorage:{getItem:key=>key==='jarvis_reply_delay_ms'?'2000':''},
  setInterval(fn){intervals.set(++intervalId,fn);return intervalId;},clearInterval(id){intervals.delete(id);},
  fetch:async()=>{sent++;if(hold) await new Promise(resolve=>pending.push(resolve));return {ok:true,json:async()=>({text:'Open Chrome'})};}};
vm.runInNewContext(code,sandbox);
let heard=0, interruptions=0;
const voice=sandbox.exports.createDesktopVoiceInput((text,meta)=>{assert.ok(meta.sttFinal-meta.speechEnd>=2160);heard++;}, msg=>{throw new Error(msg);},()=>interruptions++);
const settle=async()=>{for(let i=0;i<8;i++) await Promise.resolve();};
async function advance(ms,volume){level=volume;for(let i=0;i<ms;i+=25){now+=25;for(const fn of [...intervals.values()]) fn();await settle();}}
(async()=>{
  voice.start();await settle();
  await advance(5000,0);assert.equal(sent,0,'Silence must never be transcribed');
  await advance(150,.05);
  assert.equal(interruptions,1,'A short stop utterance must interrupt after 150ms without waiting for STT');
  await advance(150,.05);await advance(1000,0);
  assert.equal(heard,0,'A thinking pause must not submit an incomplete sentence');
  assert.equal(interruptions,1,'Speech must notify the player before transcription');
  await advance(400,.05);await advance(2200,0);
  assert.equal(heard,1,'Speech across a pause should produce one complete utterance');
  hold=true;
  await advance(300,.05);await advance(2200,0);
  assert.equal(sent,2);
  await advance(300,.05);
  pending.shift()();await settle();
  assert.equal(heard,1,'A previous transcript must not interrupt speech still in progress');
  await advance(2200,0);
  assert.equal(sent,3,'Microphone must capture while transcription is pending');
  pending.shift()();await settle();
  assert.equal(heard,2,'Consecutive segments must be delivered as one ordered turn');
  hold=false;
  voice.pause();assert.equal(track.enabled,false);assert.equal(stopped,0);
  voice.resume();assert.equal(acquired,1,'Resuming after a reply should reuse the device');
  hold=true;
  await advance(300,.05);await advance(2200,0);
  assert.equal(sent,4);
  voice.stop();
  pending.shift()();await settle();
  assert.equal(heard,2,'A late transcription must not execute after mute');
  assert.equal(stopped,1,'User mute must release the device');
  await advance(1000,.05);assert.equal(sent,4,'Muted audio must not be uploaded');
  console.log('Voice checks passed: silence suppression, endpoint delay, warm resume, hard mute.');
})().catch(error=>{console.error(error);process.exitCode=1;});
