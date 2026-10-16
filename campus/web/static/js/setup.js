// First-time setup: create the first admin, then go register their face.

api('GET', '/api/status')
  .then((status) => {
    const missing = Object.entries(status.models).filter(([, ok]) => !ok).map(([name]) => name);
    if (missing.length) {
      $('models').textContent = `Missing models: ${missing.join(', ')}. Run scripts/get_models.py once, or use the packaged download.`;
      $('models').hidden = false;
    }
  })
  .catch((e) => console.error(e));

$('setupForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  hideError();
  if ($('password').value !== $('password2').value) {
    showError('The two passwords are different.');
    return;
  }
  const button = event.submitter;
  button.disabled = true;
  try {
    await api('POST', '/api/setup', {
      login: $('login').value,
      name: $('name').value,
      password: $('password').value,
    });
    location.href = '/face';
  } catch (e) {
    showError(e.message);
    button.disabled = false;
  }
});
