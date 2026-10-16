// Tap to speak, tap again to send. The recording is turned into text on this
// computer (Vosk), the answer is found in the local knowledge base, and the
// browser reads it aloud with a voice installed on this computer.

const MAX_SECONDS = 30;
const LANG = 'en-IN';

let recorder = null;
let recording = false;
let timer = null;
let lastAnswer = '';

// ---- Screens ----------------------------------------------------------------

function show(screen) {
  for (const id of ['idle', 'processing', 'answer']) $(id).hidden = id !== screen;
  $('typeForm').hidden = screen === 'processing';
}

function setStep(name, state) {
  document.querySelector(`.steps li[data-step="${name}"]`).className = state || '';
}

function setRecording(on) {
  recording = on;
  $('mic').classList.toggle('on', on);
  $('mic').setAttribute('aria-label', on ? 'Tap when you are done' : 'Tap to speak');
  $('micHint').textContent = on ? 'Listening… tap when you’re done' : 'Tap to speak';
  $('timer').textContent = '';
}

function fail(message) {
  show('idle');
  showError(message);
}

// ---- Recording -----------------------------------------------------------------

async function startRecording() {
  stopSpeaking();
  hideError();
  show('idle');
  $('mic').disabled = true;
  recorder = new Recorder((level) => $('mic').style.setProperty('--level', level.toFixed(2)));
  try {
    await recorder.start();
  } catch (e) {
    $('mic').disabled = false;
    return fail(e.message);
  }
  $('mic').disabled = false;
  setRecording(true);
  const started = Date.now();
  timer = setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    $('timer').textContent = `${seconds}s`;
    if (seconds >= MAX_SECONDS) stopRecording();
  }, 250);
}

async function stopRecording() {
  if (!recording) return;
  clearInterval(timer);
  setRecording(false);
  const { wav, seconds } = await recorder.stop();
  if (seconds < 0.5) return fail('That was too short. Tap, ask your question, then tap again.');

  show('processing');
  $('pQuestion').textContent = '';
  setStep('hearing', 'active');
  setStep('finding', '');
  let text;
  try {
    const res = await fetch('/api/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav });
    if (res.status === 401) return (location.href = '/');
    if (res.status === 403) return (location.href = '/face');
    if (!res.ok) return fail(await errorText(res));
    text = (await res.json()).text;
  } catch (e) {
    console.error(e);
    return fail('Could not reach the app. Is it still running?');
  }
  if (!text) return fail('I couldn’t make out any words. Try again a little closer to the microphone.');
  ask(text);
}

// ---- Asking ------------------------------------------------------------------------

async function ask(question) {
  hideError();
  show('processing');
  $('pQuestion').textContent = `“${question}”`;
  setStep('hearing', 'done');
  setStep('finding', 'active');
  try {
    const result = await api('POST', '/api/ask', { question });
    showAnswer(question, result);
  } catch (e) {
    if (e.message === 'Face check required.') return (location.href = '/face');
    fail(e.message);
  }
}

function showAnswer(question, result) {
  lastAnswer = result.answer;
  $('aQuestion').textContent = `“${question}”`;
  $('aText').textContent = result.answer;
  $('aSources').textContent = result.sources.length ? 'From: ' + result.sources.join(', ') : '';
  show('answer');
  speak(result.answer);
}

// ---- Text to speech (voices installed on this computer) -------------------------------

function pickVoice() {
  const voices = speechSynthesis.getVoices().filter((v) => v.localService && v.lang.startsWith('en'));
  return (
    voices.find((v) => v.lang === LANG) ||
    voices.find((v) => v.lang === 'en-GB') ||
    voices.find((v) => v.lang === 'en-US') ||
    voices[0] ||
    null
  );
}

function voicesReady() {
  return new Promise((resolve) => {
    if (speechSynthesis.getVoices().length) return resolve();
    speechSynthesis.addEventListener('voiceschanged', resolve, { once: true });
    setTimeout(resolve, 1000);
  });
}

async function speak(text) {
  if ('speechSynthesis' in window) await voicesReady();
  const voice = 'speechSynthesis' in window ? pickVoice() : null;
  $('noVoice').hidden = Boolean(voice);
  if (!voice) return;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  speechSynthesis.speak(utterance);
}

function stopSpeaking() {
  if ('speechSynthesis' in window) speechSynthesis.cancel();
}

// ---- Wiring ------------------------------------------------------------------------------

$('mic').addEventListener('click', () => (recording ? stopRecording() : startRecording()));
$('again').addEventListener('click', startRecording);
$('replay').addEventListener('click', () => speak(lastAnswer));
$('stop').addEventListener('click', stopSpeaking);

$('typeForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const question = $('typeInput').value.trim();
  if (!question) return;
  $('typeInput').value = '';
  stopSpeaking();
  ask(question);
});

if ('speechSynthesis' in window) speechSynthesis.getVoices(); // some browsers load voices late

api('GET', '/api/me')
  .then((me) => {
    $('who').textContent = me.name;
    $('adminLink').hidden = me.role !== 'admin';
  })
  .catch((e) => console.error('Could not load profile', e));
