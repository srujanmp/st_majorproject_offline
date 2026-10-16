// Small helpers shared by every page.

const $ = (id) => document.getElementById(id);

function showError(message) {
  const box = $('error');
  box.textContent = message;
  box.hidden = false;
}

function hideError() {
  $('error').hidden = true;
}

// Turn a failed response into a readable message. The server sends {"error": "..."}.
async function errorText(res) {
  try {
    const body = await res.json();
    if (body && typeof body.error === 'string') return body.error;
  } catch (e) {
    console.error(e);
  }
  return `Something went wrong (error ${res.status}).`;
}

// fetch() a JSON API; throws an Error with a readable message on failure.
async function api(method, url, body) {
  const options = { method };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  const res = await fetch(url, options);
  if (res.status === 401 && location.pathname !== '/') location.href = '/';
  if (!res.ok) throw new Error(await errorText(res));
  return res.status === 204 ? null : res.json();
}

// Build an element safely: text always goes in as text, never as HTML.
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'className') node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child != null) node.append(child);
  }
  return node;
}
