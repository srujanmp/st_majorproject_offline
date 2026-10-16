// Runs on the browser's audio thread: passes each block of microphone samples
// to the page, which collects them until the second tap.
class RecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}

registerProcessor('recorder', RecorderProcessor);
