/** RMS speech gate with a background estimate and softer speech-ending threshold. */
export class VoiceActivity {
  private noise = 0.003;
  private samples: number[] = [];

  calibrate(rms: number) {
    if (!Number.isFinite(rms)) return;
    this.samples.push(Math.max(0,rms));
    if (this.samples.length>50) this.samples.shift();
    const sorted=[...this.samples].sort((a,b)=>a-b);
    // Lower quartile avoids training the floor on occasional speech/clicks.
    this.noise=Math.min(0.016,sorted[Math.floor((sorted.length-1)*.25)]);
  }

  speech(rms: number, active: boolean, mode='auto'): boolean {
    const scale=mode==='sensitive' ? .65 : mode==='noisy' ? 1.4 : 1;
    const attack=Math.max(.006,this.noise*2.8)*scale;
    const threshold=active ? attack*.65 : attack;
    const loud=Number.isFinite(rms) && rms>threshold;
    if (!active && !loud) this.calibrate(rms);
    return loud;
  }
}
