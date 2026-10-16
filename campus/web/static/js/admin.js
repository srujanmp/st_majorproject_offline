// Admin panel: the knowledge the assistant answers from, and user accounts.

let modules = [];
let users = [];
let editingModule = null;

function notify(message) {
  hideError();
  $('notice').textContent = message;
  $('notice').hidden = false;
  setTimeout(() => ($('notice').hidden = true), 4000);
}

// Run an action and show its error inline instead of failing silently.
async function attempt(action) {
  try {
    await action();
  } catch (e) {
    console.error(e);
    showError(e.message);
  }
}

const when = (iso) => new Date(iso).toLocaleString();

// ---- Tabs ----------------------------------------------------------------------

for (const tab of document.querySelectorAll('.tab')) {
  tab.addEventListener('click', () => {
    for (const t of document.querySelectorAll('.tab')) t.classList.toggle('active', t === tab);
    $('tab-knowledge').hidden = tab.dataset.tab !== 'knowledge';
    $('tab-users').hidden = tab.dataset.tab !== 'users';
    hideError();
  });
}

// ---- Knowledge -----------------------------------------------------------------

function resetModuleForm() {
  editingModule = null;
  $('moduleForm').reset();
  $('formTitle').textContent = 'Add knowledge';
  $('mCancel').hidden = true;
}

function editModule(module) {
  editingModule = module.id;
  $('mTitle').value = module.title;
  $('mContent').value = module.content;
  $('formTitle').textContent = 'Edit knowledge';
  $('mCancel').hidden = false;
  $('mTitle').focus();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderModules() {
  const filter = $('filter').value.trim().toLowerCase();
  const shown = modules.filter(
    (m) => !filter || m.title.toLowerCase().includes(filter) || m.content.toLowerCase().includes(filter)
  );
  $('count').textContent = modules.length;
  const list = $('modules');
  list.replaceChildren();
  if (!shown.length) {
    list.append(el('li', { className: 'muted' }, modules.length ? 'No entries match.' : 'No entries yet. Add one above or import a file.'));
    return;
  }
  for (const m of shown) {
    const preview = m.content.length > 220 ? m.content.slice(0, 220) + '…' : m.content;
    list.append(
      el('li', {},
        el('div', { className: 'item-head' },
          el('div', {},
            el('span', { className: 'item-title' }, m.title),
            el('span', { className: 'badge' }, m.source),
            el('div', { className: 'muted small' }, `Updated ${when(m.updated_at)}${m.updated_by ? ' by ' + m.updated_by : ''}`)
          ),
          el('div', { className: 'row' },
            el('button', { className: 'btn small', onclick: () => editModule(m) }, 'Edit'),
            el('button', { className: 'btn small danger', onclick: () => deleteModule(m) }, 'Delete')
          )
        ),
        el('p', { className: 'item-body' }, preview)
      )
    );
  }
}

async function loadModules() {
  modules = await api('GET', '/api/admin/modules');
  renderModules();
}

function deleteModule(module) {
  if (!confirm(`Delete "${module.title}"? The assistant stops using it straight away.`)) return;
  attempt(async () => {
    await api('DELETE', `/api/admin/modules/${module.id}`);
    if (editingModule === module.id) resetModuleForm();
    notify('Deleted.');
    await loadModules();
  });
}

$('moduleForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const body = { title: $('mTitle').value, content: $('mContent').value };
  $('mSave').disabled = true;
  attempt(async () => {
    if (editingModule) await api('PUT', `/api/admin/modules/${editingModule}`, body);
    else await api('POST', '/api/admin/modules', body);
    notify(editingModule ? 'Saved. The assistant now uses the new version.' : 'Added. The assistant can now answer from it.');
    resetModuleForm();
    await loadModules();
  }).finally(() => ($('mSave').disabled = false));
});

$('mCancel').addEventListener('click', resetModuleForm);
$('filter').addEventListener('input', renderModules);

$('importButton').addEventListener('click', () => $('importFile').click());
$('importFile').addEventListener('change', () => {
  const file = $('importFile').files[0];
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  $('importButton').disabled = true;
  $('importButton').textContent = 'Importing…';
  attempt(async () => {
    const result = await api('POST', '/api/admin/modules/import', form);
    notify(`Imported ${result.added} ${result.added === 1 ? 'entry' : 'entries'} from ${file.name}.`);
    await loadModules();
  }).finally(() => {
    $('importFile').value = '';
    $('importButton').disabled = false;
    $('importButton').textContent = 'Import a file';
  });
});

$('reindex').addEventListener('click', () => {
  $('reindex').disabled = true;
  attempt(async () => {
    const result = await api('POST', '/api/admin/reindex');
    notify(`Search index rebuilt (${result.chunks} pieces).`);
  }).finally(() => ($('reindex').disabled = false));
});

// ---- Users -------------------------------------------------------------------------

function renderUsers() {
  const filter = $('userFilter').value.trim().toLowerCase();
  const shown = users.filter((u) => !filter || u.login.toLowerCase().includes(filter) || u.name.toLowerCase().includes(filter));
  $('userCount').textContent = users.length;
  const list = $('users');
  list.replaceChildren();
  for (const u of shown) {
    list.append(
      el('li', { className: 'item-head' },
        el('div', {},
          el('span', { className: 'item-title' }, u.name),
          el('span', { className: 'badge' }, u.role),
          el('div', { className: 'muted small' }, `ID ${u.login} · ${u.has_face ? 'face registered' : 'no face registered yet'}`)
        ),
        el('div', { className: 'row' },
          el('button', { className: 'btn small', onclick: () => openFaceDialog(u) }, 'Face'),
          el('button', { className: 'btn small', onclick: () => openEditDialog(u) }, 'Edit'),
          el('button', { className: 'btn small danger', onclick: () => deleteUser(u) }, 'Delete')
        )
      )
    );
  }
  if (!shown.length) list.append(el('li', { className: 'muted' }, 'No users match.'));
}

async function loadUsers() {
  users = await api('GET', '/api/admin/users');
  renderUsers();
}

$('userFilter').addEventListener('input', renderUsers);

$('userForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  attempt(async () => {
    const user = await api('POST', '/api/admin/users', {
      login: $('uLogin').value,
      name: $('uName').value,
      role: $('uRole').value,
      password: $('uPassword').value,
    });
    notify(`Added ${user.name}. Now register their face.`);
    $('userForm').reset();
    await loadUsers();
    openFaceDialog(user);
  }).finally(() => (button.disabled = false));
});

function deleteUser(user) {
  if (!confirm(`Delete ${user.name} (${user.login})? They will no longer be able to sign in.`)) return;
  attempt(async () => {
    await api('DELETE', `/api/admin/users/${user.id}`);
    notify('User deleted.');
    await loadUsers();
  });
}

// Edit dialog
let editingUser = null;

function openEditDialog(user) {
  editingUser = user;
  $('editWho').textContent = `${user.name} (${user.login})`;
  $('eName').value = user.name;
  $('eRole').value = user.role;
  $('ePassword').value = '';
  $('editError').hidden = true;
  $('userDialog').showModal();
}

$('editClose').addEventListener('click', () => $('userDialog').close());
$('editForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const body = { name: $('eName').value, role: $('eRole').value };
  if ($('ePassword').value) body.password = $('ePassword').value;
  try {
    await api('PUT', `/api/admin/users/${editingUser.id}`, body);
    $('userDialog').close();
    notify('User saved.');
    await loadUsers();
  } catch (e) {
    $('editError').textContent = e.message;
    $('editError').hidden = false;
  }
});

// Face dialog: webcam picture or uploaded photo
let faceUser = null;
let faceStream = null;

function faceSay(message, kind) {
  $('faceStatus').textContent = message;
  $('faceStatus').className = 'status' + (kind ? ' ' + kind : '');
}

async function openFaceDialog(user) {
  faceUser = user;
  $('faceWho').textContent = `${user.name} (${user.login})`;
  faceSay(user.has_face ? 'A face is already registered. A new picture replaces it.' : '');
  $('faceCapture').disabled = true;
  $('faceDialog').showModal();
  try {
    faceStream = await startCamera($('faceVideo'));
    $('faceCapture').disabled = false;
  } catch (e) {
    faceSay(e.message + ' You can still upload a photo.', 'error');
  }
}

async function saveFace(getFrame) {
  faceSay('Saving…');
  try {
    await sendFace(`/api/admin/users/${faceUser.id}/face`, await getFrame());
    faceSay(`Face registered for ${faceUser.name}.`, 'notice');
    await loadUsers();
  } catch (e) {
    faceSay(e.message, 'error');
  }
}

$('faceCapture').addEventListener('click', () => saveFace(() => videoFrame($('faceVideo'))));
$('faceUpload').addEventListener('click', () => $('facePhoto').click());
$('facePhoto').addEventListener('change', () => {
  const file = $('facePhoto').files[0];
  $('facePhoto').value = '';
  if (file) saveFace(() => photoFrame(file));
});
$('faceClose').addEventListener('click', () => $('faceDialog').close());
$('faceDialog').addEventListener('close', () => {
  stopCamera(faceStream);
  faceStream = null;
});

attempt(loadModules);
attempt(loadUsers);
