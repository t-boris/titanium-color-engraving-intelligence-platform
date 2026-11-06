/* The start screen's page: lists the known workshops, lets the user pick or make a folder, and shows the core's start and failures. */
'use strict';
(() => {
  const known = document.getElementById('known');
  const status = document.getElementById('status');
  const log = document.getElementById('log');
  const logDetails = document.getElementById('log-details');
  const buttons = () => Array.from(document.querySelectorAll('button'));
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) { if (k === 'onClick') node.addEventListener('click', v); else if (k === 'class') node.className = v; else node.setAttribute(k, v); }
    for (const c of children) node.append(c);
    return node;
  };

  function busy(text) { status.textContent = text; status.className = 'status busy'; logDetails.hidden = true; buttons().forEach((b) => { b.disabled = true; }); }
  function failed(message, tail) {
    status.textContent = message; status.className = 'status';
    logDetails.hidden = !tail; logDetails.open = false; log.textContent = tail || '';
    buttons().forEach((b) => { b.disabled = false; });
  }

  async function open(folder, mode = 'existing') {
    busy('Запускаем ядро мастерской…');
    try {
      const result = await window.shell.picker.open(folder, mode);
      if (result && result.error) failed(result.error, result.logTail);
    } catch (e) { failed(String(e)); }
  }

  async function browse(mode) {
    const result = await window.shell.picker.browse(mode);
    if (!result) return;
    if (result.error) { failed(result.error); return; }
    await open(result.folder, mode);
  }

  async function list() {
    const choices = await window.shell.picker.choices();
    known.replaceChildren();
    if (!choices.length) { known.append(el('em', {}, 'Известных мастерских пока нет: откройте папку или создайте новую.')); return; }
    const other = choices.filter((c) => c.why !== 'last');
    const last = choices.find((c) => c.why === 'last');
    if (last) {
      const info = el('div', {}, el('strong', {}, last.label), el('div', {class: 'folder'}, last.folder));
      if (last.problem) info.append(el('p', {class: 'unavailable'}, last.problem + ' Выберите другую папку ниже.'));
      known.append(el('div', {class: 'choice last-choice'}, info,
        last.problem ? '' : el('button', {type: 'button', class: 'primary', onClick: () => open(last.folder)}, 'Продолжить')));
    }
    if (other.length) {
      const details = el('details', {}, el('summary', {}, 'Другие известные мастерские'));
      for (const c of other) details.append(el('div', {class: 'choice'}, el('div', {}, el('div', {}, c.label), el('div', {class: 'folder'}, c.folder)),
        el('button', {type: 'button', onClick: () => open(c.folder)}, 'Открыть')));
      known.append(details);
    }
  }

  document.getElementById('open-existing').addEventListener('click', () => browse('existing'));
  document.getElementById('create-new').addEventListener('click', () => browse('new'));
  list().catch((e) => failed(String(e)));
})();
