// Webcam and photo helpers for the face check.
// The browser shrinks the picture and sends raw RGB pixels, so the server
// needs no image library.

const FACE_MAX_SIDE = 640;

async function startCamera(video) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error('This browser cannot use the camera. Try Chrome, Edge or Firefox.');
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    video.srcObject = stream;
    await new Promise((resolve) => {
      if (video.readyState >= 2) resolve();
      else video.onloadeddata = resolve;
    });
    return stream;
  } catch (e) {
    console.error(e);
    throw new Error('Camera permission was blocked or no camera was found. Allow it in the address bar, then reload.');
  }
}

function stopCamera(stream) {
  if (stream) stream.getTracks().forEach((t) => t.stop());
}

// Draw any picture source (video, image) at most 640 px wide/high and return its RGB pixels.
function toRGB(source, width, height) {
  const scale = Math.min(1, FACE_MAX_SIDE / Math.max(width, height));
  const w = Math.round(width * scale);
  const h = Math.round(height * scale);
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(source, 0, 0, w, h);
  const rgba = ctx.getImageData(0, 0, w, h).data;
  const rgb = new Uint8Array(w * h * 3);
  for (let i = 0, j = 0; i < rgba.length; i += 4) {
    rgb[j++] = rgba[i];
    rgb[j++] = rgba[i + 1];
    rgb[j++] = rgba[i + 2];
  }
  return { rgb, w, h };
}

function videoFrame(video) {
  return toRGB(video, video.videoWidth, video.videoHeight);
}

async function photoFrame(file) {
  const bitmap = await createImageBitmap(file);
  const frame = toRGB(bitmap, bitmap.width, bitmap.height);
  bitmap.close();
  return frame;
}

async function sendFace(url, frame) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream', 'X-Width': String(frame.w), 'X-Height': String(frame.h) },
    body: frame.rgb,
  });
  if (!res.ok) {
    const error = new Error(await errorText(res));
    error.status = res.status;
    throw error;
  }
  return res.json();
}
