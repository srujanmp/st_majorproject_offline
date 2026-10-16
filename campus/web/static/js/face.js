// Face check after the password. Also used once by the first admin to
// register their own face right after setup.

const video = $('video');
const button = $('action');
let mode = 'verify';

function say(message, kind) {
  $('status').textContent = message;
  $('status').className = 'status' + (kind ? ' ' + kind : '');
}

async function run() {
  button.disabled = true;
  say(mode === 'enroll' ? 'Saving…' : 'Checking…');
  try {
    await sendFace(mode === 'enroll' ? '/api/face/enroll' : '/api/face/verify', videoFrame(video));
    say(mode === 'enroll' ? 'Face registered. Opening the assistant…' : 'Verified. Opening the assistant…', 'notice');
    location.href = '/';
    return;
  } catch (e) {
    if (e.status === 401) {
      location.href = '/';
      return;
    }
    say(e.message, 'error');
  }
  button.disabled = false;
}

async function init() {
  let me;
  try {
    me = await api('GET', '/api/me');
  } catch (e) {
    say(e.message, 'error');
    return;
  }
  if (me.may_enroll) {
    mode = 'enroll';
    $('heading').textContent = 'Register your face';
    $('intro').textContent = 'Look straight at the camera in good light. This picture is what you will be compared with each time you sign in.';
    button.textContent = 'Register my face';
  } else if (!me.face_enrolled) {
    $('heading').textContent = 'Face not registered';
    $('intro').textContent = 'Your face has not been registered yet. Ask an admin to add it, then sign in again.';
    $('cameraBox').hidden = true;
    return;
  }
  try {
    await startCamera(video);
    button.disabled = false;
  } catch (e) {
    say(e.message, 'error');
  }
}

button.addEventListener('click', run);
init();
