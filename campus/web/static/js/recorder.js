// Microphone recorder that produces a WAV file (16 kHz, mono, 16-bit),
// the format the offline speech model (Vosk) expects.

const TARGET_RATE = 16000;

class Recorder {
  constructor(onLevel) {
    this.onLevel = onLevel || (() => {});
  }

  async start() {
    if (!navigator.mediaDevices || !window.AudioWorkletNode) {
      throw new Error('This browser cannot record audio. Try Chrome, Edge or Firefox.');
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      console.error(e);
      throw new Error('Microphone permission was blocked or no microphone was found. Allow it in the address bar and try again.');
    }
    this.context = new AudioContext();
    await this.context.audioWorklet.addModule('/static/js/recorder-worklet.js');
    this.source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, 'recorder');
    this.chunks = [];
    this.node.port.onmessage = (event) => {
      this.chunks.push(event.data);
      let sum = 0;
      for (const s of event.data) sum += s * s;
      this.onLevel(Math.min(1, Math.sqrt(sum / event.data.length) * 6));
    };
    this.source.connect(this.node);
    this.node.connect(this.context.destination); // outputs silence; keeps the node running
  }

  // Stop and return { wav: Blob, seconds: number }.
  async stop() {
    this.node.port.onmessage = null;
    this.source.disconnect();
    this.node.disconnect();
    this.stream.getTracks().forEach((t) => t.stop());
    const rate = this.context.sampleRate;
    await this.context.close();
    this.onLevel(0);

    const length = this.chunks.reduce((n, c) => n + c.length, 0);
    const samples = new Float32Array(length);
    let offset = 0;
    for (const c of this.chunks) {
      samples.set(c, offset);
      offset += c.length;
    }
    const pcm = downsample(samples, rate, TARGET_RATE);
    return { wav: encodeWav(pcm, TARGET_RATE), seconds: pcm.length / TARGET_RATE };
  }
}

// Average groups of samples to go from e.g. 48 kHz down to 16 kHz.
function downsample(input, fromRate, toRate) {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const output = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < output.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    output[i] = sum / Math.max(1, end - start);
  }
  return output;
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset, s) => [...s].forEach((ch, i) => view.setUint8(offset + i, ch.charCodeAt(0)));
  text(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);   // header size
  view.setUint16(20, 1, true);    // PCM
  view.setUint16(22, 1, true);    // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);   // 16-bit
  text(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}
