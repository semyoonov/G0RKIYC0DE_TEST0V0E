class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const settings = (options && options.processorOptions) || {};
    this.targetRate = settings.targetRate || 16000;
    this.frameSize = settings.frameSize || 640;
    this.pending = [];
    this.phase = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    if (sampleRate === this.targetRate) {
      this.append(input[0]);
    } else {
      this.appendResampled(input[0]);
    }
    return true;
  }

  appendResampled(channel) {
    const step = sampleRate / this.targetRate;
    const samples = [];
    let position = this.phase;
    while (position < channel.length) {
      const index = Math.floor(position);
      const fraction = position - index;
      const next = channel[Math.min(index + 1, channel.length - 1)];
      samples.push(channel[index] * (1 - fraction) + next * fraction);
      position += step;
    }
    this.phase = position - channel.length;
    this.append(samples);
  }

  append(samples) {
    for (let index = 0; index < samples.length; index += 1) {
      this.pending.push(samples[index]);
    }
    while (this.pending.length >= this.frameSize) {
      const chunk = this.pending.splice(0, this.frameSize);
      const pcm = new Int16Array(chunk.length);
      for (let index = 0; index < chunk.length; index += 1) {
        const value = Math.max(-1, Math.min(1, chunk[index]));
        pcm[index] = value < 0 ? value * 0x8000 : value * 0x7fff;
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
