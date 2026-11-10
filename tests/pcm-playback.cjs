const ts=require('../frontend/node_modules/typescript');
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=ts.transpileModule(fs.readFileSync('frontend/src/voice.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const nodes=[];let finished=0;
class Context {
  constructor(){this.currentTime=1;this.state='running';this.destination={};}
  createAnalyser(){return {connect(){}};}
  async resume(){}
  createBuffer(channels,length,rate){const samples=new Float32Array(length);return {duration:length/rate,getChannelData:()=>samples};}
  createBufferSource(){const source={connect(){},disconnect(){},start(time){this.startTime=time;},stop(){this.stopped=true;}};nodes.push(source);return source;}
}
const sandbox={exports:{},setTimeout,require:()=>({}),AudioContext:Context,Float32Array,Uint8Array,atob:s=>Buffer.from(s,'base64').toString('binary'),console};
vm.runInNewContext(code,sandbox);
const player=sandbox.exports.createAudioPlayer();player.onFinished(()=>finished++);
player.beginPCM();
const bytes=Buffer.from([0,128,255,127]).toString('base64');
player.enqueuePCM(bytes,44100);player.enqueuePCM(bytes,44100);
assert.equal(nodes[0].buffer.getChannelData(0)[0],-1);
assert.ok(nodes[1].startTime>=nodes[0].startTime+nodes[0].buffer.duration);
nodes[0].onended();assert.equal(finished,0,'Temporary gaps must not resume the microphone');
player.endPCM();assert.equal(finished,0,'Wait for queued sound to finish');
nodes[1].onended();assert.equal(finished,1);
player.beginPCM();player.enqueuePCM(bytes,44100);player.stop();assert.equal(nodes[2].stopped,true);assert.equal(nodes[2].onended,null);
console.log('PCM checks passed: signed samples, ordered scheduling, completion after playback, cancellation.');
