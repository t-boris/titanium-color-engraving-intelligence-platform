/* Accessible file input with an application-styled button and selected filename. */
'use strict';
Object.assign(App, (() => {
  const {h} = App;
  const size = (n) => (n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1024 / 1024).toFixed(1) + ' MB');

  function filePick(input, buttonLabel = 'Choose file') {
    input.classList.add('file-native');
    const name = h('span', {class: 'file-name'}, 'No file selected');
    const box = h('span', {class: 'file-pick'}, h('span', {class: 'btn btn-small file-button', 'aria-hidden': 'true'}, buttonLabel), name);
    const sync = () => {
      const f = input.files && input.files[0];
      name.textContent = f ? `${f.name} · ${size(f.size)}` : 'No file selected';
      box.classList.toggle('has-file', !!f);
    };
    input.addEventListener('change', sync);
    // a caller may set input.files programmatically (tests, drag and drop): keep the name in step
    box.refresh = sync;
    return h('span', {class: 'file-field'}, input, box);
  }
  return {filePick};
})());
