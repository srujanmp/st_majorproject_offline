$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  hideError();
  const button = event.submitter;
  button.disabled = true;
  try {
    await api('POST', '/api/login', { login: $('login').value, password: $('password').value });
    location.href = '/face';
  } catch (e) {
    showError(e.message);
    $('password').value = '';
    button.disabled = false;
  }
});
