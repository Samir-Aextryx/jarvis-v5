/* AudioWorklet: mono PCM at 24 kHz, 20 ms frames, no main-thread audio copies. */
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(480);
    this.index = 0;
    this.phase = 0;
    this.sum = 0;
    this.count = 0;
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const value of input) {
      this.sum += value;
      this.count++;
      this.phase += 24000;
      if (this.phase >= sampleRate) {
        this.phase -= sampleRate;
        const sample = Math.max(-1, Math.min(1, this.sum / this.count));
        this.sum = 0; this.count = 0;
        this.frame[this.index++] = sample < 0 ? sample * 32768 : sample * 32767;
        if (this.index === 480) {
          const buffer = this.frame.buffer;
          this.port.postMessage(buffer, [buffer]);
          this.frame = new Int16Array(480);
          this.index = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PCMCapture);
