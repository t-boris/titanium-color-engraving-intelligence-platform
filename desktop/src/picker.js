/* The start screen's page: lists the known workshops, lets the user pick or make a folder, and shows the core's start and failures. */
'use strict';
(() => {
  const known = document.getElementById('known');
  const status = document.getElementById('status');
  const log = document.getElementById('log');
  const buttons = () => Array.from(document.querySelectorAll('button'));
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) { if (k === 'onClick') node.addEventListener('click', v); else if (k === 'class') node.className = v; else node.setAttribute(k, v); }
    for (const c of children) node.append(c);
    return node;
  };

  function busy(text) { status.textContent = text; status.className = 'status busy'; log.hidden = true; buttons().forEach((b) => { b.disabled = true; }); }
  function failed(message, tail) {
    status.textContent = message; status.className = 'status';
    log.hidden = !tail; log.textContent = tail || '';
    buttons().forEach((b) => { b.disabled = false; });
  }

  async function open(folder) {
    busy('Запускаем ядро мастерской…');
    const result = await window.shell.picker.open(folder);
    if (result && result.error) failed(result.error, result.logTail);
  }

  async function browse(mode) {
    const result = await window.shell.picker.browse(mode);
    if (!result) return;
    if (result.error) { failed(result.error); return; }
    await open(result.folder);
  }

  async function list() {
    const choices = await window.shell.picker.choices();
    known.replaceChildren();
    if (!choices.length) { known.append(el('em', {}, 'Известных мастерских пока нет: откройте папку или создайте новую.')); return; }
    for (const c of choices) {
      known.append(el('div', {class: 'choice'}, el('div', {}, el('div', {}, c.label), el('div', {class: 'folder'}, c.folder)),
        el('button', {type: 'button', class: 'primary', onClick: () => open(c.folder)}, 'Открыть')));
    }
  }

  document.getElementById('open-existing').addEventListener('click', () => browse('existing'));
  document.getElementById('create-new').addEventListener('click', () => browse('new'));
  list().catch((e) => failed(String(e)));
})();
