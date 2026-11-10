const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
for(const rate of [24000,44100,48000]) {
  let Processor; const frames=[];
  class Base {constructor(){this.port={postMessage:b=>frames.push(new Int16Array(b))};}}
  vm.runInNewContext(fs.readFileSync('frontend/public/pcm-capture.js','utf8'),{
    AudioWorkletProcessor:Base,sampleRate:rate,Int16Array,Math,
    registerProcessor:(name,cls)=>{Processor=cls;}
  });
  const processor=new Processor();
  for(let i=0;i<rate;i+=128) processor.process([[new Float32Array(Math.min(128,rate-i)).fill(.5)]]);
  assert.equal(frames.length,50,`${rate}: exactly 50 frames per second`);
  assert.ok(frames.every(f=>f.length===480 && f.every(v=>v===16383)),'stable PCM level and framing');
}
console.log('PCM worklet: 24/44.1/48 kHz conversion and 20 ms frames passed.');
