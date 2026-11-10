const ts=require('../frontend/node_modules/typescript');
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=ts.transpileModule(fs.readFileSync('frontend/src/voice-stream.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
let now=0,worklet,socket,heard=[],barge=0,released=0,fallbacks=0,id=0;
const tracks=[{stop(){released++;}}];
class Socket {constructor(_url,protocols){socket=this;this.protocols=protocols;this.bufferedAmount=0;this.sent=[];}send(x){this.sent.push(x);}close(){this.closed=true;}}
class Context {constructor(){this.audioWorklet={addModule:async()=>{}};this.destination={};}async resume(){}async close(){}createMediaStreamSource(){return {connect(){}};}createGain(){return {gain:{value:0},connect(){}};}}
class Worklet {constructor(){worklet=this;this.port={};}connect(n){return n;}disconnect(){}}
const activity={exports:{}}; vm.runInNewContext(ts.transpileModule(fs.readFileSync('frontend/src/voice-activity.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,activity);
const sandbox={exports:{},require:(name)=>name==='./voice-activity'?activity.exports:({createDesktopVoiceInput:()=>({start(){fallbacks++;},stop(){},resume(){},pause(){}})}),navigator:{mediaDevices:{getUserMedia:async()=>{assert.ok(socket,'Live STT connection should start before requesting microphone permission');return {getTracks:()=>tracks};}}},AudioContext:Context,AudioWorkletNode:Worklet,WebSocket:Socket,location:{protocol:'http:',host:'localhost'},localStorage:{getItem:(key)=>key==='jarvis_auth_token'?'test-token':null},crypto:{randomUUID:()=>`turn-${++id}`},performance:{now:()=>now},setTimeout,clearTimeout,Int16Array,console,window:{dispatchEvent(){}},CustomEvent:class{}};
vm.runInNewContext(code,sandbox);
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function frame(loud=true){now+=20;const pcm=new Int16Array(480).fill(loud?3000:0);worklet.port.onmessage({data:pcm.buffer});}
function event(x){socket.onmessage({data:JSON.stringify(x)});}
(async()=>{
 const voice=sandbox.exports.createStreamingVoiceInput((text,meta)=>heard.push({text,meta}),()=>{},()=>barge++);
 assert.equal(sandbox.exports.replyDelay(),0);
 voice.start();await settle();
 assert.ok(socket.protocols.includes('jarvis.stt.delay.minimal'),'Fresh settings should use the lowest-latency transcription mode');
 for(let i=0;i<4;i++)frame();
 assert.equal(barge,1,'Barge-in should not wait for the STT connection handshake');
 event({type:'ready'});
 for(let i=0;i<6;i++)frame();
 assert.equal(barge,1,'Replaying buffered startup speech must not interrupt twice');
 assert.ok(socket.sent.some(x=>x instanceof ArrayBuffer),'Frames must stream before end of speech');
 for(let i=0;i<8;i++)frame(false);
 assert.ok(socket.sent.some(x=>typeof x==='string'&&JSON.parse(x).type==='commit'),'Commit at VAD end without 2-second delay');
 event({type:'partial',id:'turn-1',text:'Open'});assert.equal(heard.length,0);
 event({type:'final',id:'turn-1',text:'Open Chrome'});event({type:'final',id:'turn-1',text:'Open Chrome'});
 assert.equal(heard.length,1,'Duplicate final must not execute twice');
 for(let i=0;i<6;i++)frame();assert.equal(barge,2,'Barge-in is independent of STT final');
 voice.stop();event({type:'final',id:'turn-2',text:'Open Outlook'});
 assert.equal(heard.length,1,'No late transcript after mute');assert.equal(released,1);
 console.log('Live capture: frames before speech end, 160 ms VAD, minimal STT delay, zero added reply delay, deduplication, barge-in and mute passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
